"""Case store: cases, drafts, SAP intents, the send-simulator outbox and draft rejections.

Models are stored as JSON blobs; SQL is always parameterised. Rejections live in their own table
because the frozen DraftStatus has no "rejected" value: a rejected draft leaves list_drafts().
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from contracts.schemas import Case, Draft, DraftStatus

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"


class SapIntent(BaseModel):
    intent_id: str
    case_id: str
    doc_type: Literal["rfq", "supplier_quotation", "purchase_order"]
    payload: dict[str, Any]
    status: Literal["proposed", "approved", "executed"]
    approver: str | None = None
    document_number: str | None = None


class OutboxEmail(BaseModel):
    """An email "sent" by the simulator. Nothing here ever reaches a real mail server."""

    outbox_id: int | None = None
    draft_id: str
    case_id: str
    to: list[str]
    cc: list[str]
    subject: str
    body: str
    approver: str
    sent_at: datetime
    via: str = "simulator"


class Rejection(BaseModel):
    draft: Draft
    rejected_by: str
    reason: str
    rejected_at: datetime


def load_seed_case() -> Case:
    return Case.model_validate_json((SEED_DIR / "case.json").read_text())


class CaseStore(Protocol):
    def get_case(self, case_id: str) -> Case: ...
    def save_case(self, case: Case) -> None: ...
    def list_cases(self) -> list[Case]: ...
    def save_draft(self, draft: Draft) -> None: ...
    def get_draft(self, draft_id: str) -> Draft: ...
    def list_drafts(
        self, case_id: str | None = None, status: DraftStatus | None = None
    ) -> list[Draft]: ...
    def save_sap_intent(self, intent: SapIntent) -> None: ...
    def list_sap_intents(
        self, case_id: str | None = None, status: str | None = None
    ) -> list[SapIntent]: ...


class InMemoryCaseStore:
    """Same interface as SqliteCaseStore, for tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.load_seed()

    def load_seed(self) -> None:
        with self._lock:
            seed = load_seed_case()
            self._cases: dict[str, Case] = {seed.case_id: seed}
            self._drafts: dict[str, Draft] = {}
            self._intents: dict[str, SapIntent] = {}
            self._outbox: list[OutboxEmail] = []
            self._rejections: dict[str, Rejection] = {}

    def get_case(self, case_id: str) -> Case:
        with self._lock:
            return self._cases[case_id].model_copy(deep=True)

    def save_case(self, case: Case) -> None:
        with self._lock:
            self._cases[case.case_id] = case.model_copy(deep=True)

    def list_cases(self) -> list[Case]:
        with self._lock:
            return [c.model_copy(deep=True) for c in self._cases.values()]

    def save_draft(self, draft: Draft) -> None:
        with self._lock:
            self._drafts[draft.draft_id] = draft.model_copy(deep=True)

    def get_draft(self, draft_id: str) -> Draft:
        with self._lock:
            return self._drafts[draft_id].model_copy(deep=True)

    def list_drafts(
        self, case_id: str | None = None, status: DraftStatus | None = None
    ) -> list[Draft]:
        with self._lock:
            return [
                d.model_copy(deep=True)
                for d in self._drafts.values()
                if (case_id is None or d.case_id == case_id)
                and (status is None or d.status == status)
            ]

    def save_sap_intent(self, intent: SapIntent) -> None:
        with self._lock:
            self._intents[intent.intent_id] = intent.model_copy(deep=True)

    def get_sap_intent(self, intent_id: str) -> SapIntent:
        with self._lock:
            return self._intents[intent_id].model_copy(deep=True)

    def list_sap_intents(
        self, case_id: str | None = None, status: str | None = None
    ) -> list[SapIntent]:
        with self._lock:
            return [
                i.model_copy(deep=True)
                for i in self._intents.values()
                if (case_id is None or i.case_id == case_id)
                and (status is None or i.status == status)
            ]

    def record_outbox(self, email: OutboxEmail) -> OutboxEmail:
        with self._lock:
            stored = email.model_copy(update={"outbox_id": len(self._outbox) + 1})
            self._outbox.append(stored)
            return stored.model_copy(deep=True)

    def list_outbox(self) -> list[OutboxEmail]:
        with self._lock:
            return [e.model_copy(deep=True) for e in self._outbox]

    def reject_draft(self, draft_id: str, rejected_by: str, reason: str) -> Rejection:
        with self._lock:
            draft = self._drafts.pop(draft_id)
            rejection = Rejection(
                draft=draft,
                rejected_by=rejected_by,
                reason=reason,
                rejected_at=datetime.now(timezone.utc),
            )
            self._rejections[draft_id] = rejection
            return rejection.model_copy(deep=True)

    def list_rejections(self, case_id: str | None = None) -> list[Rejection]:
        with self._lock:
            return [
                r.model_copy(deep=True)
                for r in self._rejections.values()
                if case_id is None or r.draft.case_id == case_id
            ]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (case_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_seq INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sap_intents (
    intent_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_seq INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rejections (
    draft_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    data TEXT NOT NULL
);
"""

_TABLES = ("cases", "drafts", "sap_intents", "outbox", "rejections")


class SqliteCaseStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def load_seed(self) -> None:
        """Reset the whole DB to data/seed/case.json with no drafts, intents or outbox."""
        seed = load_seed_case()
        with self._lock, self._conn:
            for table in _TABLES:  # constant table names, not user input
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.execute(
                "INSERT INTO cases (case_id, data) VALUES (?, ?)",
                (seed.case_id, seed.model_dump_json()),
            )

    def get_case(self, case_id: str) -> Case:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        if row is None:
            raise KeyError(case_id)
        return Case.model_validate_json(row[0])

    def save_case(self, case: Case) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO cases (case_id, data) VALUES (?, ?) "
                "ON CONFLICT (case_id) DO UPDATE SET data = excluded.data",
                (case.case_id, case.model_dump_json()),
            )

    def list_cases(self) -> list[Case]:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM cases ORDER BY case_id").fetchall()
        return [Case.model_validate_json(r[0]) for r in rows]

    def _next_seq(self, table: str) -> int:
        row = self._conn.execute(f"SELECT COALESCE(MAX(created_seq), 0) + 1 FROM {table}")
        return row.fetchone()[0]

    def save_draft(self, draft: Draft) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO drafts (draft_id, case_id, status, created_seq, data) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (draft_id) DO UPDATE SET "
                "case_id = excluded.case_id, status = excluded.status, data = excluded.data",
                (
                    draft.draft_id,
                    draft.case_id,
                    draft.status.value,
                    self._next_seq("drafts"),
                    draft.model_dump_json(),
                ),
            )

    def get_draft(self, draft_id: str) -> Draft:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM drafts WHERE draft_id = ?", (draft_id,)
            ).fetchone()
        if row is None:
            raise KeyError(draft_id)
        return Draft.model_validate_json(row[0])

    def list_drafts(
        self, case_id: str | None = None, status: DraftStatus | None = None
    ) -> list[Draft]:
        status_value = DraftStatus(status).value if status is not None else None
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM drafts "
                "WHERE (? IS NULL OR case_id = ?) AND (? IS NULL OR status = ?) "
                "ORDER BY created_seq",
                (case_id, case_id, status_value, status_value),
            ).fetchall()
        return [Draft.model_validate_json(r[0]) for r in rows]

    def save_sap_intent(self, intent: SapIntent) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sap_intents (intent_id, case_id, status, created_seq, data) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (intent_id) DO UPDATE SET "
                "case_id = excluded.case_id, status = excluded.status, data = excluded.data",
                (
                    intent.intent_id,
                    intent.case_id,
                    intent.status,
                    self._next_seq("sap_intents"),
                    intent.model_dump_json(),
                ),
            )

    def get_sap_intent(self, intent_id: str) -> SapIntent:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM sap_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        if row is None:
            raise KeyError(intent_id)
        return SapIntent.model_validate_json(row[0])

    def list_sap_intents(
        self, case_id: str | None = None, status: str | None = None
    ) -> list[SapIntent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM sap_intents "
                "WHERE (? IS NULL OR case_id = ?) AND (? IS NULL OR status = ?) "
                "ORDER BY created_seq",
                (case_id, case_id, status, status),
            ).fetchall()
        return [SapIntent.model_validate_json(r[0]) for r in rows]

    def record_outbox(self, email: OutboxEmail) -> OutboxEmail:
        """Raises sqlite3.IntegrityError if this draft was already sent."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO outbox (draft_id, data) VALUES (?, ?)",
                (email.draft_id, email.model_dump_json()),
            )
            stored = email.model_copy(update={"outbox_id": cur.lastrowid})
            self._conn.execute(
                "UPDATE outbox SET data = ? WHERE outbox_id = ?",
                (stored.model_dump_json(), cur.lastrowid),
            )
        return stored

    def list_outbox(self) -> list[OutboxEmail]:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM outbox ORDER BY outbox_id").fetchall()
        return [OutboxEmail.model_validate_json(r[0]) for r in rows]

    def reject_draft(self, draft_id: str, rejected_by: str, reason: str) -> Rejection:
        draft = self.get_draft(draft_id)
        rejection = Rejection(
            draft=draft,
            rejected_by=rejected_by,
            reason=reason,
            rejected_at=datetime.now(timezone.utc),
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO rejections (draft_id, case_id, data) VALUES (?, ?, ?)",
                (draft_id, draft.case_id, rejection.model_dump_json()),
            )
            self._conn.execute("DELETE FROM drafts WHERE draft_id = ?", (draft_id,))
        return rejection

    def list_rejections(self, case_id: str | None = None) -> list[Rejection]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM rejections WHERE (? IS NULL OR case_id = ?) ORDER BY rowid",
                (case_id, case_id),
            ).fetchall()
        return [Rejection.model_validate_json(r[0]) for r in rows]
