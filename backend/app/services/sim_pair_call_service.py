"""Safely originate internal calls between active SIM pairs."""
import asyncio
import json
import random
from datetime import datetime, timedelta, timezone

from fastmcp import Client
from sqlalchemy import select

from app.models import Config, McpServer, SimPair, SimPairCall, SimPairHistory
from app.services.mcp_service import _build_http_transport
from app.services.tmlite_shapes import naive_iso


class SimPairCallService:
    _run_lock = asyncio.Lock()
    _CDR_LOOKBACK = timedelta(hours=24)

    @staticmethod
    async def run_due(session) -> dict:
        if SimPairCallService._run_lock.locked():
            return {"started": 0, "skipped": 0, "failed": 0, "reason": "A pair call run is already in progress"}
        async with SimPairCallService._run_lock:
            config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
            if not config or not config.pairing_call_enabled:
                return {"started": 0, "skipped": 0, "failed": 0, "reason": "Pair call automation is disabled"}
            pairs = list((await session.execute(select(SimPair).where(SimPair.status == "active").order_by(SimPair.created_at))).scalars())
            if not pairs:
                return {"started": 0, "skipped": 0, "failed": 0, "reason": "No active pairs"}
            server = (await session.execute(select(McpServer).where(McpServer.name == "TmLite", McpServer.enabled.is_(True)))).scalar_one_or_none()
            if not server or server.transport != "http" or not server.url:
                raise RuntimeError("An enabled TmLite HTTP MCP server is required")
            now = datetime.now(timezone.utc)
            # Keep the cadence based on the most recent call regardless of its
            # final outcome. Otherwise a completed call becomes immediately due
            # again at the next scheduler tick.
            calls = list((await session.execute(
                select(SimPairCall)
                .where(SimPairCall.started_at >= now - timedelta(minutes=config.pairing_call_interval_minutes))
                .order_by(SimPairCall.started_at.desc())
            )).scalars())
            newest = {}
            for call in calls:
                newest.setdefault(call.pair_id, call)
            due = [pair for pair in pairs if pair.id not in newest or now - newest[pair.id].started_at >= timedelta(minutes=config.pairing_call_interval_minutes)]
            if not due:
                return {"started": 0, "skipped": 0, "failed": 0, "reason": "No pair calls are due"}
            async with Client(_build_http_transport(server.url, server.api_key)) as client:
                sims = await SimPairCallService._list_sims(client)
                by_id = {sim.get("id"): sim for sim in sims}
                reconciled = await SimPairCallService._reconcile_started_calls(session, client, by_id, now)
                if reconciled["completed"] or reconciled["failed"]:
                    await session.commit()
                started = skipped = failed = 0
                used = set()
                for pair in due:
                    if started >= config.pairing_call_max_per_run:
                        break
                    a, b = by_id.get(pair.sim_a_id), by_id.get(pair.sim_b_id)
                    if not SimPairCallService._callable(a, now) or not SimPairCallService._callable(b, now):
                        skipped += 1
                        continue
                    if pair.sim_a_id in used or pair.sim_b_id in used or a.get("gateway_name") == b.get("gateway_name"):
                        skipped += 1
                        continue
                    previous = newest.get(pair.id)
                    caller, callee = (pair.sim_b_id, pair.sim_a_id) if previous and previous.from_sim_id == pair.sim_a_id else (pair.sim_a_id, pair.sim_b_id)
                    duration = random.randint(config.pairing_call_min_seconds, config.pairing_call_max_seconds)
                    try:
                        await client.call_tool("originate_call", {"caller_sim_id": caller, "callee_sim_id": callee, "hold_seconds": duration})
                        session.add(SimPairCall(pair_id=pair.id, from_sim_id=caller, to_sim_id=callee, hold_seconds=duration))
                        session.add(SimPairHistory(pair_id=pair.id, event="call_started", details={"from_sim_id": caller, "to_sim_id": callee, "hold_seconds": duration}))
                        await session.commit(); started += 1; used.update((caller, callee))
                    except Exception as exc:
                        session.add(SimPairCall(pair_id=pair.id, from_sim_id=caller, to_sim_id=callee, hold_seconds=duration, status="failed", error=str(exc)))
                        session.add(SimPairHistory(pair_id=pair.id, event="call_failed", details={"reason": str(exc)}))
                        await session.commit(); failed += 1
                return {
                    "started": started,
                    "skipped": skipped,
                    "failed": failed,
                    "reconciled_completed": reconciled["completed"],
                    "reconciled_failed": reconciled["failed"],
                }

    @staticmethod
    def _callable(sim, now) -> bool:
        if not sim or str(sim.get("state") or "").upper() != "IDLE" or sim.get("in_call") or sim.get("resting_today"):
            return False
        raw = sim.get("next_available_at")
        if raw:
            try:
                available_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                # TmLite also returns legacy timestamps without an offset. Its
                # API timestamps are UTC; make that explicit before comparing
                # with our aware UTC clock. A malformed timestamp remains a
                # conservative "not callable" result below.
                if available_at.tzinfo is None:
                    available_at = available_at.replace(tzinfo=timezone.utc)
                return available_at <= now
            except ValueError:
                return False
        return True

    @staticmethod
    async def _list_sims(client):
        result = await client.call_tool(
            "list_sims",
            {
                "limit": 1000,
                "skip": 0,
                "fields": "state,in_call,resting_today,next_available_at,gateway_name,phone_number",
            },
        )
        value = json.loads(result[0].text)
        return value.get("items", value.get("data", value)) if isinstance(value, dict) else value

    @staticmethod
    async def _reconcile_started_calls(session, client, sims_by_id: dict, now: datetime) -> dict:
        """Persist final CDR outcomes returned by TmLite for pair calls."""
        pending = list((await session.execute(
            select(SimPairCall)
            .where(
                SimPairCall.status == "started",
                SimPairCall.started_at >= now - SimPairCallService._CDR_LOOKBACK,
            )
            .order_by(SimPairCall.started_at.desc())
        )).scalars())
        result = {"completed": 0, "failed": 0}
        calls_by_caller: dict[int, list[dict]] = {}

        for pair_call in pending:
            if pair_call.from_sim_id not in calls_by_caller:
                try:
                    response = await client.call_tool(
                        "list_calls",
                        {
                            "page": 1,
                            "limit": 50,
                            "sim_id": pair_call.from_sim_id,
                            # TmLite rejects timezone offsets here; its own
                            # CDR timestamps are naive UTC ISO strings.
                            "from_date": naive_iso(pair_call.started_at - timedelta(minutes=1)),
                        },
                    )
                    payload = json.loads(response[0].text)
                    calls_by_caller[pair_call.from_sim_id] = payload.get("items", payload.get("data", []))
                except Exception:
                    # TmLite may be temporarily unavailable; keep the record
                    # pending so the next scheduler run can reconcile it.
                    calls_by_caller[pair_call.from_sim_id] = []

            target_number = SimPairCallService._digits(sims_by_id.get(pair_call.to_sim_id, {}).get("phone_number"))
            cdr = SimPairCallService._matching_cdr(
                calls_by_caller[pair_call.from_sim_id], pair_call, target_number, now
            )
            if not cdr:
                # A finalized CDR normally appears within seconds. Waiting
                # thirty minutes tolerates asynchronous carrier processing but
                # prevents a local "started" record from claiming success
                # forever when no call reached TmLite.
                if now - pair_call.started_at >= timedelta(minutes=30):
                    pair_call.status = "failed"
                    pair_call.error = "No matching finalized TmLite CDR within 30 minutes"
                    session.add(SimPairHistory(
                        pair_id=pair_call.pair_id,
                        event="call_failed",
                        details={
                            "sim_pair_call_id": str(pair_call.id),
                            "reason": "no_matching_tmlite_cdr",
                            "from_sim_id": pair_call.from_sim_id,
                            "to_sim_id": pair_call.to_sim_id,
                        },
                    ))
                    result["failed"] += 1
                continue

            cdr_status = str(cdr.get("status") or "").upper()
            if cdr_status == "COMPLETED":
                pair_call.status, pair_call.error = "completed", None
                result["completed"] += 1
                event = "call_completed"
            elif cdr.get("finalized_at") or cdr_status in {"CANCELLED", "REJECTED", "FAILED", "BUSY", "NO_ANSWER"}:
                pair_call.status = "failed"
                pair_call.error = f"TmLite {cdr_status or 'FAILED'}: {cdr.get('hangup_cause') or cdr.get('gsm_disconnect_cause') or 'no cause'}"
                result["failed"] += 1
                event = "call_failed"
            else:
                continue

            session.add(SimPairHistory(
                pair_id=pair_call.pair_id,
                event=event,
                details={
                    "sim_pair_call_id": str(pair_call.id),
                    "tmlite_cdr_id": cdr.get("id"),
                    "status": cdr_status,
                    "duration": cdr.get("duration"),
                    "answered_at": cdr.get("answered_at"),
                    "ended_at": cdr.get("ended_at"),
                    "finalized_at": cdr.get("finalized_at"),
                    "hangup_cause": cdr.get("hangup_cause"),
                    "gsm_status": cdr.get("gsm_status"),
                },
            ))
        return result

    @staticmethod
    def _matching_cdr(cdrs: list[dict], pair_call: SimPairCall, target_number: str, now: datetime) -> dict | None:
        candidates = []
        lower_bound = pair_call.started_at - timedelta(seconds=60)
        for cdr in cdrs:
            if cdr.get("sim_card_id") != pair_call.from_sim_id:
                continue
            started_at = SimPairCallService._parse_timestamp(cdr.get("started_at"))
            if not started_at or started_at < lower_bound or started_at > now + timedelta(minutes=1):
                continue
            if target_number and SimPairCallService._digits(cdr.get("callee")) != target_number:
                continue
            candidates.append((abs((started_at - pair_call.started_at).total_seconds()), cdr))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    @staticmethod
    def _parse_timestamp(value) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            return None

    @staticmethod
    def _digits(value) -> str:
        return "".join(char for char in str(value or "") if char.isdigit())
