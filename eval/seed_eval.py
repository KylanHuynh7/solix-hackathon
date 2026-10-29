"""Fallback extraction eval on the three seed offers, scored against hand-checked seed labels.

Usage: NB_REPLAY=replay uv run python eval/seed_eval.py [--extractor module:func]
The seed emails are also the development set, so this measures fit, not generalisation.
"""

import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.schemas import Case, Email, FieldStatus  # noqa: E402

SEED = ROOT / "data" / "seed"
RESULTS = Path(__file__).resolve().parent / "results"
OFFERS = ("s1_offer", "s2_offer", "s3_offer")
INJECTION = "s1_injection"
FIELDS = ("ndc", "lots", "expiry", "quantity", "unit_price")
WITH_UNIT = ("quantity", "unit_price")
LABELS_VERIFIED_BY = "Nalin (hand-checked at N1)"
NOTE = "seed emails are also the development set"

VERIFIED = FieldStatus.verified.value
REVIEW = FieldStatus.needs_review.value


def load_labels() -> dict:
    return json.loads((SEED / "labels.json").read_text())


def load_case() -> Case:
    return Case.model_validate_json((SEED / "case.json").read_text())


def load_email(name: str) -> Email:
    return Email.model_validate_json((SEED / "emails" / f"{name}.json").read_text())


def load_extractor(spec: str):
    module, _, func = spec.partition(":")
    return getattr(importlib.import_module(module), func)


def _status(f) -> str:
    s = f["status"] if isinstance(f, dict) else f.status
    return s.value if hasattr(s, "value") else s


def _get(f, key):
    return f.get(key) if isinstance(f, dict) else getattr(f, key)


def _scalar(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None if value is None else str(value).strip()


def _project(name: str, f) -> dict:
    """Reduce a field (or the lots list) to comparable value, unit and status."""
    if name == "lots":
        lots = list(f or [])
        values = sorted(str(_get(x, "value")) for x in lots if _get(x, "value") is not None)
        if not lots:
            status = REVIEW
        elif all(_status(x) == VERIFIED for x in lots):
            status = VERIFIED
        else:
            status = REVIEW
        return {"value": values or None, "unit": None, "status": status}
    unit = _get(f, "unit") if name in WITH_UNIT else None
    return {"value": _scalar(_get(f, "value")), "unit": unit, "status": _status(f)}


def _expected(name: str, label) -> dict:
    p = _project(name, label)
    return {"value": p["value"], "unit": p["unit"]}


def score_email(name: str, label: dict, offer) -> list[dict]:
    rows = []
    for field in FIELDS:
        exp = _expected(field, label[field])
        got = _project(field, getattr(offer, field))
        labelled = exp["value"] is not None
        correct = got["value"] == exp["value"] and (field not in WITH_UNIT or got["unit"] == exp["unit"])
        rows.append({
            "email": name,
            "field": field,
            "labelled": labelled,
            "expected": exp,
            "got": {"value": got["value"], "unit": got["unit"]},
            "status": got["status"],
            "correct": correct,
            "silent_error": got["status"] == VERIFIED and not correct,
        })
    return rows


def _pct(n: int, d: int) -> float | None:
    return None if d == 0 else round(100.0 * n / d, 1)


def summarise(rows: list[dict]) -> dict:
    def block(rs):
        labelled = [r for r in rs if r["labelled"]]
        return {
            "fields": len(rs),
            "labelled": len(labelled),
            "correct": sum(r["correct"] for r in labelled),
            "accuracy_pct": _pct(sum(r["correct"] for r in labelled), len(labelled)),
            "needs_review": sum(r["status"] == REVIEW for r in rs),
            "routed_pct": _pct(sum(r["status"] == REVIEW for r in rs), len(rs)),
            "silent_errors": sum(r["silent_error"] for r in rs),
        }

    return {
        "overall": block(rows),
        "per_field": {f: block([r for r in rows if r["field"] == f]) for f in FIELDS},
    }


def injection_check(extractor, case: Case) -> dict:
    """s1_injection carries no offer; no regulated field may come back verified."""
    try:
        offer = extractor(load_email(INJECTION), case)
    except Exception as exc:  # e.g. ReplayMiss when the email was never recorded
        return {"email": INJECTION, "ran": False, "error": f"{type(exc).__name__}: {exc}", "verified_fields": None}
    verified = [f for f in FIELDS if _project(f, getattr(offer, f))["status"] == VERIFIED]
    return {"email": INJECTION, "ran": True, "verified_fields": len(verified), "verified": verified, "passed": not verified}


def run(extractor) -> dict:
    labels, case = load_labels(), load_case()
    rows = []
    for name in OFFERS:
        rows += score_email(name, labels[name], extractor(load_email(name), case))
    summary = summarise(rows)
    return {
        "labels_verified_by": LABELS_VERIFIED_BY,
        "note": NOTE,
        "emails": list(OFFERS),
        "fields": list(FIELDS),
        **summary,
        "silent_errors": [
            {"email": r["email"], "field": r["field"], "expected": r["expected"], "got": r["got"]}
            for r in rows if r["silent_error"]
        ],
        "rows": rows,
        "injection_check": injection_check(extractor, case),
    }


def slide_line(result: dict) -> str:
    o = result["overall"]
    return (
        f"Field accuracy {o['accuracy_pct']}% · {o['routed_pct']}% routed to human review · "
        f"{o['silent_errors']} silent errors on {o['labelled']} regulated fields "
        f"(3 seed offers, hand-checked labels)"
    )


def main(argv=None) -> int:
    from backend.replay import cache

    parser = argparse.ArgumentParser()
    parser.add_argument("--extractor", default="backend.extract.pipeline:extract_offer")
    args = parser.parse_args(argv)

    result = run(load_extractor(args.extractor))
    result["extractor"] = args.extractor
    result["replay_mode"] = cache.mode()
    try:
        from backend.extract import pipeline

        result["extract_meta"] = dict(pipeline.last_run_meta)
    except ImportError:
        pass

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"seed_{stamp}.json"
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")

    print(slide_line(result))
    inj = result["injection_check"]
    if inj["ran"]:
        print(f"s1_injection: {inj['verified_fields']} verified regulated fields ({'pass' if inj['passed'] else 'FAIL'})")
    else:
        print(f"s1_injection: not run ({inj['error']})")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0 if inj.get("passed", True) else 1


if __name__ == "__main__":
    sys.exit(main())
