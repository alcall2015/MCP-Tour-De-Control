"""Normalise TmLite payloads into the shapes this application reasons about.

TmLite is an external service whose field names are not guaranteed. Every
assumption about its wire format lives here and nowhere else, so a rename
upstream breaks one file with one test rather than the whole feature.
"""

from datetime import datetime, timezone


def _first(raw: dict, *names):
    for name in names:
        value = raw.get(name)
        if value not in (None, ""):
            return value
    return None


def normalize_sms(raw: dict) -> dict | None:
    ref = _first(raw, "id", "uuid", "message_id")
    sim_id = _first(raw, "sim_card_id", "sim_id")
    sender = _first(raw, "sender", "from_number", "from", "msisdn")
    if ref is None or sim_id is None or sender is None:
        return None
    return {
        "ref": f"sms:{ref}",
        "sim_id": int(sim_id),
        "from_number": str(sender),
        "text": str(_first(raw, "body", "text", "content") or ""),
        "at": str(_first(raw, "received_at", "created_at") or ""),
    }


def normalize_call(raw: dict) -> dict | None:
    """A CDR row carries no SIM id — only gateway and slot. Resolving the SIM
    is `sim_index`'s job, so this shape deliberately has no `sim_id` key."""
    ref = _first(raw, "uuid", "id")
    caller, callee = _first(raw, "caller"), _first(raw, "callee")
    if ref is None or caller is None or callee is None:
        return None
    slot = _first(raw, "sim_card_slot", "slot")
    duration = raw.get("duration")
    return {
        "ref": f"call:{ref}",
        "gateway": str(_first(raw, "gateway_name") or ""),
        "slot": int(slot) if slot is not None else None,
        "caller": str(caller),
        "callee": str(callee),
        "status": str(raw.get("status") or ""),
        "duration": int(duration) if duration is not None else None,
        "at": str(_first(raw, "started_at", "answered_at", "finalized_at") or ""),
    }


def sim_index(sims: list[dict]) -> dict[tuple[str, int], int]:
    """(gateway_name, slot) -> sim id. The only bridge between a CDR row and
    the SIM that handled it."""
    index = {}
    for sim in sims:
        gateway, slot, sim_id = sim.get("gateway_name"), sim.get("slot"), sim.get("id")
        if gateway and slot is not None and sim_id is not None:
            index[(str(gateway), int(slot))] = int(sim_id)
    return index


def naive_iso(when: datetime) -> str:
    """TmLite's from_date rejects an offset with a facade 500 rather than a
    validation error, so it must be given a naive ISO timestamp."""
    return when.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def sms_is_older_than(raw: dict, cutoff: str) -> bool:
    """Is this inbound SMS older than the window's cutoff?

    Returns False when no timestamp field can be found. That direction is
    deliberate: a caller uses this to stop paging, so answering "old" for an
    unrecognised row would end the window at the very first row and silently
    process nothing at all. Answering "not old" costs an extra page instead.
    """
    stamped = _first(raw, "received_at", "created_at")
    if stamped is None:
        return False
    return str(stamped) < cutoff
