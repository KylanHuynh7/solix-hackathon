"""Process-wide app state: the case store, the current ledger and the current SAP mock.

Files live under NEUROBIZ_DATA_DIR (default "var/"). A demo reset starts a NEW ledger file and a
new SAP mock file, so earlier chains stay intact on disk and can still be verified.
"""

import os
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from backend.ledger import SqliteLedger
from backend.sap_mock import SqliteSapMock
from backend.store import SqliteCaseStore


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]


def _latest(directory: Path, prefix: str) -> Path:
    existing = sorted(directory.glob(f"{prefix}-*.db"))
    return existing[-1] if existing else directory / f"{prefix}-{_stamp()}.db"


class AppState:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # One lock for every state-changing request: approve-once and the demo cursor rely on it.
        self.lock = threading.RLock()
        self.store = SqliteCaseStore(self.data_dir / "store.db")
        if not self.store.list_cases():
            self.store.load_seed()
        self.ledger = SqliteLedger(_latest(self.data_dir / "ledgers", "ledger"))
        self.sap = SqliteSapMock(_latest(self.data_dir / "sap", "sap"))
        self.demo_index = 0
        # The one in-flight /demo/process-next job, if any (see backend/api/demo.py).
        self.demo_job: dict | None = None
        self.last_job: dict | None = None

    def reset(self) -> None:
        with self.lock:
            self.store.load_seed()
            self.ledger.close()
            self.sap.close()
            self.ledger = SqliteLedger(self.data_dir / "ledgers" / f"ledger-{_stamp()}.db")
            self.sap = SqliteSapMock(self.data_dir / "sap" / f"sap-{_stamp()}.db")
            self.demo_index = 0

    def close(self) -> None:
        self.store.close()
        self.ledger.close()
        self.sap.close()


@lru_cache(maxsize=1)
def get_state() -> AppState:
    return AppState(os.environ.get("NEUROBIZ_DATA_DIR", "var"))
