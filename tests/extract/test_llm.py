import json
from pathlib import Path
from types import SimpleNamespace as NS

from contracts.schemas import Case, Email

from backend.extract import pipeline
from backend.extract.llm import NO_TOOL_ERROR, RETRY_NUDGE, AnthropicSpanLLM

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"
CASE = Case.model_validate_json((SEED / "case.json").read_text())
EMAIL = Email.model_validate_json((SEED / "emails" / "s1_offer.json").read_text())


def text(t):
    return NS(type="text", text=t)


def tool(inp):
    return NS(type="tool_use", name="report_spans", input=inp)


class FakeClient:
    def __init__(self, *responses):
        self.calls = []
        self._responses = list(responses)
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return NS(content=self._responses[len(self.calls) - 1])


GOOD = {
    "is_offer": True, "ndc_raw": "NDC 0169-4524-14", "product_raw": None,
    "quantity_raw": "1,200 pens", "lots": ["Lot A1001: 500 pens"], "expiry_raw": "10/27",
    "unit_price_raw": "USD 285.00 per pen", "lead_time_raw": None, "storage_raw": None,
}


def test_no_tool_use_twice_is_failsafe_and_nothing_verified():
    client = FakeClient([text("Sure! The NDC is 0169-4524-14.")], [text("still prose")])
    llm = AnthropicSpanLLM(client=client)
    offer = pipeline.extract_offer(EMAIL, CASE, llm=llm)
    assert len(client.calls) == 2
    assert client.calls[0]["tool_choice"] == {"type": "auto"}
    assert client.calls[1]["messages"][-1] == {"role": "user", "content": RETRY_NUDGE}
    assert pipeline.last_run_meta["error"] == NO_TOOL_ERROR
    fields = [offer.ndc, offer.product, offer.quantity, offer.expiry, offer.unit_price,
              offer.lead_time_days, offer.storage]
    assert all(f.status == "needs_review" and f.value is None for f in fields)
    assert offer.lots == []


def test_tool_use_on_retry_is_used():
    client = FakeClient([text("thinking")], [tool(GOOD)])
    llm = AnthropicSpanLLM(client=client)
    offer = pipeline.extract_offer(EMAIL, CASE, llm=llm)
    assert len(client.calls) == 2
    assert offer.ndc.value == "0169-4524-14"
    assert offer.quantity.value == 1200
    assert "error" not in pipeline.last_run_meta


def test_first_call_tool_use_does_not_retry():
    client = FakeClient([tool(GOOD)])
    AnthropicSpanLLM(client=client).find_spans("x", CASE)
    assert len(client.calls) == 1


def test_malformed_types_are_sanitised():
    bad = {**GOOD, "ndc_raw": 12345, "expiry_raw": ["10/27"], "quantity_raw": {"a": 1},
           "lots": ["Lot A1001: 500 pens", 7, None], "is_offer": "yes"}
    spans = AnthropicSpanLLM(client=FakeClient([tool(bad)])).find_spans("x", CASE)
    assert spans["ndc_raw"] is None and spans["expiry_raw"] is None and spans["quantity_raw"] is None
    assert spans["lots"] == ["Lot A1001: 500 pens"]
    assert spans["is_offer"] is False
    assert AnthropicSpanLLM(client=FakeClient([tool({**GOOD, "lots": "Lot A1"})])).find_spans("x", CASE)["lots"] == []
