import json
import os
import re

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

from unittest.mock import patch

import pytest
from sqlalchemy import select

from datetime import datetime, timedelta, timezone

from app.models import McpServer, SimPair, SimPairingGroup, SimPairingRun, SimPairingSim, SimPairingTopic, SimPairMessageQueue
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
            gateway_ids = sorted({sim.get("gateway_id") for sim in self._sims if sim.get("gateway_id") is not None})
            return [_Content([{"id": gateway_id, "country": "CI", "name": f"CIV-RED-{gateway_id}"} for gateway_id in gateway_ids])]
        if name == "list_sims":
            return [_Content(self._sims if args["skip"] == 0 else [])]
        raise AssertionError(f"unexpected tool call: {name}")


async def _seed_pairing_config(session):
    session.add(SimPairingGroup(name="love", enabled=True))
    session.add(SimPairingTopic(name="love"))
    session.add(McpServer(name="TmLite", transport="http", url="http://tmlite.test/mcp", enabled=True))
    await session.commit()


def _sim(sim_id, state, group="love", gateway_id=None):
    return {
        "id": sim_id,
        "state": state,
        "gateway_id": sim_id if gateway_id is None else gateway_id,
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


async def test_ensure_sim_names_never_falls_back_to_a_sim_id_label(session):
    """Even when far more SIMs need a name than the base pool holds, the
    fallback must compose a two-word name from the pool, never
    f"SIM {sim_id}" — that string is the single most obvious tell to a
    carrier's fraud detection that this traffic is machine-generated."""
    pool_size = len(SimPairingService.WEST_AFRICAN_NAMES)
    eligible = {sim_id: {"country": "CI", "group": "love"} for sim_id in range(1, pool_size + 10)}

    names, assigned = await SimPairingService._ensure_sim_names(session, eligible)
    await session.commit()

    assert assigned == len(eligible)
    for sim_id, name in names.items():
        assert not re.match(r"(?i)^sim\s*\d", name), f"sim {sim_id} got machine-looking name {name!r}"
    assert len(set(names.values())) == len(names)  # every generated name is unique


async def test_compound_fallback_name_is_unique_against_a_sim_outside_the_batch(session):
    """The unique-name check must span every row in the table, not just the
    batch being processed, even when the fallback has to compose a two-word
    name — checking only the batch is exactly the mistake that caused a
    production outage (a unique-constraint violation) last week."""
    names_pool = SimPairingService.WEST_AFRICAN_NAMES
    taken_compound = f"{names_pool[0]} {names_pool[1]}"
    # A SIM outside this run's batch already holds what would otherwise be
    # the very first compound name generated below.
    session.add(SimPairingSim(sim_id=999999, display_name=taken_compound, country="GN"))
    # Fill the entire base pool with other SIMs so the batch below must fall
    # back to a compound name.
    for offset, name in enumerate(names_pool):
        session.add(SimPairingSim(sim_id=100000 + offset, display_name=name, country="CI"))
    await session.commit()

    eligible = {1: {"country": "CI", "group": "love"}}
    names, assigned = await SimPairingService._ensure_sim_names(session, eligible)
    await session.commit()  # must not raise a unique-constraint IntegrityError

    assert assigned == 1
    assert names[1] != taken_compound
    assert " " in names[1]  # composed of two pool names, not a bare pool entry


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
    assert refreshed.archived_reason == "SIM 1 is BLOCKED in TmLite"

    new_pairs = list((await session.execute(select(SimPair).where(SimPair.id != pair.id))).scalars())
    for new_pair in new_pairs:
        assert 1 not in (new_pair.sim_a_id, new_pair.sim_b_id)


async def test_archiving_a_pair_during_sync_cancels_its_pending_queue_rows(session):
    """A pair archived in this very run must not leave a live queue row
    behind: the row was written for a pair that no longer exists as active."""
    await _seed_pairing_config(session)
    pair = SimPair(sim_a_id=1, sim_b_id=2, sim_a_name="Aïssata", sim_b_name="Aminata", country="CI", group_a="love", group_b="love", topic="love", target_messages=10)
    session.add(pair)
    await session.commit()
    session.add(SimPairMessageQueue(pair_id=pair.id, due_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
    await session.commit()

    sims = [_sim(1, "BLOCKED"), _sim(2, "IDLE"), _sim(3, "IDLE")]
    with patch(f"{MODULE}.Client", lambda transport: _FleetMcpClient(sims)):
        run = await SimPairingService.sync(session)

    assert run.summary["archived"] == 1
    queue = (await session.execute(
        select(SimPairMessageQueue).where(SimPairMessageQueue.pair_id == pair.id)
    )).scalar_one()
    assert queue.status == "cancelled"


async def test_sync_cancels_a_pending_queue_row_of_a_pair_archived_earlier(session):
    """A pair archived in a previous run must self-heal on the next sync,
    not require a one-off script to clean up its leftover queue row."""
    await _seed_pairing_config(session)
    pair = SimPair(
        sim_a_id=1, sim_b_id=2, sim_a_name="Aïssata", sim_b_name="Aminata", country="CI",
        group_a="love", group_b="love", topic="love", target_messages=10,
        status="archived", archived_reason="SIM unavailable or no longer eligible",
        archived_at=datetime.now(timezone.utc),
    )
    session.add(pair)
    await session.commit()
    session.add(SimPairMessageQueue(pair_id=pair.id, due_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
    await session.commit()

    sims = [_sim(3, "IDLE"), _sim(4, "IDLE")]
    with patch(f"{MODULE}.Client", lambda transport: _FleetMcpClient(sims)):
        await SimPairingService.sync(session)

    queue = (await session.execute(
        select(SimPairMessageQueue).where(SimPairMessageQueue.pair_id == pair.id)
    )).scalar_one()
    assert queue.status == "cancelled"


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


async def test_two_idle_sims_on_the_same_gateway_are_not_paired(session):
    await _seed_pairing_config(session)

    sims = [_sim(1, "IDLE", gateway_id=42), _sim(2, "IDLE", gateway_id=42)]
    with patch(f"{MODULE}.Client", lambda transport: _FleetMcpClient(sims)):
        run = await SimPairingService.sync(session)

    assert run.summary["created"] == 0
    assert list((await session.execute(select(SimPair))).scalars()) == []


async def test_sync_replaces_a_legacy_machine_name(session):
    """A sync repairs old "SIM 894" labels before they can reach an SMS."""
    await _seed_pairing_config(session)
    session.add_all([
        SimPairingSim(sim_id=1, display_name="SIM 894", country="CI"),
        SimPairingSim(sim_id=2, display_name="Aminata", country="CI"),
        SimPair(
            sim_a_id=1, sim_b_id=2, sim_a_name="SIM 894", sim_b_name="Aminata",
            country="CI", group_a="love", group_b="love", topic="business", target_messages=10,
        ),
    ])
    await session.commit()

    with patch(f"{MODULE}.Client", lambda transport: _FleetMcpClient([_sim(1, "IDLE"), _sim(2, "IDLE")])):
        run = await SimPairingService.sync(session)

    pair = (await session.execute(select(SimPair))).scalar_one()
    assert pair.sim_a_name != "SIM 894"
    assert not pair.sim_a_name.lower().startswith("sim ")
    assert run.summary["names_assigned"] == 1
    assert run.summary["pairs_named"] == 1


async def test_existing_sim_names_survive_a_run_that_exhausts_the_pool(session):
    """A SIM already named must never be renamed just because enough new SIMs
    arrive in the same run to exhaust the base pool and need compound
    fallback names."""
    await _seed_pairing_config(session)
    session.add(SimPairingSim(sim_id=1, display_name="Aïssata", country="CI"))
    await session.commit()

    pool_size = len(SimPairingService.WEST_AFRICAN_NAMES)
    sims = [_sim(1, "IDLE")] + [_sim(sim_id, "IDLE") for sim_id in range(2, pool_size + 5)]
    with patch(f"{MODULE}.Client", lambda transport: _FleetMcpClient(sims)):
        await SimPairingService.sync(session)

    record = (await session.execute(
        select(SimPairingSim).where(SimPairingSim.sim_id == 1)
    )).scalar_one()
    assert record.display_name == "Aïssata"
