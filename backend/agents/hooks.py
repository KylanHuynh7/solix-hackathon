"""PreToolUse allowlist hook. Fires for the main agent and every subagent."""

import re
from typing import Any

from backend.agents.tools import TOOL_NAMES
from backend.ledger import Ledger

SOURCE = "agents"
ALLOWLIST = frozenset({*TOOL_NAMES, "Agent"})
_NEEDS_HUMAN = re.compile(r"send|approve|submit|purchase|order|mail", re.IGNORECASE)


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def make_pre_tool_use(ledger: Ledger, case_id: str, subagents: frozenset[str] = frozenset()):
    """Hook callback for ClaudeAgentOptions.hooks. Agent dispatch is allowed only to `subagents`."""

    async def pre_tool_use(
        input_data: dict[str, Any], tool_use_id: str | None, context: Any
    ) -> dict[str, Any]:
        name = str(input_data.get("tool_name", ""))
        reason = None
        if name not in ALLOWLIST:
            reason = "requires human approval" if _NEEDS_HUMAN.search(name) else "tool not allowed"
        elif name == "Agent":
            target = (input_data.get("tool_input") or {}).get("subagent_type")
            if target not in subagents:
                reason = "tool not allowed"
        if reason is None:
            return {}
        ledger.append(
            case_id=case_id,
            actor=input_data.get("agent_type") or "orchestrator",
            action="tool_denied",
            source=SOURCE,
            payload={"tool": name, "reason": reason},
        )
        return _deny(reason)

    return pre_tool_use
