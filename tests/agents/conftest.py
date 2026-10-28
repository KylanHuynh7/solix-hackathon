"""Shared fixtures for the N5 orchestrator tests. Everything here is offline.

Extraction is faked by delegating to the real pipeline with canned spans built from
data/seed/labels.json. The drafting agent is faked by a runner that calls the real Toolbox.
"""

import json
import sys
import types
from pathlib import Path

import pytest

from backend.extract.pipeline import extract_offer as real_extract_offer
from backend.ledger import InMemoryLedger
from backend.store import InMemoryCaseStore
from contracts.schemas import Case, Email

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"
CASE_ID = "CASE-001"

LABELS = json.loads((SEED / "labels.json").read_text())
DIRECTORY = json.loads((SEED / "directory.json").read_text())
CASE = Case.model_validate_json((SEED / "case.json").read_text())

# Fields labels.json does not cover; each raw string is an exact substring of the seed email.
EXTRA_SPANS = {
    "s2_offer": {"product_raw": "semaglutide tablets", "lead_time_raw": "10 business days"},
    "s3_offer": {"lead_time_raw": "7 business days", "storage_raw": "Storage maintained at 2-8C"},
}

NEGOTIATOR_BODY = (
    "Hi Alex,\n\n"
    "Thank you for the offer. Two points need to change:\n\n"
    "1. Expiry 2027-10-31 is earlier than the minimum we can accept, 2028-06-30.\n"
    "2. We need all pens from a single lot.\n\n"
    "Could you confirm the price per pen and lead time? Our target is USD 290 per pen.\n\n"
    "Best regards,\nJamie Park\nNeuroBiz"
)
CONFIRMER_BODY = (
    "Hi Taylor,\n\n"
    "We have a compliant offer: Supplier Three Distribution, NDC 0169-4524-14, 1,200 pens, "
    "single lot C3300, expiry 2028-11-30, storage 2-8C, lead time 7 business days.\n\n"
    "Please confirm you would like us to proceed.\n\n"
    "Best regards,\nJamie Park\nNeuroBiz"
)


class FakeSpanLLM:
    model = "fake"

    def __init__(self, spans: dict):
        self.spans = spans

    def find_spans(self, new_text, case) -> dict:
        return dict(self.spans)


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


def load_email(key: str) -> Email:
    return Email.model_validate_json((SEED / "emails" / f"{key}.json").read_text())


class FakeRunner:
    """Stands in for the Claude Agent SDK: records each run and proposes a canned clean draft."""

    def __init__(self) -> None:
        self.runs = []
        self.results = []

    @property
    def agents(self) -> list[str]:
        return [r.agent for r in self.runs]

    async def __call__(self, run) -> None:
        self.runs.append(run)
        await run.toolbox.call("get_case_summary", {})
        body = NEGOTIATOR_BODY if run.agent == "negotiator" else CONFIRMER_BODY
        result = await run.toolbox.call(
            "propose_draft",
            {
                "recipient_role": run.recipient_role,
                "subject": f"Re: RFQ - {CASE_ID}",
                "body": body,
            },
        )
        self.results.append(result)


@pytest.fixture
def store():
    return InMemoryCaseStore()


@pytest.fixture
def ledger():
    return InMemoryLedger()


@pytest.fixture
def directory() -> dict:
    return json.loads(json.dumps(DIRECTORY))


@pytest.fixture
def case() -> Case:
    return CASE.model_copy(deep=True)


@pytest.fixture
def email():
    return load_email


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def make_offer():
    """Build the Offer for a seed email via the real pipeline with canned spans."""

    def build(key: str):
        return real_extract_offer(load_email(key), CASE.model_copy(deep=True), llm=FakeSpanLLM(spans_for(key)))

    return build


@pytest.fixture
def extract_calls(monkeypatch) -> list[str]:
    """Replace the orchestrator's extract_offer; returns the list of keys it was called with."""
    by_id = {lab["message_id"]: key for key, lab in LABELS.items()}
    calls: list[str] = []

    def fake_extract(email, case):
        key = by_id[email.message_id]
        calls.append(key)
        return real_extract_offer(email, case, llm=FakeSpanLLM(spans_for(key)))

    monkeypatch.setattr("backend.agents.orchestrator.extract_offer", fake_extract)
    return calls


@pytest.fixture
def fake_confirm(monkeypatch):
    """Provide a parse_confirmation that says the customer confirmed Supplier Three."""
    module = types.SimpleNamespace(
        parse_confirmation=lambda email, case: {"decision": "confirmed", "supplier_id": "SUP-003"}
    )
    monkeypatch.setitem(sys.modules, "backend.extract.confirm", module)


@pytest.fixture
def no_confirm(monkeypatch):
    """Force `from backend.extract.confirm import ...` to raise ImportError."""
    monkeypatch.setitem(sys.modules, "backend.extract.confirm", None)


@pytest.fixture
def send(store, ledger, runner):
    """send(key, runner=None) runs one seed email through process_email on the shared store."""
    from backend.agents import process_email

    async def _send(key: str, runner_override=None):
        return await process_email(
            load_email(key), CASE_ID, store=store, ledger=ledger,
            runner=runner_override or runner,
        )

    return _send
