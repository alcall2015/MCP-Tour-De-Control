from datetime import datetime, timedelta, timezone

import pytest

from app.services.project_status import (
    LEVEL_ATTENTION,
    LEVEL_CRITICAL,
    LEVEL_NOMINAL,
    LEVEL_UNKNOWN,
    compute_status,
)

NOW = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)
FRESH = NOW - timedelta(days=1)


def status(**overrides):
    kwargs = {
        "metrics": {"avancement": 50.0, "budget_consomme": 1000.0, "budget_total": 5000.0},
        "error": None,
        "source_modified_at": FRESH,
        "previous_metrics": None,
        "stale_days": 14,
        "budget_warn_pct": 90,
        "now": NOW,
    }
    kwargs.update(overrides)
    return compute_status(**kwargs)


def test_read_failure_is_critical():
    assert status(metrics=None, error="permission denied")["level"] == LEVEL_CRITICAL


def test_no_source_is_unknown():
    result = status(metrics=None, error=None, source_modified_at=None)
    assert result["level"] == LEVEL_UNKNOWN


def test_budget_overrun_is_critical():
    result = status(metrics={"budget_consomme": 5200.0, "budget_total": 5000.0})
    assert result["level"] == LEVEL_CRITICAL


def test_overdue_milestone_is_critical():
    result = status(metrics={"prochain_jalon": "2026-08-18"})
    assert result["level"] == LEVEL_CRITICAL


def test_milestone_today_is_not_overdue():
    result = status(metrics={"prochain_jalon": "2026-08-19"})
    assert result["level"] == LEVEL_NOMINAL


def test_budget_at_warn_threshold_is_attention():
    result = status(metrics={"budget_consomme": 4500.0, "budget_total": 5000.0})
    assert result["level"] == LEVEL_ATTENTION


def test_stale_file_is_attention():
    result = status(source_modified_at=NOW - timedelta(days=15))
    assert result["level"] == LEVEL_ATTENTION


def test_stagnant_progress_is_attention():
    result = status(
        metrics={"avancement": 40.0},
        previous_metrics={"avancement": 40.0},
    )
    assert result["level"] == LEVEL_ATTENTION


def test_progressing_project_is_nominal():
    result = status(
        metrics={"avancement": 45.0},
        previous_metrics={"avancement": 40.0},
    )
    assert result["level"] == LEVEL_NOMINAL


def test_stagnation_skipped_without_reference():
    result = status(metrics={"avancement": 40.0}, previous_metrics=None)
    assert result["level"] == LEVEL_NOMINAL


def test_missing_metrics_skip_their_rules():
    result = status(metrics={"responsable": "Fabien"})
    assert result["level"] == LEVEL_NOMINAL


def test_critical_wins_over_attention():
    result = status(
        metrics={"budget_consomme": 6000.0, "budget_total": 5000.0},
        source_modified_at=NOW - timedelta(days=40),
    )
    assert result["level"] == LEVEL_CRITICAL


def test_reason_is_human_readable():
    result = status(metrics={"budget_consomme": 5200.0, "budget_total": 5000.0})
    assert "budget" in result["reason"].lower()


def test_zero_total_with_consumption_is_critical():
    # budget_total == 0 is a present value, not a missing metric: a missing
    # metric skips its rule, but 0 does not, so a real overrun must still fire.
    result = status(metrics={"budget_consomme": 500.0, "budget_total": 0.0})
    assert result["level"] == LEVEL_CRITICAL
    assert "overrun" in result["reason"].lower()


def test_zero_total_attention_rule_does_not_crash_or_misfire():
    # With total == 0, the percentage rule must never attempt a division by
    # zero, and the critical overrun rule (which comes first) must win
    # instead of letting a low warn threshold wrongly report "attention".
    result = status(
        metrics={"budget_consomme": 1.0, "budget_total": 0.0},
        budget_warn_pct=1,
    )
    assert result["level"] == LEVEL_CRITICAL
    assert "overrun" in result["reason"].lower()
