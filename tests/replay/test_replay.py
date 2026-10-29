"""N7 replay cache: record once, replay identically, never fall back to a live call."""

import json
import os

import pytest

from backend.api.demo_stub import DEMO_ORDER
from backend.extract.parsers import clean_email
from backend.extract.llm import PROMPT_VERSION as EXTRACT_PROMPT_VERSION
from backend.replay import cache
from backend.replay.extract import ReplaySpanLLM
from backend.replay.record import record
from contracts.schemas import Case

from replay_helpers import SEED, load_email, run_demo, spans_for

_RANDOM_IDS = ("draft_id", "intent_id")


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in _RANDOM_IDS}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def _actions(ledger) -> list[tuple]:
    return [(e.actor, e.action, _strip(e.payload), e.model, e.prompt_version) for e in ledger.list()]


def _seed_case() -> Case:
    return Case.model_validate_json((SEED / "case.json").read_text())


def _files(root) -> list:
    return sorted(root.rglob("*.json"))


# --- record then replay ----------------------------------------------------


@pytest.mark.asyncio
async def test_replay_matches_fake_live_run(live, set_mode, replay_dir):
    set_mode("live")
    _, live_ledger, live_drafts = await run_demo(DEMO_ORDER)
    assert len(live_drafts) == 2
    assert {e.source for e in live_ledger.list()} == {"live"}

    set_mode("record")
    await run_demo(DEMO_ORDER)

    set_mode("replay")
    live.explode = True
    calls_before = (live.extract_calls, live.agent_calls)
    store, ledger, drafts = await run_demo(DEMO_ORDER)

    assert (live.extract_calls, live.agent_calls) == calls_before
    assert _strip(drafts) == _strip(live_drafts)
    assert _actions(ledger) == _actions(live_ledger)
    assert {e.source for e in ledger.list()} == {"replay"}
    assert ledger.verify()["ok"] is True
    # The hook and propose_draft really ran again: denial, tool calls and drafts are all there.
    actions = [e.action for e in ledger.list()]
    denied = [e.payload["tool"] for e in ledger.list() if e.action == "tool_denied"]
    assert denied.count("mcp__nb__send_email") == 2
    assert actions.count("draft_proposed") == 2
    assert any(e.payload.get("tool") == "propose_draft" for e in ledger.list() if e.action == "tool_call")
    assert len(store.list_drafts("CASE-001")) == 2


@pytest.mark.asyncio
async def test_replay_of_prewritten_extract_fixture(live, set_mode):
    email = load_email("s2_offer")
    case = _seed_case()
    text = clean_email(email.body).new_text
    key = ReplaySpanLLM().key(text, case)
    cache.save(
        "extract", key, model="claude-fake-extract", prompt_version=EXTRACT_PROMPT_VERSION,
        output={"spans": spans_for("s2_offer"), "error": None},
    )

    set_mode("replay")
    live.explode = True
    llm = ReplaySpanLLM()
    assert llm.find_spans(text, case) == spans_for("s2_offer")
    assert llm.error is None

    _, ledger, drafts = await run_demo(["s2_offer"])
    assert drafts == []
    extracted = next(e for e in ledger.list() if e.action == "fields_extracted")
    assert extracted.source == "replay"
    assert extracted.payload["ndc"] is not None
    assert extracted.model == "claude-fake-extract"


# --- misses ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_miss_logs_replay_miss_and_never_calls_live(live, set_mode):
    set_mode("replay")
    live.explode = True
    store, ledger, drafts = await run_demo(["s1_offer"])

    assert drafts == []
    assert (live.extract_calls, live.agent_calls) == (0, 0)
    misses = [e for e in ledger.list() if e.action == "check_failed" and e.payload["check"] == "replay_miss"]
    assert len(misses) == 1
    assert misses[0].source == "replay"
    assert store.get_case("CASE-001").offers == []
    assert any("needs human review" in x for x in store.get_case("CASE-001").exceptions)


@pytest.mark.asyncio
async def test_agent_miss_logs_replay_miss_and_never_calls_live(live, set_mode, replay_dir):
    set_mode("record")
    await run_demo(["s1_offer"])
    for path in (replay_dir / "agents").glob("*.json"):
        path.unlink()

    set_mode("replay")
    live.explode = True
    _, ledger, drafts = await run_demo(["s1_offer"])

    assert drafts == []
    assert live.agent_calls == 1  # only the recording run
    failed = [e for e in ledger.list() if e.action == "check_failed" and e.actor == "orchestrator"]
    assert [e.payload["check"] for e in failed] == ["replay_miss"]
    assert failed[0].payload["agent"] == "negotiator"
    assert not any(e.action == "tool_call" for e in ledger.list())


def test_bad_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("NB_REPLAY", "sometimes")
    with pytest.raises(ValueError):
        cache.mode()


# --- record ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_writes_exactly_one_file_per_call(live, set_mode, replay_dir):
    set_mode("record")
    await run_demo(DEMO_ORDER)

    calls = live.extract_calls + live.agent_calls
    assert (live.extract_calls, live.agent_calls) == (3, 2)
    assert len(cache.written) == calls
    assert len(_files(replay_dir)) == calls
    assert len(list((replay_dir / "extract").glob("*.json"))) == 3
    assert len(list((replay_dir / "agents").glob("*.json"))) == 2


@pytest.mark.asyncio
async def test_record_module_returns_written_files(live, monkeypatch, replay_dir):
    monkeypatch.setenv("NB_REPLAY", "record")
    paths = await record()
    assert sorted(paths) == _files(replay_dir)
    assert len(paths) == 5


# --- secrets ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_cached_files_contain_no_key_or_env_values(live, set_mode, replay_dir, monkeypatch):
    fake_token = "fake" + "x" * 24  # built at runtime: no high-entropy literal in the file
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "0" * 24)
    monkeypatch.setenv("NB_FAKE_TOKEN", fake_token)
    set_mode("record")
    await run_demo(DEMO_ORDER)

    values = [v for v in os.environ.values() if len(v) >= 12]
    files = _files(replay_dir)
    assert files
    for path in files:
        text = path.read_text()
        json.loads(text)
        assert "sk-ant" not in text
        assert not [v for v in values if v in text], path

    # The scrubber itself refuses to write an env secret value.
    with pytest.raises(ValueError):
        cache.save("agents", "k", model="m", prompt_version="v", output={"body": f"hi {fake_token}"})
    assert len(_files(replay_dir)) == len(files)


def test_save_refuses_output_with_a_key(replay_dir):
    with pytest.raises(ValueError):
        cache.save("extract", "k", model="m", prompt_version="v", output={"x": "sk-ant-abc"})
    assert _files(replay_dir) == []
