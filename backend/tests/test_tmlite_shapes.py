import json
from pathlib import Path

from app.services.tmlite_shapes import normalize_call, normalize_sms, sim_index

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "tmlite_payloads.json").read_text())


def test_every_fixture_sms_normalizes():
    rows = [normalize_sms(r) for r in FIXTURES["list_sms"]]
    assert all(r is not None for r in rows), "a real payload failed to normalize"
    assert all(isinstance(r["sim_id"], int) and r["from_number"] and r["ref"] for r in rows)


def test_every_fixture_call_normalizes():
    rows = [normalize_call(r) for r in FIXTURES["list_calls"]]
    assert all(r is not None for r in rows)
    assert all(r["caller"] and r["callee"] and r["status"] for r in rows)


def test_a_call_carries_gateway_and_slot_because_it_has_no_sim_id():
    row = normalize_call(FIXTURES["list_calls"][0])
    assert "sim_id" not in row
    assert row["gateway"] and isinstance(row["slot"], int)


def test_the_sim_index_resolves_a_call_to_a_sim():
    index = sim_index(FIXTURES["list_sims"])
    sim = FIXTURES["list_sims"][0]
    assert index[(sim["gateway_name"], sim["slot"])] == sim["id"]


def test_a_row_missing_a_required_field_is_dropped_not_guessed():
    assert normalize_sms({}) is None
    assert normalize_call({"caller": "33600000000"}) is None
