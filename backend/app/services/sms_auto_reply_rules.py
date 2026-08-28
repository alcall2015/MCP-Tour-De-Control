"""Who gets an automatic reply, and what it says. No I/O lives here."""
import re

# Every attempt that did not become a conversation. The three differ in how the
# leg ended, not in whether the person was reached. COMPLETED with a duration is
# a real conversation and is never followed up.
UNANSWERED_STATUSES = {"MISSED", "CANCELLED", "REJECTED"}


def digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def fleet_numbers(sims: list[dict]) -> set[str]:
    return {digits(s.get("phone_number")) for s in sims if digits(s.get("phone_number"))}


def is_fleet_number(number: str, fleet: set[str]) -> bool:
    target = digits(number)
    if not target:
        return False
    return any(target.endswith(owned) or owned.endswith(target) for owned in fleet if owned)


def whatsapp_for(target_number: str, calls: list[dict]) -> str | None:
    target = digits(target_number)
    matches = [c for c in calls if digits(c.get("callee")) == target and c.get("caller")]
    if not matches:
        return None
    return max(matches, key=lambda c: c.get("at") or "")["caller"]


def sms_triggers(messages: list[dict], fleet: set[str], calls: list[dict]) -> list[dict]:
    triggers = []
    for message in messages:
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
    recent_digits = {digits(n) for n in recent if digits(n)}
    kept, seen = [], set()
    for trigger in triggers:
        target = digits(trigger["to_number"])
        if not target or target in seen:
            continue
        if any(target.endswith(r) or r.endswith(target) for r in recent_digits):
            continue
        seen.add(target)
        kept.append(trigger)
    return kept


def render(template: str, whatsapp: str) -> str:
    return template.replace("{whatsapp}", whatsapp)
