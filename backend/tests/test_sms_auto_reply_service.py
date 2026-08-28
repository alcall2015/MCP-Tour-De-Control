import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Config, McpServer, SmsReply
from app.services.sms_auto_reply_service import SmsAutoReplyService

MODULE = "app.services.sms_auto_reply_service"

# Every call_tool invocation across every test in this module lands here too,
# regardless of which fake instance handled it. `_recorded_args` just reads it.
_ALL_CALLS: list = []

DEFAULT_SIMS = [
    {"id": 872, "phone_number": "0748524199", "gateway_name": "CIV-RED-3", "slot": 2, "state": "IDLE"},
]


class _Content:
    """Stands in for the MCP TextContent item: `result[0].text` is JSON."""

    def __init__(self, data):
        self.text = json.dumps(data)


class _FakeMcpClient:
    """Stands in for the TmLite FastMCP client. Records every send_sms."""

    def __init__(self, sms, calls, sims, sent, fail_send_to=(), on_send=None):
        self._sms, self._calls, self._sims, self._sent = sms, calls, sims, sent
        self._fail_send_to = set(fail_send_to)
        self._on_send = on_send

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, args):
        _ALL_CALLS.append((name, args))
        if name == "send_sms":
            if self._on_send:
                # Observes the world as it is *while* the send is in flight.
                await self._on_send()
            if args["to_number"] in self._fail_send_to:
                raise RuntimeError("gateway refused the message")
            self._sent.append((name, args))
            return [_Content({})]
        if name == "list_sims":
            return [_Content(self._sims)]
        if name == "list_calls":
            return [_Content(self._calls)]
        if name == "list_sms":
            return [_Content(self._sms)]
        return [_Content([])]


@contextmanager
def _tmlite(sms=None, calls=None, sims=None, fail_send_to=(), on_send=None):
    """Patch the one outbound dependency: TmLite."""
    _ALL_CALLS.clear()
    sent: list = []
    with patch(f"{MODULE}.Client", lambda transport: _FakeMcpClient(
        sms or [], calls or [], sims if sims is not None else DEFAULT_SIMS, sent,
        fail_send_to, on_send,
    )):
        yield sent


@contextmanager
def _recorded_args():
    """Extends whichever `_tmlite` fake is active to expose (tool, args) for
    every call_tool, not just send_sms."""
    yield _ALL_CALLS


async def _configure(session, **overrides):
    settings = {
        "sms_autoreply_enabled": True,
        "pairing_quiet_hours_enabled": False,
    }
    settings.update(overrides)
    config = Config(**settings)
    session.add(config)
    session.add(McpServer(name="TmLite", transport="http", url="http://tmlite.test/mcp", enabled=True))
    await session.commit()
    return config


def _sms(id, sim_card_id, sender, minutes_ago=0):
    # Relative to "now" so the client-side SMS window never has to know
    # wall-clock skew between when this file was written and when the tests
    # run. `minutes_ago` places a message outside the configured window.
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).replace(tzinfo=None).isoformat()
    return {"id": id, "sim_card_id": sim_card_id, "sender": sender, "body": "hi", "received_at": at}


def _call(caller, callee, at="2026-08-28T12:00:00"):
    # An already-answered call: proof of a WhatsApp contact, not itself an
    # unanswered-call trigger. Real TmLite rows always carry `uuid`, which
    # normalize_call prefers over `id` — so the trigger_ref built here has the
    # production shape.
    return {"id": f"{caller}-{callee}-{at}", "uuid": f"u-{caller}-{callee}-{at}",
            "caller": caller, "callee": callee, "status": "COMPLETED",
            "duration": 30, "gateway_name": "CIV-RED-3", "sim_card_slot": 2, "started_at": at}


def _missed(caller, callee, at, status="MISSED", duration=0, gateway="CIV-RED-3", slot=2):
    return {"id": f"{caller}-{callee}-{at}", "uuid": f"u-{caller}-{callee}-{at}",
            "caller": caller, "callee": callee, "status": status,
            "duration": duration, "gateway_name": gateway, "sim_card_slot": slot, "started_at": at}


