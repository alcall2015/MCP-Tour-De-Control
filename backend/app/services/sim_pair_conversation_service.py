"""Generate and deliver controlled continuations for active SIM pairs."""
import asyncio
import random
import re
from datetime import datetime, timedelta, timezone

from fastmcp import Client
from openai import OpenAI, RateLimitError
from sqlalchemy import func, select

from app.models import Config, McpServer, SimPair, SimPairHistory, SimPairMessage, SimPairMessageQueue
from app.services.mcp_service import _build_http_transport
from app.services.sim_pairing_service import SimPairingService
from app.utils import quiet_hours
from app.utils.crypto import decrypt_value


class SimPairConversationService:
    """Continue stored pair conversations. This service only sends when enabled."""

    # The backend runs one worker. This lock serializes scheduler and manual
    # runs so they cannot create two messages for the same pair at once.
    _run_lock = asyncio.Lock()
    HISTORY_LIMIT = 12
    RETRY_DELAY_MINUTES = 15
    # A message lands between the configured minimum and this multiple of it, so
    # a pair never settles into a metronomic rhythm.
    JITTER_RANGE = (1.0, 1.35)
    # Per-SIM rules drop candidates, so more are read than can be sent.
    OVERFETCH = 4
    # Everything held overnight would otherwise come due at the same second.
    WAKE_SPREAD_MINUTES = 90
    # Naming is fixed upstream (SimPairingService never assigns a "SIM {id}"
    # label anymore), but this catches the same tell from any other source —
    # the model inventing it, a stale name, a future regression — before an
    # SMS reading "SIM 882, ..." reaches a real phone and tips off the carrier.
    MACHINE_LABEL_PATTERN = re.compile(r"sim\s*\d", re.IGNORECASE)

    @staticmethod
    async def run_due(session, dry_run: bool = False, limit: int | None = None, country: str | None = None) -> dict:
        if SimPairConversationService._run_lock.locked():
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "A pair conversation run is already in progress"}
        async with SimPairConversationService._run_lock:
            return await SimPairConversationService._run_due(session, dry_run, limit, country)

    @staticmethod
    async def _run_due(session, dry_run: bool, limit: int | None, country: str | None) -> dict:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.pairing_conversation_enabled:
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "Conversation automation is disabled"}
        if not config.pairing_openrouter_api_key:
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "OpenRouter API key is not configured"}

        query = select(SimPair).where(SimPair.status == "active")
        if country:
            query = query.where(SimPair.country == country.upper())
        pairs = list((await session.execute(query.order_by(SimPair.created_at))).scalars())
        if not pairs:
            return {"sent": 0, "skipped": 0, "failed": 0, "reason": "No active pairs"}

        # A preview stays entirely local: it does not query TmLite, alter pair
        # eligibility, create a message record, or trigger an SMS.
        if dry_run:
            pair = pairs[0]
            latest = await SimPairConversationService._latest_sent_message(session, pair.id)
            sender_id, recipient_id = SimPairConversationService._next_direction(pair, latest)
            content = await SimPairConversationService._generate_message(session, pair, latest, config)
            return {
                "sent": 0,
                "skipped": 0,
                "failed": 0,
                "active_pairs": len(pairs),
                "previews": [{
                    "pair_id": str(pair.id),
                    "from_sim_id": sender_id,
                    "to_sim_id": recipient_id,
                    "content": content,
                }],
            }

        # Pair eligibility is refreshed by the dedicated sim_pairing_sync job.
        # Sending does not re-sync: it would list the whole TmLite fleet a second
        # time per run, and the IDLE check below already guards every send.
        await SimPairConversationService._enqueue_pairs(session, pairs, config)
        window = SimPairConversationService._quiet_window(config)
        if SimPairConversationService._is_quiet(datetime.now(timezone.utc), window):
            # Manual runs do not bypass quiet hours, exactly as they do not
            # bypass the per-pair interval.
            return await SimPairConversationService._summary(
                session, 0, 0, 0, 0, len(pairs),
                reason=f"Quiet hours: sending resumes at {window[1]:02d}:00 UTC",
            )

        batch_size = max(1, limit or config.pairing_max_messages_per_run)
        candidates = await SimPairConversationService._due_candidates(session, country, batch_size)
        if not candidates:
            return await SimPairConversationService._summary(session, 0, 0, 0, 0, len(pairs))

        server = (await session.execute(
            select(McpServer).where(McpServer.name == "TmLite", McpServer.enabled.is_(True))
        )).scalar_one_or_none()
        if not server or server.transport != "http" or not server.url:
            raise RuntimeError("An enabled TmLite HTTP MCP server is required")

        transport = _build_http_transport(server.url, server.api_key)
        sent = failed = 0
        async with Client(transport) as mcp_client:
            sims = await SimPairConversationService._list_sims(mcp_client)
            sims_by_id = {sim.get("id"): sim for sim in sims if sim.get("id") is not None}
            sim_ids = {sim_id for item in candidates for sim_id in (item["sender_id"], item["recipient_id"])}
            last_activity = await SimPairConversationService._last_activity_by_sim(session, sim_ids)
            chosen, deferred, held = SimPairConversationService._select_batch(
                candidates,
                sims_by_id,
                last_activity,
                datetime.now(timezone.utc),
                batch_size,
                config.pairing_sim_cooldown_minutes,
            )

            for item, reason in deferred:
                item["queue"].due_at = SimPairConversationService._retry_at(window)
                item["queue"].last_error = reason
            if deferred:
                await session.commit()

            for item in chosen:
                queue, pair = item["queue"], item["pair"]
                sender_id, recipient_id = item["sender_id"], item["recipient_id"]
                recipient = sims_by_id[recipient_id]
                try:
                    content = await SimPairConversationService._generate_message(session, pair, item["latest"], config)
                    message = SimPairMessage(
                        pair_id=pair.id,
                        from_sim_id=sender_id,
                        to_sim_id=recipient_id,
                        content=content,
                        provider="openrouter",
                        model=config.pairing_openrouter_model,
                    )
                    session.add(message)
                    await session.flush()
                    await mcp_client.call_tool(
                        "send_sms",
                        {"from_sim_id": sender_id, "to_number": recipient["phone_number"], "text": content},
                    )
                    message.status = "sent"
                    message.sent_at = datetime.now(timezone.utc)
                    queue.status = "sent"
                    queue.sent_at = message.sent_at
                    queue.last_error = None
                    pair.sent_count += 1
                    session.add(SimPairHistory(
                        pair_id=pair.id,
                        event="message_sent",
                        details={"message_id": str(message.id), "from_sim_id": sender_id, "to_sim_id": recipient_id},
                    ))
                    if pair.sent_count == pair.target_messages:
                        session.add(SimPairHistory(
                            pair_id=pair.id,
                            event="target_reached",
                            details={"sent_count": pair.sent_count, "target_messages": pair.target_messages},
                        ))
                    await session.commit()
                    sent += 1
                except Exception as exc:
                    failed += 1
                    queue.attempts += 1
                    queue.last_error = str(exc)
                    if queue.attempts >= 3:
                        queue.status = "failed"
                    else:
                        queue.due_at = SimPairConversationService._retry_at(window)
                    session.add(SimPairMessage(
                        pair_id=pair.id,
                        from_sim_id=sender_id,
                        to_sim_id=recipient_id,
                        content="",
                        provider="openrouter",
                        model=config.pairing_openrouter_model,
                        status="failed",
                        error=str(exc),
                    ))
                    session.add(SimPairHistory(pair_id=pair.id, event="message_failed", details={"reason": str(exc)}))
                    await session.commit()

        return await SimPairConversationService._summary(session, sent, len(deferred), failed, len(held), len(pairs))

    @staticmethod
    def _select_batch(candidates, sims_by_id, last_activity, now, batch_size, cooldown_minutes):
        """Pick the messages this run may send.

        Three rules, applied in order: both SIMs must be reachable, a SIM speaks
        at most once per run, and a SIM waits out its cooldown between messages.
        Only the first is an anomaly worth recording against the queue item; the
        other two are ordinary pacing and simply wait for the next run.
        """
        chosen, deferred, held = [], [], []
        busy: set[int] = set()
        cooldown = timedelta(minutes=cooldown_minutes)
        for item in candidates:
            if len(chosen) >= batch_size:
                break
            pair_sims = (item["sender_id"], item["recipient_id"])
            sender, recipient = sims_by_id.get(pair_sims[0]), sims_by_id.get(pair_sims[1])
            if not SimPairConversationService._is_sendable(sender) or not SimPairConversationService._is_sendable(recipient):
                deferred.append((item, "A paired SIM is not IDLE"))
                continue
            if any(sim_id in busy for sim_id in pair_sims):
                held.append((item, "A paired SIM already spoke in this run"))
                continue
            if cooldown and any(
                last_activity.get(sim_id) is not None and now - last_activity[sim_id] < cooldown
                for sim_id in pair_sims
            ):
                held.append((item, "A paired SIM is still in its cooldown"))
                continue
            busy.update(pair_sims)
            chosen.append(item)
        return chosen, deferred, held

    @staticmethod
    def _quiet_window(config: Config):
        return quiet_hours.quiet_window(config)

    @staticmethod
    def _is_quiet(when: datetime, window) -> bool:
        return quiet_hours.is_quiet(when, window)

    @staticmethod
    def _shift_out_of_quiet(when: datetime, window) -> datetime:
        return quiet_hours.shift_out_of_quiet(when, window, SimPairConversationService.WAKE_SPREAD_MINUTES)

    @staticmethod
    def _retry_at(window: tuple[int, int] | None) -> datetime:
        return SimPairConversationService._shift_out_of_quiet(
            datetime.now(timezone.utc) + timedelta(minutes=SimPairConversationService.RETRY_DELAY_MINUTES),
            window,
        )

    @staticmethod
    async def _due_candidates(session, country: str | None, batch_size: int) -> list[dict]:
        """Read due queue items, pairs furthest from their target first."""
        now = datetime.now(timezone.utc)
        query = (
            select(SimPairMessageQueue, SimPair)
            .join(SimPair, SimPair.id == SimPairMessageQueue.pair_id)
            .where(
                SimPairMessageQueue.status == "pending",
                SimPairMessageQueue.due_at <= now,
                # A pair archived after its queue row was created must never
                # send: sync() creates fresh pairs for the same SIM once it is
                # eligible again, and this dead row would otherwise converse
                # on the SIM's behalf at the same time as the new pair.
                SimPair.status == "active",
            )
        )
        if country:
            query = query.where(SimPair.country == country.upper())
        rows = list((await session.execute(
            query.order_by(
                # False sorts first in Postgres: no pair reaches its target + 1
                # while another pair is still short of its target.
                (SimPair.sent_count >= SimPair.target_messages).asc(),
                SimPairMessageQueue.due_at,
                SimPairMessageQueue.created_at,
            ).limit(min(batch_size * SimPairConversationService.OVERFETCH, 200))
        )).all())
        candidates = []
        for queue, pair in rows:
            latest = await SimPairConversationService._latest_sent_message(session, pair.id)
            sender_id, recipient_id = SimPairConversationService._next_direction(pair, latest)
            candidates.append({
                "queue": queue,
                "pair": pair,
                "latest": latest,
                "sender_id": sender_id,
                "recipient_id": recipient_id,
            })
        return candidates

    @staticmethod
    async def _last_activity_by_sim(session, sim_ids) -> dict[int, datetime]:
        """When each SIM last took part in a sent message, sending or receiving."""
        if not sim_ids:
            return {}
        activity: dict[int, datetime] = {}
        for column in (SimPairMessage.from_sim_id, SimPairMessage.to_sim_id):
            rows = await session.execute(
                select(column, func.max(SimPairMessage.sent_at))
                .where(SimPairMessage.status == "sent", column.in_(sim_ids))
                .group_by(column)
            )
            for sim_id, last_at in rows.all():
                if last_at and (sim_id not in activity or last_at > activity[sim_id]):
                    activity[sim_id] = last_at
        return activity

    @staticmethod
    async def queue_stats(session) -> dict:
        now = datetime.now(timezone.utc)
        pending = await session.scalar(
            select(func.count()).select_from(SimPairMessageQueue).where(SimPairMessageQueue.status == "pending")
        )
        overdue = await session.scalar(
            select(func.count()).select_from(SimPairMessageQueue)
            .where(SimPairMessageQueue.status == "pending", SimPairMessageQueue.due_at <= now)
        )
        failed = await session.scalar(
            select(func.count()).select_from(SimPairMessageQueue).where(SimPairMessageQueue.status == "failed")
        )
        under_target = await session.scalar(
            select(func.count()).select_from(SimPair)
            .where(SimPair.status == "active", SimPair.sent_count < SimPair.target_messages)
        )
        return {
            "pending": pending or 0,
            "overdue": overdue or 0,
            "failed": failed or 0,
            "pairs_under_target": under_target or 0,
        }

    @staticmethod
    async def _summary(session, sent: int, skipped: int, failed: int, held: int, active_pairs: int, reason: str | None = None) -> dict:
        stats = await SimPairConversationService.queue_stats(session)
        summary = {
            "sent": sent,
            "skipped": skipped,
            "held": held,
            "failed": failed,
            "active_pairs": active_pairs,
            "queued": stats["pending"],
            "overdue": stats["overdue"],
            "pairs_under_target": stats["pairs_under_target"],
        }
        if reason:
            summary["reason"] = reason
        return summary

    @staticmethod
    async def _enqueue_pairs(session, pairs: list[SimPair], config: Config) -> None:
        """Create one future work item per pair when no pending item exists."""
        pair_ids = [pair.id for pair in pairs]
        if not pair_ids:
            return
        pending = set((await session.execute(
            select(SimPairMessageQueue.pair_id).where(
                SimPairMessageQueue.pair_id.in_(pair_ids),
                SimPairMessageQueue.status == "pending",
            )
        )).scalars())
        last_sent = dict((await session.execute(
            select(SimPairMessage.pair_id, func.max(SimPairMessage.sent_at))
            .where(SimPairMessage.pair_id.in_(pair_ids), SimPairMessage.status == "sent")
            .group_by(SimPairMessage.pair_id)
        )).all())
        now = datetime.now(timezone.utc)
        window = SimPairConversationService._quiet_window(config)
        for pair in pairs:
            if pair.id in pending:
                continue
            previous = last_sent.get(pair.id)
            due_at = now
            if previous:
                # The configured interval is a minimum, so jitter only ever adds
                # to it and the setting keeps meaning what it says.
                spread = random.uniform(*SimPairConversationService.JITTER_RANGE)
                due_at = previous + timedelta(minutes=config.pairing_conversation_interval_minutes * spread)
            # Shifting here rather than at send time keeps the queue honest: an
            # item held overnight reads as due in the morning, not as overdue.
            session.add(SimPairMessageQueue(pair_id=pair.id, due_at=SimPairConversationService._shift_out_of_quiet(due_at, window)))
        await session.commit()

    @staticmethod
    async def _list_sims(client) -> list[dict]:
        sims = []
        for skip in range(0, 10000, 100):
            page = SimPairingService._items(await client.call_tool("list_sims", {"limit": 100, "skip": skip}))
            sims.extend(page)
            if len(page) < 100:
                break
        return sims

    @staticmethod
    def _is_sendable(sim: dict | None) -> bool:
        return bool(sim and sim.get("state") == "IDLE" and sim.get("phone_number"))

    @staticmethod
    def _next_direction(pair: SimPair, latest: SimPairMessage | None) -> tuple[int, int]:
        if latest and latest.from_sim_id == pair.sim_a_id:
            return pair.sim_b_id, pair.sim_a_id
        return pair.sim_a_id, pair.sim_b_id

    @staticmethod
    async def _latest_sent_message(session, pair_id):
        return (await session.execute(
            select(SimPairMessage)
            .where(SimPairMessage.pair_id == pair_id, SimPairMessage.status == "sent")
            .order_by(SimPairMessage.sent_at.desc())
            .limit(1)
        )).scalar_one_or_none()

    @staticmethod
    async def _generate_message(session, pair: SimPair, latest: SimPairMessage | None, config: Config) -> str:
        history = list((await session.execute(
            select(SimPairMessage)
            .where(SimPairMessage.pair_id == pair.id, SimPairMessage.status == "sent")
            .order_by(SimPairMessage.sent_at.desc())
            .limit(SimPairConversationService.HISTORY_LIMIT)
        )).scalars())
        history.reverse()
        transcript = "\n".join(
            f"{pair.sim_a_name if item.from_sim_id == pair.sim_a_id else pair.sim_b_name}: {item.content}"
            for item in history
        ) or "(This is the first message.)"
        if latest and latest.from_sim_id == pair.sim_a_id:
            sender_name, recipient_name = pair.sim_b_name, pair.sim_a_name
        else:
            sender_name, recipient_name = pair.sim_a_name, pair.sim_b_name
        prompt = (
            "Write one short French SMS continuing a fictional, consensual conversation between two adult test personas. "
            f"The sender is {sender_name}, writing to {recipient_name}; the conversation topic is {pair.topic}. "
            # Without the recipient's name the model invents one, and the invented
            # name then persists through the transcript for the whole conversation.
            f"If you address the other person by name, use {recipient_name} and no other name. "
            "Use the supplied context naturally. Keep it under 240 characters. Do not request money, credentials, personal data, or contact with third parties. "
            "Do not claim real-world facts. Return only the SMS text itself: no speaker label, no name prefix, no quotation marks, no markdown.\n\n"
            f"Conversation so far:\n{transcript}"
        )
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=decrypt_value(config.pairing_openrouter_api_key))
        response = None
        for attempt in range(3):
            try:
                response = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=config.pairing_openrouter_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8,
                    max_tokens=120,
                )
                break
            except RateLimitError:
                if attempt == 2:
                    raise
                await asyncio.sleep(5 * (attempt + 1))
        assert response is not None
        content = SimPairConversationService._clean_generated(
            response.choices[0].message.content, sender_name, recipient_name
        )
        if not content or len(content) > 240:
            raise RuntimeError("OpenRouter returned an invalid SMS")
        if SimPairConversationService.MACHINE_LABEL_PATTERN.search(content):
            raise RuntimeError("Generated SMS contains a machine-looking label")
        return content

    @staticmethod
    def _clean_generated(raw: str | None, sender_name: str, recipient_name: str) -> str:
        """Strip what the model copies from the transcript format.

        The transcript is rendered as `Name: text`, so the model tends to answer
        in the same shape. A real SMS starting with "Koffi: " is exactly the kind
        of artifact this traffic must not carry.
        """
        content = (raw or "").strip().strip('"').strip()
        # A leaked prefix already stored in history renders in the transcript as
        # "Koffi: Koffi: ...", which cues the model harder than a single one, so
        # strip repeatedly rather than once. Bounded: this must never loop on
        # a name that is itself a colon.
        for _ in range(4):
            for name in (sender_name, recipient_name):
                prefix = f"{name}:"
                if name and content.lower().startswith(prefix.lower()):
                    content = content[len(prefix):].lstrip()
                    break
            else:
                break
        return content.strip().strip('"').strip()
