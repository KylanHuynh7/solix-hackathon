"""Tests for backend/validate/outbound.py and its wiring into backend.api.outbound."""

import json
from pathlib import Path

import pytest

from backend.api import outbound as api_outbound
from backend.api.outbound import LEAK_CHECK_IS_STUB
from backend.validate.outbound import check_outbound
from contracts.schemas import Case, Draft, DraftStatus

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"


@pytest.fixture
def case():
    return Case.model_validate(json.loads((SEED / "case.json").read_text()))


def _draft(role="supplier", body="Please quote 1,200 pens.", to=None):
    return Draft(
        draft_id="D-1",
        case_id="CASE-001",
        recipient_role=role,
        to=to or ["alex.rivera@supplier1.example.com"],
        cc=[],
        subject="Quote request",
        body=body,
        status=DraftStatus.proposed,
        created_by="test",
    )


def test_supplier_draft_naming_customer_contact_has_problem(case):
    problems = check_outbound(_draft(body="Buyer is Taylor Brooks."), case)
    assert problems
    assert all(isinstance(p, str) for p in problems)


def test_clean_supplier_draft_has_no_problems(case):
    assert check_outbound(_draft(), case) == []


def test_customer_draft_naming_taylor_has_no_problems(case):
    d = _draft(role="customer", body="Hi Taylor, your quote is ready.",
               to=["taylor.brooks@customer1.example.com"])
    assert check_outbound(d, case) == []


def test_api_module_uses_real_leak_check():
    assert LEAK_CHECK_IS_STUB is False


def test_api_check_outbound_returns_leak_problem(case):
    problems = api_outbound.check_outbound(_draft(body="For Taylor Brooks at Buyer One"), case)
    assert any("customer details" in p for p in problems)
