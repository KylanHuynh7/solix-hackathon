"""Demo controls: reset, process the next seeded email in the background, and poll its status.

Processing runs backend.agents.process_email (N5) by default; NEUROBIZ_PROCESSOR=stub selects the
offline stub in demo_stub.py (a rehearsal and backup path that needs no API key). Agent runs take
tens of seconds and make blocking model calls, so each job runs in a worker thread with its own
event loop and the API stays responsive while the UI polls GET /demo/status.
"""

import asyncio
import os
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.api.demo_stub import DEMO_ORDER, load_demo_email
from backend.api.demo_stub import process_email as stub_process_email
from backend.api.state import AppState, get_state

router = APIRouter(prefix="/demo")

CASE_ID = "CASE-001"

Processor = Callable[..., Awaitable[dict[str, Any]]]


def default_processor() -> tuple[str, Processor]:
    if os.environ.get("NEUROBIZ_PROCESSOR", "agents").lower() == "stub":
        return "stub", stub_process_email
    from backend.agents import process_email

    return "agents", process_email


# Tests override this dependency to run the stub or a fake.
def get_processor() -> tuple[str, Processor]:
    return default_processor()


def _status(state: AppState) -> dict[str, Any]:
    i = state.demo_index
    job = state.demo_job
    return {
        "next": DEMO_ORDER[i] if i < len(DEMO_ORDER) else None,
        "index": i,
        "total": len(DEMO_ORDER),
        "order": list(DEMO_ORDER),
        "processing": job["key"] if job else None,
        "last": state.last_job,
    }


def _run_job(state: AppState, key: str, name: str, process: Processor, job: dict) -> None:
    """Worker thread: run one email through the processor, then record the outcome."""
    email = load_demo_email(key)
    outcome: dict[str, Any] = {"key": key, "processor": name, "message_id": email.message_id}
    try:
        result = asyncio.run(process(email, CASE_ID, store=state.store, ledger=state.ledger))
        outcome.update(ok=True, result=result)
    except Exception as exc:  # report it to the UI; the email can be retried
        outcome.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:500])
        state.ledger.append(
            case_id=CASE_ID,
            actor="system",
            action="check_failed",
            source="api",
            payload={"check": "process_email", "key": key, "error": outcome["error"]},
        )
    outcome["seconds"] = round(time.monotonic() - job["started"], 1)
    with state.lock:
        if outcome["ok"]:
            state.demo_index += 1
        state.last_job = outcome
        state.demo_job = None


@router.get("/status")
def demo_status(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return _status(state)


@router.post("/reset")
def demo_reset(state: AppState = Depends(get_state)) -> dict[str, Any]:
    with state.lock:
        if state.demo_job:
            raise HTTPException(status_code=409, detail="an email is still processing; wait for it")
        state.reset()
        state.last_job = None
        state.ledger.append(
            case_id=CASE_ID,
            actor="system",
            action="demo_reset",
            source="api",
            payload={"ledger_file": state.ledger.path.name},
        )
        return _status(state)


@router.post("/process-next")
def demo_process_next(
    state: AppState = Depends(get_state),
    processor: tuple[str, Processor] = Depends(get_processor),
) -> dict[str, Any]:
    """Start processing the next seeded email and return at once; poll GET /demo/status."""
    with state.lock:
        if state.demo_job:
            raise HTTPException(status_code=409, detail=f"still processing {state.demo_job['key']}")
        if state.demo_index >= len(DEMO_ORDER):
            raise HTTPException(status_code=409, detail="all seeded emails processed; reset")
        key = DEMO_ORDER[state.demo_index]
        name, process = processor
        job = {"key": key, "started": time.monotonic()}
        state.demo_job = job
    threading.Thread(
        target=_run_job, args=(state, key, name, process, job), daemon=True, name=f"demo-{key}"
    ).start()
    return {"processing": load_demo_email(key).message_id, "key": key, "processor": name}
