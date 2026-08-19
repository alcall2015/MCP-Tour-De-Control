"""Project status rules and trend computation. Pure functions, no I/O."""

from datetime import datetime, timedelta

from app.utils.suivi_parser import parse_date

LEVEL_CRITICAL = "critical"
LEVEL_ATTENTION = "attention"
LEVEL_NOMINAL = "nominal"
LEVEL_UNKNOWN = "unknown"

TREND_WINDOW_DAYS = 7


def compute_status(
    *,
    metrics: dict | None,
    error: str | None,
    source_modified_at: datetime | None,
    previous_metrics: dict | None,
    stale_days: int,
    budget_warn_pct: int,
    now: datetime,
    has_kpi_source: bool,
    has_snapshot: bool,
) -> dict:
    """Evaluate the status rules in order and return the first match.

    Returns {"level": one of the LEVEL_* constants, "reason": short English explanation}.
    A missing metric skips its rule rather than failing.

    `has_kpi_source` and `has_snapshot` disambiguate the three ways a project
    can end up with no usable metrics: no is_kpi_source link at all, a link
    attached but never yet refreshed, and a successful read of an empty
    SUIVI tab (an empty dict is falsy just like None).
    """
    if error:
        return {"level": LEVEL_CRITICAL, "reason": f"read failed: {error}"}

    if not metrics:
        if not has_kpi_source:
            return {"level": LEVEL_UNKNOWN, "reason": "no source"}
        if not has_snapshot:
            return {"level": LEVEL_UNKNOWN, "reason": "not refreshed yet"}
        return {"level": LEVEL_UNKNOWN, "reason": "SUIVI tab is empty"}

    consumed = _number(metrics.get("budget_consomme"))
    total = _number(metrics.get("budget_total"))

    if consumed is not None and total is not None:
        if consumed > total:
            return {"level": LEVEL_CRITICAL, "reason": "budget overrun"}

    milestone = parse_date(metrics.get("prochain_jalon"))
    if milestone is not None and milestone < now.date():
        return {"level": LEVEL_CRITICAL, "reason": f"milestone overdue since {milestone.isoformat()}"}

    if consumed is not None and total is not None and total > 0:
        if (consumed / total) * 100 >= budget_warn_pct:
            return {"level": LEVEL_ATTENTION, "reason": f"budget at {round(consumed / total * 100)}% of total"}

    if source_modified_at is not None:
        days = (now - source_modified_at).days
        if days >= stale_days:
            return {"level": LEVEL_ATTENTION, "reason": f"no update for {days} days"}

    current_progress = _number(metrics.get("avancement"))
    previous_progress = _number((previous_metrics or {}).get("avancement"))
    if current_progress is not None and previous_progress is not None:
        if current_progress <= previous_progress:
            return {"level": LEVEL_ATTENTION, "reason": "progress stalled"}

    return {"level": LEVEL_NOMINAL, "reason": "on track"}


def select_reference(history: list[tuple[datetime, dict | None]], latest_captured_at: datetime):
    """Pick the trend reference: newest snapshot at least TREND_WINDOW_DAYS older than the latest.

    Falls back to the oldest available snapshot. `history` is newest-first and excludes the latest.
    Returns the (captured_at, metrics) tuple, or None when there is no history.
    """
    if not history:
        return None
    cutoff = latest_captured_at - timedelta(days=TREND_WINDOW_DAYS)
    for captured_at, metrics in history:
        if captured_at <= cutoff:
            return (captured_at, metrics)
    return history[-1]


def compute_trends(metrics: dict | None, reference_metrics: dict | None) -> dict[str, float]:
    """Delta per numeric metric present in both snapshots. Non-numeric keys are ignored."""
    if not metrics or not reference_metrics:
        return {}
    trends: dict[str, float] = {}
    for key, value in metrics.items():
        current = _number(value)
        previous = _number(reference_metrics.get(key))
        if current is not None and previous is not None:
            trends[key] = round(current - previous, 4)
    return trends


def _number(value) -> float | None:
    """Coerce a metric to float, or None when it is not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