async def test_a_reply_goes_out_from_the_receiving_sim(session):
    await _configure(session)
    with _tmlite(sms=[_sms("1", 872, "0700003331")],
                 calls=[_call("33600000002", "0700003331")]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 1
    assert sent[0][1] == {"from_sim_id": 872, "to_number": "0700003331",
                          "text": "Salut, j'essaye de te joindre. Ecris-moi sur WhatsApp au 33600000002."}


async def test_the_same_trigger_is_never_answered_twice(session):
    await _configure(session)
    payload = dict(sms=[_sms("1", 872, "0700003331")], calls=[_call("33600000002", "0700003331")])
    with _tmlite(**payload):
        await SmsAutoReplyService.run(session)
    with _tmlite(**payload) as sent:
        second = await SmsAutoReplyService.run(session)
    assert second["sent"] == 0 and sent == []


async def test_the_ref_dedupe_alone_stops_a_repeat_once_the_cooldown_has_expired(session):
    # test_the_same_trigger_is_never_answered_twice passes even with the
    # trigger_ref dedupe query deleted, because the 24h recipient cooldown
    # alone also suppresses the second run. Here the stored reply's
    # created_at is pushed outside the cooldown window before the second run,
    # so only the trigger_ref filter can be responsible for the trigger being
    # skipped a second time. This is the scenario that matters in production
    # whenever the lookback window is configured longer than the cooldown.
    config = await _configure(session)
    payload = dict(sms=[_sms("1", 872, "0700003331")], calls=[_call("33600000002", "0700003331")])
    with _tmlite(**payload):
        first = await SmsAutoReplyService.run(session)
    assert first["sent"] == 1

    row = (await session.execute(select(SmsReply))).scalar_one()
    row.created_at = datetime.now(timezone.utc) - timedelta(
        hours=config.sms_autoreply_recipient_cooldown_hours + 1)
    await session.commit()

    with _tmlite(**payload) as sent:
        second = await SmsAutoReplyService.run(session)
    # Not just "sent == 0": if the trigger_ref filter were gone, the trigger
    # would still reach _store(), which would then hit the DB's UNIQUE
    # constraint on trigger_ref and report a failure instead of silently
    # doing nothing. Asserting failed == 0 too is what forces the trigger to
    # have been dropped before ever attempting to claim it.
    assert second["sent"] == 0 and second["failed"] == 0 and sent == []


async def test_an_unresolvable_whatsapp_number_is_skipped_not_sent(session):
    await _configure(session)
    with _tmlite(sms=[_sms("1", 872, "0788888888")], calls=[]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and result["skipped"] == 1 and sent == []
    row = (await session.execute(select(SmsReply))).scalar_one()
    assert row.status == "skipped" and row.error == "No caller found for this number"


async def test_quiet_hours_stop_every_send(session):
    now = datetime.now(timezone.utc)
    await _configure(session, pairing_quiet_hours_enabled=True,
                     pairing_quiet_start_hour=now.hour, pairing_quiet_end_hour=(now.hour + 1) % 24)
    with _tmlite(sms=[_sms("1", 872, "0700003331")], calls=[_call("33600000002", "0700003331")]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and "Quiet hours" in result["reason"] and sent == []


async def test_disabled_does_nothing(session):
    # The data below is fully sendable: the same payload sends one message when
    # the flag is on. Only the gate stops it.
    await _configure(session, sms_autoreply_enabled=False)
    with _tmlite(sms=[_sms("1", 872, "0700003331")],
                 calls=[_call("33600000002", "0700003331")]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and sent == []
    assert result["reason"] == "SMS auto-reply is disabled"
    assert (await session.execute(select(SmsReply))).scalars().all() == []


async def test_one_person_called_twice_receives_a_single_message(session):
    await _configure(session)
    # The same callee, two distinct MISSED calls — the real production pattern.
    calls = [_missed("33321576643", "+2250708243098", "2026-08-28T13:19:53"),
             _missed("33321576643", "+2250708243098", "2026-08-28T13:27:24")]
    with _tmlite(sms=[], calls=calls) as sent:
        first = await SmsAutoReplyService.run(session)
    assert first["sent"] == 1 and len(sent) == 1
    with _tmlite(sms=[], calls=calls) as sent:
        second = await SmsAutoReplyService.run(session)
    assert second["sent"] == 0 and sent == []


async def test_a_cancelled_or_rejected_call_is_followed_up(session):
    await _configure(session)
    calls = [_missed("33600000001", "+2250700001111", "2026-08-28T13:00:00", status="REJECTED")]
    with _tmlite(sms=[], calls=calls) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 1 and len(sent) == 1


async def test_an_answered_call_is_not_followed_up(session):
    await _configure(session)
    calls = [_missed("33600000001", "+2250700001111", "2026-08-28T13:00:00",
                     status="COMPLETED", duration=42)]
    with _tmlite(sms=[], calls=calls) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and sent == []


async def test_a_dry_run_previews_even_when_the_feature_is_disabled(session):
    # This is the whole point of dry_run: the feature ships disabled, and the
    # documented first step is to preview what it *would* send before ever
    # arming it. A dry run sends no SMS and writes no row by construction, so
    # gating it on sms_autoreply_enabled protects nothing while blocking the
    # only way to look before arming the unattended job.
    await _configure(session, sms_autoreply_enabled=False)
    with _tmlite(sms=[_sms("1", 872, "0700003331")], calls=[_call("33600000002", "0700003331")]) as sent:
        result = await SmsAutoReplyService.run(session, dry_run=True)
    assert sent == []
    assert result["previews"][0]["to_number"] == "0700003331"
    assert result["previews"][0]["content"] is not None
    assert (await session.execute(select(SmsReply))).scalars().all() == []


async def test_a_real_run_still_stays_gated_when_disabled(session):
    # Proves the enabled gate was narrowed to the real-run path, not removed
    # outright: with the exact same sendable payload that the dry-run test
    # above previews successfully, a real run must still refuse to send.
    await _configure(session, sms_autoreply_enabled=False)
    with _tmlite(sms=[_sms("1", 872, "0700003331")], calls=[_call("33600000002", "0700003331")]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and sent == []
    assert result["reason"] == "SMS auto-reply is disabled"
    assert (await session.execute(select(SmsReply))).scalars().all() == []


async def test_a_dry_run_sends_nothing_and_stores_nothing(session):
    await _configure(session)
    with _tmlite(sms=[_sms("1", 872, "0700003331")], calls=[_call("33600000002", "0700003331")]) as sent:
        result = await SmsAutoReplyService.run(session, dry_run=True)
    assert sent == [] and result["previews"][0]["to_number"] == "0700003331"
    assert (await session.execute(select(SmsReply))).scalars().all() == []


async def test_a_dry_run_never_previews_an_unsendable_message(session):
    await _configure(session)
    with _tmlite(sms=[_sms("1", 872, "0788888888")], calls=[]) as sent:
        result = await SmsAutoReplyService.run(session, dry_run=True)
    assert sent == []
    preview = result["previews"][0]
    assert preview["content"] is None
    assert preview["skip_reason"] == "No caller found for this number"


async def test_the_fetchers_ask_for_only_the_configured_window(session):
    await _configure(session, sms_autoreply_lookback_minutes=30)
    expected = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(tzinfo=None)
    with _tmlite(sms=[], calls=[]) as _, _recorded_args() as args:
        await SmsAutoReplyService.run(session)
    from_dates = [a["from_date"] for tool, a in args if tool == "list_calls"]
    assert from_dates, "list_calls was called without a window"
    # Naive: TmLite answers an offset-bearing from_date with a facade 500.
    assert "+" not in from_dates[0]
    asked = datetime.fromisoformat(from_dates[0])
    assert asked.tzinfo is None
    # And actually the configured window: 30 minutes back, not the 60-minute
    # default and not "now". The tolerance only absorbs test-run latency.
    assert abs((asked - expected).total_seconds()) < 5, from_dates[0]


async def test_a_message_older_than_the_window_is_not_answered(session):
    # list_sms takes no date filter, so the window is enforced here. Both
    # senders are equally sendable; only the timestamp separates them.
    await _configure(session, sms_autoreply_lookback_minutes=30)
    with _tmlite(sms=[_sms("fresh", 872, "0700003331"),
                      _sms("old", 872, "0700004442", minutes_ago=90)],
                 calls=[_call("33600000002", "0700003331"),
                        _call("33600000003", "0700004442")]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 1
    assert [args["to_number"] for _, args in sent] == ["0700003331"]
    assert (await session.execute(
        select(SmsReply.trigger_ref).where(SmsReply.trigger_ref == "sms:old")
    )).scalars().all() == []


async def test_a_call_whose_sim_cannot_be_resolved_is_skipped_not_sent(session):
    await _configure(session)
    # A gateway/slot pair absent from the SIM index: nothing tells us which SIM
    # took the call, so there is no defensible number to answer from.
    calls = [_missed("33600000001", "+2250700001111", "2026-08-28T13:00:00",
                     gateway="CIV-BLUE-9", slot=7)]
    with _tmlite(sms=[], calls=calls) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and result["skipped"] == 1 and sent == []
    row = (await session.execute(select(SmsReply))).scalar_one()
    assert row.status == "skipped" and row.error == "No SIM recorded for this contact"


async def test_a_dry_run_never_previews_a_call_with_no_resolved_sim(session):
    await _configure(session)
    calls = [_missed("33600000001", "+2250700001111", "2026-08-28T13:00:00",
                     gateway="CIV-BLUE-9", slot=7)]
    with _tmlite(sms=[], calls=calls) as sent:
        result = await SmsAutoReplyService.run(session, dry_run=True)
    assert sent == []
    preview = result["previews"][0]
    assert preview["content"] is None
    assert preview["skip_reason"] == "No SIM recorded for this contact"


async def test_an_empty_sim_list_stops_the_run(session):
    await _configure(session)
    # Inbound traffic from one of the operator's own SIMs (DEFAULT_SIMS). With
    # no fleet to compare against, is_fleet_number() answers False for
    # everything and the fleet would auto-reply to itself.
    with _tmlite(sms=[_sms("1", 872, "0748524199")],
                 calls=[_call("33600000002", "0748524199")], sims=[]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and sent == []
    assert "SIM" in result["reason"]
    assert (await session.execute(select(SmsReply))).scalars().all() == []


async def test_sims_with_unusable_numbers_also_stop_the_run(session):
    # A non-empty list_sims whose phone_number values are junk reduces to a
    # fleet that matches nothing, which is exactly as dangerous as an empty
    # list_sims: is_fleet_number() would answer False for everything and the
    # fleet's own SIM-pairing traffic would become a trigger. Two distinct
    # kinds of junk are covered here: values fleet_numbers() drops outright
    # (null, empty, digit-free), which used to be the only case tested; and a
    # short-but-nonzero value ("1") that survives fleet_numbers() into a
    # *non-empty* fleet but falls under MIN_MATCH_DIGITS, so same_number()
    # still matches nothing. A plain `not fleet` check would miss the second
    # case entirely, which is the gap this test guards against.
    await _configure(session)
    junk_sims = [
        {"id": 1, "phone_number": None, "gateway_name": "CIV-RED-1", "slot": 1, "state": "IDLE"},
        {"id": 2, "phone_number": "", "gateway_name": "CIV-RED-2", "slot": 2, "state": "IDLE"},
        {"id": 3, "phone_number": "n/a", "gateway_name": "CIV-RED-3", "slot": 3, "state": "IDLE"},
        {"id": 4, "phone_number": "1", "gateway_name": "CIV-RED-4", "slot": 4, "state": "IDLE"},
    ]
    with _tmlite(sms=[_sms("1", 872, "0748524199")],
                 calls=[_call("33600000002", "0748524199")], sims=junk_sims) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and sent == []
    assert "SIM" in result["reason"]
    assert (await session.execute(select(SmsReply))).scalars().all() == []


async def test_unprovisioned_sims_with_no_phone_number_are_ignored_not_stopped(session):
    # Production shape: spare/unprovisioned cards carry phone_number: None and
    # no SIM group. TmLite holds no number for them, so they are not sending
    # SMS whose sender we would need to recognise — they must not enter the
    # fleet set and must not block a run that otherwise has a perfectly usable
    # fleet number.
    await _configure(session)
    sims = DEFAULT_SIMS + [
        {"id": 772, "phone_number": None, "slot": 1, "state": "PENDING_CHECK",
         "sim_group_name": None, "gateway_name": "CIV-RED-1"},
        {"id": 771, "phone_number": None, "slot": 1, "state": "PENDING_CHECK",
         "sim_group_name": None, "gateway_name": "CIV-RED-2"},
        {"id": 467, "phone_number": None, "slot": 2, "state": "IDLE",
         "sim_group_name": None, "gateway_name": "CIV-RED-3"},
        {"id": 466, "phone_number": None, "slot": 3, "state": "IDLE",
         "sim_group_name": None, "gateway_name": "CIV-RED-4"},
        {"id": 234, "phone_number": None, "slot": 4, "state": "IDLE",
         "sim_group_name": None, "gateway_name": "CIV-RED-5"},
        {"id": 107, "phone_number": None, "slot": 5, "state": "IDLE",
         "sim_group_name": None, "gateway_name": "CIV-RED-6"},
    ]
    with _tmlite(sms=[_sms("1", 872, "0700003331")],
                 calls=[_call("33600000002", "0700003331")], sims=sims) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 1
    assert sent[0][1]["to_number"] == "0700003331"


async def test_the_trigger_is_committed_before_the_message_goes_out(session, setup_db):
    """A crash between send_sms returning and the outcome being written must
    not leave the trigger free to be answered again. Only a committed row
    survives that, so the claim is read from a second connection while the
    send is still in flight."""
    await _configure(session)
    seen: list = []

    async def _peek():
        maker = async_sessionmaker(setup_db, class_=AsyncSession, expire_on_commit=False)
        async with maker() as other:
            seen.append((await other.execute(select(SmsReply.status))).scalars().all())

    with _tmlite(sms=[_sms("1", 872, "0700003331")],
                 calls=[_call("33600000002", "0700003331")], on_send=_peek) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 1 and len(sent) == 1
    assert seen == [["sending"]], "the trigger was not committed before the send"
    row = (await session.execute(select(SmsReply))).scalar_one()
    assert row.status == "sent" and row.sent_at is not None


async def test_a_send_failure_is_recorded_on_the_claimed_row_and_the_batch_continues(session):
    await _configure(session)
    payload = dict(sms=[_sms("1", 872, "0700003331"), _sms("2", 872, "0700004442")],
                   calls=[_call("33600000002", "0700003331"),
                          _call("33600000003", "0700004442")])
    with _tmlite(**payload, fail_send_to={"0700003331"}) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["failed"] == 1 and result["sent"] == 1
    # The trigger after the failing one still got its turn.
    assert [args["to_number"] for _, args in sent] == ["0700004442"]
    rows = {r.to_number: r for r in (await session.execute(select(SmsReply))).scalars()}
    # One row per trigger: the failure updates its claim, it never inserts a
    # second row carrying the same trigger_ref.
    assert len(rows) == 2
    assert rows["0700003331"].status == "failed"
    assert "gateway refused" in rows["0700003331"].error
    assert rows["0700004442"].status == "sent"

    # And the failed attempt is not retried into a second unsolicited message.
    with _tmlite(**payload) as sent:
        second = await SmsAutoReplyService.run(session)
    assert second["sent"] == 0 and sent == []


async def test_sms_reply_defaults_to_sending_not_sent(session):
    """The service always passes status explicitly today, so this default is
    only a safety net for the next author who doesn't. It must never claim a
    message went out when none did."""
    reply = SmsReply(trigger_kind="sms", trigger_ref="sms:default-check", sim_id=1,
                     to_number="0700000000", whatsapp_number=None, content="x")
    session.add(reply)
    await session.commit()
    assert reply.status == "sending"


async def test_stats_counts_a_claim_whose_outcome_was_never_written(session):
    session.add(SmsReply(trigger_kind="sms", trigger_ref="sms:crashed", sim_id=872,
                         to_number="0700003331", whatsapp_number="33600000002",
                         content="x", status="sending"))
    await session.commit()
    stats = await SmsAutoReplyService.stats(session)
    assert stats["sending"] == 1
    assert stats["sent"] == 0 and stats["failed"] == 0 and stats["skipped"] == 0


async def test_one_sim_with_an_unusable_number_stops_the_whole_run(session):
    # The fleet guard has to hold for every SIM, not for the fleet on average.
    # This SIM's real MSISDN is unknown to us, so its own SIM-pairing traffic
    # would look like an outside contact and we would auto-reply to it. The
    # reason names how many rows are affected and their ids so the operator can
    # fix the TmLite data.
    await _configure(session)
    sims = DEFAULT_SIMS + [{"id": 903, "phone_number": "1", "gateway_name": "CIV-RED-4",
                            "slot": 4, "state": "IDLE"}]
    with _tmlite(sms=[_sms("1", 872, "0700003331")],
                 calls=[_call("33600000002", "0700003331")], sims=sims) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and sent == []
    assert "1 of 2" in result["reason"] and "903" in result["reason"]
    assert (await session.execute(select(SmsReply))).scalars().all() == []
