import os

os.environ.setdefault("ENCRYPTION_KEY", "LOHFyasyawfKr9DJJpfITXBzO33W_ID2O64CkB5jom8=")

import uuid
from datetime import datetime, timedelta, timezone

from app.models import SimPair
from app.services.sim_pair_conversation_service import SimPairConversationService
from app.services.sim_pair_conversation_service import SimPairConversationService as Service

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _pair(a: int, b: int, sent_count: int = 0, target: int = 10) -> SimPair:
    return SimPair(
        id=uuid.uuid4(),
        sim_a_id=a,
        sim_b_id=b,
        sim_a_name=f"A{a}",
        sim_b_name=f"B{b}",
        country="CI",
        group_a="love",
        group_b="love",
        topic="love",
        target_messages=target,
        sent_count=sent_count,
    )


def _candidate(a: int, b: int, **kwargs) -> dict:
    pair = _pair(a, b, **kwargs)
    return {"queue": object(), "pair": pair, "latest": None, "sender_id": a, "recipient_id": b}


def _sims(*sim_ids: int, state: str = "IDLE") -> dict:
    return {sim_id: {"id": sim_id, "state": state, "phone_number": f"+2250000{sim_id}"} for sim_id in sim_ids}


def test_a_sim_speaks_at_most_once_per_run():
    candidates = [_candidate(1, 2), _candidate(1, 3), _candidate(4, 5)]
    chosen, deferred, held = SimPairConversationService._select_batch(
        candidates, _sims(1, 2, 3, 4, 5), {}, NOW, batch_size=10, cooldown_minutes=0
    )
    assert [(item["sender_id"], item["recipient_id"]) for item in chosen] == [(1, 2), (4, 5)]
    assert deferred == []
    assert len(held) == 1


def test_cooldown_holds_a_recently_active_sim():
    candidates = [_candidate(1, 2), _candidate(3, 4)]
    last_activity = {2: NOW - timedelta(minutes=5)}
    chosen, _, held = SimPairConversationService._select_batch(
        candidates, _sims(1, 2, 3, 4), last_activity, NOW, batch_size=10, cooldown_minutes=20
    )
    assert [item["sender_id"] for item in chosen] == [3]
    assert held[0][1] == "A paired SIM is still in its cooldown"


def test_cooldown_expires():
    candidates = [_candidate(1, 2)]
    last_activity = {2: NOW - timedelta(minutes=21)}
    chosen, _, held = SimPairConversationService._select_batch(
        candidates, _sims(1, 2), last_activity, NOW, batch_size=10, cooldown_minutes=20
    )
    assert len(chosen) == 1
    assert held == []


def test_zero_cooldown_disables_the_rule():
    candidates = [_candidate(1, 2)]
    last_activity = {1: NOW}
    chosen, _, held = SimPairConversationService._select_batch(
        candidates, _sims(1, 2), last_activity, NOW, batch_size=10, cooldown_minutes=0
    )
    assert len(chosen) == 1
    assert held == []


def test_an_unreachable_sim_is_deferred_not_held():
    candidates = [_candidate(1, 2)]
    sims = _sims(1, 2)
    sims[2]["state"] = "BUSY"
    chosen, deferred, held = SimPairConversationService._select_batch(
        candidates, sims, {}, NOW, batch_size=10, cooldown_minutes=0
    )
    assert chosen == []
    assert held == []
    assert deferred[0][1] == "A paired SIM is not IDLE"


def test_a_sim_missing_from_tmlite_is_deferred():
    candidates = [_candidate(1, 99)]
    chosen, deferred, _ = SimPairConversationService._select_batch(
        candidates, _sims(1), {}, NOW, batch_size=10, cooldown_minutes=0
    )
    assert chosen == []
    assert deferred[0][1] == "A paired SIM is not IDLE"


def test_batch_size_caps_the_run():
    candidates = [_candidate(1, 2), _candidate(3, 4), _candidate(5, 6)]
    chosen, deferred, held = SimPairConversationService._select_batch(
        candidates, _sims(1, 2, 3, 4, 5, 6), {}, NOW, batch_size=2, cooldown_minutes=0
    )
    assert len(chosen) == 2
    # The cap stops the walk; the remainder is untouched, not marked as skipped.
    assert deferred == [] and held == []


def test_a_speaker_label_is_stripped_from_the_sms():
    # The transcript is rendered "Name: text", so the model imitates the shape.
    assert Service._clean_generated("Koffi: Mon coeur bat pour toi.", "Koffi", "Ibrahima") == "Mon coeur bat pour toi."
    assert Service._clean_generated("ibrahima: Salut !", "Koffi", "Ibrahima") == "Salut !"


def test_ordinary_text_with_a_colon_is_left_alone():
    assert Service._clean_generated("Mon amour: tu me manques.", "Koffi", "Ibrahima") == "Mon amour: tu me manques."
    assert Service._clean_generated('"Bonjour toi"', "Koffi", "Ibrahima") == "Bonjour toi"


def test_empty_generation_stays_empty_for_the_caller_to_reject():
    assert Service._clean_generated(None, "Koffi", "Ibrahima") == ""
    assert Service._clean_generated("   ", "Koffi", "Ibrahima") == ""


def test_a_doubled_speaker_label_is_fully_stripped():
    # History that already leaked a prefix renders as "Koffi: Koffi: ..." in the
    # transcript, so one pass is not enough.
    assert Service._clean_generated("Koffi: Koffi: Salut Cheikh !", "Koffi", "Cheikh") == "Salut Cheikh !"
    assert Service._clean_generated("Koffi: Cheikh: Salut !", "Koffi", "Cheikh") == "Salut !"
