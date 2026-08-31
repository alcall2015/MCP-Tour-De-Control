import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_async_session
from app.main import app
from app.models import Base, SimPair

TEST_DATABASE_URL = "postgresql+asyncpg://mcp:mcp_secret@localhost:5432/mcp_control_test"


@pytest.fixture(autouse=True)
async def api_session_override():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_get_session
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


def _make_pair(status: str, created_at: datetime, index: int) -> SimPair:
    return SimPair(
        id=uuid.uuid4(),
        sim_a_id=index * 2,
        sim_b_id=index * 2 + 1,
        sim_a_name=f"Sim A{index}",
        sim_b_name=f"Sim B{index}",
        country="CI",
        group_a="love",
        group_b="love",
        topic="love",
        target_messages=10,
        sent_count=0,
        status=status,
        archived_reason="done" if status == "archived" else None,
        created_at=created_at,
        archived_at=created_at if status == "archived" else None,
    )


@pytest.fixture
async def seeded_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_get_session

    async with session_factory() as session:
        yield session

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_manage_sim_pairing_groups():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/sim-pairing/groups", json={"name": "love"})
        assert created.status_code == 201
        group_id = created.json()["id"]

        listed = await client.get("/api/v1/sim-pairing/groups")
        assert listed.status_code == 200
        assert [group["name"] for group in listed.json()] == ["love"]

        duplicate = await client.post("/api/v1/sim-pairing/groups", json={"name": "love"})
        assert duplicate.status_code == 409

        deleted = await client.delete(f"/api/v1/sim-pairing/groups/{group_id}")
        assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_list_pairs_status_filter(seeded_session: AsyncSession):
    now = datetime.now(timezone.utc)
    for i in range(3):
        seeded_session.add(_make_pair("active", now - timedelta(minutes=i), i))
    for i in range(5):
        seeded_session.add(_make_pair("archived", now - timedelta(minutes=i + 10), i + 10))
    await seeded_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        active = await client.get("/api/v1/sim-pairing/pairs", params={"status": "active"})
        assert active.status_code == 200
        assert len(active.json()) == 3
        assert all(pair["status"] == "active" for pair in active.json())

        archived = await client.get("/api/v1/sim-pairing/pairs", params={"status": "archived"})
        assert archived.status_code == 200
        assert len(archived.json()) == 5
        assert all(pair["status"] == "archived" for pair in archived.json())

        unfiltered = await client.get("/api/v1/sim-pairing/pairs")
        assert unfiltered.status_code == 200
        assert len(unfiltered.json()) == 8


@pytest.mark.asyncio
async def test_list_pairs_unknown_status_rejected(seeded_session: AsyncSession):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/sim-pairing/pairs", params={"status": "bogus"})
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_pairs_pagination_is_stable(seeded_session: AsyncSession):
    now = datetime.now(timezone.utc)
    # created_at strictly decreasing with index, so ordering (desc) is deterministic.
    for i in range(10):
        seeded_session.add(_make_pair("active", now - timedelta(minutes=i), i))
    await seeded_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page1 = await client.get("/api/v1/sim-pairing/pairs", params={"limit": 4, "offset": 0})
        page2 = await client.get("/api/v1/sim-pairing/pairs", params={"limit": 4, "offset": 4})
        page3 = await client.get("/api/v1/sim-pairing/pairs", params={"limit": 4, "offset": 8})

        assert [p["id"] for p in page1.json()] == [p["id"] for p in page1.json()]  # sanity: deterministic response
        ids_page1 = [p["id"] for p in page1.json()]
        ids_page2 = [p["id"] for p in page2.json()]
        ids_page3 = [p["id"] for p in page3.json()]

        assert len(ids_page1) == 4
        assert len(ids_page2) == 4
        assert len(ids_page3) == 2
        # No overlap between pages, and all ids together cover every seeded row exactly once.
        assert set(ids_page1) & set(ids_page2) == set()
        assert set(ids_page2) & set(ids_page3) == set()
        assert len(set(ids_page1) | set(ids_page2) | set(ids_page3)) == 10

        default_limit = await client.get("/api/v1/sim-pairing/pairs")
        assert len(default_limit.json()) == 10  # under the default 25 cap


@pytest.mark.asyncio
async def test_pairs_count(seeded_session: AsyncSession):
    for i in range(2):
        seeded_session.add(_make_pair("active", datetime.now(timezone.utc), i))
    for i in range(7):
        seeded_session.add(_make_pair("archived", datetime.now(timezone.utc), i + 100))
    await seeded_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/sim-pairing/pairs/count")
        assert response.status_code == 200
        assert response.json() == {"active": 2, "archived": 7}
