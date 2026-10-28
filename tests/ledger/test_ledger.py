import sqlite3

import pytest

from backend.ledger import GENESIS_HASH, InMemoryLedger, SqliteLedger, compute_hash


def _append_n(ledger, n, case_id="CASE-001"):
    return [
        ledger.append(
            case_id=case_id,
            actor="orchestrator",
            action="tool_call",
            source="test",
            payload={"i": i, "note": f"event {i}"},
        )
        for i in range(n)
    ]


@pytest.fixture(params=["sqlite", "memory"])
def ledger(request, tmp_path):
    if request.param == "memory":
        yield InMemoryLedger()
    else:
        sqlite_ledger = SqliteLedger(tmp_path / "ledger.db")
        yield sqlite_ledger
        sqlite_ledger.close()


def _raw_conn(path):
    """A second connection that bypasses the append-only triggers, simulating a tamperer."""
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER audit_events_no_update")
    conn.execute("DROP TRIGGER audit_events_no_delete")
    return conn


def test_chain_verifies_after_five_appends(ledger):
    events = _append_n(ledger, 5)

    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert events[0].prev_hash == GENESIS_HASH
    for prev, cur in zip(events, events[1:]):
        assert cur.prev_hash == prev.hash
    assert ledger.verify() == {"ok": True, "first_broken_seq": None, "count": 5}


def test_empty_ledger_verifies(ledger):
    assert ledger.verify() == {"ok": True, "first_broken_seq": None, "count": 0}


def test_hash_matches_documented_formula(ledger):
    event = _append_n(ledger, 1)[0]
    assert event.hash == compute_hash(event.model_dump(mode="json"))
    assert len(event.hash) == 64
    assert event.ts.tzinfo is not None


def test_list_filters_by_case_and_round_trips(ledger):
    _append_n(ledger, 2, case_id="CASE-001")
    _append_n(ledger, 1, case_id="CASE-002")
    ledger.append(
        case_id="CASE-001",
        actor="human:Jamie Park",
        action="draft_approved",
        source="api",
        payload={"draft_id": "D-1"},
        model="claude-sonnet-5-5",
        prompt_version="v1",
    )

    assert len(ledger.list()) == 4
    case_1 = ledger.list("CASE-001")
    assert [e.seq for e in case_1] == [1, 2, 4]
    assert case_1[-1].actor == "human:Jamie Park"
    assert case_1[-1].model == "claude-sonnet-5-5"
    assert case_1[-1].payload == {"draft_id": "D-1"}


def test_no_update_or_delete_methods():
    for cls in (SqliteLedger, InMemoryLedger):
        for name in ("update", "delete", "remove", "edit", "pop", "clear"):
            assert not hasattr(cls, name)


def test_correction_is_a_new_event(ledger):
    _append_n(ledger, 2)
    fix = ledger.append(
        case_id="CASE-001",
        actor="human:Jamie Park",
        action="fields_extracted",
        source="api",
        payload={"corrects_seq": 2, "field": "expiry", "value": "2028-11-30"},
    )
    assert fix.seq == 3
    assert ledger.verify()["ok"]


def test_rejects_missing_required_fields(ledger):
    with pytest.raises(ValueError):
        ledger.append(case_id="", actor="system", action="tool_call", source="t", payload={})


def test_non_json_payload_values_hash_stably(ledger):
    from datetime import date

    ledger.append(
        case_id="CASE-001",
        actor="system",
        action="check_failed",
        source="validator",
        payload={"min_expiry": date(2028, 6, 30)},
    )
    assert ledger.verify()["ok"]


def test_sqlite_triggers_block_update_and_delete(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = SqliteLedger(path)
    _append_n(ledger, 2)
    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE audit_events SET payload = '{}' WHERE seq = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM audit_events WHERE seq = 1")
    conn.close()
    ledger.close()


def test_edited_payload_detected_at_that_seq(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = SqliteLedger(path)
    _append_n(ledger, 5)
    conn = _raw_conn(path)
    conn.execute(
        "UPDATE audit_events SET payload = ? WHERE seq = ?", ('{"i":99,"note":"forged"}', 3)
    )
    conn.commit()
    conn.close()

    assert ledger.verify() == {"ok": False, "first_broken_seq": 3, "count": 5}
    ledger.close()


def test_edit_with_recomputed_hash_breaks_next_link(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = SqliteLedger(path)
    _append_n(ledger, 5)
    forged = ledger.list()[2].model_dump(mode="json")
    forged["payload"] = {"i": 99, "note": "forged"}
    forged_hash = compute_hash(forged)
    conn = _raw_conn(path)
    conn.execute(
        "UPDATE audit_events SET payload = ?, hash = ? WHERE seq = ?",
        ('{"i":99,"note":"forged"}', forged_hash, 3),
    )
    conn.commit()
    conn.close()

    assert ledger.verify() == {"ok": False, "first_broken_seq": 4, "count": 5}
    ledger.close()


def test_deleted_row_detected(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = SqliteLedger(path)
    _append_n(ledger, 5)
    conn = _raw_conn(path)
    conn.execute("DELETE FROM audit_events WHERE seq = ?", (2,))
    conn.commit()
    conn.close()

    assert ledger.verify() == {"ok": False, "first_broken_seq": 2, "count": 4}
    ledger.close()


def test_non_json_payload_tamper_detected(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = SqliteLedger(path)
    _append_n(ledger, 3)
    conn = _raw_conn(path)
    conn.execute("UPDATE audit_events SET payload = ? WHERE seq = ?", ("not json", 1))
    conn.commit()
    conn.close()

    assert ledger.verify() == {"ok": False, "first_broken_seq": 1, "count": 3}
    ledger.close()


def test_persists_across_reopen(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = SqliteLedger(path)
    _append_n(ledger, 3)
    ledger.close()

    reopened = SqliteLedger(path)
    event = _append_n(reopened, 1)[0]
    assert event.seq == 4
    assert reopened.verify() == {"ok": True, "first_broken_seq": None, "count": 4}
    reopened.close()


def test_in_memory_tamper_detected():
    ledger = InMemoryLedger()
    _append_n(ledger, 5)
    ledger._events[2].payload["note"] = "forged"
    assert ledger.verify() == {"ok": False, "first_broken_seq": 3, "count": 5}


def test_list_returns_copies():
    ledger = InMemoryLedger()
    _append_n(ledger, 1)
    ledger.list()[0].payload["note"] = "mutated by caller"
    assert ledger.verify()["ok"]
