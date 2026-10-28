import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from contracts.schemas import Case, Email, Field

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"
EMAIL_FILES = sorted((SEED / "emails").glob("*.json"))


def load(path: Path):
    return json.loads(path.read_text())


def test_case_loads():
    Case.model_validate(load(SEED / "case.json"))


def test_seed_has_expected_emails():
    names = {p.stem for p in EMAIL_FILES}
    assert {"s1_offer", "s2_offer", "s3_offer", "cust_yes", "s1_injection"} <= names


@pytest.mark.parametrize("path", EMAIL_FILES, ids=lambda p: p.stem)
def test_email_loads(path):
    Email.model_validate(load(path))


def test_directory_maps_every_contact():
    directory = load(SEED / "directory.json")
    assert len(directory["suppliers"]) == 3
    assert len(directory["customers"]) == 1
    mapping = directory["email_to_id"]
    for supplier in directory["suppliers"]:
        for contact in supplier["contacts"]:
            assert mapping[contact["email"]] == supplier["supplier_id"]
    for customer in directory["customers"]:
        for contact in customer["contacts"]:
            assert mapping[contact["email"]] == customer["customer_id"]
        assert customer["account_manager"]["email"] in mapping


def test_labels_load_as_fields():
    labels = load(SEED / "labels.json")
    emails = {p.stem: Email.model_validate(load(p)) for p in EMAIL_FILES}
    assert set(labels) == set(emails)
    for stem, label in labels.items():
        assert label["message_id"] == emails[stem].message_id
        for name in ("ndc", "expiry", "quantity"):
            Field.model_validate(label[name])
        for lot in label["lots"]:
            Field.model_validate(lot)


def new_text(body: str) -> str:
    """The reply above any quoted history ("On ... wrote:" followed by "> " lines)."""
    return re.split(r"\n\s*On .+wrote:\s*\n", body, maxsplit=1)[0]


def test_label_ndcs_exist_in_openfda_cache():
    cache = load(SEED / "openfda_cache.json")
    labels = load(SEED / "labels.json")
    ndcs = {label["ndc"]["value"] for label in labels.values()} - {None}
    assert ndcs
    assert ndcs <= set(cache)
    assert load(SEED / "case.json")["line_item"]["requested_ndc"] in cache


def test_unit_price_evidence_is_from_new_text():
    labels = load(SEED / "labels.json")
    for stem, label in labels.items():
        if "unit_price" not in label:
            continue
        Field.model_validate(label["unit_price"])
        body = load(SEED / "emails" / f"{stem}.json")["body"]
        assert label["unit_price"]["evidence"] in new_text(body)


@pytest.mark.live
def test_openfda_dosage_forms_still_match():
    cache = load(SEED / "openfda_cache.json")
    for package_ndc, entry in cache.items():
        query = urllib.parse.urlencode(
            {"search": f'packaging.package_ndc:"{package_ndc}"', "limit": 1}
        )
        with urllib.request.urlopen(f"https://api.fda.gov/drug/ndc.json?{query}", timeout=30) as resp:
            result = json.load(resp)["results"][0]
        assert result["dosage_form"] == entry["dosage_form"]


def test_price_and_quantity_labels_keep_unit():
    labels = load(SEED / "labels.json")
    checked = 0
    for label in labels.values():
        for name in ("unit_price", "quantity"):
            raw = label.get(name)
            if raw is None or raw.get("unit") is None:
                continue
            assert Field.model_validate(raw).unit == raw["unit"]
            checked += 1
    assert checked == 6  # unit_price and quantity for s1, s2, s3


def test_price_units_are_currency_per_basis():
    labels = load(SEED / "labels.json")
    prices = [label["unit_price"] for label in labels.values() if "unit_price" in label]
    assert prices
    for price in prices:
        assert re.fullmatch(r"[A-Z]{3}/[a-z]+", price["unit"]), price["unit"]
