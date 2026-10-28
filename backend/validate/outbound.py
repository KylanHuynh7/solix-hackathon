"""API-facing adapter for the outbound leak check: plain-English problems for a draft."""

import json
from functools import cache
from pathlib import Path

from backend.validate.checks import check_outbound as _check_outbound
from backend.validate.checks import exceptions_for
from contracts.schemas import Case, Draft

DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "seed" / "directory.json"


@cache
def _directory() -> dict:
    return json.loads(DIRECTORY.read_text())


def check_outbound(draft: Draft, case: Case) -> list[str]:
    return exceptions_for(_check_outbound(draft, case, _directory()))
