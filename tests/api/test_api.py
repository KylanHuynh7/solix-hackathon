import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.api.demo import get_processor
from backend.api.demo_stub import process_email as stub_process_email
from backend.api.state import AppState, get_state
from backend.main import app

CASE = "CASE-001"


@pytest.fixture
def state(tmp_path):
    s = AppState(tmp_path / "var")
    yield s
    s.close()


@pytest.fixture
def client(state):
    app.dependency_overrides[get_state] = lambda: state
    app.dependency_overrides[get_processor] = lambda: ("stub", stub_process_email)
    yield TestClient(app)
    app.dependency_overrides.clear()


def wait_idle(client, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/demo/status").json()
        if status["processing"] is None:
            return status
        time.sleep(0.02)
    raise AssertionError("demo job did not finish")


def process(client, n):
    """Run n seeded emails through the background job; return each finished job's outcome."""
    out = []
    for _ in range(n):
        started = client.post("/demo/process-next")
        assert started.status_code == 200, started.json()
        status = wait_idle(client)
        assert status["last"]["ok"], status["last"]
        out.append({"processed": status["last"]["key"], "result": status["last"]["result"], **status})
    return out


def proposed(client, role):
    drafts = client.get("/drafts", params={"status": "proposed"}).json()
    return next(d for d in drafts if d["recipient_role"] == role)


def actions(client):
    return [e["action"] for e in client.get("/audit", params={"case_id": CASE}).json()]


def test_cases_endpoints(client):
    cases = client.get("/cases").json()
    assert [c["case_id"] for c in cases] == [CASE]
    assert client.get(f"/cases/{CASE}").json()["state"] == "Quoting"
    assert client.get("/cases/NOPE").status_code == 404


def test_approve_sends_exactly_once_and_logs_both_events(client):
    process(client, 1)  # s1_offer -> negotiator counter-offer
    draft = proposed(client, "supplier")

    response = client.post(f"/drafts/{draft['draft_id']}/approve", json={"approver": "Jamie Park"})
    assert response.status_code == 200
    assert response.json()["draft"]["status"] == "sent"
    assert response.json()["draft"]["approver"] == "Jamie Park"

    outbox = client.get("/outbox").json()
    assert len(outbox) == 1
    assert outbox[0]["draft_id"] == draft["draft_id"]
    assert outbox[0]["via"] == "simulator"

    events = client.get("/audit", params={"case_id": CASE}).json()
    approved = [e for e in events if e["action"] == "draft_approved"]
    sent = [e for e in events if e["action"] == "email_sent"]
    assert len(approved) == 1 and len(sent) == 1
    assert approved[0]["actor"] == sent[0]["actor"] == "human:Jamie Park"
    assert approved[0]["seq"] < sent[0]["seq"]


def test_double_approve_is_409_and_sends_nothing_more(client):
    process(client, 1)
    draft_id = proposed(client, "supplier")["draft_id"]
    assert client.post(f"/drafts/{draft_id}/approve", json={"approver": "Jamie"}).status_code == 200
    again = client.post(f"/drafts/{draft_id}/approve", json={"approver": "Jamie"})
    assert again.status_code == 409
    assert len(client.get("/outbox").json()) == 1
    assert actions(client).count("email_sent") == 1


@pytest.mark.parametrize("approver", ["", "   "])
def test_approve_requires_a_human_name(client, approver):
    process(client, 1)
    draft_id = proposed(client, "supplier")["draft_id"]
    response = client.post(f"/drafts/{draft_id}/approve", json={"approver": approver})
    assert response.status_code == 422
    assert client.get("/outbox").json() == []


def test_approve_missing_approver_field_is_422(client):
    process(client, 1)
    draft_id = proposed(client, "supplier")["draft_id"]
    assert client.post(f"/drafts/{draft_id}/approve", json={}).status_code == 422


def test_approve_unknown_draft_is_404(client):
    assert client.post("/drafts/NOPE/approve", json={"approver": "Jamie"}).status_code == 404


def test_edited_body_is_what_gets_sent(client):
    process(client, 1)
    draft_id = proposed(client, "supplier")["draft_id"]
    client.post(
        f"/drafts/{draft_id}/approve",
        json={"approver": "Jamie", "edited_body": "Edited by a human."},
    )
    assert client.get("/outbox").json()[0]["body"] == "Edited by a human."
    approved = [
        e for e in client.get("/audit").json() if e["action"] == "draft_approved"
    ]
    assert approved[0]["payload"]["edited"] is True


def test_empty_edited_body_is_blocked_by_outbound_check(client):
    process(client, 1)
    draft_id = proposed(client, "supplier")["draft_id"]
    response = client.post(
        f"/drafts/{draft_id}/approve", json={"approver": "Jamie", "edited_body": "  "}
    )
    assert response.status_code == 422
    assert client.get("/outbox").json() == []
    assert "check_failed" in actions(client)
    assert client.get("/drafts", params={"status": "proposed"}).json()


def test_reject_logs_and_removes_from_queue(client):
    process(client, 1)
    draft_id = proposed(client, "supplier")["draft_id"]
    response = client.post(
        f"/drafts/{draft_id}/reject", json={"approver": "Jamie", "reason": "tone"}
    )
    assert response.status_code == 200
    assert client.get("/drafts", params={"status": "proposed"}).json() == []
    rejected = client.get("/drafts", params={"status": "rejected"}).json()
    assert rejected[0]["draft_id"] == draft_id
    assert rejected[0]["reason"] == "tone"
    event = [e for e in client.get("/audit").json() if e["action"] == "draft_rejected"][0]
    assert event["actor"] == "human:Jamie"
    assert event["payload"]["reason"] == "tone"
    # A rejected draft can't then be approved.
    assert client.post(f"/drafts/{draft_id}/approve", json={"approver": "J"}).status_code == 404
    assert client.get("/outbox").json() == []


def test_reject_requires_reason(client):
    process(client, 1)
    draft_id = proposed(client, "supplier")["draft_id"]
    response = client.post(f"/drafts/{draft_id}/reject", json={"approver": "Jamie", "reason": ""})
    assert response.status_code == 422


def test_seeded_sequence_matches_storyline(client):
    s1, s2, s3, inj, cust = process(client, 5)

    assert s1["processed"] == "s1_offer"
    assert len(s1["result"]["exceptions"]) == 2
    assert s1["result"]["drafts"][0]["created_by"] == "negotiator"

    assert "TABLET" in s2["result"]["exceptions"][0].upper()
    assert s2["result"]["drafts"] == []

    assert s3["result"]["drafts"][0]["recipient_role"] == "customer"
    assert s3["result"]["exceptions"] == []
    case = client.get(f"/cases/{CASE}").json()
    s3_offer = next(o for o in case["offers"] if o["supplier_id"] == "SUP-003")
    assert s3_offer["unit_price"]["value"] == 310.0  # not the stale 275 in quoted history

    assert inj["result"]["drafts"] == []
    assert "tool_denied" in actions(client)

    assert cust["processed"] == "cust_yes"
    assert client.get(f"/cases/{CASE}").json()["state"] == "Confirmed"
    assert cust["next"] is None
    assert client.post("/demo/process-next").status_code == 409


def test_full_flow_to_ordered_and_ledger_verifies(client):
    process(client, 3)
    customer_draft = proposed(client, "customer")
    client.post(f"/drafts/{customer_draft['draft_id']}/approve", json={"approver": "Jamie Park"})
    assert client.get(f"/cases/{CASE}").json()["state"] == "AwaitingCustomer"

    process(client, 2)
    intents = client.get("/sap-intents", params={"case_id": CASE}).json()
    assert [i["doc_type"] for i in intents] == ["rfq", "supplier_quotation", "purchase_order"]
    assert all(i["status"] == "proposed" for i in intents)

    numbers = []
    for intent in intents:
        r = client.post(f"/sap-intents/{intent['intent_id']}/approve", json={"approver": "Jamie"})
        assert r.status_code == 200
        assert r.json()["status"] == "executed"
        numbers.append(r.json()["document_number"])
    assert numbers == ["RFQ-6000001", "QTN-7000001", "PO-4500001"]

    again = client.post(
        f"/sap-intents/{intents[0]['intent_id']}/approve", json={"approver": "Jamie"}
    )
    assert again.status_code == 409

    assert client.get(f"/cases/{CASE}").json()["state"] == "Ordered"
    assert actions(client).count("sap_document_created") == 3
    verify = client.get("/audit/verify").json()
    assert verify["ok"] is True
    assert verify["count"] > 10


def test_sap_intent_approve_requires_approver(client):
    process(client, 5)
    intent_id = client.get("/sap-intents").json()[0]["intent_id"]
    r = client.post(f"/sap-intents/{intent_id}/approve", json={"approver": " "})
    assert r.status_code == 422
    assert client.get("/sap-intents", params={"status": "executed"}).json() == []


def test_reset_gives_clean_case_and_new_ledger(client, state):
    process(client, 3)
    old_ledger = state.ledger.path
    draft_id = proposed(client, "customer")["draft_id"]
    client.post(f"/drafts/{draft_id}/approve", json={"approver": "Jamie"})

    status = client.post("/demo/reset").json()
    assert status["next"] == "s1_offer"
    case = client.get(f"/cases/{CASE}").json()
    assert case["offers"] == [] and case["exceptions"] == [] and case["state"] == "Quoting"
    assert client.get("/drafts").json() == []
    assert client.get("/outbox").json() == []
    assert client.get("/sap-intents").json() == []

    assert state.ledger.path != old_ledger
    assert old_ledger.exists()
    assert [e["action"] for e in client.get("/audit").json()] == ["demo_reset"]
    assert client.get("/audit/verify").json()["ok"] is True


def test_full_sequence_twice_from_reset(client):
    for _ in range(2):
        client.post("/demo/reset")
        process(client, 5)
        assert client.get(f"/cases/{CASE}").json()["state"] == "Confirmed"
        assert client.get("/audit/verify").json()["ok"] is True


def test_sap_router_is_not_mounted(client):
    assert client.post("/sap/purchase-order", json={"d": {}}).status_code == 404


def test_demo_status(client):
    assert client.get("/demo/status").json()["next"] == "s1_offer"
    process(client, 1)
    assert client.get("/demo/status").json()["next"] == "s2_offer"


def _blocking_processor(gate: threading.Event):
    async def process(email, case_id, *, store, ledger):
        gate.wait(5)
        return {"drafts": [], "log": [], "exceptions": []}

    return ("fake", process)


def test_process_next_returns_at_once_and_blocks_a_second_job(client):
    gate = threading.Event()
    app.dependency_overrides[get_processor] = lambda: _blocking_processor(gate)
    started = client.post("/demo/process-next")
    assert started.status_code == 200
    assert started.json()["key"] == "s1_offer"
    assert started.json()["processing"].startswith("<s1-offer")
    assert client.get("/demo/status").json()["processing"] == "s1_offer"
    assert client.post("/demo/process-next").status_code == 409
    assert client.post("/demo/reset").status_code == 409
    gate.set()
    status = wait_idle(client)
    assert status["last"]["ok"] is True
    assert status["next"] == "s2_offer"


def test_failed_job_is_reported_logged_and_retryable(client):
    async def broken(email, case_id, *, store, ledger):
        raise RuntimeError("model unavailable")

    app.dependency_overrides[get_processor] = lambda: ("fake", broken)
    client.post("/demo/process-next")
    status = wait_idle(client)
    assert status["last"]["ok"] is False
    assert "model unavailable" in status["last"]["error"]
    assert status["next"] == "s1_offer"  # not advanced: the same email can be retried
    failed = [e for e in client.get("/audit").json() if e["action"] == "check_failed"]
    assert failed[-1]["payload"]["check"] == "process_email"
    assert client.get("/audit/verify").json()["ok"] is True


def test_emails_endpoint(client):
    emails = client.get("/emails").json()
    assert len(emails) == 5
    one = client.get("/emails", params={"message_id": "<s3-offer-001@supplier3.example.com>"})
    assert [e["sender"] for e in one.json()] == ["morgan.chen@supplier3.example.com"]
    assert client.get("/emails", params={"message_id": "nope"}).json() == []


def test_default_processor_is_the_real_agents(monkeypatch):
    from backend.api.demo import default_processor

    monkeypatch.delenv("NEUROBIZ_PROCESSOR", raising=False)
    assert default_processor()[0] == "agents"
    monkeypatch.setenv("NEUROBIZ_PROCESSOR", "stub")
    assert default_processor()[0] == "stub"
