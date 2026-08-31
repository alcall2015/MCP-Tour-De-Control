import json
import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import McpServer, SimPair, SimPairingGroup, SimPairingRun, SimPairingSim, SimPairingTopic
from app.services.sim_pairing_service import SimPairingService

MODULE = "app.services.sim_pairing_service"


class _Content:
    """Stands in for the MCP TextContent item: `result[0].text` is JSON."""

    def __init__(self, data):
        self.text = json.dumps(data)


class _FleetMcpClient:
    """Stands in for the TmLite client for a full sync(): serves one fixed
    gateway (country CI) and a caller-supplied fleet of SIMs."""

    def __init__(self, sims):
        self._sims = sims

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name, args):
        if name == "list_gateways":
            return [_Content([{"id": 1, "country": "CI", "name": "CIV-RED-1"}])]
        if name == "list_sims":
            return [_Content(self._sims if args["skip"] == 0 else [])]
        raise AssertionError(f"unexpected tool call: {name}")


async def _seed_pairing_config(session):
    session.add(SimPairingGroup(name="love", enabled=True))
    session.add(SimPairingTopic(name="love"))
    session.add(McpServer(name="TmLite", transport="http", url="http://tmlite.test/mcp", enabled=True))
    await session.commit()


def _sim(sim_id, state, group="love", gateway_id=1):
    return {
        "id": sim_id,
        "state": state,
        "gateway_id": gateway_id,
        "sim_group_name": group,
        "phone_number": f"07{sim_id:08d}",
    }


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


async def test_a_busy_sim_keeps_its_pair_but_is_not_used_to_create_a_new_one(session):
    """BUSY is transient (mid-call): archiving on it would destroy history and
    reset sent_count every run, so an existing pair must survive. But it also
    cannot actually send right now, so it must not be handed a new pair."""
    await _seed_pairing_config(session)
    pair = SimPair(sim_a_id=1, sim_b_id=2, sim_a_name="Aïssata", sim_b_name="Aminata", country="CI", group_a="love", group_b="love", topic="love", target_messages=10)
    session.add(pair)
    await session.commit()

    sims = [_sim(1, "BUSY"), _sim(2, "IDLE"), _sim(3, "IDLE")]
    with patch(f"{MODULE}.Client", lambda transport: _FleetMcpClient(sims)):
        run = await SimPairingService.sync(session)

    assert run.summary["archived"] == 0
    refreshed = (await session.execute(select(SimPair).where(SimPair.id == pair.id))).scalar_one()
    assert refreshed.status == "active"

    # SIM 1 is BUSY: it must not appear in any newly created pair.
    new_pairs = list((await session.execute(select(SimPair).where(SimPair.id != pair.id))).scalars())
    for new_pair in new_pairs:
        assert 1 not in (new_pair.sim_a_id, new_pair.sim_b_id)


async def test_a_blocked_sim_has_its_pairs_archived_and_gets_no_new_pair(session):
    """BLOCKED is durable: it needs a manual TmLite reset_sim_blocking before
    it can rejoin, so it belongs with OFFLINE/DISABLED, not with the
    transient states."""
    await _seed_pairing_config(session)
    pair = SimPair(sim_a_id=1, sim_b_id=2, sim_a_name="Aïssata", sim_b_name="Aminata", country="CI", group_a="love", group_b="love", topic="love", target_messages=10)
    session.add(pair)
    await session.commit()

    sims = [_sim(1, "BLOCKED"), _sim(2, "IDLE"), _sim(3, "IDLE")]
    with patch(f"{MODULE}.Client", lambda transport: _FleetMcpClient(sims)):
        run = await SimPairingService.sync(session)

    assert run.summary["archived"] == 1
    refreshed = (await session.execute(select(SimPair).where(SimPair.id == pair.id))).scalar_one()
    assert refreshed.status == "archived"

    new_pairs = list((await session.execute(select(SimPair).where(SimPair.id != pair.id))).scalars())
    for new_pair in new_pairs:
        assert 1 not in (new_pair.sim_a_id, new_pair.sim_b_id)


async def test_two_idle_sims_still_get_paired(session):
    """Guard against over-tightening: two ordinary IDLE SIMs must still be
    paired as before."""
    await _seed_pairing_config(session)

    sims = [_sim(1, "IDLE"), _sim(2, "IDLE")]
    with patch(f"{MODULE}.Client", lambda transport: _FleetMcpClient(sims)):
        run = await SimPairingService.sync(session)

    assert run.summary["created"] == 1
    pairs = list((await session.execute(select(SimPair))).scalars())
    assert len(pairs) == 1
    assert {pairs[0].sim_a_id, pairs[0].sim_b_id} == {1, 2}
