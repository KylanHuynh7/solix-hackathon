"""GET /cases/{case_id}/solix-bundle: the read-only Solix archive export."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.api.state import AppState, get_state
from backend.archive.bundle import build_bundle

router = APIRouter()


@router.get("/cases/{case_id}/solix-bundle")
def solix_bundle(case_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    # Held only for a consistent snapshot; nothing is written.
    with state.lock:
        try:
            return build_bundle(case_id, state.store, state.ledger)
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found") from None
