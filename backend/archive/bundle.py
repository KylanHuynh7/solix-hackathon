"""Read-only Solix archive export: one JSON bundle per case.

build_bundle only reads from the store and ledger. It writes no ledger event, no DB row and no
file. The bundle's own sha256 covers everything except the "integrity" key.
"""

import hashlib
from datetime import datetime, timezone
from typing import Any

from backend.ledger import canonical_json
from contracts.schemas import Field

REGULATED_FIELDS = ("ndc", "lots", "expiry", "quantity", "unit_price")


def _field(field: Field) -> dict[str, Any]:
    data = field.model_dump(mode="json")
    return {
        "value": data["value"],
        "unit": data["unit"],
        "status": data["status"],
        "evidence": data["evidence"],
        "reason": data["reason"],
    }


def _offer(offer) -> dict[str, Any]:
    out: dict[str, Any] = {
        "supplier_id": offer.supplier_id,
        "source_message_id": offer.source_message_id,
    }
    for name in REGULATED_FIELDS:
        value = getattr(offer, name)
        out[name] = [_field(f) for f in value] if isinstance(value, list) else _field(value)
    return out


def _unique(values) -> list[str]:
    return sorted({str(v) for v in values if v is not None and str(v).strip()})


def _approval(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "draft_id": draft["draft_id"],
        "status": draft["status"],
        "approver": draft["approver"],
        "created_by": draft["created_by"],
        "recipient_role": draft["recipient_role"],
        "subject": draft["subject"],
    }


def bundle_sha256(bundle: dict[str, Any]) -> str:
    body = {k: v for k, v in bundle.items() if k != "integrity"}
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


def build_bundle(case_id: str, store, ledger) -> dict[str, Any]:
    """Raises KeyError for an unknown case."""
    case = store.get_case(case_id)

    approvals = [_approval(d.model_dump(mode="json")) for d in store.list_drafts(case_id)]
    approvals += [
        {**_approval(r.draft.model_dump(mode="json")), "status": "rejected",
         "approver": r.rejected_by, "reason": r.reason}
        for r in store.list_rejections(case_id)
    ]

    events = [e.model_dump(mode="json") for e in ledger.list(case_id)]

    bundle: dict[str, Any] = {
        "bundle_version": "1",
        "source_system": "TransPharmic",
        "target": "SOLIXCloud Enterprise / Email Archiving - export format (mock; no live Solix API)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case": case.model_dump(mode="json"),
        "offers_with_evidence": [_offer(o) for o in case.offers],
        "approvals": approvals,
        "outbox": [
            e.model_dump(mode="json") for e in store.list_outbox() if e.case_id == case_id
        ],
        "sap_documents": [
            {
                "intent_id": i.intent_id,
                "doc_type": i.doc_type,
                "document_number": i.document_number,
                "approver": i.approver,
            }
            for i in store.list_sap_intents(case_id, "executed")
        ],
        "ledger": {
            "events": events,
            "verify": ledger.verify(),
            "head_hash": events[-1]["hash"] if events else None,
        },
        "retention": {
            "record_class": "pharma-procurement",
            "legal_hold": False,
            "hold_keys": {
                "lots": _unique(lot.value for o in case.offers for lot in o.lots),
                "ndcs": _unique(
                    [case.line_item.requested_ndc] + [o.ndc.value for o in case.offers]
                ),
                "suppliers": _unique(o.supplier_id for o in case.offers),
            },
            "basis": "built to 21 CFR 11.10(e) audit-trail properties; not validated",
        },
    }
    bundle["integrity"] = {"bundle_sha256": bundle_sha256(bundle)}
    return bundle
