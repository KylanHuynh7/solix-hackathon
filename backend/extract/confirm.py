"""Customer confirmation parser: deterministic, reads only the new (unquoted) text."""

import json
import re
from pathlib import Path

from contracts.schemas import Case, Email, FieldStatus, Offer

from backend.extract.parsers import clean_email

_SEED = Path(__file__).resolve().parents[2] / "data" / "seed"

_ACCEPT = re.compile(
    r"\b(?:confirm(?:ed)?\s+acceptance|we\s+accept|please\s+proceed|approved\s+to\s+proceed)\b",
    re.IGNORECASE,
)
_CONDITION = re.compile(
    r"\b(?:if|provided\s+that|subject\s+to|as\s+long\s+as|only\s+if)\b", re.IGNORECASE
)
_DECLINE = re.compile(
    r"\b(?:declin(?:e|es|ed)|not\s+proceed|reject(?:s|ed)?|no\s+longer\s+need)\b", re.IGNORECASE
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def _sentences(text: str) -> list[str]:
    return [m.group().strip() for m in _SENTENCE.finditer(text) if m.group().strip()]


def _word_re(term: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def _name_variants(name: str) -> list[str]:
    """Full name, then shorter prefixes of two or more words ("Supplier Three")."""
    words = name.split()
    return [" ".join(words[:n]) for n in range(len(words), 1, -1)]


def _supplier_names() -> dict[str, str]:
    directory = json.loads((_SEED / "directory.json").read_text())
    return {s["supplier_id"]: s["name"] for s in directory["suppliers"]}


def _identify(text: str, offers: list[Offer]) -> tuple[Offer | None, str | None, str | None]:
    """Return (offer, lot, problem). Lot id first, then supplier name."""
    by_lot: dict[int, tuple[Offer, str]] = {}
    for i, offer in enumerate(offers):
        for lot in offer.lots:
            if lot.value and _word_re(str(lot.value)).search(text):
                by_lot[i] = (offer, str(lot.value))
    if len(by_lot) == 1:
        offer, lot = next(iter(by_lot.values()))
        return offer, lot, None
    if len(by_lot) > 1:
        return None, None, "lot id matches more than one offer"

    names = _supplier_names()
    by_name = [
        o
        for o in offers
        if o.supplier_id in names
        and any(_word_re(v).search(text) for v in _name_variants(names[o.supplier_id]))
    ]
    if len(by_name) == 1:
        return by_name[0], None, None
    if len(by_name) > 1:
        return None, None, "supplier name matches more than one offer"
    return None, None, "no lot id or supplier name matches an offer"


def parse_confirmation(email: Email, case: Case) -> dict:
    text = clean_email(email.body).new_text
    sentences = _sentences(text)

    accept = next((s for s in sentences if _ACCEPT.search(s)), None)
    decline = next((s for s in sentences if _DECLINE.search(s)), None)
    condition = _CONDITION.search(text)

    if decline and not accept:
        decision, evidence = "declined", decline
    elif accept and not decline:
        decision, evidence = ("conditional", accept) if condition else ("confirmed", accept)
    else:
        decision, evidence = "unclear", accept or decline

    offer, lot, problem = _identify(text, case.offers)

    result = {
        "decision": decision,
        "supplier_id": offer.supplier_id if offer else None,
        "lot": lot,
        "evidence": evidence,
        "status": "needs_review",
        "reason": "",
    }

    if decision == "conditional":
        cond_sentence = next((s for s in sentences if _CONDITION.search(s)), condition.group())
        result["reason"] = f"acceptance is conditional: {cond_sentence!r}"
    elif decision == "declined":
        result["reason"] = "customer declined"
    elif decision == "unclear":
        result["reason"] = (
            "acceptance and decline both present" if accept and decline else "no explicit acceptance or decline"
        )
    elif offer is None:
        result["reason"] = problem or "offer not identified"
    else:
        regulated = [offer.ndc, offer.quantity, offer.expiry, *offer.lots]
        bad = [f for f in regulated if f.status != FieldStatus.verified]
        if bad or not offer.lots:
            result["reason"] = "identified offer has regulated fields that are not verified"
        else:
            result["status"] = "verified"
            result["reason"] = "explicit unconditional acceptance of one verified offer"
    return result
