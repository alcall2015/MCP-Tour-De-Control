import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import Config, Project, ProjectLink, ProjectSnapshot


async def test_project_defaults(session):
    project = Project(name="AVA Voice Agent")
    session.add(project)
    await session.commit()
    await session.refresh(project)

    assert isinstance(project.id, uuid.UUID)
    assert project.position == 0
    assert project.stale_days == 14
    assert project.budget_warn_pct == 90


async def test_links_and_snapshots_cascade(session):
    project = Project(name="Tour De Control")
    session.add(project)
    await session.commit()
    await session.refresh(project)

    session.add(
        ProjectLink(
            project_id=project.id,
            label="Suivi hebdo",
            url="https://docs.google.com/spreadsheets/d/ABC123/edit",
            kind="sheet",
            file_id="ABC123",
            is_kpi_source=True,
        )
    )
    session.add(
        ProjectSnapshot(
            project_id=project.id,
            captured_at=datetime.now(timezone.utc),
            metrics={"avancement": 40, "budget_total": 3000},
        )
    )
    await session.commit()

    await session.delete(project)
    await session.commit()

    links = (await session.execute(select(ProjectLink))).scalars().all()
    snapshots = (await session.execute(select(ProjectSnapshot))).scalars().all()
    assert links == []
    assert snapshots == []


async def test_snapshot_stores_error_without_metrics(session):
    project = Project(name="Broken")
    session.add(project)
    await session.commit()
    await session.refresh(project)

    session.add(ProjectSnapshot(project_id=project.id, error="permission denied"))
    await session.commit()

    snapshot = (await session.execute(select(ProjectSnapshot))).scalar_one()
    assert snapshot.error == "permission denied"
    assert snapshot.metrics is None


async def test_config_has_google_columns(session):
    config = Config()
    session.add(config)
    await session.commit()
    await session.refresh(config)

    assert config.google_sa_key == ""
    assert config.projects_cron == "0 6 * * *"
