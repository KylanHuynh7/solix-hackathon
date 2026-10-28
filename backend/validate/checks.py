"""Deterministic offer and outbound-draft checks. No model calls, no network."""

import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote_plus

from pydantic import BaseModel

from contracts.schemas import Case, Draft, Field, FieldStatus, Offer

OPENFDA_CACHE = Path(__file__).resolve().parents[2] / "data" / "seed" / "openfda_cache.json"

REGULATED = ("ndc", "lots", "expiry", "quantity", "unit_price")
UNIT_ALIASES = {"pen": "pen", "pens": "pen", "syringe": "pen", "syringes": "pen"}


class CheckResult(BaseModel):
    check: str
    ok: bool
    field: str | None = None
    reason: str


def load_openfda(path: Path = OPENFDA_CACHE) -> dict:
    return json.loads(path.read_text())


def _unit(raw: str | None) -> str | None:
    if not raw:
        return None
    word = raw.strip().lower()
    return UNIT_ALIASES.get(word, word.removesuffix("s") if word.endswith("s") else word)


def _pack(entry: dict | None) -> tuple[int, str, str] | None:
    """Parse '4 SYRINGE, PLASTIC in 1 CARTON (...)' -> (4, 'pen', 'carton')."""
    desc = (entry or {}).get("package_description") or ""
    m = re.match(r"\s*(\d+)\s+([A-Za-z]+)\b.*?\bin\s+1\s+([A-Za-z]+)", desc)
    if not m:
        return None
    return int(m.group(1)), _unit(m.group(2)), _unit(m.group(3))


def _num(value) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _money(x: Decimal) -> str:
    return f"{x:,.0f}" if x == x.to_integral_value() else f"{x:,.2f}"


def _to_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _unverified(f: Field) -> bool:
    return f.value is None or f.status == FieldStatus.needs_review


def _gate(check: str, name: str, *fields: Field) -> CheckResult | None:
    """Fail closed: a check never passes on a missing or needs_review input."""
    if any(_unverified(f) for f in fields):
        return CheckResult(check=check, ok=False, field=name,
                           reason=f"{name} not verified; needs human review")
    return None


def _ndc_known(offer: Offer, openfda: dict) -> CheckResult:
    if blocked := _gate("ndc_known", "ndc", offer.ndc):
        return blocked
    ndc = offer.ndc.value
    ok = ndc in openfda
    reason = f"NDC {ndc} found in openFDA" if ok else f"NDC {ndc} not found in openFDA"
    return CheckResult(check="ndc_known", ok=ok, field="ndc", reason=reason)


def _dosage_form(offer: Offer, case: Case, openfda: dict) -> CheckResult:
    if blocked := _gate("dosage_form", "ndc", offer.ndc):
        return blocked
    required = case.requirement.dosage_form
    entry = openfda.get(offer.ndc.value)
    if not entry:
        return CheckResult(check="dosage_form", ok=False, field="ndc",
                           reason="dosage form unknown; NDC not in openFDA")
    form = entry["dosage_form"]
    if required.lower() == "injection pen":
        ok = "INJECTION" in form.upper()
    else:
        ok = form.lower() == required.lower()
    if ok:
        reason = f"offered {form.lower()}; matches required {required}"
    else:
        reason = f"offered {form.split(',')[0].lower()}s; customer requires {required}"
    return CheckResult(check="dosage_form", ok=ok, field="ndc", reason=reason)


def _expiry_min(offer: Offer, case: Case) -> CheckResult:
    exp = offer.expiry
    d = _to_date(exp.value) if exp.value is not None else None
    if d is None or exp.status == FieldStatus.needs_review:
        return CheckResult(check="expiry_min", ok=False, field="expiry",
                           reason="expiry not verified; needs human review")
    minimum = case.requirement.min_expiry
    ok = d >= minimum
    reason = (f"expiry {d} meets minimum {minimum}" if ok
              else f"expiry {d} is before the required minimum {minimum}")
    return CheckResult(check="expiry_min", ok=ok, field="expiry", reason=reason)


def _single_lot(offer: Offer, case: Case) -> CheckResult:
    if not case.requirement.single_lot:
        return CheckResult(check="single_lot", ok=True, field="lots",
                           reason="customer does not require a single lot")
    if blocked := _gate("single_lot", "lots", *offer.lots):
        return blocked
    n = len(offer.lots)
    ok = n == 1
    reason = "single lot offered" if ok else (
        "no lot stated; customer requires a single lot" if n == 0
        else f"offered {n} lots; customer requires a single lot")
    return CheckResult(check="single_lot", ok=ok, field="lots", reason=reason)


