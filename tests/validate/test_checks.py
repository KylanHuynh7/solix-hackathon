"""Tests for backend/validate/checks.py (written before the implementation exists)."""

import json
from pathlib import Path

import pytest

from backend.validate.checks import (
    CheckResult,
    check_outbound,
    exceptions_for,
    validate_offer,
)
from contracts.schemas import Case, Draft, DraftStatus, Field, FieldStatus, Offer

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"

SUPPLIER_IDS = {"s1_offer": "SUP-001", "s2_offer": "SUP-002", "s3_offer": "SUP-003"}

NOT_LABELLED = dict(value=None, status=FieldStatus.needs_review, reason="not labelled")


def _load(name):
    return json.loads((SEED / name).read_text())


def _field(d):
    return Field.model_validate(d)


def _build_offer(key):
    label = _load("labels.json")[key]
    return Offer(
        supplier_id=SUPPLIER_IDS[key],
        round=1,
        ndc=_field(label["ndc"]),
        product=Field(**NOT_LABELLED),
        quantity=_field(label["quantity"]),
        lots=[_field(x) for x in label["lots"]],
        expiry=_field(label["expiry"]),
        unit_price=_field(label["unit_price"]),
        lead_time_days=Field(**NOT_LABELLED),
        storage=Field(**NOT_LABELLED),
        source_message_id=label["message_id"],
    )


@pytest.fixture
def case():
    return Case.model_validate(_load("case.json"))


@pytest.fixture
def openfda():
    return _load("openfda_cache.json")


@pytest.fixture
def directory():
    return _load("directory.json")


@pytest.fixture
def s1():
    return _build_offer("s1_offer")


@pytest.fixture
def s2():
    return _build_offer("s2_offer")


@pytest.fixture
def s3():
    return _build_offer("s3_offer")


def by_name(results):
    names = [r.check for r in results]
    assert len(names) == len(set(names)), f"duplicate check names: {names}"
    return {r.check: r for r in results}


def run(offer, case, openfda):
    return by_name(validate_offer(offer, case, openfda))


CHECK_NAMES = {
    "ndc_known",
    "dosage_form",
    "expiry_min",
    "single_lot",
    "quantity_unit",
    "price_basis",
    "needs_review",
}


def test_one_result_per_check_name(s3, case, openfda):
    results = validate_offer(s3, case, openfda)
    assert all(isinstance(r, CheckResult) for r in results)
    assert {r.check for r in results} == CHECK_NAMES
    assert len(results) == len(CHECK_NAMES)


# ---- seed offers ----


def test_s1_fails_expiry_min_and_single_lot(s1, case, openfda):
    r = run(s1, case, openfda)
    # 10/27 -> 2027-10-31 is before the 2028-06-30 minimum; three lots vs single_lot
    assert r["expiry_min"].ok is False
    assert r["single_lot"].ok is False
    assert r["expiry_min"].reason
    assert r["single_lot"].reason


def test_s2_fails_dosage_form_and_quantity_unit(s2, case, openfda):
    r = run(s2, case, openfda)
    assert r["dosage_form"].ok is False
    assert r["quantity_unit"].ok is False


def test_s2_dosage_form_reason_names_both_forms(s2, case, openfda):
    reason = run(s2, case, openfda)["dosage_form"].reason.lower()
    assert "tablet" in reason
    assert "injection pen" in reason
    # spec text, loosely
    assert "offered tablets" in reason or "tablet" in reason


def test_s3_passes_all_core_checks(s3, case, openfda):
    r = run(s3, case, openfda)
    for name in (
        "ndc_known",
        "dosage_form",
        "expiry_min",
        "single_lot",
        "quantity_unit",
        "price_basis",
    ):
        assert r[name].ok is True, f"{name}: {r[name].reason}"


def test_s3_needs_review_passes_when_regulated_fields_verified(s3, case, openfda):
    # lead_time_days / storage are unlabelled (needs_review) but not regulated
    r = run(s3, case, openfda)
    assert r["needs_review"].ok is True
    assert exceptions_for(validate_offer(s3, case, openfda)) == []


# ---- price basis / carton conversion ----


