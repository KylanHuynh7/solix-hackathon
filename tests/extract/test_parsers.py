import json
from pathlib import Path

import pytest

from backend.extract.parsers import (
    clean_email,
    parse_expiry,
    parse_ndc,
    parse_price,
    parse_quantity,
)
from contracts.schemas import FieldStatus

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"
VERIFIED = FieldStatus.verified
REVIEW = FieldStatus.needs_review


def _load(path: Path):
    return json.loads(path.read_text())


def _body(name: str) -> str:
    return _load(SEED / "emails" / f"{name}.json")["body"]


LABELS = _load(SEED / "labels.json")
KNOWN_NDCS = set(_load(SEED / "openfda_cache.json").keys())
OFFERS = ["s1_offer", "s2_offer", "s3_offer"]


# --- clean_email ----------------------------------------------------------

def test_s3_new_text_has_current_price_not_old():
    cleaned = clean_email(_body("s3_offer"))
    assert "310.00" in cleaned.new_text
    assert "275.00" not in cleaned.new_text


def test_s3_old_price_only_in_quoted_text():
    cleaned = clean_email(_body("s3_offer"))
    assert "275.00" in cleaned.quoted_text


def test_s1_new_text_has_no_quote_markers():
    cleaned = clean_email(_body("s1_offer"))
    assert "wrote:" not in cleaned.new_text
    for line in cleaned.new_text.splitlines():
        assert not line.startswith(">")


def test_s1_keeps_greeting_body():
    cleaned = clean_email(_body("s1_offer"))
    assert "Thanks for reaching out" in cleaned.new_text


def test_s1_signature_has_sender_name():
    cleaned = clean_email(_body("s1_offer"))
    assert "Alex Rivera" in cleaned.signature


def test_s1_multi_lot_lines_survive_cleaning():
    new_text = clean_email(_body("s1_offer")).new_text
    for lot in ("A1001", "A1002", "A1003"):
        assert lot in new_text


# --- labels, parametrised -------------------------------------------------

@pytest.mark.parametrize("name", OFFERS)
def test_label_ndc(name):
    label = LABELS[name]["ndc"]
    got = parse_ndc(label["raw"], KNOWN_NDCS)
    assert got.value == label["value"]
    assert got.status == VERIFIED


@pytest.mark.parametrize("name", OFFERS)
def test_label_expiry(name):
    label = LABELS[name]["expiry"]
    got = parse_expiry(label["raw"])
    assert got.value == label["value"]
    assert got.status == VERIFIED


@pytest.mark.parametrize("name", OFFERS)
def test_label_quantity(name):
    label = LABELS[name]["quantity"]
    got = parse_quantity(label["raw"])
    assert got.value == label["value"]
    assert got.unit == label["unit"]
    assert got.status == VERIFIED


@pytest.mark.parametrize("name", OFFERS)
def test_label_unit_price(name):
    label = LABELS[name]["unit_price"]
    got = parse_price(label["raw"])
    assert got.value == label["value"]
    assert got.unit == label["unit"]
    assert got.status == VERIFIED


def test_cust_yes_expiry_parses():
    label = LABELS["cust_yes"]["expiry"]
    got = parse_expiry(label["raw"])
    assert got.value == label["value"] == "2028-11-30"
    assert got.status == VERIFIED


def test_null_labels_stay_null_in_ground_truth():
    # Regulated fields not stated in the email must be null with a reason.
    for name in ("cust_yes", "s1_injection"):
        for key in ("ndc", "quantity"):
            assert LABELS[name][key]["value"] is None
            assert LABELS[name][key]["reason"]
    assert LABELS["s1_injection"]["lots"] == []


def test_empty_input_is_null_with_reason():
    for got in (
        parse_ndc("", KNOWN_NDCS),
        parse_expiry(""),
        parse_quantity(""),
        parse_price(""),
    ):
        assert got.value is None
        assert got.status == REVIEW
        assert got.reason


# --- NDC edge cases -------------------------------------------------------

@pytest.mark.parametrize("raw", ["00169-4524-14", "00169452414"])
def test_eleven_digit_ndc_normalises_to_known_form(raw):
    got = parse_ndc(raw, KNOWN_NDCS)
    assert got.value == "0169-4524-14"
    assert got.status == VERIFIED


def test_unhyphenated_ten_digit_ndc_needs_review():
    got = parse_ndc("0169452414", KNOWN_NDCS)
    assert got.status == REVIEW
    assert got.value in (None, "0169-4524-14")
    assert got.reason


