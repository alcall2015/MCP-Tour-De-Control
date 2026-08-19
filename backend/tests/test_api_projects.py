import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_async_session
from app.main import app
from app.models import Base, Project, ProjectLink, ProjectSnapshot

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_async_session():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_get_async_session
    yield async_session
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_create_and_list_project(client):
    response = await client.post("/api/v1/projects", json={"name": "AVA Voice Agent"})
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "AVA Voice Agent"
    assert created["stale_days"] == 14
    assert created["budget_warn_pct"] == 90

    listed = await client.get("/api/v1/projects")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["status"]["level"] == "unknown"
    assert body[0]["links"] == []


async def test_update_and_delete_project(client):
    created = (await client.post("/api/v1/projects", json={"name": "Tmp"})).json()

    updated = await client.put(
        f"/api/v1/projects/{created['id']}", json={"name": "Renamed", "stale_days": 7}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["stale_days"] == 7

    deleted = await client.delete(f"/api/v1/projects/{created['id']}")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/projects")).json() == []


async def test_add_link_derives_kind_and_file_id(client):
    project = (await client.post("/api/v1/projects", json={"name": "P"})).json()

    response = await client.post(
        f"/api/v1/projects/{project['id']}/links",
        json={
            "label": "Suivi hebdo",
            "url": "https://docs.google.com/spreadsheets/d/SHEET42/edit#gid=0",
            "is_kpi_source": True,
        },
    )
    assert response.status_code == 201
    link = response.json()
    assert link["kind"] == "sheet"
    assert link["is_kpi_source"] is True

    listed = (await client.get("/api/v1/projects")).json()
    assert listed[0]["links"][0]["label"] == "Suivi hebdo"


async def test_delete_link(client):
    project = (await client.post("/api/v1/projects", json={"name": "P"})).json()
    link = (
        await client.post(
            f"/api/v1/projects/{project['id']}/links",
            json={"label": "Doc", "url": "https://docs.google.com/document/d/D1/edit"},
        )
    ).json()

    response = await client.delete(f"/api/v1/projects/links/{link['id']}")
    assert response.status_code == 204
    assert (await client.get("/api/v1/projects")).json()[0]["links"] == []


async def test_decisions_and_summary_are_not_parsed_as_project_ids(client, setup_test_db):
    project = (await client.post("/api/v1/projects", json={"name": "P"})).json()

    async with setup_test_db() as session:
        session.add(
            ProjectSnapshot(
                project_id=uuid.UUID(project["id"]),
                captured_at=datetime.now(timezone.utc),
                metrics={
                    "decision_attendue": "Arbitrer le contrat X",
                    "budget_consomme": 8400.0,
                    "budget_total": 12000.0,
                },
            )
        )
        await session.commit()

    decisions = await client.get("/api/v1/projects/decisions")
    assert decisions.status_code == 200
    assert decisions.json() == [
        {
            "project_id": project["id"],
            "project_name": "P",
            "decision": "Arbitrer le contrat X",
        }
    ]

    summary = await client.get("/api/v1/projects/summary")
    assert summary.status_code == 200
    assert summary.json() == {
        "consumed": 8400.0,
        "total": 12000.0,
        "remaining": 3600.0,
        "projects_counted": 1,
    }


async def test_refresh_endpoint_calls_the_service(client):
    with patch(
        "app.routers.projects.ProjectService.refresh_all", new=AsyncMock(return_value=3)
    ) as refresh:
        response = await client.post("/api/v1/projects/refresh")

    assert response.status_code == 200
    assert response.json() == {"refreshed": 3}
    refresh.assert_awaited_once()


async def test_refresh_reports_google_errors_as_400(client):
    from app.services.google_service import GoogleAccessError

    with patch(
        "app.routers.projects.ProjectService.refresh_all",
        new=AsyncMock(side_effect=GoogleAccessError("key not configured")),
    ):
        response = await client.post("/api/v1/projects/refresh")

    assert response.status_code == 400
    assert "key not configured" in response.json()["detail"]


async def test_project_detail_returns_history(client, setup_test_db):
    project = (await client.post("/api/v1/projects", json={"name": "P"})).json()
    now = datetime.now(timezone.utc)

    async with setup_test_db() as session:
        session.add(
            ProjectSnapshot(project_id=uuid.UUID(project["id"]), captured_at=now, metrics={"avancement": 20.0})
        )
        session.add(
            ProjectSnapshot(
                project_id=uuid.UUID(project["id"]),
                captured_at=now - timedelta(days=9),
                metrics={"avancement": 10.0},
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/projects/{project['id']}")
    assert response.status_code == 200
    body = response.json()
    assert len(body["history"]) == 2
    assert body["trends"]["avancement"] == 10.0


async def test_get_unknown_project_returns_404(client):
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_update_unknown_link_returns_404(client):
    response = await client.put(
        f"/api/v1/projects/links/{uuid.uuid4()}", json={"label": "Renamed"}
    )
    assert response.status_code == 404


async def test_delete_unknown_link_returns_404(client):
    response = await client.delete(f"/api/v1/projects/links/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_update_unknown_project_returns_404(client):
    response = await client.put(
        f"/api/v1/projects/{uuid.uuid4()}", json={"name": "Renamed"}
    )
    assert response.status_code == 404


async def test_delete_unknown_project_returns_404(client):
    response = await client.delete(f"/api/v1/projects/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_add_link_to_unknown_project_returns_404(client):
    response = await client.post(
        f"/api/v1/projects/{uuid.uuid4()}/links",
        json={"label": "Doc", "url": "https://docs.google.com/document/d/D1/edit"},
    )
    assert response.status_code == 404


async def test_refresh_unknown_project_returns_404(client):
    response = await client.post(f"/api/v1/projects/{uuid.uuid4()}/refresh")
    assert response.status_code == 404


async def test_refresh_project_without_kpi_source_returns_zero(client):
    project = (await client.post("/api/v1/projects", json={"name": "P"})).json()

    with patch(
        "app.routers.projects.ProjectService.refresh_one", new=AsyncMock(return_value=False)
    ):
        response = await client.post(f"/api/v1/projects/{project['id']}/refresh")

    assert response.status_code == 200
    assert response.json() == {"refreshed": 0}
