"""Delete archived SIM pairs once they are older than the retention window.

None of sim_pair_message, sim_pair_history or sim_pair_message_queue declares a
foreign key to sim_pair, so there is no cascade to rely on: removing a pair
without its children would leave rows nothing can ever find again. All four
tables are cleared in one transaction, children first.
"""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, select

from app.models import SimPair, SimPairHistory, SimPairMessage, SimPairMessageQueue

log = structlog.get_logger()

# Upper bound on the pairs deleted per call. Without it the first purge to meet
# a real backlog would delete every eligible pair at once: one large transaction
# holding locks on four tables, with `pair_id IN (...)` expanding to one bind
# parameter per id against asyncpg's 32767 limit. The job runs every fifteen
# minutes, so a backlog drains over successive runs instead of in one stall.
PURGE_BATCH_SIZE = 500


async def purge_archived_pairs(session, retention_days: int) -> dict:
    empty = {"pairs": 0, "messages": 0, "history": 0, "queue": 0}
    # Zero means keep everything. An archived pair with no archived_at predates
    # that column, and its age is unknown — never guess and delete.
    if retention_days <= 0:
        return empty

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    pair_ids = list((await session.execute(
        select(SimPair.id).where(
            SimPair.status == "archived",
            SimPair.archived_at.is_not(None),
            SimPair.archived_at < cutoff,
        )
        # Oldest first, so repeated runs always advance through the backlog
        # rather than revisiting the same batch.
        .order_by(SimPair.archived_at)
        .limit(PURGE_BATCH_SIZE)
    )).scalars())
    if not pair_ids:
        return empty

    removed = dict(empty)
    for key, model in (("messages", SimPairMessage), ("history", SimPairHistory),
                       ("queue", SimPairMessageQueue)):
        result = await session.execute(delete(model).where(model.pair_id.in_(pair_ids)))
        removed[key] = result.rowcount or 0
    result = await session.execute(delete(SimPair).where(SimPair.id.in_(pair_ids)))
    removed["pairs"] = result.rowcount or 0

    await session.commit()
    log.info("Purged archived SIM pairs", retention_days=retention_days, **removed)
    return removed
