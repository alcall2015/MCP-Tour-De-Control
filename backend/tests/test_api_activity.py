import os
import uuid

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_async_session
from app.main import app
from app.models import Base, DocumentActivity, TrackedDocument
from app.services.activity_view import heatmap_span
from app.services.text_extractor import DOC_MIME

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


async def _seed(async_session, section="Soutien-Scolaire", days_ago=1, added=142, removed=5):
    async with async_session() as session:
        doc = TrackedDocument(
            file_id=f"F{uuid.uuid4().hex[:8]}",
            name="Recherche GoogleFlow",
            mime_type=DOC_MIME,
            section=section,
            web_url="https://docs.google.com/document/d/F1/edit",
            last_modified_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            last_author="Fabien",
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        session.add(
            DocumentActivity(
                document_id=doc.id,
                day=date.today() - timedelta(days=days_ago),
                added=added,
                removed=removed,
                author="Fabien",
            )
        )
        await session.commit()
        return doc.id


def test_heatmap_span_starts_on_a_monday_53_columns_back():
    start, end = heatmap_span(date(2026, 8, 20))  # a Thursday
    assert start.weekday() == 0
    assert end == date(2026, 8, 20)
    assert (end - start).days == 52 * 7 + 3


async def test_documents_groups_by_section(client, setup_test_db):
    await _seed(setup_test_db)
    response = await client.get("/api/v1/activity/documents")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "Soutien-Scolaire"
    doc = body[0]["documents"][0]
    assert doc["last_added"] == 142
    assert doc["last_removed"] == 5
    assert doc["last_author"] == "Fabien"


async def test_documents_without_a_section_land_in_ungrouped(client, setup_test_db):
    await _seed(setup_test_db, section=None)
    body = (await client.get("/api/v1/activity/documents")).json()
    assert body[0]["name"] == "Ungrouped"


async def test_document_with_no_activity_reports_zero(client, setup_test_db):
    async with setup_test_db() as session:
        session.add(
            TrackedDocument(
                file_id="P1",
                name="Facture",
                mime_type="application/pdf",
                section="Admin",
                web_url="https://drive.google.com/file/d/P1/view",
            )
        )
        await session.commit()

    doc = (await client.get("/api/v1/activity/documents")).json()[0]["documents"][0]
    assert doc["last_added"] == 0
    assert doc["last_removed"] == 0
    assert doc["last_activity_day"] is None


async def test_heatmap_fills_absent_days_with_zero(client, setup_test_db):
    await _seed(setup_test_db, days_ago=2, added=10, removed=3)
    body = (await client.get("/api/v1/activity/heatmap")).json()

    start, end = heatmap_span(date.today())
    assert len(body["days"]) == (end - start).days + 1
    assert body["total_changes"] == 13

    by_day = {d["day"]: d for d in body["days"]}
    active = by_day[(date.today() - timedelta(days=2)).isoformat()]
    assert (active["added"], active["removed"], active["total"]) == (10, 3, 13)
    quiet = by_day[(date.today() - timedelta(days=1)).isoformat()]
    assert quiet["total"] == 0


async def test_scan_endpoint_calls_the_scanner(client):
    with patch(
        "app.routers.activity.DocumentScanner.scan_all", new=AsyncMock(return_value=7)
    ) as scan:
        response = await client.post("/api/v1/activity/scan")

    assert response.status_code == 200
    assert response.json() == {"walked": 7}
    scan.assert_awaited_once()


async def test_scan_reports_configuration_errors_as_400(client):
    from app.services.google_service import GoogleAccessError

    with patch(
        "app.routers.activity.DocumentScanner.scan_all",
        new=AsyncMock(side_effect=GoogleAccessError("No Drive folder configured")),
    ):
        response = await client.post("/api/v1/activity/scan")

    assert response.status_code == 400
    assert "No Drive folder configured" in response.json()["detail"]
