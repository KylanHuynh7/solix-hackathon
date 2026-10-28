"""Live extraction of one email: python -m backend.extract.run <email.json>"""

import json
import sys
from pathlib import Path

from contracts.schemas import Case, Email

from backend.extract.pipeline import extract_offer

CASE_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "case.json"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m backend.extract.run <email.json>", file=sys.stderr)
        return 2
    email = Email.model_validate(json.loads(Path(argv[1]).read_text()))
    case = Case.model_validate(json.loads(CASE_PATH.read_text()))
    print(extract_offer(email, case).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
