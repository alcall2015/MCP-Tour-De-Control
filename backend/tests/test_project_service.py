import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import Config, Project, ProjectLink, ProjectSnapshot
from app.services.google_service import GoogleAccessError
from app.services.project_service import (
    ProjectService,
    budget_summary,
    pending_decisions,
)
from app.utils.crypto import encrypt_value

NOW = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)


async def _project_with_source(session, name="AVA", file_id="SHEET1"):
    project = Project(name=name)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    session.add(
        ProjectLink(
            project_id=project.id,
            label="Suivi",
            url=f"https://docs.google.com/spreadsheets/d/{file_id}/edit",
            kind="sheet",
            file_id=file_id,
            is_kpi_source=True,
        )
    )
    session.add(Config(google_sa_key=encrypt_value('{"type": "service_account"}')))
    await session.commit()
    return project


def _fake_google(metrics=None, modified_at=None, error=None):
    google = MagicMock()
    if error:
        google.read_suivi.side_effect = GoogleAccessError(error)
    else:
        google.read_suivi.return_value = metrics or {}
    google.get_modified_time.return_value = modified_at
    return google


async def test_refresh_all_writes_one_snapshot_per_project(session):
    project = await _project_with_source(session)
    google = _fake_google({"avancement": 72.0}, NOW - timedelta(days=1))

    with patch("app.services.project_service.GoogleService", return_value=google):
        count = await ProjectService.refresh_all(session)

    assert count == 1
    snapshots = (await session.execute(select(ProjectSnapshot))).scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].metrics == {"avancement": 72.0}
    assert snapshots[0].project_id == project.id
    assert snapshots[0].error is None


async def test_refresh_all_skips_projects_without_kpi_source(session):
    session.add(Project(name="No source"))
    session.add(Config(google_sa_key=encrypt_value('{"type": "service_account"}')))
    await session.commit()

    with patch("app.services.project_service.GoogleService", return_value=_fake_google()):
        count = await ProjectService.refresh_all(session)

    assert count == 0
    assert (await session.execute(select(ProjectSnapshot))).scalars().all() == []


async def test_refresh_all_records_read_errors(session):
    await _project_with_source(session)
    google = _fake_google(error="permission denied")

    with patch("app.services.project_service.GoogleService", return_value=google):
        await ProjectService.refresh_all(session)

    snapshot = (await session.execute(select(ProjectSnapshot))).scalar_one()
    assert snapshot.metrics is None
    assert "permission denied" in snapshot.error


async def test_refresh_all_without_google_key_raises(session):
    await _project_with_source(session)
    config = (await session.execute(select(Config))).scalar_one()
    config.google_sa_key = ""
    await session.commit()

    with pytest.raises(GoogleAccessError):
        await ProjectService.refresh_all(session)


async def test_refresh_one_with_kpi_source_writes_snapshot(session):
    project = await _project_with_source(session)
    google = _fake_google({"avancement": 55.0}, NOW - timedelta(days=1))

    with patch("app.services.project_service.GoogleService", return_value=google):
        result = await ProjectService.refresh_one(session, project.id)

    assert result is True
    snapshots = (await session.execute(select(ProjectSnapshot))).scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].project_id == project.id
    assert snapshots[0].metrics == {"avancement": 55.0}
    assert snapshots[0].error is None


async def test_refresh_one_without_kpi_source_returns_false(session):
    project = Project(name="No source")
    session.add(project)
    session.add(Config(google_sa_key=encrypt_value('{"type": "service_account"}')))
    await session.commit()
    await session.refresh(project)

    with patch("app.services.project_service.GoogleService", return_value=_fake_google()):
        result = await ProjectService.refresh_one(session, project.id)

    assert result is False
    assert (await session.execute(select(ProjectSnapshot))).scalars().all() == []


async def test_refresh_one_with_unknown_project_id_returns_false(session):
    project = await _project_with_source(session)
    unknown_id = uuid.uuid4()
    assert unknown_id != project.id

    with patch("app.services.project_service.GoogleService", return_value=_fake_google()):
        result = await ProjectService.refresh_one(session, unknown_id)

    assert result is False
    assert (await session.execute(select(ProjectSnapshot))).scalars().all() == []


async def test_snapshot_error_clears_metrics_even_if_read_suivi_succeeded(session):
    await _project_with_source(session)
    google = MagicMock()
    google.read_suivi.return_value = {"avancement": 60.0}
    google.get_modified_time.side_effect = GoogleAccessError("modified time failed")

    with patch("app.services.project_service.GoogleService", return_value=google):
        await ProjectService.refresh_all(session)

    snapshot = (await session.execute(select(ProjectSnapshot))).scalar_one()
    assert snapshot.metrics is None
    assert snapshot.source_modified_at is None
    assert "modified time failed" in snapshot.error


async def test_build_views_exposes_status_trends_and_sparkline(session):
    project = await _project_with_source(session)
    session.add(
        ProjectSnapshot(
            project_id=project.id,
            captured_at=NOW - timedelta(days=8),
            metrics={"avancement": 40.0},
            source_modified_at=NOW - timedelta(days=8),
        )
    )
    session.add(
        ProjectSnapshot(
            project_id=project.id,
            captured_at=NOW,
            metrics={"avancement": 48.0},
            source_modified_at=NOW - timedelta(days=1),
        )
    )
    await session.commit()

    views = await ProjectService.build_views(session, now=NOW)

    assert len(views) == 1
    view = views[0]
    assert view["name"] == "AVA"
    assert view["status"]["level"] == "nominal"
    assert view["trends"]["avancement"] == 8.0
    assert view["sparkline"] == [40.0, 48.0]
    assert view["captured_at"] == NOW
    assert len(view["links"]) == 1


async def test_build_views_without_snapshot_is_unknown(session):
    await _project_with_source(session)

    views = await ProjectService.build_views(session, now=NOW)

    assert views[0]["status"]["level"] == "unknown"
    assert views[0]["metrics"] is None
    assert views[0]["sparkline"] == []


def test_pending_decisions_collects_non_empty_values():
    views = [
        {"id": "1", "name": "A", "metrics": {"decision_attendue": "Arbitrer X"}},
        {"id": "2", "name": "B", "metrics": {"decision_attendue": "  "}},
        {"id": "3", "name": "C", "metrics": {"avancement": 10.0}},
        {"id": "4", "name": "D", "metrics": None},
    ]
    assert pending_decisions(views) == [
        {"project_id": "1", "project_name": "A", "decision": "Arbitrer X"}
    ]


def test_budget_summary_sums_latest_metrics():
    views = [
        {"metrics": {"budget_consomme": 8400.0, "budget_total": 12000.0}},
        {"metrics": {"budget_consomme": 3100.0, "budget_total": 3000.0}},
        {"metrics": {"avancement": 10.0}},
        {"metrics": None},
    ]
    assert budget_summary(views) == {
        "consumed": 11500.0,
        "total": 15000.0,
        "remaining": 3500.0,
        "projects_counted": 2,
    }


def test_budget_summary_without_data():
    assert budget_summary([{"metrics": None}]) == {
        "consumed": 0.0,
        "total": 0.0,
        "remaining": 0.0,
        "projects_counted": 0,
    }
