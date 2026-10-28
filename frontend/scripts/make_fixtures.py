"""Regenerate frontend/src/fixtures/*.json by running the K3 API (demo stub) on the seed data.

Run from the repo root:  PYTHONPATH=. uv run python frontend/scripts/make_fixtures.py

FIXTURES ONLY: the output is sample data for offline UI work, not real case data.
"""

import json
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.state import AppState, get_state
from backend.main import app
from contracts.schemas import Draft, DraftStatus

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed"
OUT = ROOT / "frontend" / "src" / "fixtures"
CASE = "CASE-001"


def write(name: str, data) -> None:
    (OUT / name).write_text(json.dumps(data, indent=2) + "\n")


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    state = AppState(tmp / "var")
    app.dependency_overrides[get_state] = lambda: state
    client = TestClient(app)
    try:
        client.post("/demo/reset")
        for _ in range(5):  # s1_offer, s2_offer, s3_offer, s1_injection, cust_yes
            client.post("/demo/process-next")

        # A third draft, rejected by a human, so the UI has one of each kind.
        draft = Draft(
            draft_id="DRAFT-fixture-rejected",
            case_id=CASE,
            recipient_role="supplier",
            to=["jordan.lee@supplier2.example.com"],
            cc=[],
            subject="Re: RFQ: Semaglutide injection pens - CASE-001",
            body=(
                "Hi Jordan,\n\nThanks for the offer. We need injection pens, not tablets. "
                "Do you have NDC 0169-4524-14 available?\n\nBest regards,\nJamie Park\nNeuroBiz"
            ),
            status=DraftStatus.proposed,
            created_by="negotiator",
        )
        state.store.save_draft(draft)
        state.ledger.append(
            case_id=CASE,
            actor="negotiator",
            action="draft_proposed",
            source="fixture",
            payload={"draft_id": draft.draft_id, "recipient_role": "supplier"},
        )
        client.post(
            f"/drafts/{draft.draft_id}/reject",
            json={
                "approver": "Jamie Park",
                "reason": "Supplier Two only has tablets; drop them from this case instead.",
            },
        )

        drafts = client.get("/drafts").json() + client.get(
            "/drafts", params={"status": "rejected"}
        ).json()

        OUT.mkdir(parents=True, exist_ok=True)
        write("cases.json", client.get("/cases").json())
        write("drafts.json", drafts)
        write("audit.json", client.get("/audit", params={"case_id": CASE}).json())
        write("sap_intents.json", client.get("/sap-intents").json())
        write("outbox.json", client.get("/outbox").json())
        write(
            "emails.json",
            [json.loads(p.read_text()) for p in sorted((SEED / "emails").glob("*.json"))],
        )
        shutil.copy(SEED / "directory.json", OUT / "directory.json")
        print(f"wrote fixtures to {OUT}")
    finally:
        app.dependency_overrides.clear()
        state.close()
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