def _carton_offer(s3, cartons=300):
    o = s3.model_copy(deep=True)
    o.unit_price = o.unit_price.model_copy(
        update={"value": 1140, "unit": "USD/carton", "raw": "USD 1,140 per carton"}
    )
    o.quantity = o.quantity.model_copy(
        update={"value": cartons, "unit": "carton", "raw": f"{cartons} cartons"}
    )
    return o


def test_carton_price_converted_with_pack_size(s3, case, openfda):
    r = run(_carton_offer(s3), case, openfda)
    assert r["price_basis"].ok is True
    assert "USD 1,140/carton = USD 285/pen at 4 per carton" in r["price_basis"].reason


def test_carton_quantity_300_equals_1200_pens(s3, case, openfda):
    r = run(_carton_offer(s3, 300), case, openfda)
    assert r["quantity_unit"].ok is True


def test_carton_quantity_299_fails(s3, case, openfda):
    r = run(_carton_offer(s3, 299), case, openfda)
    assert r["quantity_unit"].ok is False


def test_unknown_price_basis_fails(s3, case, openfda):
    o = s3.model_copy(deep=True)
    o.unit_price = o.unit_price.model_copy(update={"unit": "USD/box"})
    r = run(o, case, openfda)
    assert r["price_basis"].ok is False


# ---- unverified regulated fields ----


def test_null_expiry_needs_review(s3, case, openfda):
    o = s3.model_copy(deep=True)
    o.expiry = Field(
        value=None,
        raw="10/27",
        status=FieldStatus.needs_review,
        reason="ambiguous month/year vs month/day",
    )
    results = validate_offer(o, case, openfda)
    r = by_name(results)
    assert r["expiry_min"].ok is False
    assert r["expiry_min"].reason == "expiry not verified; needs human review"
    assert "expiry not verified; needs human review" in exceptions_for(results)
    assert r["needs_review"].ok is False
    assert "expiry" in r["needs_review"].reason.lower()


def test_exceptions_for_returns_reasons_of_failed_checks_only(s2, case, openfda):
    results = validate_offer(s2, case, openfda)
    failed = [x.reason for x in results if not x.ok]
    assert failed
    assert exceptions_for(results) == failed


# ---- NDC ----


def test_unknown_ndc_fails_ndc_known(s3, case, openfda):
    o = s3.model_copy(deep=True)
    o.ndc = o.ndc.model_copy(update={"value": "0000-0000-00", "raw": "NDC 0000-0000-00"})
    r = run(o, case, openfda)
    assert r["ndc_known"].ok is False


# ---- outbound leak check ----


def _draft(role="supplier", to=None, cc=None, subject="Quote request", body="Please quote 1,200 pens."):
    return Draft(
        draft_id="D-1",
        case_id="CASE-001",
        recipient_role=role,
        to=to if to is not None else ["alex.rivera@supplier1.example.com"],
        cc=cc or [],
        subject=subject,
        body=body,
        status=DraftStatus.proposed,
        created_by="test",
    )


def _leak(draft, case, directory):
    return by_name(check_outbound(draft, case, directory))["no_customer_leak"]


def test_clean_supplier_draft_passes(case, directory):
    assert _leak(_draft(), case, directory).ok is True


@pytest.mark.parametrize(
    "body",
    [
        "Quoting for Taylor Brooks.",
        "TAYLOR BROOKS needs this.",
        "taylor brooks needs this.",
        "This is for Buyer One Health System.",
        "BUYER ONE HEALTH SYSTEM wants it.",
    ],
)
def test_supplier_body_leak_fails(case, directory, body):
    assert _leak(_draft(body=body), case, directory).ok is False


def test_supplier_cc_customer_email_fails(case, directory):
    d = _draft(cc=["taylor.brooks@customer1.example.com"])
    assert _leak(d, case, directory).ok is False


def test_supplier_to_customer_email_fails(case, directory):
    d = _draft(to=["Taylor.Brooks@Customer1.example.com"])
    assert _leak(d, case, directory).ok is False


