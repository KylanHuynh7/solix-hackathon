"""ReplayRunner: records the tool calls a drafting agent made and re-issues them on replay.

Recording happens at the PreToolUse hook, which sees every tool the model asked for (allowed or
not). Replay sends each recorded call through the SAME hook and, if allowed, the SAME Toolbox,
so propose_draft checks and the tool_call / tool_denied / draft_proposed events all happen for real.
"""

import dataclasses
from typing import Any

from backend.replay import cache

COMPONENT = "agents"


def _key(run) -> str:
    from backend.agents.orchestrator import PROMPT_VERSION

    text = f"{run.agent}\n{run.recipient_role}\n{run.system_prompt}\n{run.prompt}"
    return cache.make_key(COMPONENT, run.model, PROMPT_VERSION, text)


def _denied(result: Any) -> bool:
    out = (result or {}).get("hookSpecificOutput") or {}
    return out.get("permissionDecision") == "deny"


class ReplayRunner:
    """Wraps a runner (the orchestrator's sdk_runner) with record/replay."""

    def __init__(self, inner) -> None:
        self.inner = inner

    async def __call__(self, run) -> None:
        current = cache.mode()
        if current == cache.LIVE:
            return await self.inner(run)
        key = _key(run)
        if current == cache.REPLAY:
            await self._replay(run, cache.load(COMPONENT, key)["calls"])
            return None

        calls: list[dict] = []

        async def recording_hook(input_data: dict, tool_use_id, context) -> dict:
            calls.append(
                {
                    "tool_name": input_data.get("tool_name"),
                    "tool_input": input_data.get("tool_input") or {},
                    "agent_type": input_data.get("agent_type"),
                }
            )
            return await run.hook(input_data, tool_use_id, context)

        await self.inner(dataclasses.replace(run, hook=recording_hook))
        from backend.agents.orchestrator import PROMPT_VERSION

        cache.save(COMPONENT, key, model=run.model, prompt_version=PROMPT_VERSION, output={"calls": calls})
        return None

    @staticmethod
    async def _replay(run, calls: list[dict]) -> None:
        from backend.agents.tools import SERVER

        prefix = f"mcp__{SERVER}__"
        for call in calls:
            name = str(call.get("tool_name") or "")
            args = call.get("tool_input") or {}
            input_data = {"tool_name": name, "tool_input": args}
            if call.get("agent_type"):
                input_data["agent_type"] = call["agent_type"]
            if _denied(await run.hook(input_data, None, None)):
                continue
            if name.startswith(prefix):
                await run.toolbox.call(name[len(prefix):], args)
            # An allowed "Agent" dispatch has nothing to execute: its subagent's calls follow.
