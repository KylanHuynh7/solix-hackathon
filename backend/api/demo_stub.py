"""STUB for N5's backend.agents.process_email: writes the expected seeded drafts and exceptions.

Same signature as the real entry point so K6 can swap the import. Offers come from the hand-checked
labels in data/seed/labels.json, not from a model. Nothing here sends anything: drafts are only
proposed, SAP documents are only proposed as intents.
"""

import json
import uuid
from typing import Any

from backend.ledger import Ledger
from backend.store import SEED_DIR, CaseStore, SapIntent
from contracts.schemas import CaseState, Draft, DraftStatus, Email, Field, FieldStatus, Offer

SOURCE = "demo_stub"
DEMO_ORDER = ("s1_offer", "s2_offer", "s3_offer", "s1_injection", "cust_yes")


def _load(name: str) -> Any:
    return json.loads((SEED_DIR / name).read_text())


def load_demo_email(key: str) -> Email:
    return Email.model_validate(_load(f"emails/{key}.json"))


def _missing(reason: str = "not stated in email") -> Field:
    return Field(status=FieldStatus.needs_review, reason=reason)


def _field(value, raw, status=FieldStatus.verified, unit=None, reason=None) -> Field:
    return Field(value=value, unit=unit, raw=raw, evidence=raw, status=status, reason=reason)


# Fields labels.json does not cover. Evidence strings are exact substrings of the seed emails.
_EXTRAS: dict[str, dict[str, Field]] = {
    "s1_offer": {},
    "s2_offer": {
        "product": _field("semaglutide tablets", "semaglutide tablets"),
        "lead_time_days": _field(
            10,
            "10 business days",
            FieldStatus.needs_review,
            unit="business_day",
            reason="stated in business days, not calendar days",
        ),
    },
    "s3_offer": {
        "lead_time_days": _field(
            7,
            "7 business days",
            FieldStatus.needs_review,
            unit="business_day",
            reason="stated in business days, not calendar days",
        ),
        "storage": _field("2-8C", "Storage maintained at 2-8C"),
    },
}


def _offer(key: str, email: Email, supplier_id: str, round_: int) -> Offer:
    label = _load("labels.json")[key]
    extras = _EXTRAS[key]
    return Offer(
        supplier_id=supplier_id,
        round=round_,
        ndc=Field(**label["ndc"]),
        product=extras.get("product", _missing()),
        quantity=Field(**label["quantity"]),
        lots=[Field(**lot) for lot in label["lots"]],
        expiry=Field(**label["expiry"]),
        unit_price=Field(**label["unit_price"]),
        lead_time_days=extras.get("lead_time_days", _missing()),
        storage=extras.get("storage", _missing()),
        source_message_id=email.message_id,
    )


def _supplier_name(directory: dict, supplier_id: str) -> str:
    return next(s["name"] for s in directory["suppliers"] if s["supplier_id"] == supplier_id)


