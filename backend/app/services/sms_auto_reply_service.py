"""Answer inbound SMS and follow up the most recent unanswered call.

Every reply uses one fixed template. There is deliberately no LLM in this
path: an automatic notification must read the same every time.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from fastmcp import Client
from sqlalchemy import func, select

from app.models import Config, McpServer, SmsReply
from app.services.mcp_service import _build_http_transport
from app.services.sim_pairing_service import SimPairingService
from app.services import sms_auto_reply_rules as rules
from app.services.tmlite_shapes import normalize_call, normalize_sms, sim_index
from app.utils import quiet_hours

log = structlog.get_logger()

# Why a message would not be sent even though a trigger exists for it. Shared
# between the real run (which stores it on the skipped SmsReply row) and the
# dry run (which must never preview a message the real run would refuse).
_NO_WHATSAPP = "No caller found for this number"
_NO_SIM = "No SIM recorded for this contact"


class SmsAutoReplyService:
    _run_lock = asyncio.Lock()

    @staticmethod
    async def run(session, dry_run: bool = False) -> dict:
        if SmsAutoReplyService._run_lock.locked():
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "A run is already in progress"}
        async with SmsAutoReplyService._run_lock:
            return await SmsAutoReplyService._run(session, dry_run)

    @staticmethod
    async def _run(session, dry_run: bool) -> dict:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.sms_autoreply_enabled:
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "SMS auto-reply is disabled"}

        window = quiet_hours.quiet_window(config)
        if not dry_run and quiet_hours.is_quiet(datetime.now(timezone.utc), window):
            return {"sent": 0, "skipped": 0, "failed": 0,
                    "reason": f"Quiet hours: replies resume at {window[1]:02d}:00 UTC"}

        server = (await session.execute(
            select(McpServer).where(McpServer.name == "TmLite", McpServer.enabled.is_(True))
        )).scalar_one_or_none()
        if not server or server.transport != "http" or not server.url:
            raise RuntimeError("An enabled TmLite HTTP MCP server is required")

        sent = skipped = failed = 0
        previews = []
        since = datetime.now(timezone.utc) - timedelta(minutes=config.sms_autoreply_lookback_minutes)
        async with Client(_build_http_transport(server.url, server.api_key)) as client:
            sims = await SmsAutoReplyService._all_sims(client)
            # An empty fleet is never valid, so it is an upstream failure rather
            # than a state to work from. Carrying on with an empty `fleet` would
            # make is_fleet_number() false for everything: the fleet's own
            # SIM-pairing SMS would become triggers and we would auto-reply to
            # our own SIMs. Stop instead — and check for a *usable* number, not
            # just a non-empty `fleet` set, because fleet_numbers() only drops
            # digit-free values. A short-but-nonzero phone_number (e.g. a stray
            # "1" in a SIM row) survives into `fleet` but falls under
            # MIN_MATCH_DIGITS, so same_number() — and therefore
            # is_fleet_number() — would still answer False for every real
            # number, which is exactly the broken state this guard exists to
            # catch.
            if not sims:
                return {"sent": 0, "skipped": 0, "failed": 0,
                        "reason": "TmLite returned no SIM cards; refusing to run without a fleet"}
            fleet = rules.fleet_numbers(sims)
            if not any(len(number) >= rules.MIN_MATCH_DIGITS for number in fleet):
                return {"sent": 0, "skipped": 0, "failed": 0,
                        "reason": "TmLite returned SIMs with no usable phone numbers; refusing to run without a fleet"}
            index = sim_index(sims)
            messages = [m for m in (normalize_sms(r) for r in await SmsAutoReplyService._recent_sms(client, since)) if m]
            calls = [c for c in (normalize_call(r) for r in await SmsAutoReplyService._recent_calls(client, since)) if c]

            triggers = rules.sms_triggers(messages, fleet, calls)
            missed = rules.missed_call_trigger(calls, fleet, index)
            if missed:
                triggers.append(missed)

            # Two independent guards. trigger_ref stops the same event being
            # answered twice; the recipient cooldown stops one person receiving
            # several messages because they were called several times.
            refs = [t["ref"] for t in triggers] or [""]
            already = set((await session.execute(
                select(SmsReply.trigger_ref).where(SmsReply.trigger_ref.in_(refs))
            )).scalars())
            triggers = [t for t in triggers if t["ref"] not in already]

            cooldown_since = datetime.now(timezone.utc) - timedelta(hours=config.sms_autoreply_recipient_cooldown_hours)
            recent = set((await session.execute(
                select(SmsReply.to_number).where(SmsReply.created_at >= cooldown_since)
            )).scalars())
            triggers = rules.drop_recent_recipients(triggers, recent)[: config.sms_autoreply_max_per_run]

            for trigger in triggers:
                # One decision, used identically whether we are about to send
                # or only preview: never touch a trigger we can't actually
                # deliver, and never show the operator a message we'd refuse
                # to send for real.
                if not trigger["whatsapp"]:
                    reason = _NO_WHATSAPP
                elif not trigger["sim_id"]:
                    reason = _NO_SIM
                else:
                    reason = None

                if dry_run:
                    if reason:
                        previews.append({**trigger, "content": None, "skip_reason": reason})
                    else:
                        content = rules.render(config.sms_autoreply_template, trigger["whatsapp"])
                        previews.append({**trigger, "content": content, "skip_reason": None})
                    continue

                if reason:
                    if await SmsAutoReplyService._store(
                        session,
                        SmsReply(trigger_kind=trigger["kind"], trigger_ref=trigger["ref"],
                                 sim_id=trigger["sim_id"] or 0, to_number=trigger["to_number"],
                                 whatsapp_number=trigger["whatsapp"], content="", status="skipped",
                                 error=reason),
                        trigger["ref"],
                    ):
                        skipped += 1
                    continue

                content = rules.render(config.sms_autoreply_template, trigger["whatsapp"])
                reply = SmsReply(trigger_kind=trigger["kind"], trigger_ref=trigger["ref"],
                                 sim_id=trigger["sim_id"], to_number=trigger["to_number"],
                                 whatsapp_number=trigger["whatsapp"], content=content, status="sending")
                # Claim the trigger before sending, never after. If the process
                # dies, is redeployed, or loses the database between the send
                # and the outcome, this committed row still holds the
                # trigger_ref and feeds the recipient cooldown, so the next run
                # treats this person as handled. That biases the service to
                # at-most-once: the worst case is a recipient who gets nothing,
                # never one who gets the same unsolicited SMS twice.
                if not await SmsAutoReplyService._store(session, reply, trigger["ref"]):
                    failed += 1
                    continue

                try:
                    await client.call_tool("send_sms", {"from_sim_id": trigger["sim_id"],
                                                        "to_number": trigger["to_number"], "text": content})
                except Exception as exc:
                    # The row already exists: record the failure on it. Inserting
                    # a second row with the same trigger_ref would raise
                    # IntegrityError here and drop every remaining trigger.
                    await SmsAutoReplyService._record_outcome(session, reply, "failed", error=str(exc))
                    failed += 1
                    continue

                await SmsAutoReplyService._record_outcome(session, reply, "sent",
                                                          sent_at=datetime.now(timezone.utc))
                sent += 1

        result = {"sent": sent, "skipped": skipped, "failed": failed}
        if dry_run:
            result["previews"] = previews
        return result

    @staticmethod
    async def _store(session, reply: SmsReply, ref: str) -> bool:
        """Insert one row and commit it, reporting success rather than raising.

        A trigger whose bookkeeping fails must cost only itself: an exception
        escaping here would drop every remaining trigger in the batch and fail
        the whole run.
        """
        session.add(reply)
        try:
            await session.commit()
            return True
        except Exception:
            log.exception("sms_auto_reply_claim_failed", trigger_ref=ref)
            await SmsAutoReplyService._safe_rollback(session, ref)
            return False

    @staticmethod
    async def _record_outcome(session, reply: SmsReply, status: str, error: str | None = None,
                              sent_at: datetime | None = None) -> None:
        """Write the outcome onto the row claimed before the send.

        This updates; it never inserts. The row is already committed, so a
        second insert carrying the same trigger_ref would violate the UNIQUE
        constraint. Its own database work is guarded for the same reason as
        `_store`: one trigger must never cost the others their turn.
        """
        ref = reply.trigger_ref
        try:
            reply.status = status
            reply.error = error
            reply.sent_at = sent_at
            await session.commit()
        except Exception:
            # The send already happened (or already failed); only the record of
            # it is lost. The row stays in "sending", which stats() counts.
            log.exception("sms_auto_reply_outcome_not_recorded", trigger_ref=ref, status=status)
            await SmsAutoReplyService._safe_rollback(session, ref)

    @staticmethod
    async def _safe_rollback(session, ref: str) -> None:
        try:
            await session.rollback()
        except Exception:
            log.exception("sms_auto_reply_rollback_failed", trigger_ref=ref)

    @staticmethod
    def _naive_iso(when: datetime) -> str:
        """TmLite's from_date rejects an offset with a facade 500, not a
        validation error. It wants naive ISO."""
        return when.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    @staticmethod
    async def _all_sims(client) -> list[dict]:
        """The fleet is small and needed in full for the index. Pages with skip."""
        rows = []
        for index in range(10):
            page = SimPairingService._items(
                await client.call_tool("list_sims", {"limit": 100, "skip": index * 100})
            )
            if not isinstance(page, list) or not page:
                break
            rows.extend(page)
            if len(page) < 100:
                break
        return rows

    @staticmethod
    async def _recent_calls(client, since: datetime) -> list[dict]:
        """Windowed by the server: list_calls honours from_date."""
        rows = []
        for page in range(1, 11):
            batch = SimPairingService._items(await client.call_tool(
                "list_calls",
                {"limit": 100, "page": page, "from_date": SmsAutoReplyService._naive_iso(since)},
            ))
            if not isinstance(batch, list) or not batch:
                break
            rows.extend(batch)
            if len(batch) < 100:
                break
        return rows

    @staticmethod
    async def _recent_sms(client, since: datetime) -> list[dict]:
        """list_sms accepts no date filter — only limit and page. It returns
        newest first, so stop at the first row older than the window rather than
        walking the whole table every fifteen minutes. Both timestamps are naive
        ISO, so a string comparison orders them correctly.
        """
        cutoff = SmsAutoReplyService._naive_iso(since)
        rows = []
        for page in range(1, 11):
            batch = SimPairingService._items(await client.call_tool("list_sms", {"limit": 100, "page": page}))
            if not isinstance(batch, list) or not batch:
                break
            for row in batch:
                if str(row.get("received_at") or "") < cutoff:
                    return rows
                rows.append(row)
            if len(batch) < 100:
                break
        return rows

    @staticmethod
    async def stats(session) -> dict:
        counts = {}
        # "sending" is counted too: a row left in it is a claimed trigger whose
        # outcome was never written back (a crash between the send and the
        # update). Those must surface, not vanish from the totals.
        for status in ("sent", "failed", "skipped", "sending"):
            counts[status] = await session.scalar(
                select(func.count()).select_from(SmsReply).where(SmsReply.status == status)
            ) or 0
        counts["last_sent_at"] = await session.scalar(select(func.max(SmsReply.sent_at)))
        return counts