@pytest.mark.parametrize("raw", ["0169-4524-14", "NDC 0169-4524-14"])
def test_hyphenated_ten_digit_known_ndc_verified(raw):
    got = parse_ndc(raw, KNOWN_NDCS)
    assert got.value == "0169-4524-14"
    assert got.status == VERIFIED


@pytest.mark.parametrize("raw", ["0169-4524-1", "169-4524-14", "01690-45-14", "0169-45244-14"])
def test_malformed_ndc_segments_rejected(raw):
    got = parse_ndc(raw, KNOWN_NDCS)
    assert got.value is None
    assert got.status == REVIEW
    assert got.reason


def test_eleven_digit_with_no_known_match_is_not_guessed():
    got = parse_ndc("00000-0000-00", KNOWN_NDCS)
    assert got.value is None
    assert got.status == REVIEW


def test_ndc_garbage_is_null():
    got = parse_ndc("call me maybe", KNOWN_NDCS)
    assert got.value is None
    assert got.status == REVIEW


# --- expiry edge cases ----------------------------------------------------

def test_expiry_mm_yy_is_pharma_convention():
    got = parse_expiry("10/27")
    assert got.value == "2027-10-31"
    assert got.status == VERIFIED
    assert got.reason == "MM/YY pharma convention"


def test_expiry_mm_yyyy():
    got = parse_expiry("03/2028")
    assert got.value == "2028-03-31"
    assert got.status == VERIFIED


@pytest.mark.parametrize("raw", ["Nov 2028", "November 2028", "2028-11"])
def test_expiry_month_year_forms(raw):
    got = parse_expiry(raw)
    assert got.value == "2028-11-30"
    assert got.status == VERIFIED


def test_expiry_iso_date_as_is():
    got = parse_expiry("2027-10-31")
    assert got.value == "2027-10-31"
    assert got.status == VERIFIED


def test_expiry_ambiguous_day_month_is_null():
    got = parse_expiry("05/06/2028")
    assert got.value is None
    assert got.status == REVIEW
    assert "ambiguous" in got.reason.lower()


def test_expiry_dd_mm_yyyy_flagged_for_review():
    got = parse_expiry("31/10/2027")
    assert got.value == "2027-10-31"
    assert got.status == REVIEW
    assert "DD/MM/YYYY" in got.reason


@pytest.mark.parametrize("raw", ["soon", "13/27", "2027-13-45", "n/a"])
def test_expiry_garbage_is_null(raw):
    got = parse_expiry(raw)
    assert got.value is None
    assert got.status == REVIEW
    assert got.reason


# --- quantity -------------------------------------------------------------

def test_quantity_with_thousands_separator():
    got = parse_quantity("1,200 pens")
    assert got.value == 1200
    assert got.unit == "pen"
    assert got.status == VERIFIED


def test_quantity_unknown_unit_needs_review():
    got = parse_quantity("1,200 widgets")
    assert got.status == REVIEW
    assert got.reason


def test_quantity_without_unit_needs_review():
    got = parse_quantity("1200")
    assert got.status == REVIEW


def test_quantity_garbage_is_null():
    got = parse_quantity("lots of pens")
    assert got.value is None
    assert got.status == REVIEW


# --- price ----------------------------------------------------------------

def test_price_per_carton_with_thousands_separator():
    got = parse_price("USD 1,140 per carton")
    assert got.value == 1140.0
    assert got.unit == "USD/carton"
    assert got.status == VERIFIED


def test_price_dollar_slash_pen():
    got = parse_price("$310/pen")
    assert got.value == 310.0
    assert got.unit == "USD/pen"
    assert got.status == VERIFIED


def test_price_without_basis_needs_review():
    got = parse_price("USD 285.00")
    assert got.status == REVIEW
    assert got.reason


def test_price_garbage_is_null():
    got = parse_price("cheap")
    assert got.value is None
    assert got.status == REVIEW


def test_price_from_cleaned_s3_text_is_current_not_old():
    # The old quote (275.00) sits in quoted text; the current price must be picked from new text.
    cleaned = clean_email(_body("s3_offer"))
    assert "USD 310.00 per pen" in cleaned.new_text
    got = parse_price("USD 310.00 per pen")
    assert got.value == 310.0
    assert got.evidence in cleaned.new_text
    assert got.evidence not in cleaned.quoted_text
