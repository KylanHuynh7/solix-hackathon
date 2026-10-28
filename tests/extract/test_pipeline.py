import json
import os
from pathlib import Path

import pytest

from backend.extract import pipeline
from backend.extract.pipeline import extract_offer
from contracts.schemas import Case, Email, FieldStatus

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"
VERIFIED = FieldStatus.verified
REVIEW = FieldStatus.needs_review

LABELS = json.loads((SEED / "labels.json").read_text())
CASE = Case.model_validate_json((SEED / "case.json").read_text())


def _email(name: str) -> Email:
    return Email.model_validate_json((SEED / "emails" / f"{name}.json").read_text())


class FakeSpanLLM:
    model = "fake"

    def __init__(self, spans: dict):
        self.spans = spans
        self.calls = 0

    def find_spans(self, new_text, case) -> dict:
        self.calls += 1
        return dict(self.spans)


def _spans_from_labels(key: str, **overrides) -> dict:
    lab = LABELS[key]
    spans = {
        "is_offer": True,
        "ndc_raw": lab["ndc"]["raw"],
        "product_raw": None,
        "quantity_raw": lab["quantity"]["raw"],
        "lots": [lot["raw"] for lot in lab["lots"]],
        "expiry_raw": lab["expiry"]["raw"],
        "unit_price_raw": lab["unit_price"]["raw"],
        "lead_time_raw": None,
        "storage_raw": None,
    }
    spans.update(overrides)
    return spans


def _fake(key: str, **overrides) -> FakeSpanLLM:
    return FakeSpanLLM(_spans_from_labels(key, **overrides))


def _all_fields(offer):
    return [
        offer.ndc, offer.product, offer.quantity, offer.expiry,
        offer.unit_price, offer.lead_time_days, offer.storage, *offer.lots,
    ]


@pytest.mark.parametrize(
    "key,supplier",
    [("s1_offer", "SUP-001"), ("s2_offer", "SUP-002"), ("s3_offer", "SUP-003")],
)
def test_offer_matches_labels(key, supplier):
    email = _email(key)
    lab = LABELS[key]
    offer = extract_offer(email, CASE, llm=_fake(key))

    assert offer.supplier_id == supplier
    assert offer.round == 1
    assert offer.source_message_id == email.message_id == lab["message_id"]

    assert offer.ndc.value == lab["ndc"]["value"]
    assert offer.ndc.status == VERIFIED

    assert offer.expiry.status == VERIFIED
    assert str(offer.expiry.value) == lab["expiry"]["value"]

    assert offer.quantity.value == lab["quantity"]["value"]
    assert offer.quantity.unit == lab["quantity"]["unit"]
    assert offer.quantity.status == VERIFIED

    assert offer.unit_price.value == lab["unit_price"]["value"]
    assert offer.unit_price.unit == lab["unit_price"]["unit"]
    assert offer.unit_price.status == VERIFIED

    # lots extracted separately, never merged
    assert [f.value for f in offer.lots] == [lot["value"] for lot in lab["lots"]]
    assert all(f.status == VERIFIED for f in offer.lots)


def test_s1_multi_lot_kept_separate():
    offer = extract_offer(_email("s1_offer"), CASE, llm=_fake("s1_offer"))
    assert [f.value for f in offer.lots] == ["A1001", "A1002", "A1003"]


def test_s3_old_price_from_quoted_history_is_rejected():
    llm = _fake("s3_offer", unit_price_raw="USD 275.00 per pen")
    offer = extract_offer(_email("s3_offer"), CASE, llm=llm)
    assert offer.unit_price.value is None
    assert offer.unit_price.status == REVIEW
    assert "quoted history" in offer.unit_price.reason


def test_span_not_in_email_is_possible_hallucination():
    llm = _fake("s1_offer", ndc_raw="NDC 0169-9999-99")
    offer = extract_offer(_email("s1_offer"), CASE, llm=llm)
    assert offer.ndc.value is None
    assert offer.ndc.status == REVIEW
    assert "possible hallucination" in offer.ndc.reason


def test_null_span_is_not_stated():
    llm = _fake("s1_offer", expiry_raw=None)
    offer = extract_offer(_email("s1_offer"), CASE, llm=llm)
    assert offer.expiry.value is None
    assert offer.expiry.status == REVIEW
    assert "not stated in email" in offer.expiry.reason


def test_injection_email_yields_no_verified_fields():
    spans = {
        "is_offer": False, "ndc_raw": None, "product_raw": None, "quantity_raw": None,
        "lots": [], "expiry_raw": None, "unit_price_raw": None,
        "lead_time_raw": None, "storage_raw": None,
    }
    offer = extract_offer(_email("s1_injection"), CASE, llm=FakeSpanLLM(spans))
    assert offer.lots == []
    assert all(f.status != VERIFIED for f in _all_fields(offer))
    assert all(f.value is None for f in _all_fields(offer))


def test_unknown_sender_marks_everything_for_review():
    email = _email("s1_offer").model_copy(update={"sender": "stranger@unknown.example.org"})
    offer = extract_offer(email, CASE, llm=_fake("s1_offer"))
    assert offer.supplier_id == "UNKNOWN"
    assert offer.lots, "lots should still be present, but flagged"
    assert all(f.status == REVIEW for f in _all_fields(offer))


def test_round_increments_for_repeat_supplier():
    first = extract_offer(_email("s1_offer"), CASE, llm=_fake("s1_offer"))
    case2 = CASE.model_copy(update={"offers": [*CASE.offers, first]})
    second = extract_offer(_email("s1_offer"), case2, llm=_fake("s1_offer"))
    assert first.round == 1
    assert second.round == 2
    # a different supplier is unaffected
    other = extract_offer(_email("s3_offer"), case2, llm=_fake("s3_offer"))
    assert other.round == 1


def test_signature_and_run_meta():
    offer = extract_offer(_email("s1_offer"), CASE, llm=_fake("s1_offer"))
    assert offer.supplier_id == "SUP-001"
    meta = pipeline.last_run_meta
    assert "model" in meta and "prompt_version" in meta
    assert meta["model"] == "fake"
    assert meta["prompt_version"]


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
def test_live_anthropic_s1():
    offer = extract_offer(_email("s1_offer"), CASE)
    assert offer.ndc.value == "0169-4524-14"
    assert offer.quantity.value == 1200