def _quantity_unit(offer: Offer, case: Case, openfda: dict) -> CheckResult:
    q = offer.quantity
    want, case_unit = case.line_item.quantity, _unit(case.line_item.unit)

    def fail(reason: str) -> CheckResult:
        return CheckResult(check="quantity_unit", ok=False, field="quantity", reason=reason)

    if blocked := _gate("quantity_unit", "quantity", q):
        return blocked
    qty, unit = _num(q.value), _unit(q.unit)
    if qty is None or unit is None:
        return fail("quantity or unit not stated; cannot compare to request")
    if unit == case_unit:
        converted = qty
    elif blocked := _gate("quantity_unit", "ndc", offer.ndc):
        return blocked
    else:
        pack = _pack(openfda.get(offer.ndc.value))
        if not (pack and unit == pack[2] and pack[1] == case_unit):
            return fail(f"cannot convert offered {q.unit} to {case.line_item.unit}")
        converted = qty * pack[0]
    ok = converted >= want
    reason = (f"{converted:,.0f} {case.line_item.unit} offered covers the {want:,} requested" if ok
              else f"{converted:,.0f} {case.line_item.unit} offered is below the {want:,} requested")
    return CheckResult(check="quantity_unit", ok=ok, field="quantity", reason=reason)


def _price_basis(offer: Offer, case: Case, openfda: dict) -> CheckResult:
    p = offer.unit_price
    if blocked := _gate("price_basis", "unit_price", p):
        return blocked
    price = _num(p.value)

    def fail(reason: str) -> CheckResult:
        return CheckResult(check="price_basis", ok=False, field="unit_price", reason=reason)

    if price is None or not p.unit or "/" not in p.unit:
        return fail("price or price basis not stated")
    currency, basis_raw = p.unit.split("/", 1)
    basis, case_unit = _unit(basis_raw), _unit(case.line_item.unit)
    if basis == case_unit:
        return CheckResult(check="price_basis", ok=True, field="unit_price",
                           reason=f"{currency} {_money(price)}/{case.line_item.unit}")
    if blocked := _gate("price_basis", "ndc", offer.ndc):
        return blocked
    pack = _pack(openfda.get(offer.ndc.value))
    if pack and basis == pack[2] and pack[1] == case_unit:
        per = price / pack[0]
        return CheckResult(
            check="price_basis", ok=True, field="unit_price",
            reason=(f"{currency} {_money(price)}/{basis_raw} = {currency} {_money(per)}/"
                    f"{case.line_item.unit} at {pack[0]} per {basis_raw}"))
    return fail(f"cannot convert price basis '{basis_raw}' to per {case.line_item.unit}")


def _needs_review(offer: Offer) -> CheckResult:
    flagged = []
    for name in REGULATED:
        fields = getattr(offer, name)
        fields = fields if isinstance(fields, list) else [fields]
        if any(f.status == FieldStatus.needs_review for f in fields):
            flagged.append(name)
    if not flagged:
        return CheckResult(check="needs_review", ok=True, field=None,
                           reason="no regulated field needs review")
    return CheckResult(check="needs_review", ok=False, field=flagged[0],
                       reason="needs review: " + ", ".join(flagged))


def validate_offer(offer: Offer, case: Case, openfda: dict | None = None) -> list[CheckResult]:
    openfda = load_openfda() if openfda is None else openfda
    return [
        _ndc_known(offer, openfda),
        _dosage_form(offer, case, openfda),
        _expiry_min(offer, case),
        _single_lot(offer, case),
        _quantity_unit(offer, case, openfda),
        _price_basis(offer, case, openfda),
        _needs_review(offer),
    ]


def exceptions_for(results: list[CheckResult]) -> list[str]:
    return [r.reason for r in results if not r.ok]


def normalise(s: str) -> str:
    """Collapse case, spacing, punctuation, URL-encoding and unicode tricks to a-z0-9."""
    prev = None
    while s != prev:
        prev, s = s, unquote_plus(s)
    s = unicodedata.normalize("NFKC", s).casefold()
    return re.sub(r"[^a-z0-9]", "", s)


def _customer_identifiers(customer_id: str, customer: dict) -> list[tuple[str, str]]:
    ids = [("customer id", customer_id), ("organisation name", customer.get("name", ""))]
    for contact in customer.get("contacts", []):
        name, email = contact.get("name", ""), contact.get("email", "")
        ids.append(("contact name", name))
        if name.split():
            ids.append(("contact surname", name.split()[-1]))
        ids.append(("contact email", email))
        local, _, domain = email.partition("@")
        ids.append(("email local part", local))
        ids.append(("email domain", domain))
    return ids


def check_outbound(draft: Draft, case: Case, directory: dict) -> list[CheckResult]:
    """Leak check: supplier-facing drafts must not reveal the customer."""
    if draft.recipient_role != "supplier":
        return [CheckResult(check="no_customer_leak", ok=True, field=None,
                            reason="customer draft; leak check not applicable")]
    cid = case.requirement.customer_id
    customer = next((c for c in directory.get("customers", []) if c["customer_id"] == cid), {})
    haystack = normalise("\n".join([draft.subject, draft.body, *draft.to, *draft.cc]))
    matched = []
    for label, raw in dict.fromkeys(_customer_identifiers(cid, customer)):
        needle = normalise(raw)
        if len(needle) >= 4 and needle in haystack:
            matched.append(f"{label} '{raw}'")
    if matched:
        return [CheckResult(check="no_customer_leak", ok=False, field=None,
                            reason="supplier draft reveals customer details: " + ", ".join(matched))]
    return [CheckResult(check="no_customer_leak", ok=True, field=None,
                        reason="no customer details in supplier draft")]
