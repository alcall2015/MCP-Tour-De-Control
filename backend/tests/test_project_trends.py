from datetime import datetime, timedelta, timezone

from app.services.project_status import compute_trends, select_reference

NOW = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)


def test_compute_trends_numeric_only():
    current = {"avancement": 45.0, "budget_consomme": 8400.0, "responsable": "Fabien"}
    reference = {"avancement": 40.0, "budget_consomme": 8000.0, "responsable": "Sam"}
    assert compute_trends(current, reference) == {"avancement": 5.0, "budget_consomme": 400.0}


def test_compute_trends_ignores_keys_missing_on_one_side():
    assert compute_trends({"a": 2.0, "b": 1.0}, {"a": 1.0}) == {"a": 1.0}


def test_compute_trends_without_reference():
    assert compute_trends({"a": 1.0}, None) == {}
    assert compute_trends(None, {"a": 1.0}) == {}


def test_select_reference_prefers_snapshot_at_least_a_week_old():
    history = [
        (NOW - timedelta(days=2), {"avancement": 44.0}),
        (NOW - timedelta(days=8), {"avancement": 40.0}),
        (NOW - timedelta(days=30), {"avancement": 10.0}),
    ]
    captured_at, metrics = select_reference(history, NOW)
    assert captured_at == NOW - timedelta(days=8)
    assert metrics == {"avancement": 40.0}


def test_select_reference_falls_back_to_oldest():
    history = [
        (NOW - timedelta(days=1), {"avancement": 44.0}),
        (NOW - timedelta(days=3), {"avancement": 42.0}),
    ]
    captured_at, _ = select_reference(history, NOW)
    assert captured_at == NOW - timedelta(days=3)


def test_select_reference_without_history():
    assert select_reference([], NOW) is None
