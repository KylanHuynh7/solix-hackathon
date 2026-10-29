"""Offer extraction: the model finds quotes, code verifies them and decides the values."""

import json
import re
from pathlib import Path

from contracts.schemas import Case, Email, Field, FieldStatus, Offer

from backend.extract import llm as llm_module
from backend.extract.llm import SpanLLM
from backend.extract.parsers import (
    clean_email,
    parse_expiry,
    parse_ndc,
    parse_price,
    parse_quantity,
)
from backend.replay.extract import ReplaySpanLLM

_SEED = Path(__file__).resolve().parents[2] / "data" / "seed"

last_run_meta: dict = {"model": None, "prompt_version": llm_module.PROMPT_VERSION}

_V = FieldStatus.verified
_R = FieldStatus.needs_review

_LOT_ID = re.compile(r"^\W*Lot\s*(?:#|no\.?|number)?\s*:?\s*([A-Za-z0-9][A-Za-z0-9-]*)", re.IGNORECASE)
_LEAD = re.compile(r"(\d+)\s*(business|working|calendar)?\s*days?\b", re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _unquote(text: str) -> str:
    return re.sub(r"(?m)^\s*>+ ?", "", text)


def _none(raw: str | None, reason: str) -> Field:
    return Field(value=None, raw=raw, evidence=None, status=_R, reason=reason)


def _ground(span, new_text: str, quoted_text: str) -> tuple[str | None, str | None]:
    """Return (usable span, failure reason). Exactly one is None."""
    if not isinstance(span, str) or not span.strip():
        return None, "not stated in email"
    needle = _norm(span)
    if needle in _norm(new_text):
        return span.strip(), None
    if needle in _norm(_unquote(quoted_text)):
        return None, "found only in quoted history, not the new message"
    return None, "quote not found in email (possible hallucination)"


def _lead_time(span: str) -> Field:
    m = _LEAD.search(span)
    if not m:
        return Field(value=None, raw=span, evidence=span, status=_R, reason="no number of days found in quote")
    days, kind = int(m.group(1)), m.group(2)
    if kind and kind.lower() in ("business", "working"):
        return Field(value=days, unit="days", raw=span, evidence=span, status=_V, reason="business days as stated")
    if kind:
        return Field(value=days, unit="days", raw=span, evidence=span, status=_V, reason="calendar days as stated")
    return Field(value=days, unit="days", raw=span, evidence=span, status=_R, reason="business vs calendar days not stated")


def _lot(span: str) -> Field:
    m = _LOT_ID.match(span)
    if not m:
        return _none(span, "could not find a lot ID in the quote").model_copy(update={"evidence": span})
    return Field(value=m.group(1), raw=span, evidence=span, status=_V, reason="lot explicitly stated in the offer")


def _text(span: str) -> Field:
    return Field(value=span, raw=span, evidence=span, status=_V, reason="text as stated")


def _supplier_id(sender: str) -> str:
    directory = json.loads((_SEED / "directory.json").read_text())
    return directory["email_to_id"].get(sender.strip().lower(), "UNKNOWN")


def _known_ndcs() -> set[str]:
    return set(json.loads((_SEED / "openfda_cache.json").read_text()))


def extract_offer(email: Email, case: Case, *, llm: SpanLLM | None = None) -> Offer:
    if llm is None:
        llm = ReplaySpanLLM()
    cleaned = clean_email(email.body)
    spans = llm.find_spans(cleaned.new_text, case)
    last_run_meta.update(
        model=getattr(llm, "model", type(llm).__name__), prompt_version=llm_module.PROMPT_VERSION
    )
    last_run_meta.pop("error", None)
    if getattr(llm, "error", None):
        last_run_meta["error"] = llm.error

    supplier_id = _supplier_id(email.sender)
    round_ = 1 + sum(1 for o in case.offers if o.supplier_id == supplier_id)

    def field(key: str, parse) -> Field:
        span, why = _ground(spans.get(key), cleaned.new_text, cleaned.quoted_text)
        if span is None:
            return _none(None, why)
        return parse(span)

    if spans.get("is_offer") is not True:
        empty = _none(None, "no offer in this email")
        return Offer(
            supplier_id=supplier_id, round=round_, ndc=empty, product=empty, quantity=empty,
            lots=[], expiry=empty, unit_price=empty, lead_time_days=empty, storage=empty,
            source_message_id=email.message_id,
        )

    known = _known_ndcs()
    lots: list[Field] = []
    for lot_span in spans.get("lots") or []:
        span, why = _ground(lot_span, cleaned.new_text, cleaned.quoted_text)
        lots.append(_none(None, why) if span is None else _lot(span))

    offer = Offer(
        supplier_id=supplier_id,
        round=round_,
        ndc=field("ndc_raw", lambda s: parse_ndc(s, known)),
        product=field("product_raw", _text),
        quantity=field("quantity_raw", parse_quantity),
        lots=lots,
        expiry=field("expiry_raw", parse_expiry),
        unit_price=field("unit_price_raw", parse_price),
        lead_time_days=field("lead_time_raw", _lead_time),
        storage=field("storage_raw", _text),
        source_message_id=email.message_id,
    )

    if supplier_id == "UNKNOWN":
        reason = "sender is not in the supplier directory"
        names = ("ndc", "product", "quantity", "expiry", "unit_price", "lead_time_days", "storage")
        for name in names:
            f = getattr(offer, name)
            setattr(offer, name, f.model_copy(update={"status": _R, "reason": _join(reason, f.reason)}))
        offer.lots = [f.model_copy(update={"status": _R, "reason": _join(reason, f.reason)}) for f in offer.lots]
    return offer


def _join(prefix: str, reason: str | None) -> str:
    return prefix if not reason else f"{prefix}; {reason}"
