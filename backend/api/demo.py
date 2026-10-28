"""Demo controls: reset and process the next seeded email.

process-next calls the STUB in demo_stub.py for now; K6 swaps in backend.agents.process_email.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.api.demo_stub import DEMO_ORDER, load_demo_email, process_email
from backend.api.state import AppState, get_state

router = APIRouter(prefix="/demo")

CASE_ID = "CASE-001"


def _status(state: AppState) -> dict[str, Any]:
    i = state.demo_index
    return {
        "next": DEMO_ORDER[i] if i < len(DEMO_ORDER) else None,
        "index": i,
        "total": len(DEMO_ORDER),
        "order": list(DEMO_ORDER),
    }


@router.get("/status")
def demo_status(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return _status(state)


@router.post("/reset")
def demo_reset(state: AppState = Depends(get_state)) -> dict[str, Any]:
    with state.lock:
        state.reset()
        state.ledger.append(
            case_id=CASE_ID,
            actor="system",
            action="demo_reset",
            source="api",
            payload={"ledger_file": state.ledger.path.name},
        )
        return _status(state)


@router.post("/process-next")
async def demo_process_next(state: AppState = Depends(get_state)) -> dict[str, Any]:
    with state.lock:
        if state.demo_index >= len(DEMO_ORDER):
            raise HTTPException(status_code=409, detail="all seeded emails processed; reset")
        key = DEMO_ORDER[state.demo_index]
        result = await process_email(
            load_demo_email(key), CASE_ID, store=state.store, ledger=state.ledger
        )
        state.demo_index += 1
        return {"processed": key, "result": result, **_status(state)}