async def process_email(
    email: Email, case_id: str, *, store: CaseStore, ledger: Ledger
) -> dict[str, Any]:
    key = next(k for k in DEMO_ORDER if load_demo_email(k).message_id == email.message_id)
    directory = _load("directory.json")
    sender_id = directory["email_to_id"].get(email.sender, "UNKNOWN")
    case = store.get_case(case_id)
    log: list[str] = []
    drafts: list[Draft] = []
    exceptions: list[str] = []

    def event(actor: str, action: str, payload: dict) -> None:
        ledger.append(case_id=case_id, actor=actor, action=action, source=SOURCE, payload=payload)
        log.append(f"{actor}: {action}")

    def set_state(new: CaseState, reason: str) -> None:
        if case.state != new:
            event(
                "orchestrator",
                "case_state_changed",
                {"from": case.state.value, "to": new.value, "reason": reason},
            )
            case.state = new

    def propose(actor: str, role: str, to: list[str], subject: str, body: str) -> None:
        draft = Draft(
            draft_id=f"DRAFT-{uuid.uuid4().hex[:8]}",
            case_id=case_id,
            recipient_role=role,
            to=to,
            cc=[],
            subject=subject,
            body=body,
            status=DraftStatus.proposed,
            created_by=actor,
        )
        store.save_draft(draft)
        drafts.append(draft)
        event(
            actor,
            "draft_proposed",
            {"draft_id": draft.draft_id, "recipient_role": role, "subject": subject},
        )

    def fail(check: str, message: str) -> None:
        exceptions.append(message)
        event("orchestrator", "check_failed", {"check": check, "message": message})

    event(
        "system",
        "email_ingested",
        {"message_id": email.message_id, "sender": email.sender, "subject": email.subject},
    )

    if key in ("s1_offer", "s2_offer", "s3_offer"):
        round_ = 1 + sum(o.supplier_id == sender_id for o in case.offers)
        offer = _offer(key, email, sender_id, round_)
        case.offers.append(offer)
        event(
            "extractor",
            "fields_extracted",
            {
                "message_id": email.message_id,
                "supplier_id": sender_id,
                "ndc": offer.ndc.value,
                "lots": [lot.value for lot in offer.lots],
                "expiry": offer.expiry.value,
                "quantity": offer.quantity.value,
                "unit_price": offer.unit_price.value,
                "unit_price_unit": offer.unit_price.unit,
            },
        )
        who = f"{_supplier_name(directory, sender_id)} ({sender_id})"
        req = case.requirement

        if key == "s1_offer":
            fail(
                "min_expiry",
                f"{who} offer: expiry {offer.expiry.value} is before the customer minimum "
                f"{req.min_expiry.isoformat()}.",
            )
            lots = ", ".join(lot.value for lot in offer.lots)
            fail(
                "single_lot",
                f"{who} offer: {len(offer.lots)} lots ({lots}) but the customer requires "
                "a single lot.",
            )
            set_state(CaseState.Exception, "supplier offer failed checks")
            propose(
                "negotiator",
                "supplier",
                [email.sender],
                email.subject,
                "Hi Alex,\n\n"
                "Thank you for the offer. Before we can proceed, two points need to change:\n\n"
                f"1. Expiry: 10/27 (2027-10-31) is earlier than the minimum we can accept, "
                f"{req.min_expiry.isoformat()}.\n"
                f"2. Lots: we need all {case.line_item.quantity:,} pens from a single lot; "
                f"the offer splits them across {len(offer.lots)} lots ({lots}).\n\n"
                f"Could you offer {case.line_item.quantity:,} pens from a single lot with expiry "
                f"on or after {req.min_expiry.isoformat()}, and confirm the price per pen and "
                "lead time?\n\n"
                "Best regards,\nJamie Park\nNeuroBiz",
            )

        elif key == "s2_offer":
            fda = _load("openfda_cache.json")[offer.ndc.value]
            fail(
                "dosage_form",
                f"{who} offer: NDC {offer.ndc.value} is {fda['brand_name']} "
                f"({fda['dosage_form'].lower()}, {fda['route'][0].lower()}) per openFDA; "
                f"the customer requires an {req.dosage_form}.",
            )
            set_state(CaseState.Exception, "supplier offer failed checks")

        else:  # s3_offer: compliant
            set_state(CaseState.Quoting, "compliant offer received")
            customer = directory["customers"][0]
            propose(
                "confirmer",
                "customer",
                [customer["contacts"][0]["email"]],
                "Confirmation needed: Semaglutide pens for clinical trial - CASE-001",
                "Hi Taylor,\n\n"
                "We have a compliant offer for your clinical trial supply:\n\n"
                f"- Supplier: {_supplier_name(directory, sender_id)}\n"
                f"- Product: {case.line_item.product} (NDC {offer.ndc.value})\n"
                f"- Quantity: {offer.quantity.value:,} pens, single lot {offer.lots[0].value}\n"
                f"- Expiry: 11/2028 ({offer.expiry.value}), meets your minimum of "
                f"{req.min_expiry.isoformat()}\n"
                "- Storage: 2-8C throughout transit\n"
                "- Lead time: 7 business days\n\n"
                "Please confirm you would like us to proceed.\n\n"
                "Best regards,\nJamie Park\nNeuroBiz",
            )

    elif key == "s1_injection":
        event(
            "orchestrator",
            "tool_denied",
            {
                "tool": "approve_purchase_order",
                "reason": "agents cannot approve; the request came from email text "
                "(untrusted data), not from a human approver",
                "message_id": email.message_id,
            },
        )
        exceptions.append(
            "Supplier One Pharma (SUP-001) email asked the system to approve the PO. "
            "Ignored: only a human can approve."
        )

    elif key == "cust_yes":
        set_state(CaseState.Confirmed, "customer confirmed Supplier Three offer")
        chosen = next(o for o in case.offers if o.supplier_id == "SUP-003")
        # NDC 0169-4524-14 is a carton of 4 pens: 1,200 pens = 300 cartons at 4 x USD 310.
        pens_per_carton = 4
        base = {
            "CaseId": case_id,
            "Material": chosen.ndc.value,
            "Quantity": chosen.quantity.value // pens_per_carton,
            "Unit": "carton",
            "Supplier": chosen.supplier_id,
            "Batch": chosen.lots[0].value,
            "ShelfLifeExpiry": chosen.expiry.value,
        }
        priced = {
            **base,
            "NetPrice": round(chosen.unit_price.value * pens_per_carton, 2),
            "Currency": "USD",
        }
        for doc_type, payload in (
            ("rfq", base),
            ("supplier_quotation", priced),
            ("purchase_order", priced),
        ):
            intent = SapIntent(
                intent_id=f"SAPI-{uuid.uuid4().hex[:8]}",
                case_id=case_id,
                doc_type=doc_type,
                payload=payload,
                status="proposed",
            )
            store.save_sap_intent(intent)
            event(
                "confirmer",
                "tool_call",
                {"tool": "propose_sap_document", "intent_id": intent.intent_id, "doc_type": doc_type},
            )

    case.exceptions.extend(exceptions)
    store.save_case(case)
    return {
        "drafts": [d.model_dump(mode="json") for d in drafts],
        "log": log,
        "exceptions": exceptions,
    }
