import sqlite3
from datetime import datetime, timezone

import pytest

from backend.store import InMemoryCaseStore, OutboxEmail, SapIntent, SqliteCaseStore
from contracts.schemas import CaseState, Draft, DraftStatus


@pytest.fixture(params=["sqlite", "memory"])
def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryCaseStore()
    else:
        s = SqliteCaseStore(tmp_path / "store.db")
        s.load_seed()
        yield s
        s.close()


def make_draft(draft_id="D-1", status=DraftStatus.proposed, case_id="CASE-001"):
    return Draft(
        draft_id=draft_id,
        case_id=case_id,
        recipient_role="supplier",
        to=["a@x.example.com"],
        cc=[],
        subject="s",
        body="b",
        status=status,
        created_by="negotiator",
    )


def test_seed_case(store):
    case = store.get_case("CASE-001")
    assert case.line_item.quantity == 1200
    assert [c.case_id for c in store.list_cases()] == ["CASE-001"]
    with pytest.raises(KeyError):
        store.get_case("NOPE")


def test_save_case_round_trips(store):
    case = store.get_case("CASE-001")
    case.state = CaseState.Exception
    case.exceptions.append("x")
    store.save_case(case)
    assert store.get_case("CASE-001").state == CaseState.Exception
    assert store.get_case("CASE-001").exceptions == ["x"]


def test_drafts_filter_and_update(store):
    store.save_draft(make_draft("D-1"))
    store.save_draft(make_draft("D-2", DraftStatus.sent))
    store.save_draft(make_draft("D-3", case_id="CASE-002"))
    assert [d.draft_id for d in store.list_drafts()] == ["D-1", "D-2", "D-3"]
    assert [d.draft_id for d in store.list_drafts(status=DraftStatus.proposed)] == ["D-1", "D-3"]
    assert [d.draft_id for d in store.list_drafts("CASE-001", DraftStatus.sent)] == ["D-2"]

    d1 = store.get_draft("D-1")
    d1.status = DraftStatus.approved
    store.save_draft(d1)
    assert store.get_draft("D-1").status == DraftStatus.approved
    assert [d.draft_id for d in store.list_drafts()] == ["D-1", "D-2", "D-3"]
    with pytest.raises(KeyError):
        store.get_draft("NOPE")


def test_sap_intents(store):
    intent = SapIntent(
        intent_id="I-1", case_id="CASE-001", doc_type="rfq", payload={"a": 1}, status="proposed"
    )
    store.save_sap_intent(intent)
    assert store.list_sap_intents("CASE-001", "proposed")[0].payload == {"a": 1}
    assert store.list_sap_intents(status="executed") == []


def test_reject_moves_draft_out_of_queue(store):
    store.save_draft(make_draft("D-1"))
    store.reject_draft("D-1", "Jamie", "wrong tone")
    assert store.list_drafts() == []
    assert store.list_rejections("CASE-001")[0].reason == "wrong tone"


def test_load_seed_clears_everything(store):
    store.save_draft(make_draft())
    store.save_sap_intent(
        SapIntent(intent_id="I", case_id="CASE-001", doc_type="rfq", payload={}, status="proposed")
    )
    store.record_outbox(
        OutboxEmail(
            draft_id="D-1",
            case_id="CASE-001",
            to=[],
            cc=[],
            subject="",
            body="",
            approver="J",
            sent_at=datetime.now(timezone.utc),
        )
    )
    store.load_seed()
    assert store.list_drafts() == []
    assert store.list_sap_intents() == []
    assert store.list_outbox() == []


def test_sqlite_outbox_rejects_second_send_of_same_draft(tmp_path):
    s = SqliteCaseStore(tmp_path / "store.db")
    email = OutboxEmail(
        draft_id="D-1",
        case_id="CASE-001",
        to=["a@x.example.com"],
        cc=[],
        subject="s",
        body="b",
        approver="J",
        sent_at=datetime.now(timezone.utc),
    )
    assert s.record_outbox(email).outbox_id == 1
    with pytest.raises(sqlite3.IntegrityError):
        s.record_outbox(email)
    s.close()


def test_sql_injection_in_filters_is_inert(tmp_path):
    s = SqliteCaseStore(tmp_path / "store.db")
    s.load_seed()
    s.save_draft(make_draft())
    assert s.list_drafts(case_id="x' OR '1'='1") == []
    s.close()
