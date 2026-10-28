"""Hash-chained, append-only audit ledger.

Each event's hash is sha256(prev_hash + canonical_json(event without "hash")), with the
genesis prev_hash being 64 zeros. There are no update or delete functions: a correction
is a new event whose payload references the seq it corrects.
"""

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from contracts.schemas import AuditEvent

GENESIS_HASH = "0" * 64

# Shared action vocabulary. Not enforced, so new agent actions never break a live run.
ACTIONS = frozenset(
    {
        "email_ingested",
        "fields_extracted",
        "check_failed",
        "tool_call",
        "tool_denied",
        "draft_proposed",
        "draft_approved",
        "draft_rejected",
        "email_sent",
        "sap_document_created",
        "case_state_changed",
    }
)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(event: dict[str, Any]) -> str:
    """Hash of an event dict (JSON-mode dump); any "hash" key is ignored."""
    body = {k: v for k, v in event.items() if k != "hash"}
    return hashlib.sha256((body["prev_hash"] + canonical_json(body)).encode()).hexdigest()


def _build_event(
    *,
    seq: int,
    prev_hash: str,
    case_id: str,
    actor: str,
    action: str,
    source: str,
    payload: dict[str, Any],
    model: str | None,
    prompt_version: str | None,
) -> AuditEvent:
    if not case_id or not actor or not action or not source:
        raise ValueError("case_id, actor, action and source are required")
    event = AuditEvent(
        seq=seq,
        ts=datetime.now(timezone.utc),
        case_id=case_id,
        actor=actor,
        action=action,
        source=source,
        # Round-trip through canonical JSON so the stored payload hashes identically on verify.
        payload=json.loads(canonical_json(payload)),
        model=model,
        prompt_version=prompt_version,
        prev_hash=prev_hash,
        hash="",
    )
    event.hash = compute_hash(event.model_dump(mode="json"))
    return event


def _verify_chain(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Check seq continuity, prev_hash links and each hash. Events are JSON-mode dicts in seq order."""
    prev_hash = GENESIS_HASH
    for expected_seq, event in enumerate(events, start=1):
        if event["seq"] != expected_seq or event["prev_hash"] != prev_hash:
            # A gap or broken link: report the first seq that is missing or unlinked.
            return {"ok": False, "first_broken_seq": expected_seq, "count": len(events)}
        if compute_hash(event) != event["hash"]:
            return {"ok": False, "first_broken_seq": event["seq"], "count": len(events)}
        prev_hash = event["hash"]
    return {"ok": True, "first_broken_seq": None, "count": len(events)}


class Ledger(Protocol):
    def append(
        self,
        *,
        case_id: str,
        actor: str,
        action: str,
        source: str,
        payload: dict,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> AuditEvent: ...

    def list(self, case_id: str | None = None) -> list[AuditEvent]: ...

    def verify(self) -> dict: ...


class InMemoryLedger:
    """Same interface as SqliteLedger, for tests."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def append(
        self,
        *,
        case_id: str,
        actor: str,
        action: str,
        source: str,
        payload: dict,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> AuditEvent:
        with self._lock:
            prev_hash = self._events[-1].hash if self._events else GENESIS_HASH
            event = _build_event(
                seq=len(self._events) + 1,
                prev_hash=prev_hash,
                case_id=case_id,
                actor=actor,
                action=action,
                source=source,
                payload=payload,
                model=model,
                prompt_version=prompt_version,
            )
            self._events.append(event)
            return event.model_copy(deep=True)

    def list(self, case_id: str | None = None) -> list[AuditEvent]:
        with self._lock:
            return [
                e.model_copy(deep=True)
                for e in self._events
                if case_id is None or e.case_id == case_id
            ]

    def verify(self) -> dict:
        with self._lock:
            return _verify_chain([e.model_dump(mode="json") for e in self._events])


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    case_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    source TEXT NOT NULL,
    payload TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_case_id ON audit_events (case_id);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update
    BEFORE UPDATE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
    BEFORE DELETE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
"""

_COLUMNS = (
    "seq, ts, case_id, actor, action, source, payload, model, prompt_version, prev_hash, hash"
)


class SqliteLedger:
    """Append-only ledger in SQLite. Triggers block UPDATE/DELETE; verify() catches tampering
    that bypasses them (e.g. a dropped trigger or a hand-edited file)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def append(
        self,
        *,
        case_id: str,
        actor: str,
        action: str,
        source: str,
        payload: dict,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> AuditEvent:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            seq, prev_hash = (row[0] + 1, row[1]) if row else (1, GENESIS_HASH)
            event = _build_event(
                seq=seq,
                prev_hash=prev_hash,
                case_id=case_id,
                actor=actor,
                action=action,
                source=source,
                payload=payload,
                model=model,
                prompt_version=prompt_version,
            )
            data = event.model_dump(mode="json")
            self._conn.execute(
                f"INSERT INTO audit_events ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    data["seq"],
                    data["ts"],
                    data["case_id"],
                    data["actor"],
                    data["action"],
                    data["source"],
                    canonical_json(data["payload"]),
                    data["model"],
                    data["prompt_version"],
                    data["prev_hash"],
                    data["hash"],
                ),
            )
            return event

    def _rows(self, case_id: str | None) -> list[dict[str, Any]]:
        if case_id is None:
            cur = self._conn.execute(f"SELECT {_COLUMNS} FROM audit_events ORDER BY seq")
        else:
            cur = self._conn.execute(
                f"SELECT {_COLUMNS} FROM audit_events WHERE case_id = ? ORDER BY seq",
                (case_id,),
            )
        names = [d[0] for d in cur.description]
        rows = []
        for values in cur.fetchall():
            row = dict(zip(names, values))
            try:
                row["payload"] = json.loads(row["payload"])
            except json.JSONDecodeError:
                pass  # left as raw text, so verify() reports this row's hash as broken
            rows.append(row)
        return rows

    def list(self, case_id: str | None = None) -> list[AuditEvent]:
        with self._lock:
            return [AuditEvent.model_validate(row) for row in self._rows(case_id)]

    def verify(self) -> dict:
        with self._lock:
            rows = self._rows(None)
        # Hash the stored text as-is (not re-parsed models), so any byte-level edit is caught.
        return _verify_chain(rows)
