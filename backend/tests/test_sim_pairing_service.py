import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import McpServer, SimPairingGroup, SimPairingRun, SimPairingSim, SimPairingTopic
from app.services.sim_pairing_service import SimPairingService

MODULE = "app.services.sim_pairing_service"


class _PoisoningMcpClient:
    """Stands in for a TmLite client whose first call fails with a genuine
    database error (not just a Python exception), leaving the session in the
    same "needs rollback before reuse" state a real flush failure would."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, args):
        self._session.add(SimPairingSim(sim_id=1, display_name="Aïssata", country="CI"))
        self._session.add(SimPairingSim(sim_id=2, display_name="Aïssata", country="CI"))
        await self._session.flush()  # always raises IntegrityError before returning
        raise AssertionError("unreachable")


async def test_a_new_sim_is_not_given_a_name_already_held_by_an_ineligible_sim(session):
    # Aissata belongs to a SIM that has since left the tracked groups, so it is
    # absent from the "eligible" dict handed to _ensure_sim_names below — but
    # its display_name row is still there, and still unique across the table.
    session.add(SimPairingSim(sim_id=500, display_name="Aïssata", country="GN"))
    await session.commit()

    eligible = {600: {"country": "CI", "group": "love"}}
    names, assigned = await SimPairingService._ensure_sim_names(session, eligible)
    await session.commit()  # must not raise a unique-constraint IntegrityError

    assert assigned == 1
    assert names[600] != "Aïssata"
    assert names[600] == "Aminata"  # next free name in WEST_AFRICAN_NAMES


async def test_a_sim_with_an_existing_record_keeps_its_name_and_gets_country_refreshed(session):
    session.add(SimPairingSim(sim_id=42, display_name="Fatou", country="CI"))
    await session.commit()

    eligible = {42: {"country": "SN", "group": "love"}}
    names, assigned = await SimPairingService._ensure_sim_names(session, eligible)
    await session.commit()

    assert assigned == 0
    assert names[42] == "Fatou"

    record = (await session.execute(
        select(SimPairingSim).where(SimPairingSim.sim_id == 42)
    )).scalar_one()
    assert record.display_name == "Fatou"
    assert record.country == "SN"


async def test_sync_records_a_failed_run_instead_of_leaving_it_stuck_running(session):
    session.add(SimPairingGroup(name="love", enabled=True))
    session.add(SimPairingTopic(name="love"))
    session.add(McpServer(name="TmLite", transport="http", url="http://tmlite.test/mcp", enabled=True))
    await session.commit()

    with patch(f"{MODULE}.Client", lambda transport: _PoisoningMcpClient(session)):
        with pytest.raises(Exception, match="duplicate key value"):
            await SimPairingService.sync(session)

    run = (await session.execute(select(SimPairingRun))).scalar_one()
    assert run.status == "failed"
    assert run.error is not None
    assert "duplicate key value" in run.error
