"""Fleet-wide quiet hours, expressed in UTC.

Shared by SIM Pairing and SMS auto-reply so both obey one window and one set
of settings. Equal bounds describe an empty window, never a silent day.
"""
import random
from datetime import datetime, timedelta, timezone

WAKE_SPREAD_MINUTES = 90


def quiet_window(config) -> tuple[int, int] | None:
    if not config.pairing_quiet_hours_enabled:
        return None
    start, end = config.pairing_quiet_start_hour, config.pairing_quiet_end_hour
    return None if start == end else (start, end)


def is_quiet(when: datetime, window: tuple[int, int] | None) -> bool:
    if window is None:
        return False
    start, end = window
    hour = when.astimezone(timezone.utc).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def shift_out_of_quiet(when: datetime, window: tuple[int, int] | None,
                       spread_minutes: int = WAKE_SPREAD_MINUTES) -> datetime:
    if not is_quiet(when, window):
        return when
    when = when.astimezone(timezone.utc)
    wake = when.replace(hour=window[1], minute=0, second=0, microsecond=0)
    if wake <= when:
        wake += timedelta(days=1)
    return wake + timedelta(minutes=random.uniform(0, spread_minutes))
