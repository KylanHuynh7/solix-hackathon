import pytest

from backend.agents.hooks import make_pre_tool_use
from conftest import CASE_ID


@pytest.fixture
def hook(ledger):
    return make_pre_tool_use(ledger, CASE_ID, frozenset({"negotiator"}))


def _decision(out):
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    return spec["permissionDecision"], spec["permissionDecisionReason"]


def _denied(ledger):
    return [e for e in ledger.list(CASE_ID) if e.action == "tool_denied"]


@pytest.mark.asyncio
async def test_send_email_requires_human_approval(hook, ledger):
    out = await hook({"tool_name": "mcp__nb__send_email", "tool_input": {}}, "t1", None)

    assert _decision(out) == ("deny", "requires human approval")
    denied = _denied(ledger)
    assert len(denied) == 1
    assert denied[0].payload == {"tool": "mcp__nb__send_email", "reason": "requires human approval"}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["approve_purchase_order", "mcp__nb__submit_po", "SendMail"])
async def test_approve_like_names_require_human_approval(hook, ledger, name):
    out = await hook({"tool_name": name, "tool_input": {}}, "t1", None)
    assert _decision(out) == ("deny", "requires human approval")
    assert _denied(ledger)[0].payload["tool"] == name


@pytest.mark.asyncio
async def test_bash_is_not_allowed(hook, ledger):
    out = await hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, "t1", None)

    assert _decision(out) == ("deny", "tool not allowed")
    assert _denied(ledger)[0].payload == {"tool": "Bash", "reason": "tool not allowed"}


@pytest.mark.asyncio
async def test_propose_draft_is_allowed(hook, ledger):
    out = await hook({"tool_name": "mcp__nb__propose_draft", "tool_input": {}}, "t1", None)
    assert out == {}
    assert _denied(ledger) == []


@pytest.mark.asyncio
async def test_agent_dispatch_allowed_only_to_named_subagent(hook, ledger):
    ok = await hook({"tool_name": "Agent", "tool_input": {"subagent_type": "negotiator"}}, "t1", None)
    assert ok == {}
    assert _denied(ledger) == []

    bad = await hook({"tool_name": "Agent", "tool_input": {"subagent_type": "general-purpose"}}, "t2", None)
    assert _decision(bad) == ("deny", "tool not allowed")
    assert len(_denied(ledger)) == 1


@pytest.mark.asyncio
async def test_agent_dispatch_without_subagent_type_is_denied(hook):
    out = await hook({"tool_name": "Agent", "tool_input": {}}, "t1", None)
    assert _decision(out) == ("deny", "tool not allowed")


@pytest.mark.asyncio
async def test_denial_records_calling_subagent(hook, ledger):
    await hook({"tool_name": "Bash", "tool_input": {}, "agent_type": "negotiator"}, "t1", None)
    assert _denied(ledger)[0].actor == "negotiator"
