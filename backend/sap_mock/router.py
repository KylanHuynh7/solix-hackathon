"""FastAPI router for the SAP mock, served at /sap. Not mounted in backend/main.py until K3.

The DB path comes from NEUROBIZ_SAP_DB (default sap_mock.db). Tests override get_sap via
app.dependency_overrides.
"""

import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.sap_mock.sap import MissingKeysError, SqliteSapMock


class ODataBody(BaseModel):
    d: dict[str, Any]


@lru_cache(maxsize=1)
def get_sap() -> SqliteSapMock:
    return SqliteSapMock(os.environ.get("NEUROBIZ_SAP_DB", "sap_mock.db"))


router = APIRouter(prefix="/sap", tags=["sap-mock"])


def _create(sap: SqliteSapMock, doc_type: str, body: ODataBody) -> dict[str, Any]:
    try:
        return sap.create_document(doc_type, body.d)
    except MissingKeysError as exc:
        raise HTTPException(
            status_code=422, detail={"error": str(exc), "missing": exc.missing}
        ) from exc


@router.post("/rfq", status_code=201)
def create_rfq(body: ODataBody, sap: SqliteSapMock = Depends(get_sap)) -> dict[str, Any]:
    return _create(sap, "rfq", body)


@router.post("/supplier-quotation", status_code=201)
def create_supplier_quotation(
    body: ODataBody, sap: SqliteSapMock = Depends(get_sap)
) -> dict[str, Any]:
    return _create(sap, "supplier_quotation", body)


@router.post("/purchase-order", status_code=201)
def create_purchase_order(
    body: ODataBody, sap: SqliteSapMock = Depends(get_sap)
) -> dict[str, Any]:
    return _create(sap, "purchase_order", body)


@router.get("/documents")
def list_documents(
    case_id: str | None = None, sap: SqliteSapMock = Depends(get_sap)
) -> list[dict[str, Any]]:
    return sap.list_documents(case_id)
