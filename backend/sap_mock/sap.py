"""SQLite-backed mock of the three SAP documents NeuroBiz creates.

The mock only records documents; it has no approval logic. Callers (the K3 approve flow) must
check for human approval and write the ledger event before calling it.
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocSpec:
    document_type: str
    prefix: str
    first_number: int
    required: tuple[str, ...]


DOC_SPECS: dict[str, DocSpec] = {
    "rfq": DocSpec(
        "RFQ", "RFQ", 6000001, ("CaseId", "Material", "Quantity", "Unit", "Supplier")
    ),
    "supplier_quotation": DocSpec(
        "SupplierQuotation",
        "QTN",
        7000001,
        ("CaseId", "Material", "Quantity", "Unit", "Supplier", "NetPrice", "Currency"),
    ),
    "purchase_order": DocSpec(
        "PurchaseOrder",
        "PO",
        4500001,
        ("CaseId", "Material", "Quantity", "Unit", "Supplier", "NetPrice", "Currency"),
    ),
}


class MissingKeysError(ValueError):
    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"missing required keys: {', '.join(missing)}")
        self.missing = missing


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sap_documents (
    document_number TEXT PRIMARY KEY,
    doc_type TEXT NOT NULL,
    number INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (doc_type, number)
);
CREATE INDEX IF NOT EXISTS sap_documents_case_id ON sap_documents (case_id);
"""


class SqliteSapMock:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def create_document(self, doc_type: str, d: dict[str, Any]) -> dict[str, Any]:
        """Create one document from an OData-style "d" body. Raises MissingKeysError."""
        spec = DOC_SPECS[doc_type]
        missing = [k for k in spec.required if d.get(k) in (None, "")]
        if missing:
            raise MissingKeysError(missing)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT MAX(number) FROM sap_documents WHERE doc_type = ?", (doc_type,)
            ).fetchone()
            number = spec.first_number if row[0] is None else row[0] + 1
            document_number = f"{spec.prefix}-{number}"
            created_at = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "INSERT INTO sap_documents "
                "(document_number, doc_type, number, case_id, created_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    document_number,
                    doc_type,
                    number,
                    str(d["CaseId"]),
                    created_at,
                    json.dumps(d, sort_keys=True, default=str),
                ),
            )
        return {
            "DocumentNumber": document_number,
            "DocumentType": spec.document_type,
            "CaseId": str(d["CaseId"]),
            "CreatedAt": created_at,
        }

    def list_documents(self, case_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT document_number, doc_type, case_id, created_at, payload FROM sap_documents"
        params: tuple[Any, ...] = ()
        if case_id is not None:
            query += " WHERE case_id = ?"
            params = (case_id,)
        query += " ORDER BY created_at, document_number"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "DocumentNumber": number,
                "DocumentType": DOC_SPECS[doc_type].document_type,
                "CaseId": row_case_id,
                "CreatedAt": created_at,
                "Payload": json.loads(payload),
            }
            for number, doc_type, row_case_id, created_at, payload in rows
        ]
