import asyncio
import os

import pytest

from backend.agents import process_email
from backend.api.demo_stub import DEMO_ORDER
from backend.ledger import ACTIONS
from backend.validate.checks import check_outbound
from contracts.schemas import CaseState, Draft

from conftest import CASE_ID, DIRECTORY, load_email

REVIEW = "customer reply needs human review"


def _events(ledger, action):
    return [e for e in ledger.list(CASE_ID) if e.action == action]


def _failed_checks(ledger):
    return [e.payload.get("check") for e in _events(ledger, "check_failed")]


def _state(store):
    return store.get_case(CASE_ID).state


# --- supplier offers -------------------------------------------------------


@pytest.mark.asyncio
async def test_s1_offer_fails_checks_and_drafts_counter_offer(store, ledger, runner, extract_calls, send):
    result = await send("s1_offer")

    assert _state(store) == CaseState.Exception
    assert any("2027-10-31" in e or "2028-06-30" in e for e in result["exceptions"])
    assert any("3 lots" in e for e in result["exceptions"])

    assert runner.agents == ["negotiator"]
    assert len(result["drafts"]) == 1
    draft = result["drafts"][0]
    assert draft["created_by"] == "negotiator"
    assert draft["recipient_role"] == "supplier"
    assert draft["to"] == ["alex.rivera@supplier1.example.com"]
    assert draft["cc"] == []
    assert len(store.list_drafts(CASE_ID)) == 1

    actions = {e.action for e in ledger.list(CASE_ID)}
    assert {"email_ingested", "fields_extracted", "check_failed", "case_state_changed",
            "draft_proposed"} <= actions
    assert {"expiry_min", "single_lot"} <= set(_failed_checks(ledger))
    change = _events(ledger, "case_state_changed")[0].payload
    assert change["from"] == "Quoting" and change["to"] == "Exception"


@pytest.mark.asyncio
async def test_s1_prompt_wraps_email_as_untrusted(runner, extract_calls, send):
    await send("s1_offer")
    prompt = runner.runs[0].prompt
    assert "<untrusted_email>" in prompt and "</untrusted_email>" in prompt
    assert runner.runs[0].recipient_role == "supplier"


@pytest.mark.asyncio
async def test_s2_wrong_dosage_form_flags_exception_without_draft(store, ledger, runner, extract_calls, send):
    result = await send("s2_offer")

    assert _state(store) == CaseState.Exception
    assert any("tablet" in e.lower() or "injection pen" in e.lower() for e in result["exceptions"])
    assert "dosage_form" in _failed_checks(ledger)
    assert result["drafts"] == []
    assert store.list_drafts(CASE_ID) == []
    assert runner.runs == []


@pytest.mark.asyncio
async def test_s2_after_s1_still_no_second_draft(store, runner, extract_calls, send):
    await send("s1_offer")
    result = await send("s2_offer")
    assert result["drafts"] == []
    assert runner.agents == ["negotiator"]
    assert len(store.list_drafts(CASE_ID)) == 1


@pytest.mark.asyncio
async def test_s3_compliant_offer_asks_customer_to_confirm(store, ledger, runner, extract_calls, send):
    result = await send("s3_offer")

    assert _state(store) == CaseState.AwaitingCustomer
    assert result["exceptions"] == []
    assert runner.agents == ["confirmer"]
    assert len(result["drafts"]) == 1
    draft = result["drafts"][0]
    assert draft["created_by"] == "confirmer"
    assert draft["recipient_role"] == "customer"
    assert draft["to"] == ["taylor.brooks@customer1.example.com"]
    assert _failed_checks(ledger) == []


# --- injection -------------------------------------------------------------


@pytest.mark.asyncio
async def test_injection_email_is_denied_not_followed(store, ledger, runner, extract_calls, send):
    result = await send("s1_injection")

    denied = _events(ledger, "tool_denied")
    assert len(denied) == 1
    assert denied[0].payload["tool"] == "approve_purchase_order"
    assert "Ignore prior instructions" in denied[0].payload["quote"]

    assert result["drafts"] == []
    assert result["exceptions"], "a human should be told about the injection attempt"
    assert runner.runs == []
    assert extract_calls == []
    assert _state(store) == CaseState.Quoting
    assert store.list_sap_intents(CASE_ID) == []