@pytest.mark.parametrize("subject", ["Quote for CUST-001", "quote for cust-001"])
def test_supplier_subject_customer_id_fails(case, directory, subject):
    assert _leak(_draft(subject=subject), case, directory).ok is False


def test_customer_draft_may_mention_customer(case, directory):
    d = _draft(
        role="customer",
        to=["taylor.brooks@customer1.example.com"],
        subject="Your quote CUST-001",
        body="Hello Taylor Brooks, quote attached for Buyer One Health System.",
    )
    assert _leak(d, case, directory).ok is True


def test_default_openfda_cache_loads(s3, case, openfda):
    assert validate_offer(s3, case) == validate_offer(s3, case, openfda)


# ---- hardening: leak-check bypasses and fail-closed gating ----

BYPASS_BODIES = [
    "TAYLOR  BROOKS",
    "Taylor\nBrooks",
    "Taylor Brooks",
    "T a y l o r Brooks",
    "taylor.brooks@\ncustomer1.example.com",
    "taylor%2Ebrooks@customer1.example.com",
    "see https://portal.example.org/rfq?org=Buyer+One+Health+System",
    "buyer-one-health-system.com",
    "CUST 001",
    "Ms. Brooks",
    "reply via customer1.example.com",
]


@pytest.mark.parametrize("body", BYPASS_BODIES)
def test_bypass_strings_fail_check_outbound(case, directory, body):
    result = _leak(_draft(body=body), case, directory)
    assert result.ok is False
    assert "customer" in result.reason


def test_leak_reason_names_matched_identifier(case, directory):
    result = _leak(_draft(body="CUST 001"), case, directory)
    assert "customer id" in result.reason


def test_normal_supplier_draft_with_supplier_name_passes(case, directory):
    d = _draft(
        subject="RFQ: semaglutide injection pens, 1,200 units",
        body=(
            "Hello Alex Rivera at Supplier One Pharma,\n"
            "Please quote NDC 0169-4524-14, 1,200 pens, single lot, minimum expiry 06/2028, "
            "stored at 2-8C. Reply to alex.rivera@supplier1.example.com. Thank you."
        ),
        cc=["jamie.park@neurobiz.example.com"],
    )
    assert _leak(d, case, directory).ok is True


def _with(offer, **fields):
    return offer.model_copy(update=fields)


def _nr(field):
    return field.model_copy(update={"status": FieldStatus.needs_review})


@pytest.mark.parametrize(
    "check, field",
    [
        ("ndc_known", "ndc"),
        ("dosage_form", "ndc"),
        ("quantity_unit", "quantity"),
        ("price_basis", "unit_price"),
        ("expiry_min", "expiry"),
    ],
)
def test_needs_review_input_fails_check(s3, case, openfda, check, field):
    offer = _with(s3, **{field: _nr(getattr(s3, field))})
    result = run(offer, case, openfda)[check]
    assert result.ok is False
    assert f"{field} not verified; needs human review" == result.reason


def test_single_lot_needs_review_lot_fails(s3, case, openfda):
    offer = _with(s3, lots=[_nr(s3.lots[0])])
    result = run(offer, case, openfda)["single_lot"]
    assert result.ok is False
    assert result.reason == "lots not verified; needs human review"


def test_single_lot_with_one_none_lot_fails(s3, case, openfda):
    none_lot = Field(value=None, status=FieldStatus.verified)
    result = run(_with(s3, lots=[none_lot]), case, openfda)["single_lot"]
    assert result.ok is False


def test_unverified_ndc_blocks_carton_conversion(s3, case, openfda):
    offer = _with(
        s3,
        ndc=_nr(s3.ndc),
        quantity=s3.quantity.model_copy(update={"value": 300, "unit": "carton"}),
    )
    result = run(offer, case, openfda)["quantity_unit"]
    assert result.ok is False
    assert result.reason == "ndc not verified; needs human review"


def test_s3_still_passes_six_checks_after_hardening(s3, case, openfda):
    results = run(s3, case, openfda)
    for name in ("ndc_known", "dosage_form", "expiry_min", "single_lot",
                 "quantity_unit", "price_basis"):
        assert results[name].ok is True, (name, results[name].reason)
