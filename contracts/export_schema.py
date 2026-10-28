"""Write the JSON Schema of every contract model to contracts/schema.json.

Run: uv run python -m contracts.export_schema
"""

import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

from contracts.schemas import (
    AuditEvent,
    Case,
    CustomerRequirement,
    Draft,
    Email,
    Field,
    LineItem,
    Offer,
)

MODELS = [Field, Offer, LineItem, CustomerRequirement, Case, Draft, AuditEvent, Email]
OUT = Path(__file__).parent / "schema.json"


def main() -> None:
    _, schema = models_json_schema(
        [(m, "validation") for m in MODELS], title="NeuroBiz contracts"
    )
    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
