"""Offline fixtures for the N7 replay tests.

The "live" model clients are fakes: FakeLiveSpanLLM returns canned spans built from labels.json,
and fake_sdk_runner behaves like the Agent SDK (every tool request goes through the hook first,
then to the Toolbox if allowed). Both count their calls and can be switched to explode, so tests
can prove replay never makes a live call.
"""

from pathlib import Path

import pytest
from replay_helpers import CASE_ID, CONFIRMER_BODY, NEGOTIATOR_BODY, load_email, spans_for

from backend.extract.parsers import clean_email
from backend.replay import cache

_BY_TEXT = {
    clean_email(load_email(k).body).new_text: k for k in ("s1_offer", "s2_offer", "s3_offer")
}


class Live:
    """Shared call counter for the fake live clients."""

    def __init__(self) -> None:
        self.extract_calls = 0
        self.agent_calls = 0
        self.explode = False

    def check(self) -> None:
        if self.explode:
            raise AssertionError("a live model call was made in replay mode")


@pytest.fixture
def live(monkeypatch) -> Live:
    state = Live()

    class FakeLiveSpanLLM:
        model = "claude-fake-extract"

        def __init__(self, client=None) -> None:
            state.check()
            self.error = None

        def find_spans(self, new_text, case) -> dict:
            state.check()
            state.extract_calls += 1
            return spans_for(_BY_TEXT[new_text])

    async def fake_sdk_runner(run) -> None:
        state.check()
        state.agent_calls += 1
        body = NEGOTIATOR_BODY if run.agent == "negotiator" else CONFIRMER_BODY
        requests = [
            ("Agent", {"subagent_type": run.agent}),
            ("mcp__nb__get_case_summary", {}),
            ("mcp__nb__get_validation_results", {}),
            ("mcp__nb__send_email", {"to": "x@example.com"}),  # denied by the hook
            (
                "mcp__nb__propose_draft",
                {"recipient_role": run.recipient_role, "subject": f"Re: RFQ - {CASE_ID}", "body": body},
            ),
        ]
        for name, args in requests:
            data = {"tool_name": name, "tool_input": args}
            if name != "Agent":
                data["agent_type"] = run.agent
            out = await run.hook(data, None, None)
            if out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
                continue
            if name.startswith("mcp__nb__"):
                await run.toolbox.call(name.removeprefix("mcp__nb__"), args)

    monkeypatch.setattr("backend.extract.llm.AnthropicSpanLLM", FakeLiveSpanLLM)
    monkeypatch.setattr("backend.agents.orchestrator.sdk_runner", fake_sdk_runner)
    return state


@pytest.fixture(autouse=True)
def replay_dir(tmp_path, monkeypatch) -> Path:
    """Never touch the real data/replay in tests."""
    root = tmp_path / "replay"
    monkeypatch.setenv("NB_REPLAY_DIR", str(root))
    monkeypatch.delenv("NB_REPLAY", raising=False)
    monkeypatch.setattr(cache, "written", [])
    return root


@pytest.fixture
def set_mode(monkeypatch):
    def _set(value: str) -> None:
        monkeypatch.setenv("NB_REPLAY", value)

    return _set
