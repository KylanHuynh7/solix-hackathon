"""Record the demo: python -m backend.replay.record

Runs the seed emails in DEMO_ORDER through the real process_email (live model calls) on a fresh
in-memory store and ledger, writing each model output to data/replay/ for NB_REPLAY=replay.
"""

import asyncio
import os

from backend.replay import cache


async def record() -> list:
    from backend.agents import process_email
    from backend.api.demo_stub import DEMO_ORDER, load_demo_email
    from backend.ledger import InMemoryLedger
    from backend.store import InMemoryCaseStore, load_seed_case

    store, ledger = InMemoryCaseStore(), InMemoryLedger()
    case_id = load_seed_case().case_id
    start = len(cache.written)
    for key in DEMO_ORDER:
        result = await process_email(load_demo_email(key), case_id, store=store, ledger=ledger)
        print(f"{key}: {len(result['drafts'])} draft(s), {len(result['exceptions'])} exception(s)")
    failures = [e for e in ledger.list() if e.action == "check_failed" and e.actor == "orchestrator"]
    for e in failures:
        print(f"WARNING agent failure: {e.payload}")
    return cache.written[start:]


def main() -> None:
    os.environ["NB_REPLAY"] = cache.RECORD
    paths = asyncio.run(record())
    print(f"wrote {len(paths)} replay file(s):")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
