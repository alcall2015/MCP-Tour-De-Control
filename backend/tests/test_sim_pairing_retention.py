import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import SimPair, SimPairHistory, SimPairMessage, SimPairMessageQueue
from app.services.sim_pairing_retention import purge_archived_pairs


def _pair(session, *, status, archived_days_ago=None):
    pair = SimPair(
        id=uuid.uuid4(), sim_a_id=1, sim_b_id=2, sim_a_name="Aminata", sim_b_name="Adama",
        country="GUINEA", group_a="g", group_b="g", topic="love", status=status,
        archived_at=None if archived_days_ago is None
        else datetime.now(timezone.utc) - timedelta(days=archived_days_ago),
    )
    session.add(pair)
    session.add(SimPairMessage(pair_id=pair.id, from_sim_id=1, to_sim_id=2,
                               content="x", model="m", status="sent"))
    session.add(SimPairHistory(pair_id=pair.id, event="created"))
    session.add(SimPairMessageQueue(pair_id=pair.id, due_at=datetime.now(timezone.utc)))
    return pair


async def test_an_old_archived_pair_is_removed_from_all_four_tables(session):
    pair = _pair(session, status="archived", archived_days_ago=100)
    await session.commit()

    removed = await purge_archived_pairs(session, retention_days=90)

    assert removed == {"pairs": 1, "messages": 1, "history": 1, "queue": 1}
    for model in (SimPair, SimPairMessage, SimPairHistory, SimPairMessageQueue):
        rows = (await session.execute(select(model))).scalars().all()
        assert rows == [], f"{model.__name__} still holds a row for the purged pair"


async def test_a_recently_archived_pair_is_kept(session):
    _pair(session, status="archived", archived_days_ago=10)
    await session.commit()
    assert await purge_archived_pairs(session, retention_days=90) == {
        "pairs": 0, "messages": 0, "history": 0, "queue": 0}


async def test_an_active_pair_is_never_purged_however_old(session):
    pair = _pair(session, status="active")
    pair.created_at = datetime.now(timezone.utc) - timedelta(days=999)
    await session.commit()
    assert (await purge_archived_pairs(session, retention_days=1))["pairs"] == 0


async def test_zero_retention_disables_the_purge(session):
    _pair(session, status="archived", archived_days_ago=9999)
    await session.commit()
    assert await purge_archived_pairs(session, retention_days=0) == {
        "pairs": 0, "messages": 0, "history": 0, "queue": 0}


async def test_an_archived_pair_with_no_archived_at_is_left_alone(session):
    # Rows predating the archived_at column must not be deleted on a guess.
    _pair(session, status="archived", archived_days_ago=None)
    await session.commit()
    assert (await purge_archived_pairs(session, retention_days=1))["pairs"] == 0
