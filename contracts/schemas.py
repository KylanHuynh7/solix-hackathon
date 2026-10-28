"""Shared data contracts for NeuroBiz. Frozen after N1; lanes must not edit."""

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class FieldStatus(str, Enum):
    verified = "verified"
    needs_review = "needs_review"


class Field(BaseModel):
    """One extracted value with its source evidence. value is null when not determinable.

    unit: for quantities, the counting unit as stated (e.g. "pen", "tablet"). For prices,
    "<CURRENCY>/<counting unit as stated in the email>", e.g. "USD/pen", "USD/carton",
    "USD/tablet". Extraction records the basis as stated and never converts between bases;
    conversion is a validator job using pack size.
    """

    value: Any | None = None
    unit: str | None = None
    raw: str | None = None
    evidence: str | None = None
    status: FieldStatus
    reason: str | None = None


class Offer(BaseModel):
    supplier_id: str
    round: int
    ndc: Field
    product: Field
    quantity: Field
    lots: list[Field]
    expiry: Field
    unit_price: Field
    lead_time_days: Field
    storage: Field
    source_message_id: str


class LineItem(BaseModel):
    requested_ndc: str
    product: str
    dosage_form: str
    quantity: int
    unit: str


class CustomerRequirement(BaseModel):
    customer_id: str
    min_expiry: date
    single_lot: bool
    dosage_form: str
    storage_range: str


class CaseState(str, Enum):
    New = "New"
    Quoting = "Quoting"
    Exception = "Exception"
    AwaitingCustomer = "AwaitingCustomer"
    Confirmed = "Confirmed"
    Ordered = "Ordered"


class Case(BaseModel):
    case_id: str
    line_item: LineItem
    requirement: CustomerRequirement
    offers: list[Offer]
    state: CaseState
    exceptions: list[str]


class DraftStatus(str, Enum):
    proposed = "proposed"
    approved = "approved"
    sent = "sent"


class Draft(BaseModel):
    draft_id: str
    case_id: str
    recipient_role: Literal["supplier", "customer"]
    to: list[str]
    cc: list[str]
    subject: str
    body: str
    status: DraftStatus
    approver: str | None = None
    created_by: str


class AuditEvent(BaseModel):
    seq: int
    ts: datetime
    case_id: str
    actor: str
    action: str
    source: str
    payload: dict[str, Any]
    model: str | None = None
    prompt_version: str | None = None
    prev_hash: str
    hash: str


class Email(BaseModel):
    message_id: str
    thread_id: str
    sender: str
    to: list[str]
    cc: list[str]
    subject: str
    date: datetime
    body: str
