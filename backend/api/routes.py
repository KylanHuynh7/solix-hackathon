"""Read API plus the human approval gate for drafts and SAP intents.

Invariants: no endpoint lets an agent send; every approve/reject needs a non-empty human name;
a draft or intent can only be approved once; every state change writes a ledger event.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.outbound import LEAK_CHECK_IS_STUB, check_outbound
from backend.api.state import AppState, get_state
from backend.sap_mock import MissingKeysError
from backend.store import OutboxEmail
from contracts.schemas import Case, CaseState, Draft, DraftStatus

router = APIRouter()

SOURCE = "api"


class ApproveDraftBody(BaseModel):
    approver: str
    edited_body: str | None = None


class RejectDraftBody(BaseModel):
    approver: str
    reason: str


class ApproveIntentBody(BaseModel):
    approver: str


def _require(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise HTTPException(status_code=422, detail=f"{name} must not be empty")
    return value


def set_case_state(state: AppState, case: Case, new: CaseState, actor: str, reason: str) -> Case:
    if case.state == new:
        return case
    old = case.state
    case.state = new
    state.store.save_case(case)
    state.ledger.append(
        case_id=case.case_id,
        actor=actor,
        action="case_state_changed",
        source=SOURCE,
        payload={"from": old.value, "to": new.value, "reason": reason},
    )
    return case


# --- cases ---------------------------------------------------------------------------------


@router.get("/cases")
def list_cases(state: AppState = Depends(get_state)) -> list[Case]:
    return state.store.list_cases()


@router.get("/cases/{case_id}")
def get_case(case_id: str, state: AppState = Depends(get_state)) -> Case:
    try:
        return state.store.get_case(case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="case not found") from None


# --- drafts --------------------------------------------------------------------------------


@router.get("/drafts")
def list_drafts(
    case_id: str | None = None,
    status: Literal["proposed", "approved", "sent", "rejected"] | None = None,
    state: AppState = Depends(get_state),
) -> list[dict[str, Any]]:
    """Drafts as contract JSON. Rejected drafts carry status "rejected", rejected_by and reason."""
    if status == "rejected":
        return [
            {
                **r.draft.model_dump(mode="json"),
                "status": "rejected",
                "rejected_by": r.rejected_by,
                "reason": r.reason,
            }
            for r in state.store.list_rejections(case_id)
        ]
    draft_status = DraftStatus(status) if status else None
    return [d.model_dump(mode="json") for d in state.store.list_drafts(case_id, draft_status)]


def _get_draft(state: AppState, draft_id: str) -> Draft:
    try:
        return state.store.get_draft(draft_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="draft not found") from None


@router.post("/drafts/{draft_id}/approve")
def approve_draft(
    draft_id: str, body: ApproveDraftBody, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    approver = _require(body.approver, "approver")
    actor = f"human:{approver}"
    with state.lock:
        draft = _get_draft(state, draft_id)
        if draft.status != DraftStatus.proposed:
            raise HTTPException(status_code=409, detail=f"draft is already {draft.status.value}")

        edited = body.edited_body is not None and body.edited_body != draft.body
        if edited:
            draft.body = body.edited_body

        case = state.store.get_case(draft.case_id)
        problems = check_outbound(draft, case)
        if problems:
            state.ledger.append(
                case_id=draft.case_id,
                actor="system",
                action="check_failed",
                source=SOURCE,
                payload={"draft_id": draft_id, "check": "outbound", "problems": problems},
            )
            raise HTTPException(status_code=422, detail={"problems": problems})

        draft.status = DraftStatus.approved
        draft.approver = approver
        state.store.save_draft(draft)
        state.ledger.append(
            case_id=draft.case_id,
            actor=actor,
            action="draft_approved",
            source=SOURCE,
            payload={
                "draft_id": draft_id,
                "recipient_role": draft.recipient_role,
                "edited": edited,
                "leak_check": "stub" if LEAK_CHECK_IS_STUB else "backend.validate",
            },
        )

        try:
            sent = state.store.record_outbox(
                OutboxEmail(
                    draft_id=draft_id,
                    case_id=draft.case_id,
                    to=draft.to,
                    cc=draft.cc,
                    subject=draft.subject,
                    body=draft.body,
                    approver=approver,
                    sent_at=datetime.now(timezone.utc),
                )
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="draft was already sent") from None
        draft.status = DraftStatus.sent
        state.store.save_draft(draft)
        state.ledger.append(
            case_id=draft.case_id,
            actor=actor,
            action="email_sent",
            source=SOURCE,
            payload={
                "draft_id": draft_id,
                "outbox_id": sent.outbox_id,
                "to": draft.to,
                "cc": draft.cc,
                "subject": draft.subject,
                "via": "simulator",
            },
        )

        if draft.recipient_role == "customer" and case.state in (
            CaseState.Quoting,
            CaseState.Exception,
        ):
            set_case_state(state, case, CaseState.AwaitingCustomer, actor, "customer email sent")

        return {"draft": draft.model_dump(mode="json"), "outbox": sent.model_dump(mode="json")}


@router.post("/drafts/{draft_id}/reject")
def reject_draft(
    draft_id: str, body: RejectDraftBody, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    approver = _require(body.approver, "approver")
    reason = _require(body.reason, "reason")
    with state.lock:
        draft = _get_draft(state, draft_id)
        if draft.status != DraftStatus.proposed:
            raise HTTPException(status_code=409, detail=f"draft is already {draft.status.value}")
        rejection = state.store.reject_draft(draft_id, approver, reason)
        state.ledger.append(
            case_id=draft.case_id,
            actor=f"human:{approver}",
            action="draft_rejected",
            source=SOURCE,
            payload={"draft_id": draft_id, "reason": reason},
        )
        return rejection.model_dump(mode="json")


# --- SAP intents ---------------------------------------------------------------------------


@router.get("/sap-intents")
def list_sap_intents(
    case_id: str | None = None,
    status: Literal["proposed", "approved", "executed"] | None = None,
    state: AppState = Depends(get_state),
) -> list[dict[str, Any]]:
    return [i.model_dump(mode="json") for i in state.store.list_sap_intents(case_id, status)]


@router.post("/sap-intents/{intent_id}/approve")
def approve_sap_intent(
    intent_id: str, body: ApproveIntentBody, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    approver = _require(body.approver, "approver")
    actor = f"human:{approver}"
    with state.lock:
        try:
            intent = state.store.get_sap_intent(intent_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="SAP intent not found") from None
        if intent.status != "proposed":
            raise HTTPException(status_code=409, detail=f"SAP intent is already {intent.status}")

        try:
            document = state.sap.create_document(intent.doc_type, intent.payload)
        except MissingKeysError as exc:
            state.ledger.append(
                case_id=intent.case_id,
                actor="system",
                action="check_failed",
                source=SOURCE,
                payload={"intent_id": intent_id, "check": "sap_payload", "missing": exc.missing},
            )
            raise HTTPException(status_code=422, detail={"missing": exc.missing}) from None

        intent.status = "executed"
        intent.approver = approver
        intent.document_number = document["DocumentNumber"]
        state.store.save_sap_intent(intent)
        state.ledger.append(
            case_id=intent.case_id,
            actor=actor,
            action="sap_document_created",
            source=SOURCE,
            payload={
                "intent_id": intent_id,
                "doc_type": intent.doc_type,
                "document_number": document["DocumentNumber"],
                "document_type": document["DocumentType"],
            },
        )

        if intent.doc_type == "purchase_order":
            case = state.store.get_case(intent.case_id)
            set_case_state(state, case, CaseState.Ordered, actor, "purchase order created")

        return intent.model_dump(mode="json")


# --- outbox and audit ----------------------------------------------------------------------


@router.get("/outbox")
def list_outbox(state: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in state.store.list_outbox()]


@router.get("/audit")
def list_audit(
    case_id: str | None = None, state: AppState = Depends(get_state)
) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in state.ledger.list(case_id)]


@router.get("/audit/verify")
def verify_audit(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return {**state.ledger.verify(), "ledger_file": state.ledger.path.name}
