"""Fetch the Wegovy and Rybelsus package NDCs from openFDA into data/seed/openfda_cache.json.

Run by a human only (network access): uv run python data/seed/fetch_ndcs.py
"""

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.fda.gov/drug/ndc.json"
CACHE = Path(__file__).parent / "openfda_cache.json"


def search(brand: str) -> list[dict]:
    query = urllib.parse.urlencode({"search": f'brand_name:"{brand}"', "limit": 20})
    with urllib.request.urlopen(f"{API}?{query}", timeout=30) as resp:
        return json.load(resp).get("results", [])


def strengths(product: dict) -> str:
    return ", ".join(
        f"{i.get('name', '?')} {i.get('strength', '?')}"
        for i in product.get("active_ingredients", [])
    )


def pick_wegovy(results: list[dict]) -> dict | None:
    injections = [
        r for r in results
        if "INJECTION" in r.get("dosage_form", "").upper() and r.get("packaging")
    ]
    for r in injections:
        if any("2.4 mg" in i.get("strength", "") for i in r.get("active_ingredients", [])):
            return r
    return injections[0] if injections else None


def pick_rybelsus(results: list[dict]) -> dict | None:
    for r in results:
        if r.get("dosage_form", "").upper() == "TABLET" and r.get("packaging"):
            return r
    return None


def entry(product: dict, fetched_at: str) -> dict:
    package = product["packaging"][0]
    return {
        "product_ndc": product.get("product_ndc"),
        "package_ndc": package["package_ndc"],
        "brand_name": product.get("brand_name"),
        "generic_name": product.get("generic_name"),
        "dosage_form": product.get("dosage_form"),
        "route": product.get("route"),
        "active_ingredients": product.get("active_ingredients"),
        "package_description": package.get("description"),
        "fetched_at": fetched_at,
    }


def main() -> int:
    fetched_at = datetime.now(timezone.utc).isoformat()
    chosen = {
        "Wegovy": pick_wegovy(search("Wegovy")),
        "Rybelsus": pick_rybelsus(search("Rybelsus")),
    }
    missing = [brand for brand, product in chosen.items() if product is None]
    if missing:
        print(f"ERROR: no matching openFDA product for: {', '.join(missing)}", file=sys.stderr)
        return 1

    cache = {}
    for brand, product in chosen.items():
        e = entry(product, fetched_at)
        cache[e["package_ndc"]] = e
        print(f"{brand}: {e['package_ndc']} | {e['brand_name']} | {e['dosage_form']} | {strengths(product)}")

    CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
    print(f"wrote {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
