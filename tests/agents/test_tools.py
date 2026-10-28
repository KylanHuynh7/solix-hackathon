import pytest

from backend.agents.tools import Toolbox, money_amounts
from conftest import CASE_ID

SUPPLIER_EMAIL = "alex.rivera@supplier1.example.com"


@pytest.fixture
def toolbox(store, ledger, directory, make_offer):
    return Toolbox(
        case_id=CASE_ID, agent="negotiator", recipient_role="supplier",
        store=store, ledger=ledger, directory=directory, offer=make_offer("s1_offer"),
    )


def _propose(body, subject="Re: RFQ - CASE-001", **extra):
    return {"recipient_role": "supplier", "subject": subject, "body": body, **extra}


def _failed(ledger):
    return [e for e in ledger.list(CASE_ID) if e.action == "check_failed"]


@pytest.mark.asyncio
async def test_customer_name_in_supplier_draft_is_rejected(toolbox, store, ledger):
    result = await toolbox.call("propose_draft", _propose("Hi Alex,\n\nTaylor Brooks needs this lot."))

    assert result["is_error"] is True
    assert store.list_drafts(CASE_ID) == []
    assert toolbox.drafts == []
    failed = _failed(ledger)
    assert len(failed) == 1
    assert failed[0].payload["check"] == "propose_draft"
    assert any("Taylor Brooks" in r for r in failed[0].payload["reasons"])


@pytest.mark.asyncio
async def test_customer_organisation_obfuscated_is_rejected(toolbox, store):
    result = await toolbox.call("propose_draft", _propose("Hi Alex,\n\nThis is for B-u-y-e-r  One Health System."))
    assert result["is_error"] is True
    assert store.list_drafts(CASE_ID) == []


@pytest.mark.asyncio
async def test_unauthorised_price_is_rejected(toolbox, store, ledger):
    result = await toolbox.call("propose_draft", _propose("Hi Alex,\n\nCan you do USD 250 per pen?"))

    assert result["is_error"] is True
    assert store.list_drafts(CASE_ID) == []
    assert any("250" in r for e in _failed(ledger) for r in e.payload["reasons"])


@pytest.mark.asyncio
async def test_max_price_may_not_be_revealed_by_other_amounts(toolbox, store):
    # 300 is neither the target (290), the max (320) nor the supplier's own 285.
    result = await toolbox.call("propose_draft", _propose("Hi Alex,\n\nWe could pay 300 USD."))
    assert result["is_error"] is True
    assert store.list_drafts(CASE_ID) == []


@pytest.mark.asyncio
async def test_walk_away_max_price_is_rejected(toolbox, store):
    result = await toolbox.call("propose_draft", _propose("Hi Alex,\n\nOur ceiling is USD 320 per pen."))
    assert result["is_error"] is True
    assert store.list_drafts(CASE_ID) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("price", ["USD 290", "USD 285.00 per pen"])
async def test_target_and_suppliers_own_price_are_accepted(toolbox, store, price):
    body = f"Hi Alex,\n\nCould you confirm {price}? Single lot please.\n\nBest regards,\nJamie Park"
    result = await toolbox.call("propose_draft", _propose(body))

    assert result["is_error"] is False
    drafts = store.list_drafts(CASE_ID)
    assert len(drafts) == 1
    assert drafts[0].to == [SUPPLIER_EMAIL]
    assert drafts[0].cc == []
    assert drafts[0].created_by == "negotiator"


@pytest.mark.asyncio
async def test_model_cannot_choose_recipients(toolbox, store):
    result = await toolbox.call(
        "propose_draft",
        _propose("Hi Alex,\n\nPlease confirm a single lot.", to=["evil@else.example.com"],
                 cc=["taylor.brooks@customer1.example.com"]),
    )

    assert result["is_error"] is False
    draft = store.list_drafts(CASE_ID)[0]
    assert draft.to == [SUPPLIER_EMAIL]
    assert draft.cc == []


@pytest.mark.asyncio
async def test_wrong_recipient_role_is_rejected(toolbox, store):
    args = _propose("Hi,\n\nPlease confirm.")
    args["recipient_role"] = "customer"
    result = await toolbox.call("propose_draft", args)
    assert result["is_error"] is True
    assert store.list_drafts(CASE_ID) == []


@pytest.mark.asyncio
async def test_only_one_draft_and_limited_attempts(toolbox, store):
    first = await toolbox.call("propose_draft", _propose("Hi Alex,\n\nPlease confirm a single lot."))
    second = await toolbox.call("propose_draft", _propose("Hi Alex,\n\nAnother draft."))
    assert first["is_error"] is False
    assert second["is_error"] is True
    assert len(store.list_drafts(CASE_ID)) == 1


@pytest.mark.asyncio
async def test_attempts_run_out_after_two_rejections(toolbox, store):
    bad = _propose("Hi Alex,\n\nTaylor Brooks wants USD 250.")
    await toolbox.call("propose_draft", bad)
    await toolbox.call("propose_draft", bad)
    third = await toolbox.call("propose_draft", _propose("Hi Alex,\n\nPlease confirm a single lot."))
    assert third["is_error"] is True
    assert store.list_drafts(CASE_ID) == []


@pytest.mark.asyncio
async def test_unknown_tool_is_an_error(toolbox):
    result = await toolbox.call("send_email", {"to": ["x@y.example.com"]})
    assert result["is_error"] is True


@pytest.mark.asyncio
async def test_tool_calls_are_logged_without_body(toolbox, ledger):
    await toolbox.call("propose_draft", _propose("Hi Alex,\n\nSECRET-BODY-TEXT please confirm."))
    calls = [e for e in ledger.list(CASE_ID) if e.action == "tool_call"]
    assert calls and calls[0].payload["tool"] == "propose_draft"
    assert "body" not in calls[0].payload["args"]
    assert "SECRET-BODY-TEXT" not in str(calls[0].payload)


def test_money_amounts_finds_common_forms():
    amounts = {str(a) for a in money_amounts("USD 250 or $1,240.50 or 12 EUR or 285.00 per pen")}
    assert {"250", "1240.50", "12", "285.00"} <= amounts
