import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import itertools
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, update

from app.models import Config, McpServer, SimPair, SimPairHistory, SimPairMessage, SimPairMessageQueue
from app.services.sim_pair_conversation_service import SimPairConversationService as Service
from app.utils.crypto import encrypt_value

MODULE = "app.services.sim_pair_conversation_service"


class _FakeMcpClient:
    """Stands in for the TmLite FastMCP client and records every send_sms."""

    def __init__(self, recorder):
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, args):
        self._recorder.append((name, args))
        return []


@contextmanager
def _tmlite(sims, contents=None):
    """Patch the two outbound dependencies: TmLite and OpenRouter."""
    sent_sms = []
    texts = iter(contents) if contents is not None else (f"Message {n}" for n in itertools.count(1))

    def _create(**kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = next(texts)
        return response

    openai_client = MagicMock()
    openai_client.chat.completions.create.side_effect = _create

    with (
        patch(f"{MODULE}.Client", lambda transport: _FakeMcpClient(sent_sms)),
        patch(f"{MODULE}.OpenAI", MagicMock(return_value=openai_client)),
        patch.object(Service, "_list_sims", new=AsyncMock(return_value=sims)),
    ):
        yield sent_sms


def _sim(sim_id: int, state: str = "IDLE") -> dict:
    return {"id": sim_id, "state": state, "phone_number": f"+22500000{sim_id}"}


async def _configure(session, **overrides):
    settings = {
        "pairing_openrouter_api_key": encrypt_value("or-test-key"),
        "pairing_conversation_enabled": True,
        "pairing_conversation_interval_minutes": 30,
        "pairing_target_messages": 10,
        "pairing_max_messages_per_run": 10,
        # The cooldown and the quiet window have their own unit tests. Neutralised
        # here so these tests do not depend on the wall clock.
        "pairing_sim_cooldown_minutes": 0,
        "pairing_quiet_hours_enabled": False,
    }
    settings.update(overrides)
    config = Config(**settings)
    session.add(config)
    session.add(McpServer(name="TmLite", transport="http", url="http://tmlite.test/mcp", enabled=True))
    await session.commit()
    return config


async def _pair(session, a=1, b=2, sent_count=0, target=10) -> SimPair:
    pair = SimPair(
        id=uuid.uuid4(), sim_a_id=a, sim_b_id=b, sim_a_name=f"Aminata{a}", sim_b_name=f"Ousmane{b}",
        country="CI", group_a="love", group_b="love", topic="love",
        target_messages=target, sent_count=sent_count,
    )
    session.add(pair)
    await session.commit()
    return pair


async def _messages(session, pair_id=None):
    query = select(SimPairMessage).order_by(SimPairMessage.created_at)
    if pair_id:
        query = query.where(SimPairMessage.pair_id == pair_id)
    return list((await session.execute(query)).scalars())


async def _age_the_conversation(session, hours=1):
    """Push every sent message back in time so the next one becomes due,
    keeping their relative order intact."""
    await session.execute(update(SimPairMessage).values(sent_at=SimPairMessage.sent_at - timedelta(hours=hours)))
    await session.commit()


async def test_a_conversation_starts_with_sim_a(session):
    await _configure(session)
    pair = await _pair(session)

    with _tmlite([_sim(1), _sim(2)]) as sent_sms:
        result = await Service.run_due(session)

    assert result["sent"] == 1
    assert [name for name, _ in sent_sms] == ["send_sms"]
    assert sent_sms[0][1] == {"from_sim_id": 1, "to_number": "+225000002", "text": "Message 1"}

    messages = await _messages(session)
    assert [(m.from_sim_id, m.to_sim_id, m.status) for m in messages] == [(1, 2, "sent")]
    await session.refresh(pair)
    assert pair.sent_count == 1

    queue = list((await session.execute(select(SimPairMessageQueue))).scalars())
    assert [item.status for item in queue] == ["sent"]


async def test_the_conversation_continues_from_the_other_sim(session):
    await _configure(session)
    pair = await _pair(session)

    with _tmlite([_sim(1), _sim(2)]):
        await Service.run_due(session)
        await _age_the_conversation(session)
        result = await Service.run_due(session)

    assert result["sent"] == 1
    messages = await _messages(session)
    assert [(m.from_sim_id, m.to_sim_id) for m in messages] == [(1, 2), (2, 1)]
    await session.refresh(pair)
    assert pair.sent_count == 2


async def test_a_pair_reaches_its_target_alternating_five_and_five(session):
    await _configure(session)
    pair = await _pair(session)

    with _tmlite([_sim(1), _sim(2)]):
        for turn in range(10):
            result = await Service.run_due(session)
            assert result["sent"] == 1, f"turn {turn}: {result}"
            await _age_the_conversation(session)

    messages = await _messages(session)
    senders = [m.from_sim_id for m in messages]
    assert len(messages) == 10
    assert senders == [1, 2] * 5, senders
    assert senders.count(1) == 5 and senders.count(2) == 5
    assert all(m.status == "sent" for m in messages)
    assert [m.content for m in messages] == [f"Message {n}" for n in range(1, 11)]

    await session.refresh(pair)
    assert pair.sent_count == pair.target_messages == 10

    events = [e.event for e in (await session.execute(
        select(SimPairHistory).where(SimPairHistory.pair_id == pair.id)
    )).scalars()]
    # Crossing the target is recorded exactly once, not on every later message.
    assert events.count("target_reached") == 1
    assert events.count("message_sent") == 10


async def test_a_pair_below_target_is_served_before_one_that_reached_it(session):
    await _configure(session, pairing_max_messages_per_run=1)
    done = await _pair(session, a=1, b=2, sent_count=10)
    starting = await _pair(session, a=3, b=4, sent_count=0)
    # The finished pair has been waiting longer, so plain FIFO would pick it.
    done.created_at = datetime.now(timezone.utc) - timedelta(days=1)
    await session.commit()

    with _tmlite([_sim(1), _sim(2), _sim(3), _sim(4)]) as sent_sms:
        result = await Service.run_due(session)

    assert result["sent"] == 1
    assert sent_sms[0][1]["from_sim_id"] == 3
    assert (await _messages(session, starting.id)) != []
    assert (await _messages(session, done.id)) == []


async def test_quiet_hours_pause_sending(session):
    now = datetime.now(timezone.utc)
    await _configure(
        session,
        pairing_quiet_hours_enabled=True,
        pairing_quiet_start_hour=now.hour,
        pairing_quiet_end_hour=(now.hour + 1) % 24,
    )
    await _pair(session)

    with _tmlite([_sim(1), _sim(2)]) as sent_sms:
        result = await Service.run_due(session)

    assert result["sent"] == 0
    assert "Quiet hours" in result["reason"]
    assert sent_sms == []
    assert await _messages(session) == []
    # The schedule is still maintained overnight, only delivery stops.
    assert list((await session.execute(select(SimPairMessageQueue))).scalars()) != []


async def test_sending_resumes_outside_the_quiet_window(session):
    now = datetime.now(timezone.utc)
    await _configure(
        session,
        pairing_quiet_hours_enabled=True,
        pairing_quiet_start_hour=(now.hour + 2) % 24,
        pairing_quiet_end_hour=(now.hour + 3) % 24,
    )
    await _pair(session)

    with _tmlite([_sim(1), _sim(2)]) as sent_sms:
        result = await Service.run_due(session)

    assert result["sent"] == 1
    assert len(sent_sms) == 1


async def test_automation_disabled_sends_nothing(session):
    await _configure(session, pairing_conversation_enabled=False)
    await _pair(session)

    with _tmlite([_sim(1), _sim(2)]) as sent_sms:
        result = await Service.run_due(session)

    assert result == {"sent": 0, "skipped": 0, "failed": 0, "reason": "Conversation automation is disabled"}
    assert sent_sms == []


async def test_an_unavailable_sim_defers_the_conversation(session):
    await _configure(session)
    await _pair(session)

    with _tmlite([_sim(1), _sim(2, state="BUSY")]) as sent_sms:
        result = await Service.run_due(session)

    assert result["sent"] == 0 and result["skipped"] == 1
    assert sent_sms == []
    item = (await session.execute(select(SimPairMessageQueue))).scalar_one()
    assert item.status == "pending"
    assert item.last_error == "A paired SIM is not IDLE"
    assert item.due_at > datetime.now(timezone.utc)


async def test_an_invalid_generation_is_recorded_and_retried(session):
    await _configure(session)
    pair = await _pair(session)

    with _tmlite([_sim(1), _sim(2)], contents=["x" * 300]) as sent_sms:
        result = await Service.run_due(session)

    assert result["sent"] == 0 and result["failed"] == 1
    assert sent_sms == []
    failure = (await _messages(session))[0]
    assert failure.status == "failed"
    assert "invalid SMS" in failure.error
    item = (await session.execute(select(SimPairMessageQueue))).scalar_one()
    assert item.status == "pending" and item.attempts == 1
    await session.refresh(pair)
    assert pair.sent_count == 0


async def test_generate_message_rejects_a_machine_looking_label(session):
    """A generated SMS naming a SIM ("SIM 882") is the single most obvious
    tell to a carrier's fraud detection that this traffic is machine-driven,
    so it must be rejected rather than delivered — whatever produced it."""
    config = await _configure(session)
    pair = await _pair(session)

    with _tmlite([_sim(1), _sim(2)], contents=["SIM 882, comment vas-tu ?"]):
        with pytest.raises(RuntimeError, match="machine-looking label"):
            await Service._generate_message(session, pair, None, config)


async def test_generate_message_accepts_the_same_message_without_the_label(session):
    config = await _configure(session)
    pair = await _pair(session)

    with _tmlite([_sim(1), _sim(2)], contents=["Coucou, comment vas-tu ?"]):
        content = await Service._generate_message(session, pair, None, config)

    assert content == "Coucou, comment vas-tu ?"


async def test_an_archived_pairs_due_queue_row_is_not_sent(session):
    """Both SIMs are IDLE and the row is due, so nothing but the archived
    status of the pair stops it from being sent. This isolates the guard
    from the ordinary IDLE check, which would otherwise mask a regression."""
    await _configure(session)
    active_pair = await _pair(session, a=1, b=2)
    # Give the active pair a recent sent message so _enqueue_pairs schedules
    # its next turn in the future rather than immediately, keeping the run's
    # only due candidate the archived pair below.
    session.add(SimPairMessage(
        pair_id=active_pair.id, from_sim_id=1, to_sim_id=2, content="hi",
        provider="openrouter", model="m", status="sent", sent_at=datetime.now(timezone.utc),
    ))
    await session.commit()

    archived_pair = await _pair(session, a=3, b=4)
    archived_pair.status = "archived"
    await session.commit()
    session.add(SimPairMessageQueue(
        pair_id=archived_pair.id, due_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    ))
    await session.commit()

    with _tmlite([_sim(1), _sim(2), _sim(3), _sim(4)]) as sent_sms:
        result = await Service.run_due(session)

    assert result["sent"] == 0
    assert sent_sms == []
    queue = (await session.execute(
        select(SimPairMessageQueue).where(SimPairMessageQueue.pair_id == archived_pair.id)
    )).scalar_one()
    assert queue.status == "pending"
