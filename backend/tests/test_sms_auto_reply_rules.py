from app.services.sms_auto_reply_rules import (
    drop_recent_recipients, fleet_numbers, is_fleet_number, missed_call_trigger,
    render, sms_triggers, whatsapp_for,
)

FLEET = fleet_numbers([{"phone_number": "0748524199"}, {"phone_number": "0705435020"}])
INDEX = {("CIV-RED-3", 2): 872}


def _call(caller, callee, at, status="MISSED", duration=0, gateway="CIV-RED-3", slot=2):
    return {"ref": f"call:{caller}-{callee}-{at}", "gateway": gateway, "slot": slot,
            "caller": caller, "callee": callee, "status": status, "duration": duration, "at": at}


def test_a_fleet_number_is_recognised_whatever_its_formatting():
    assert is_fleet_number("+2250748524199", FLEET)
    assert is_fleet_number("0748524199", FLEET)
    assert not is_fleet_number("0700003331", FLEET)


def test_whatsapp_for_resolves_across_number_formats():
    # Same person, one CDR stored with a country code, the other without.
    calls = [_call("33600000002", "+2250788542981", "2026-08-28T12:00:00")]
    assert whatsapp_for("0788542981", calls) == "33600000002"

    calls = [_call("33600000002", "0788542981", "2026-08-28T12:00:00")]
    assert whatsapp_for("+2250788542981", calls) == "33600000002"


def test_a_short_garbage_fleet_entry_never_matches_a_real_number():
    fleet = fleet_numbers([{"phone_number": "1"}])
    assert not is_fleet_number("0700003331", fleet)


def test_the_whatsapp_number_is_the_most_recent_caller_of_that_number():
    calls = [_call("33600000001", "0700003331", "2026-08-28T10:00:00"),
             _call("33600000002", "0700003331", "2026-08-28T12:00:00"),
             _call("33600000003", "0709999999", "2026-08-28T13:00:00")]
    assert whatsapp_for("0700003331", calls) == "33600000002"
    assert whatsapp_for("0711111111", calls) is None


def test_sms_from_the_fleet_never_becomes_a_trigger():
    calls = [_call("33600000002", "0700003331", "2026-08-28T12:00:00")]
    messages = [
        {"ref": "sms:1", "sim_id": 872, "from_number": "0700003331", "text": "?", "at": "x"},
        {"ref": "sms:2", "sim_id": 872, "from_number": "0705435020", "text": "?", "at": "x"},
    ]
    assert [t["ref"] for t in sms_triggers(messages, FLEET, calls)] == ["sms:1"]


def test_an_sms_with_no_resolvable_caller_is_kept_but_marked_unresolved():
    messages = [{"ref": "sms:3", "sim_id": 872, "from_number": "0788888888", "text": "?", "at": "x"}]
    assert sms_triggers(messages, FLEET, [])[0]["whatsapp"] is None


def test_only_the_most_recent_missed_call_is_taken():
    calls = [_call("33600000001", "0700001111", "2026-08-28T10:00:00"),
             _call("33600000002", "0700002222", "2026-08-28T12:00:00"),
             _call("33600000003", "0700003333", "2026-08-28T11:00:00", status="COMPLETED", duration=42)]
    trigger = missed_call_trigger(calls, FLEET, INDEX)
    assert trigger["to_number"] == "0700002222"
    assert trigger["whatsapp"] == "33600000002"
    assert trigger["sim_id"] == 872


def test_an_answered_call_is_never_followed_up():
    calls = [_call("33600000003", "0700003333", "2026-08-28T11:00:00", status="COMPLETED", duration=42)]
    assert missed_call_trigger(calls, FLEET, INDEX) is None


def test_every_unanswered_status_counts():
    # MISSED, CANCELLED and REJECTED all describe an attempt that did not
    # become a conversation, and all three are followed up.
    for status in ("MISSED", "CANCELLED", "REJECTED"):
        calls = [_call("33600000001", "0700001111", "2026-08-28T10:00:00", status=status)]
        assert missed_call_trigger(calls, FLEET, INDEX) is not None, status


def test_a_completed_call_with_a_duration_wins_over_nothing():
    # Only COMPLETED-with-audio is excluded, and it is excluded even when it is
    # the most recent row.
    calls = [_call("33600000001", "0700001111", "2026-08-28T10:00:00", status="CANCELLED"),
             _call("33600000002", "0700002222", "2026-08-28T12:00:00", status="COMPLETED", duration=42)]
    assert missed_call_trigger(calls, FLEET, INDEX)["to_number"] == "0700001111"


def test_a_call_from_an_unknown_gateway_slot_yields_no_sim():
    calls = [_call("33600000001", "0700001111", "2026-08-28T10:00:00", gateway="CIV-RED-9", slot=1)]
    assert missed_call_trigger(calls, FLEET, INDEX)["sim_id"] is None


def test_a_recipient_messaged_recently_is_dropped():
    triggers = [{"ref": "call:1", "kind": "missed_call", "sim_id": 872,
                 "to_number": "+2250700002222", "whatsapp": "33600000002"}]
    # Same person, different formatting, already messaged.
    assert drop_recent_recipients(triggers, {"0700002222"}) == []
    assert drop_recent_recipients(triggers, {"0700009999"}) == triggers


def test_the_template_is_rendered_verbatim():
    assert render("Ecris-moi au {whatsapp}.", "33600000002") == "Ecris-moi au 33600000002."
