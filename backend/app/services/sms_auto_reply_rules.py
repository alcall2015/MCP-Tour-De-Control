"""Who gets an automatic reply, and what it says. No I/O lives here."""
import re

# Every attempt that did not become a conversation. The three differ in how the
# leg ended, not in whether the person was reached. COMPLETED with a duration is
# a real conversation and is never followed up.
UNANSWERED_STATUSES = {"MISSED", "CANCELLED", "REJECTED"}


def digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


# Floor for suffix comparisons. Real fleet numbers are 9 digits (Guinea, e.g.
# 614966686) or 10 digits (Ivory Coast, e.g. 0748524199), so 8 digits rejects
# malformed data (e.g. a stray "1" in a SIM row's phone_number) without ever
# rejecting a real number.
MIN_MATCH_DIGITS = 8


def same_number(a, b) -> bool:
    """True if two values are the same subscriber, regardless of the format
    each source used (country code, leading zero, ...), via digit-only suffix
    matching. Every comparison in this module must go through here — the
    TmLite API's number formats are inconsistent, so exact equality is never
    correct. Inputs shorter than MIN_MATCH_DIGITS never match, so one
    malformed short number can't silently swallow a whole number range."""
    da, db = digits(a), digits(b)
    if len(da) < MIN_MATCH_DIGITS or len(db) < MIN_MATCH_DIGITS:
        return False
    return da.endswith(db) or db.endswith(da)


# Floor for whether a value is a plausible mobile destination at all -- a
# different question from same_number()'s "are these two values the same
# subscriber", which is what MIN_MATCH_DIGITS governs; the two floors may
# need to move independently, so they are kept as separate constants. Guinea
# national numbers are 9 digits and Ivory Coast national numbers are 10, so 8
# is a safety margin below the shortest legitimate case: it never rejects a
# real number, while rejecting carrier short codes (3-6 digits).
MIN_DESTINATION_DIGITS = 8


def is_messageable_destination(value) -> bool:
    """True if a value could plausibly be a real person's mobile number,
    rather than carrier/system traffic that cannot be messaged back. Both
    conditions are required: an alphanumeric sender ID (e.g. "PASS_1GB", a
    promo) fails the no-alphabetic-characters check, and a short code (e.g.
    "8117", a balance notice) fails the digit-count check. A real number
    never contains letters, in any format the API returns it."""
    text = str(value or "")
    if any(ch.isalpha() for ch in text):
        return False
    return len(digits(text)) >= MIN_DESTINATION_DIGITS


def fleet_numbers(sims: list[dict]) -> set[str]:
    return {digits(s.get("phone_number")) for s in sims if digits(s.get("phone_number"))}


def is_fleet_number(number: str, fleet: set[str]) -> bool:
    return any(same_number(number, owned) for owned in fleet)


def whatsapp_for(target_number: str, calls: list[dict]) -> str | None:
    matches = [c for c in calls if same_number(target_number, c.get("callee")) and c.get("caller")]
    if not matches:
        return None
    return max(matches, key=lambda c: c.get("at") or "")["caller"]


def sms_triggers(messages: list[dict], fleet: set[str], calls: list[dict]) -> list[dict]:
    triggers = []
    for message in messages:
        if not is_messageable_destination(message["from_number"]):
            continue
        if is_fleet_number(message["from_number"], fleet):
            continue
        triggers.append({
            "ref": message["ref"],
            "kind": "sms",
            "sim_id": message["sim_id"],
            "to_number": message["from_number"],
            "whatsapp": whatsapp_for(message["from_number"], calls),
        })
    return triggers


def missed_call_trigger(calls: list[dict], fleet: set[str],
                        index: dict[tuple[str, int], int]) -> dict | None:
    candidates = [
        c for c in calls
        if c.get("status") in UNANSWERED_STATUSES
        and not (c.get("duration") or 0)
        and c.get("callee")
        and is_messageable_destination(c["callee"])
        and not is_fleet_number(c["callee"], fleet)
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda c: c.get("at") or "")
    return {
        "ref": latest["ref"],
        "kind": "missed_call",
        # The CDR has no SIM id; only (gateway, slot) can resolve it.
        "sim_id": index.get((latest.get("gateway"), latest.get("slot"))),
        "to_number": latest["callee"],
        "whatsapp": latest.get("caller"),
    }


def drop_recent_recipients(triggers: list[dict], recent: set[str]) -> list[dict]:
    """One person, one message per cooldown — whatever number format each
    source used, and however many times they were called."""
    kept = []
    for trigger in triggers:
        target = trigger["to_number"]
        target_digits = digits(target)
        if not target_digits:
            continue
        # Against the recipients already kept in this batch, compare with
        # same_number() like everywhere else: the same person often appears
        # twice in one run — once as an SMS sender, once as the most recent
        # unanswered call — under two different formats, and digit equality
        # would let both through as two identical messages. same_number()
        # never matches values shorter than MIN_MATCH_DIGITS, so those still
        # fall back to exact digit equality.
        if any(same_number(target, k["to_number"]) or digits(k["to_number"]) == target_digits
               for k in kept):
            continue
        if any(same_number(target, r) for r in recent):
            continue
        kept.append(trigger)
    return kept


def render(template: str, whatsapp: str) -> str:
    return template.replace("{whatsapp}", whatsapp)