# --- customer reply --------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_yes_confirms_and_proposes_three_sap_intents(
    store, ledger, extract_calls, fake_confirm, send
):
    await send("s3_offer")
    await send("cust_yes")

    assert _state(store) == CaseState.Confirmed
    intents = store.list_sap_intents(CASE_ID)
    assert sorted(i.doc_type for i in intents) == ["purchase_order", "rfq", "supplier_quotation"]
    assert all(i.status == "proposed" for i in intents)

    by_type = {i.doc_type: i.payload for i in intents}
    for payload in by_type.values():
        assert payload["Quantity"] == 300
        assert payload["Unit"] == "carton"
        assert payload["Material"] == "0169-4524-14"
        assert payload["Supplier"] == "SUP-003"
        assert payload["Batch"] == "C3300"
        assert str(payload["ShelfLifeExpiry"]) == "2028-11-30"
    for doc_type in ("supplier_quotation", "purchase_order"):
        assert by_type[doc_type]["NetPrice"] == 1240.0
        assert by_type[doc_type]["Currency"] == "USD"
    assert "NetPrice" not in by_type["rfq"]


@pytest.mark.asyncio
async def test_customer_yes_without_parser_needs_human_review(
    store, ledger, extract_calls, no_confirm, send
):
    await send("s3_offer")
    changes_before = len(_events(ledger, "case_state_changed"))

    result = await send("cust_yes")

    assert REVIEW in result["exceptions"]
    assert _state(store) == CaseState.AwaitingCustomer
    assert len(_events(ledger, "case_state_changed")) == changes_before
    assert store.list_sap_intents(CASE_ID) == []
    assert result["drafts"] == []


@pytest.mark.asyncio
async def test_customer_yes_before_any_offer_is_not_confirmed(store, fake_confirm, send):
    result = await send("cust_yes")
    assert REVIEW in result["exceptions"]
    assert _state(store) == CaseState.Quoting
    assert store.list_sap_intents(CASE_ID) == []


# --- unknown sender --------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_sender_goes_to_human_review(store, ledger, runner, extract_calls):
    email = load_email("s1_offer").model_copy(update={"sender": "someone@else.example.com"})
    result = await process_email(email, CASE_ID, store=store, ledger=ledger, runner=runner)

    assert result["drafts"] == []
    assert result["exceptions"]
    assert runner.runs == []
    assert extract_calls == []
    assert _state(store) == CaseState.Quoting


# --- agent failure ---------------------------------------------------------


def _agent_failures(ledger):
    return [e for e in _events(ledger, "check_failed") if e.payload.get("check") == "agent_failed"]


@pytest.mark.asyncio
async def test_runner_that_raises_is_logged_not_fatal(store, ledger, extract_calls, send):
    async def boom(run):
        raise RuntimeError("simulated agent crash")

    result = await send("s1_offer", boom)

    assert result["drafts"] == []
    assert store.list_drafts(CASE_ID) == []
    failures = _agent_failures(ledger)
    assert len(failures) == 1
    assert "simulated agent crash" in failures[0].payload["error"]
    assert _state(store) == CaseState.Exception


@pytest.mark.asyncio
async def test_runner_that_times_out_is_logged_not_fatal(
    store, ledger, extract_calls, send, monkeypatch
):
    monkeypatch.setattr("backend.agents.orchestrator.AGENT_TIMEOUT_S", 0.05)

    async def slow(run):
        await asyncio.sleep(5)

    result = await send("s1_offer", slow)

    assert result["drafts"] == []
    assert store.list_drafts(CASE_ID) == []
    failures = _agent_failures(ledger)
    assert len(failures) == 1
    assert "timed out" in failures[0].payload["error"]


@pytest.mark.asyncio
async def test_runner_that_proposes_nothing_is_logged(store, ledger, extract_calls, send):
    async def idle(run):
        return None

    result = await send("s1_offer", idle)
    assert result["drafts"] == []
    assert len(_agent_failures(ledger)) == 1


# --- full demo -------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_demo_sequence(store, ledger, runner, extract_calls, fake_confirm, send):
    drafts = []
    for key in DEMO_ORDER:
        result = await send(key)
        drafts += result["drafts"]

    assert _state(store) == CaseState.Confirmed
    assert len(drafts) == 2
    assert [d["created_by"] for d in drafts] == ["negotiator", "confirmer"]
    assert len(store.list_drafts(CASE_ID)) == 2
    assert len(store.list_sap_intents(CASE_ID)) == 3
    assert ledger.verify()["ok"] is True
    assert {e.action for e in ledger.list()} <= ACTIONS
    # the injection email never reached an agent or the extractor
    assert "s1_injection" not in extract_calls
    assert runner.agents == ["negotiator", "confirmer"]


# --- live ------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
async def test_live_s1_offer_real_agent(store, ledger):
    # No monkeypatching: real extraction and the real Claude Agent SDK runner.
    result = await process_email(load_email("s1_offer"), CASE_ID, store=store, ledger=ledger, runner=None)

    assert _state(store) == CaseState.Exception
    negotiator = [d for d in result["drafts"] if d["created_by"] == "negotiator"]
    assert len(negotiator) <= 1
    case = store.get_case(CASE_ID)
    for d in negotiator:
        failed = [r for r in check_outbound(Draft.model_validate(d), case, DIRECTORY) if not r.ok]
        assert failed == []
