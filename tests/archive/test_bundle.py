import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.api.state import AppState, get_state
from backend.ledger import canonical_json
from backend.main import app

CASE = "CASE-001"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # The real agents processor, served from the cached replays in data/replay: no network.
    monkeypatch.setenv("NB_REPLAY", "replay")
    monkeypatch.delenv("NB_REPLAY_DIR", raising=False)
    monkeypatch.delenv("NEUROBIZ_PROCESSOR", raising=False)
    state = AppState(tmp_path / "var")
    app.dependency_overrides[get_state] = lambda: state
    yield TestClient(app)
    app.dependency_overrides.clear()
    state.close()


def wait_idle(client, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/demo/status").json()
        if status["processing"] is None:
            return status
        time.sleep(0.02)
    raise AssertionError("demo job did not finish")


@pytest.fixture
def processed(client):
    assert client.post("/demo/reset").status_code == 200
    for _ in range(5):
        assert client.post("/demo/process-next").status_code == 200
        status = wait_idle(client)
        assert status["last"]["ok"], status["last"]
    return client


def test_bundle_contents(processed):
    response = processed.get(f"/cases/{CASE}/solix-bundle")
    assert response.status_code == 200
    bundle = response.json()

    assert bundle["bundle_version"] == "1"
    assert bundle["source_system"] == "TransPharmic"

    offers = bundle["offers_with_evidence"]
    assert len(offers) == 3
    for offer in offers:
        assert offer["supplier_id"] and offer["source_message_id"]
        assert any(offer[name]["evidence"] for name in ("ndc", "expiry", "quantity", "unit_price"))
        for name in ("ndc", "expiry", "quantity", "unit_price"):
            assert set(offer[name]) == {"value", "unit", "status", "evidence", "reason"}

    assert "C3300" in bundle["retention"]["hold_keys"]["lots"]

    ledger = bundle["ledger"]
    assert ledger["verify"]["ok"] is True
    assert ledger["head_hash"] == ledger["events"][-1]["hash"]

    body = {k: v for k, v in bundle.items() if k != "integrity"}
    expected = hashlib.sha256(canonical_json(body).encode()).hexdigest()
    assert bundle["integrity"]["bundle_sha256"] == expected


def test_bundle_is_read_only(processed):
    before = processed.get("/audit").json()
    assert processed.get(f"/cases/{CASE}/solix-bundle").status_code == 200
    after = processed.get("/audit").json()
    assert len(after) == len(before)
    assert after[-1]["hash"] == before[-1]["hash"]


def test_unknown_case_is_404(client):
    assert client.get("/cases/NOPE/solix-bundle").status_code == 404


def test_bundle_carries_no_api_key(processed):
    text = json.dumps(processed.get(f"/cases/{CASE}/solix-bundle").json())
    assert "sk-ant" not in text
