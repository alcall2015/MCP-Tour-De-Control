import json
from datetime import datetime, timezone

from fastmcp import Client
from sqlalchemy import select

from app.models import (
    Config,
    McpServer,
    SimPair,
    SimPairHistory,
    SimPairingGroup,
    SimPairingRun,
    SimPairingSim,
    SimPairingTopic,
)
from app.services.mcp_service import _build_http_transport


class SimPairingService:
    """Synchronize deterministic SIM pairs; this service never sends SMS."""

    # A SIM in one of these states needs a manual TmLite intervention (or is
    # simply gone) before it can be part of a pair again, so an existing pair
    # is archived. Everything else — BUSY, RINGING, etc. — is a SIM merely
    # mid-call at sync time and must never cost a pair its history.
    DURABLE_BAD_STATES = {"OFFLINE", "DISABLED", "BLOCKED"}

    # These are local labels for the pairing application. They never rename a
    # SIM in TmLite, so carrier-facing configuration stays untouched.
    WEST_AFRICAN_NAMES = (
        "Aïssata", "Aminata", "Adama", "Awa", "Binta", "Fatou", "Kadiatou",
        "Mariama", "Ndeye", "Sira", "Abdou", "Amadou", "Cheikh", "Ibrahima",
        "Koffi", "Moussa", "Ousmane", "Sékou", "Yao", "Youssouf",
    )

    @staticmethod
    async def sync(session):
        run = SimPairingRun()
        session.add(run)
        await session.commit()
        try:
            config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
            target_messages = config.pairing_target_messages if config else 10
            group_names = {g.name.lower() for g in (await session.execute(select(SimPairingGroup).where(SimPairingGroup.enabled == True))).scalars()}
            topics = [t.name for t in (await session.execute(select(SimPairingTopic).order_by(SimPairingTopic.name))).scalars()]
            if not group_names or not topics:
                return await SimPairingService._finish(session, run, {"created": 0, "archived": 0, "eligible": 0})
            server = (await session.execute(select(McpServer).where(McpServer.name == "TmLite", McpServer.enabled == True))).scalar_one_or_none()
            if not server or server.transport != "http" or not server.url:
                raise RuntimeError("An enabled TmLite HTTP MCP server is required")
            transport = _build_http_transport(server.url, server.api_key)
            async with Client(transport) as client:
                gateways = SimPairingService._items(await client.call_tool("list_gateways", {"limit": 100, "skip": 0}))
                countries_by_id = {g.get("id"): str(g.get("country") or g.get("country_name") or "").upper() for g in gateways}
                countries_by_name = {str(g.get("name") or "").upper(): str(g.get("country") or g.get("country_name") or "").upper() for g in gateways}
                sims = []
                for skip in range(0, 10000, 100):
                    page = SimPairingService._items(await client.call_tool("list_sims", {"limit": 100, "skip": skip}))
                    sims.extend(page)
                    if len(page) < 100:
                        break
            # Group and country membership is a static property of the SIM,
            # independent of its transient carrier state, so it is computed
            # once and then split two ways by state.
            candidates = {
                sim["id"]: {"state": sim.get("state"), "country": countries_by_id.get(sim.get("gateway_id")) or countries_by_name.get(str(sim.get("gateway_name") or "").upper(), ""), "group": str(sim.get("sim_group_name") or "")}
                for sim in sims
                if sim.get("id") is not None
                and str(sim.get("sim_group_name") or "").lower() in group_names
                and (countries_by_id.get(sim.get("gateway_id")) or countries_by_name.get(str(sim.get("gateway_name") or "").upper(), ""))
            }
            # "Keep this pair alive?" asks whether the SIM is durably gone.
            # BUSY/RINGING/etc. are transient call states that must never
            # cost a pair its history and sent_count.
            kept_alive = {sim_id: info for sim_id, info in candidates.items() if info["state"] not in SimPairingService.DURABLE_BAD_STATES}
            # "Create a new pair with this SIM?" asks whether it can actually
            # send right now, matching the conversation service's own IDLE
            # guard exactly, so a pair is never created only to sit stuck.
            creatable = {sim_id: info for sim_id, info in candidates.items() if info["state"] == "IDLE"}
            # Names are maintained for the broader kept-alive set so a pair
            # whose SIM is momentarily busy still has its name refreshed.
            names, names_assigned = await SimPairingService._ensure_sim_names(session, kept_alive)
            active_pairs = list((await session.execute(select(SimPair).where(SimPair.status == "active"))).scalars())
            archived = 0
            pairs_named = 0
            for pair in active_pairs:
                a, b = kept_alive.get(pair.sim_a_id), kept_alive.get(pair.sim_b_id)
                if not a or not b or a["country"] != b["country"]:
                    pair.status, pair.archived_reason, pair.archived_at = "archived", "SIM unavailable or no longer eligible", datetime.now(timezone.utc)
                    session.add(SimPairHistory(pair_id=pair.id, event="archived", details={"reason": pair.archived_reason}))
                    archived += 1
                elif pair.sim_a_name != names[pair.sim_a_id] or pair.sim_b_name != names[pair.sim_b_id]:
                    pair.sim_a_name, pair.sim_b_name = names[pair.sim_a_id], names[pair.sim_b_id]
                    pairs_named += 1
            await session.flush()
            active_pairs = [p for p in active_pairs if p.status == "active"]
            used = {frozenset((p.sim_a_id, p.sim_b_id)) for p in active_pairs}
            counts = {sim_id: 0 for sim_id in creatable}
            for pair in active_pairs:
                counts[pair.sim_a_id] = counts.get(pair.sim_a_id, 0) + 1
                counts[pair.sim_b_id] = counts.get(pair.sim_b_id, 0) + 1
            created = 0
            ids = sorted(creatable)
            for index, a_id in enumerate(ids):
                for b_id in ids[index + 1:]:
                    if counts[a_id] >= 3 or counts[b_id] >= 3 or frozenset((a_id, b_id)) in used:
                        continue
                    a, b = creatable[a_id], creatable[b_id]
                    if a["country"] != b["country"]:
                        continue
                    topic = topics[created % len(topics)]
                    pair = SimPair(
                        sim_a_id=a_id,
                        sim_b_id=b_id,
                        sim_a_name=names[a_id],
                        sim_b_name=names[b_id],
                        country=a["country"],
                        group_a=a["group"],
                        group_b=b["group"],
                        topic=topic,
                        target_messages=target_messages,
                    )
                    session.add(pair)
                    await session.flush()
                    session.add(SimPairHistory(pair_id=pair.id, event="created", details={"country": pair.country, "topic": topic, "sim_a_name": pair.sim_a_name, "sim_b_name": pair.sim_b_name, "target_messages": target_messages}))
                    used.add(frozenset((a_id, b_id))); counts[a_id] += 1; counts[b_id] += 1; created += 1
            # "eligible" now reports the creatable set: the number that
            # actually gates whether new pairs get made, so an operator
            # wondering why "created" is low or zero can act on this number
            # directly. "kept_alive" is reported alongside it since it is the
            # (larger) set that decides which existing pairs survive.
            return await SimPairingService._finish(session, run, {"created": created, "archived": archived, "eligible": len(creatable), "kept_alive": len(kept_alive), "names_assigned": names_assigned, "pairs_named": pairs_named})
        except Exception as exc:
            # A flush failure leaves the session unusable until it is rolled
            # back; without this, the commit below raises PendingRollbackError
            # and the run is left stuck at "running" forever.
            await session.rollback()
            try:
                run.status, run.error, run.completed_at = "failed", str(exc), datetime.now(timezone.utc)
                await session.commit()
            except Exception:
                # Never let a failure in recording the failure mask the
                # original exception.
                await session.rollback()
            raise

    @staticmethod
    def _items(result):
        value = json.loads(result[0].text)
        return value.get("items", value.get("data", value)) if isinstance(value, dict) else value

    @staticmethod
    async def _ensure_sim_names(session, eligible):
        """Return one persistent, human-friendly label for every eligible SIM."""
        sim_ids = sorted(eligible)
        if not sim_ids:
            return {}, 0
        records = list((await session.execute(
            select(SimPairingSim).where(SimPairingSim.sim_id.in_(sim_ids))
        )).scalars())
        by_id = {record.sim_id: record for record in records}
        # display_name is unique across the whole table, not just this eligible
        # subset, so the pool of taken names must come from every row. Otherwise
        # a name already held by a now-ineligible SIM looks free and gets handed
        # to a new SIM, and the commit dies on the unique constraint.
        used_names = set((await session.execute(select(SimPairingSim.display_name))).scalars())
        assigned = 0
        for sim_id in sim_ids:
            record = by_id.get(sim_id)
            if record:
                record.country = eligible[sim_id]["country"]
                continue
            base = next((name for name in SimPairingService.WEST_AFRICAN_NAMES if name not in used_names), None)
            display_name = base or f"SIM {sim_id}"
            record = SimPairingSim(
                sim_id=sim_id,
                display_name=display_name,
                country=eligible[sim_id]["country"],
            )
            session.add(record)
            by_id[sim_id] = record
            used_names.add(display_name)
            assigned += 1
        await session.flush()
        return {sim_id: record.display_name for sim_id, record in by_id.items()}, assigned

    @staticmethod
    async def _finish(session, run, summary):
        run.status, run.summary, run.completed_at = "success", summary, datetime.now(timezone.utc)
        await session.commit()
        return run
