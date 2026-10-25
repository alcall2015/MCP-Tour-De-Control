from app.services.sms_auto_reply_rules import (
    drop_recent_recipients, fleet_numbers, is_fleet_number, is_messageable_destination,
    missed_call_trigger, render, sms_triggers, whatsapp_for,
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


def test_a_cdr_sim_id_wins_over_the_current_gateway_slot_mapping():
    call = _call("33600000001", "0700001111", "2026-08-28T10:00:00")
    call["sim_id"] = 987
    assert missed_call_trigger([call], FLEET, INDEX)["sim_id"] == 987


def test_a_recipient_messaged_recently_is_dropped():
    triggers = [{"ref": "call:1", "kind": "missed_call", "sim_id": 872,
                 "to_number": "+2250700002222", "whatsapp": "33600000002"}]
    # Same person, different formatting, already messaged.
    assert drop_recent_recipients(triggers, {"0700002222"}) == []
    assert drop_recent_recipients(triggers, {"0700009999"}) == triggers


def test_the_template_is_rendered_verbatim():
    assert render("Ecris-moi au {whatsapp}.", "33600000002") == "Ecris-moi au 33600000002."


def test_render_selects_one_of_the_configured_alternatives():
    template = "Salut {whatsapp}.\n---\nBonjour {whatsapp}."
    assert render(template, "33600000002") in {
        "Salut 33600000002.",
        "Bonjour 33600000002.",
    }


def test_is_messageable_destination_rejects_carrier_traffic():
    # Alphanumeric sender ID (a promo) and a short code (a balance notice):
    # neither is a person who can be messaged back.
    assert not is_messageable_destination("PASS_1GB")
    assert not is_messageable_destination("8117")


def test_is_messageable_destination_accepts_every_real_format():
    for number in ("+2250700007076", "+224610401035", "+2250714433777",
                   "0748524199", "629040718"):
        assert is_messageable_destination(number), number


def test_carrier_noise_never_becomes_an_sms_trigger():
    for sender in ("PASS_1GB", "8117"):
        messages = [{"ref": f"sms:{sender}", "sim_id": 872, "from_number": sender,
                     "text": "?", "at": "x"}]
        assert sms_triggers(messages, FLEET, []) == []


def test_real_sms_senders_in_every_format_become_triggers():
    # An empty fleet, deliberately: this is testing the destination
    # predicate, not fleet exclusion (which 0748524199 would otherwise hit,
    # since it is one of FLEET's own numbers).
    for number in ("+2250700007076", "+224610401035", "+2250714433777",
                   "0748524199", "629040718"):
        messages = [{"ref": f"sms:{number}", "sim_id": 872, "from_number": number,
                     "text": "?", "at": "x"}]
        refs = [t["ref"] for t in sms_triggers(messages, set(), [])]
        assert refs == [f"sms:{number}"], number


def test_carrier_noise_never_becomes_a_missed_call_trigger():
    for callee in ("PASS_1GB", "8117"):
        calls = [_call("33600000001", callee, "2026-08-28T10:00:00")]
        assert missed_call_trigger(calls, FLEET, INDEX) is None


def test_real_missed_call_callees_in_every_format_become_triggers():
    # An empty fleet for the same reason as the SMS-sender version above.
    for number in ("+2250700007076", "+224610401035", "+2250714433777",
                   "0748524199", "629040718"):
        calls = [_call("33600000001", number, "2026-08-28T10:00:00")]
        trigger = missed_call_trigger(calls, set(), INDEX)
        assert trigger is not None and trigger["to_number"] == number, number


def test_a_missed_call_to_a_short_code_is_never_followed_up():
    calls = [_call("33600000001", "8117", "2026-08-28T10:00:00")]
    assert missed_call_trigger(calls, FLEET, INDEX) is None


def test_one_person_in_two_formats_gets_one_message_in_a_single_run():
    # The same subscriber reaches us twice in one batch: once as an SMS sender
    # stored without the country code, once as the most recent unanswered call
    # stored with it. Only one message may go out.
    triggers = [
        {"ref": "sms:1", "kind": "sms", "sim_id": 872,
         "to_number": "0700002222", "whatsapp": "33600000002"},
        {"ref": "call:1", "kind": "missed_call", "sim_id": 872,
         "to_number": "+2250700002222", "whatsapp": "33600000002"},
    ]
    assert [t["ref"] for t in drop_recent_recipients(triggers, set())] == ["sms:1"]
