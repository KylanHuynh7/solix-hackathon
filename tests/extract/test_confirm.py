from datetime import datetime
from pathlib import Path

from backend.extract.confirm import parse_confirmation
from contracts.schemas import Case, Email, Field, FieldStatus, Offer

SEED = Path(__file__).resolve().parents[2] / "data" / "seed"
BASE = Case.model_validate_json((SEED / "case.json").read_text())
V = FieldStatus.verified
R = FieldStatus.needs_review


def _f(value, status=V):
    return Field(value=value, status=status)


def _offer(sid: str, lot: str, status=V) -> Offer:
    return Offer(
        supplier_id=sid, round=1, ndc=_f("0000-0000-00", status), product=_f("Semaglutide"),
        quantity=_f(100), lots=[_f(lot, status)], expiry=_f("2028-11-30"), unit_price=_f(1.0),
        lead_time_days=_f(5), storage=_f("2-8C"), source_message_id=f"<{sid}>",
    )


def _case(offers=None) -> Case:
    offers = offers or [_offer("SUP-001", "A1100"), _offer("SUP-002", "B2200"), _offer("SUP-003", "C3300")]
    return BASE.model_copy(update={"offers": offers})


def _email(body: str) -> Email:
    return Email(
        message_id="<c1>", thread_id="T", sender="taylor.brooks@customer1.example.com",
        to=["jamie.park@neurobiz.example.com"], cc=[], subject="Re: x",
        date=datetime(2026, 10, 8), body=body,
    )


def test_cust_yes_fixture():
    email = Email.model_validate_json((SEED / "emails" / "cust_yes.json").read_text())
    r = parse_confirmation(email, _case())
    assert (r["decision"], r["supplier_id"], r["lot"], r["status"]) == (
        "confirmed", "SUP-003", "C3300", "verified")
    assert r["evidence"].startswith("We confirm acceptance of Supplier Three's offer")


def test_conditional():
    r = parse_confirmation(_email("We accept Lot C3300 if single lot."), _case())
    assert r["decision"] == "conditional" and r["status"] == "needs_review"
    assert "if single lot" in r["reason"]


def test_declined():
    r = parse_confirmation(_email("We decline Lot C3300, we no longer need it."), _case())
    assert r["decision"] == "declined" and r["status"] == "needs_review"


def test_no_lot_or_supplier():
    r = parse_confirmation(_email("We accept. Please proceed."), _case())
    assert r["decision"] == "confirmed" and r["supplier_id"] is None
    assert r["status"] == "needs_review"


def test_quoted_acceptance_ignored():
    r = parse_confirmation(_email("Thanks.\n\n> We accept Lot C3300. Please proceed."), _case())
    assert r["decision"] == "unclear" and r["status"] == "needs_review"


def test_supplier_name_fallback():
    r = parse_confirmation(_email("Please proceed with Supplier Two."), _case())
    assert r["supplier_id"] == "SUP-002" and r["lot"] is None and r["status"] == "verified"


def test_unverified_offer_not_verified():
    case = _case([_offer("SUP-003", "C3300", R)])
    r = parse_confirmation(_email("We accept Lot C3300."), case)
    assert r["decision"] == "confirmed" and r["status"] == "needs_review"


def test_ambiguous_lot():
    case = _case([_offer("SUP-001", "X1"), _offer("SUP-002", "X1")])
    r = parse_confirmation(_email("We accept Lot X1."), case)
    assert r["supplier_id"] is None and r["status"] == "needs_review"
