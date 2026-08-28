import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Config
from app.services.sim_pair_conversation_service import SimPairConversationService as Service

OVERNIGHT = (22, 7)


def _config(enabled: bool = True, start: int = 22, end: int = 7) -> Config:
    return Config(
        pairing_quiet_hours_enabled=enabled,
        pairing_quiet_start_hour=start,
        pairing_quiet_end_hour=end,
    )


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 27, hour, minute, tzinfo=timezone.utc)


def test_window_is_none_when_disabled_or_empty():
    assert Service._quiet_window(_config(enabled=False)) is None
    # Equal bounds describe no quiet time, not a silent fleet for 24 hours.
    assert Service._quiet_window(_config(start=7, end=7)) is None
    assert Service._quiet_window(_config()) == OVERNIGHT


@pytest.mark.parametrize("hour,quiet", [(21, False), (22, True), (23, True), (0, True), (6, True), (7, False), (12, False)])
def test_a_window_spanning_midnight(hour, quiet):
    assert Service._is_quiet(_at(hour), OVERNIGHT) is quiet


@pytest.mark.parametrize("hour,quiet", [(0, False), (1, True), (4, True), (5, False), (23, False)])
def test_a_window_within_one_day(hour, quiet):
    assert Service._is_quiet(_at(hour), (1, 5)) is quiet


def test_no_window_is_never_quiet():
    assert Service._is_quiet(_at(3), None) is False


def test_a_daytime_due_time_is_untouched():
    when = _at(14, 30)
    assert Service._shift_out_of_quiet(when, OVERNIGHT) == when


def test_an_early_morning_due_time_wakes_the_same_day():
    shifted = Service._shift_out_of_quiet(_at(3), OVERNIGHT)
    assert _at(7) <= shifted <= _at(7) + timedelta(minutes=Service.WAKE_SPREAD_MINUTES)
    assert not Service._is_quiet(shifted, OVERNIGHT)


def test_a_late_evening_due_time_wakes_the_next_day():
    shifted = Service._shift_out_of_quiet(_at(23, 30), OVERNIGHT)
    assert _at(7) + timedelta(days=1) <= shifted <= _at(7) + timedelta(days=1, minutes=Service.WAKE_SPREAD_MINUTES)


def test_pairs_held_overnight_do_not_wake_as_one_burst():
    shifted = {Service._shift_out_of_quiet(_at(2), OVERNIGHT) for _ in range(20)}
    assert len(shifted) > 1
