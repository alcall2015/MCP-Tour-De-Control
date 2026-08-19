"""Project refresh orchestration and read models."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Config, Project, ProjectSnapshot
from app.services.google_service import GoogleAccessError, GoogleService
from app.services.project_status import (
    TREND_WINDOW_DAYS,
    compute_status,
    compute_trends,
    select_reference,
)
from app.utils.crypto import decrypt_value

log = structlog.get_logger()

SPARKLINE_POINTS = 30
SPARKLINE_METRIC = "avancement"


def _is_number(value) -> bool:
    """True for int/float values, excluding bool (a subclass of int)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class ProjectService:
    @staticmethod
    async def refresh_all(session: AsyncSession) -> int:
        """Read every project's KPI source and write one snapshot each. Returns the count."""
        google = await ProjectService._build_google(session)
        projects = await ProjectService._list_projects(session)

        refreshed = 0
        for project in projects:
            if await ProjectService._snapshot(session, project, google):
                refreshed += 1

        await session.commit()
        log.info("Projects refreshed", count=refreshed)
        return refreshed

    @staticmethod
    async def refresh_one(session: AsyncSession, project_id: uuid.UUID) -> bool:
        """Refresh a single project. Returns False when it has no KPI source."""
        google = await ProjectService._build_google(session)
        result = await session.execute(
            select(Project).options(selectinload(Project.links)).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            return False

        written = await ProjectService._snapshot(session, project, google)
        await session.commit()
        return written

    @staticmethod
    async def build_views(session: AsyncSession, now: datetime | None = None) -> list[dict]:
        """Assemble one view dict per project: status, metrics, trends and sparkline."""
        now = now or datetime.now(timezone.utc)
        projects = await ProjectService._list_projects(session)

        views = []
        for project in projects:
            snapshots = await ProjectService._recent_snapshots(session, project.id)
            views.append(ProjectService._build_view(project, snapshots, now))
        return views

    @staticmethod
    async def _build_google(session: AsyncSession) -> GoogleService:
        config = (await session.execute(select(Config).limit(1))).scalar_one_or_none()
        if not config or not config.google_sa_key:
            raise GoogleAccessError("Google service account key not configured")
        return GoogleService(decrypt_value(config.google_sa_key))

    @staticmethod
    async def _list_projects(session: AsyncSession) -> list[Project]:
        result = await session.execute(
            select(Project).options(selectinload(Project.links)).order_by(Project.position, Project.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def _recent_snapshots(session: AsyncSession, project_id: uuid.UUID) -> list[ProjectSnapshot]:
        """Newest first, capped at SPARKLINE_POINTS."""
        result = await session.execute(
            select(ProjectSnapshot)
            .where(ProjectSnapshot.project_id == project_id)
            .order_by(ProjectSnapshot.captured_at.desc())
            .limit(SPARKLINE_POINTS)
        )
        return list(result.scalars().all())

    @staticmethod
    async def _snapshot(session: AsyncSession, project: Project, google: GoogleService) -> bool:
        """Read the KPI source and add a snapshot. Returns False when there is no source."""
        source = next((link for link in project.links if link.is_kpi_source and link.file_id), None)
        if not source:
            return False

        metrics, modified_at, error = None, None, None
        try:
            # The Google client is blocking — keep it off the event loop.
            metrics = await asyncio.to_thread(google.read_suivi, source.file_id)
            modified_at = await asyncio.to_thread(google.get_modified_time, source.file_id)
        except GoogleAccessError as exc:
            error = str(exc)
            metrics = None
            modified_at = None
            log.warning("Project source read failed", project=project.name, error=error)

        session.add(
            ProjectSnapshot(
                project_id=project.id,
                metrics=metrics,
                source_modified_at=modified_at,
                error=error,
            )
        )
        return True

    @staticmethod
    def _build_view(project: Project, snapshots: list[ProjectSnapshot], now: datetime) -> dict:
        latest = snapshots[0] if snapshots else None
        history = [(s.captured_at, s.metrics) for s in snapshots[1:]]
        reference = select_reference(history, latest.captured_at) if latest else None
        reference_metrics = reference[1] if reference else None

        # On a failed read the latest snapshot carries no metrics. Fall back to
        # the most recent snapshot without an error so the card keeps showing
        # its last known values (with their own date) instead of going blank.
        good_snapshot = next((s for s in snapshots if s.error is None), None)
        display_metrics = good_snapshot.metrics if good_snapshot else None
        metrics_captured_at = good_snapshot.captured_at if good_snapshot else None

        # select_reference() falls back to the oldest snapshot even when it is
        # younger than TREND_WINDOW_DAYS — correct for trend deltas, but the
        # stagnation rule (spec rule 6) must only fire from a reference that is
        # genuinely at least TREND_WINDOW_DAYS older than the latest snapshot.
        stagnation_reference_metrics = None
        if latest and reference:
            reference_captured_at = reference[0]
            if reference_captured_at <= latest.captured_at - timedelta(days=TREND_WINDOW_DAYS):
                stagnation_reference_metrics = reference_metrics

        has_kpi_source = any(link.is_kpi_source and link.file_id for link in project.links)

        status = compute_status(
            metrics=display_metrics,
            error=latest.error if latest else None,
            source_modified_at=latest.source_modified_at if latest else None,
            previous_metrics=stagnation_reference_metrics,
            stale_days=project.stale_days,
            budget_warn_pct=project.budget_warn_pct,
            now=now,
            has_kpi_source=has_kpi_source,
            has_snapshot=latest is not None,
        )

        sparkline = [
            value
            for value in (
                (s.metrics or {}).get(SPARKLINE_METRIC) for s in reversed(snapshots)
            )
            if _is_number(value)
        ]

        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "position": project.position,
            "stale_days": project.stale_days,
            "budget_warn_pct": project.budget_warn_pct,
            "links": [
                {
                    "id": link.id,
                    "label": link.label,
                    "url": link.url,
                    "kind": link.kind,
                    "is_kpi_source": link.is_kpi_source,
                    "position": link.position,
                }
                for link in project.links
            ],
            "status": status,
            "metrics": display_metrics,
            "trends": compute_trends(display_metrics, reference_metrics),
            "sparkline": sparkline,
            "captured_at": latest.captured_at if latest else None,
            "metrics_captured_at": metrics_captured_at,
            "source_modified_at": latest.source_modified_at if latest else None,
            "error": latest.error if latest else None,
        }


def pending_decisions(views: list[dict]) -> list[dict]:
    """Collect non-empty `decision_attendue` values across all project views."""
    decisions = []
    for view in views:
        raw = (view.get("metrics") or {}).get("decision_attendue")
        text = str(raw).strip() if raw is not None else ""
        if text:
            decisions.append(
                {
                    "project_id": view["id"],
                    "project_name": view["name"],
                    "decision": text,
                }
            )
    return decisions


def budget_summary(views: list[dict]) -> dict:
    """Sum consumed and total budget across projects that report both."""
    consumed = 0.0
    total = 0.0
    counted = 0
    for view in views:
        metrics = view.get("metrics") or {}
        project_consumed = metrics.get("budget_consomme")
        project_total = metrics.get("budget_total")
        if _is_number(project_consumed) and _is_number(project_total):
            consumed += float(project_consumed)
            total += float(project_total)
            counted += 1
    return {
        "consumed": consumed,
        "total": total,
        "remaining": total - consumed,
        "projects_counted": counted,
    }
