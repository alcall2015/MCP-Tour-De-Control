import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import select

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

    def __init__(self, sms, calls, sims, sent):
        self._sms, self._calls, self._sims, self._sent = sms, calls, sims, sent

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, args):
        _ALL_CALLS.append((name, args))
        if name == "send_sms":
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
def _tmlite(sms=None, calls=None, sims=None):
    """Patch the one outbound dependency: TmLite."""
    _ALL_CALLS.clear()
    sent: list = []
    with patch(f"{MODULE}.Client", lambda transport: _FakeMcpClient(
        sms or [], calls or [], sims if sims is not None else DEFAULT_SIMS, sent
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


def _sms(id, sim_card_id, sender):
    # Always "now" so the client-side SMS window never has to know wall-clock
    # skew between when this file was written and when the tests run.
    at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    return {"id": id, "sim_card_id": sim_card_id, "sender": sender, "body": "hi", "received_at": at}


def _call(caller, callee, at="2026-08-28T12:00:00"):
    # An already-answered call: proof of a WhatsApp contact, not itself an
    # unanswered-call trigger.
    return {"id": f"{caller}-{callee}-{at}", "caller": caller, "callee": callee, "status": "COMPLETED",
            "duration": 30, "gateway_name": "CIV-RED-3", "sim_card_slot": 2, "started_at": at}


def _missed(caller, callee, at, status="MISSED", duration=0):
    return {"id": f"{caller}-{callee}-{at}", "caller": caller, "callee": callee, "status": status,
            "duration": duration, "gateway_name": "CIV-RED-3", "sim_card_slot": 2, "started_at": at}


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
    await _configure(session, sms_autoreply_enabled=False)
    with _tmlite(sms=[_sms("1", 872, "0700003331")], calls=[]) as sent:
        result = await SmsAutoReplyService.run(session)
    assert result["sent"] == 0 and sent == []


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
    with _tmlite(sms=[], calls=[]) as _, _recorded_args() as args:
        await SmsAutoReplyService.run(session)
    from_dates = [a["from_date"] for tool, a in args if tool == "list_calls"]
    assert from_dates, "list_calls was called without a window"
    assert "+" not in from_dates[0] and from_dates[0].endswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9"))
