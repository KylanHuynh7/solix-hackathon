"""Shared helpers for the N7 replay tests, imported by conftest.py and test_replay.py."""

import json
from pathlib import Path

from backend.ledger import InMemoryLedger
from backend.store import InMemoryCaseStore
from contracts.schemas import Email

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"
CASE_ID = "CASE-001"
LABELS = json.loads((SEED / "labels.json").read_text())
EXTRA_SPANS = {
    "s2_offer": {"product_raw": "semaglutide tablets", "lead_time_raw": "10 business days"},
    "s3_offer": {"lead_time_raw": "7 business days", "storage_raw": "Storage maintained at 2-8C"},
}
NEGOTIATOR_BODY = (
    "Hi Alex,\n\nThank you for the offer. Two points need to change:\n\n"
    "1. Expiry 2027-10-31 is earlier than the minimum we can accept, 2028-06-30.\n"
    "2. We need all pens from a single lot.\n\n"
    "Could you confirm the price per pen and lead time? Our target is USD 290 per pen.\n\n"
    "Best regards,\nJamie Park\nNeuroBiz"
)
CONFIRMER_BODY = (
    "Hi Taylor,\n\nWe have a compliant offer: Supplier Three Distribution, NDC 0169-4524-14, "
    "1,200 pens, single lot C3300, expiry 2028-11-30, storage 2-8C, lead time 7 business days.\n\n"
    "Please confirm you would like us to proceed.\n\nBest regards,\nJamie Park\nNeuroBiz"
)


def load_email(key: str) -> Email:
    return Email.model_validate_json((SEED / "emails" / f"{key}.json").read_text())


def spans_for(key: str) -> dict:
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
    spans.update(EXTRA_SPANS.get(key, {}))
    return spans


async def run_demo(keys) -> tuple[InMemoryCaseStore, InMemoryLedger, list[dict]]:
    """Run seed emails through the real process_email with the default (replay-wrapped) runner."""
    from backend.agents import process_email

    store, ledger = InMemoryCaseStore(), InMemoryLedger()
    drafts: list[dict] = []
    for key in keys:
        result = await process_email(load_email(key), CASE_ID, store=store, ledger=ledger)
        drafts += result["drafts"]
    return store, ledger, drafts
