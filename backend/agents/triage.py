"""Deterministic triage of an inbound email. No model calls, no network."""

import re
import unicodedata

from backend.extract.parsers import clean_email
from contracts.schemas import Email

SUPPLIER_OFFER = "supplier_offer"
CUSTOMER_REPLY = "customer_reply"
SUSPICIOUS = "suspicious"
UNKNOWN = "unknown"

INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all|prior|previous)\s+instructions\b", re.IGNORECASE),
    re.compile(r"\bapprove\s+the\s+(?:po|order)\b", re.IGNORECASE),
    re.compile(r"\bdisregard\b", re.IGNORECASE),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
)


def _flatten(text: str) -> str:
    # NFKC folds full-width and other look-alike characters; whitespace runs become one space.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text))


def find_injection(text: str) -> str | None:
    """First injection-looking phrase in the text, as written, or None."""
    flat = _flatten(text)
    for pattern in INJECTION_PATTERNS:
        if m := pattern.search(flat):
            return m.group(0)
    return None


def sender_id(email: Email, directory: dict) -> str:
    return directory["email_to_id"].get(email.sender.strip().lower(), "UNKNOWN")


def classify(email: Email, directory: dict) -> str:
    if find_injection(clean_email(email.body).new_text) or find_injection(email.subject):
        return SUSPICIOUS
    who = sender_id(email, directory)
    if who.startswith("SUP-"):
        return SUPPLIER_OFFER
    if who.startswith("CUST-"):
        return CUSTOMER_REPLY
    return UNKNOWN
