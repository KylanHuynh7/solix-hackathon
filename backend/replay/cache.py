"""Record/replay cache at the model boundary, so the stage demo is fast and identical every time.

NB_REPLAY = "live" (default) | "record" | "replay". record runs live and writes the output;
replay reads it and raises ReplayMiss on a miss, never falling back to a live call.
Files live in data/replay/<component>/<key>.json (NB_REPLAY_DIR overrides the root).
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

LIVE, RECORD, REPLAY = "live", "record", "replay"
MODES = (LIVE, RECORD, REPLAY)
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "replay"

# Paths written by this process in record mode, in order. record.py prints these.
written: list[Path] = []


class ReplayMiss(LookupError):
    def __init__(self, component: str, key: str) -> None:
        super().__init__(f"no recorded {component} output for key {key[:12]}")
        self.component = component
        self.key = key


def mode() -> str:
    value = os.environ.get("NB_REPLAY", LIVE).strip().lower() or LIVE
    if value not in MODES:
        raise ValueError(f"NB_REPLAY must be one of {', '.join(MODES)}, got {value!r}")
    return value


def ledger_source() -> str:
    return "replay" if mode() == REPLAY else "live"


def cache_dir() -> Path:
    return Path(os.environ.get("NB_REPLAY_DIR") or DEFAULT_DIR)


def make_key(component: str, model: str, prompt_version: str, text: str) -> str:
    # NUL separators so ("ab", "c") and ("a", "bc") never collide.
    joined = "\0".join((component, model or "", prompt_version or "", text))
    return hashlib.sha256(joined.encode()).hexdigest()


def path_for(component: str, key: str) -> Path:
    return cache_dir() / component / f"{key}.json"


def load(component: str, key: str) -> Any:
    path = path_for(component, key)
    if not path.is_file():
        raise ReplayMiss(component, key)
    return json.loads(path.read_text())["output"]


def _secret_values() -> list[str]:
    names = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    return [v for k, v in os.environ.items() if len(v) >= 8 and any(n in k.upper() for n in names)]


def save(component: str, key: str, *, model: str, prompt_version: str, output: Any) -> Path:
    # The filename is the key, so it is not repeated inside the file.
    record = {
        "component": component,
        "model": model,
        "prompt_version": prompt_version,
        "output": output,
    }
    text = json.dumps(record, indent=2, sort_keys=True, default=str)
    if "sk-ant" in text or any(v in text for v in _secret_values()):
        raise ValueError(f"refusing to write {component} replay file: output contains a secret")
    path = path_for(component, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n")
    written.append(path)
    return path


class SourceLedger:
    """Ledger wrapper that stamps every event's source with "replay" or "live" for the mode."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def append(self, *, source: str, **kwargs):
        return self._inner.append(source=ledger_source(), **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def tag_ledger(ledger):
    return ledger if isinstance(ledger, SourceLedger) else SourceLedger(ledger)
