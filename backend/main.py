"""TransPharmic API entrypoint.

Run: uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.demo import router as demo_router
from backend.api.routes import router as api_router
from backend.archive.router import router as archive_router

app = FastAPI(title="TransPharmic")
app.include_router(api_router)
app.include_router(demo_router)
app.include_router(archive_router)
# The /sap mock router is deliberately not mounted: its POSTs would bypass the human approval
# gate. SAP documents are created only via POST /sap-intents/{id}/approve.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
