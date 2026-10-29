"""In-process MCP tools for the drafting agents. Read-only lookups plus propose_draft.

There is deliberately no send, approve or SAP tool: agents can only propose a draft, and
propose_draft checks it in code before it reaches the review queue.
"""

import json
import re
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from backend.ledger import Ledger
from backend.store import CaseStore
from backend.validate.checks import CheckResult, check_outbound
from contracts.schemas import Draft, DraftStatus, FieldStatus, Offer

SERVER = "nb"
SOURCE = "agents"
TOOLS = ("get_case_summary", "get_validation_results", "get_buyer_limits", "propose_draft")
TOOL_NAMES = tuple(f"mcp__{SERVER}__{t}" for t in TOOLS)
BUYER_LIMITS = Path(__file__).resolve().parent / "config" / "buyer_limits.json"
MAX_SUBJECT, MAX_BODY = 200, 4000

_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_CUR = r"(?:USD|US\$|EUR|GBP|\$|€|£)"
_MONEY = (
    re.compile(_CUR + r"\s*" + _NUM, re.IGNORECASE),
    re.compile(_NUM + r"\s*(?:USD|EUR|GBP|dollars?)\b", re.IGNORECASE),
    re.compile(_NUM + r"\s*(?:per|/)\s*(?:pen|carton|unit|tablet|syringe)s?\b", re.IGNORECASE),
)


def load_buyer_limits(path: Path = BUYER_LIMITS) -> dict:
    return json.loads(path.read_text())


def money_amounts(text: str) -> list[Decimal]:
    text = unicodedata.normalize("NFKC", text)
    found: list[Decimal] = []
    for pattern in _MONEY:
        for m in pattern.finditer(text):
            try:
                found.append(Decimal(m.group(1).replace(",", "")))
            except InvalidOperation:
                continue
    return found


def _fmt(x: Decimal) -> str:
    return f"{x:f}".rstrip("0").rstrip(".") if "." in f"{x:f}" else f"{x:f}"


def _text(payload: Any, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    return {"content": [{"type": "text", "text": text}], "is_error": is_error}


class Toolbox:
    """Tool handlers bound to one case and one drafting agent. The SDK server wraps these."""

    def __init__(
        self,
        *,
        case_id: str,
        agent: str,
        recipient_role: str,
        store: CaseStore,
        ledger: Ledger,
        directory: dict,
        offer: Offer | None = None,
        results: list[CheckResult] | None = None,
        buyer_limits: dict | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.case_id = case_id
        self.agent = agent
        self.recipient_role = recipient_role
        self.store = store
        self.ledger = ledger
        self.directory = directory
        self.offer = offer
        self.results = list(results or [])
        limits = load_buyer_limits() if buyer_limits is None else buyer_limits
        self.limits = limits.get(case_id)
        self.model = model
        self.prompt_version = prompt_version
        self.max_attempts = max_attempts
        self.attempts = 0
        self.drafts: list[Draft] = []

    def _event(self, action: str, payload: dict) -> None:
        self.ledger.append(
            case_id=self.case_id, actor=self.agent, action=action, source=SOURCE,
            payload=payload, model=self.model, prompt_version=self.prompt_version,
        )

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args if isinstance(args, dict) else {}
        logged = {k: v for k, v in args.items() if k != "body"}
        if "body" in args:
            logged["body_chars"] = len(str(args["body"]))
        self._event("tool_call", {"tool": name, "args": logged})
        handler = {
            "get_case_summary": self._case_summary,
            "get_validation_results": self._validation_results,
            "get_buyer_limits": self._buyer_limits,
            "propose_draft": self._propose_draft,
        }.get(name)
        if handler is None:
            return _text(f"unknown tool {name}", is_error=True)
        return handler(args)

    # --- read-only lookups ------------------------------------------------

    def _supplier(self) -> dict | None:
        sid = self.offer.supplier_id if self.offer else None
        return next((s for s in self.directory.get("suppliers", []) if s["supplier_id"] == sid), None)

    def _customer(self, customer_id: str) -> dict | None:
        return next(
            (c for c in self.directory.get("customers", []) if c["customer_id"] == customer_id), None
        )

    def _case_summary(self, _args: dict) -> dict[str, Any]:
        case = self.store.get_case(self.case_id)
        customer = self._customer(case.requirement.customer_id) or {}
        manager = customer.get("account_manager", {})
        req = case.requirement
        summary: dict[str, Any] = {
            "case_id": case.case_id,
            "state": case.state.value,
            "line_item": case.line_item.model_dump(mode="json"),
            "requirement": {
                "min_expiry": req.min_expiry.isoformat(),
                "single_lot": req.single_lot,
                "dosage_form": req.dosage_form,
                "storage_range": req.storage_range,
            },
            "sign_as": {"name": manager.get("name"), "company": "TransPharmic"},
            "recipient_role": self.recipient_role,
        }
        if self.offer is not None:
            supplier = self._supplier() or {}
            summary["offer"] = self.offer.model_dump(mode="json", exclude={"source_message_id"})
            summary["supplier"] = {
                "name": supplier.get("name"),
                "contact_name": (supplier.get("contacts") or [{}])[0].get("name"),
            }
        if self.recipient_role == "customer":
            # Customer identity is only ever shown to the agent writing to that customer.
            contact = (customer.get("contacts") or [{}])[0]
            summary["customer"] = {"name": customer.get("name"), "contact_name": contact.get("name")}
        return _text(summary)

    def _validation_results(self, _args: dict) -> dict[str, Any]:
        return _text([r.model_dump() for r in self.results])

    def _buyer_limits(self, _args: dict) -> dict[str, Any]:
        if self.limits is None:
            return _text("no buyer limits set for this case; do not mention any price", is_error=True)
        return _text(self.limits)

    # --- propose_draft ----------------------------------------------------

    def _recipients(self, case) -> list[str]:
        if self.recipient_role == "supplier":
            entry = self._supplier()
        else:
            entry = self._customer(case.requirement.customer_id)
        contacts = (entry or {}).get("contacts") or []
        return [contacts[0]["email"]] if contacts and contacts[0].get("email") else []

    def _allowed_amounts(self) -> set[Decimal]:
        allowed: set[Decimal] = set()
        if self.limits:
            # The walk-away max is never allowed in a supplier draft; only the target is.
            if self.limits.get("target_unit_price") is not None:
                allowed.add(Decimal(str(self.limits["target_unit_price"])))
        price = self.offer.unit_price if self.offer else None
        if price is not None and price.status == FieldStatus.verified and price.value is not None:
            allowed.add(Decimal(str(price.value)))
        return allowed

    def _check(self, draft: Draft, case) -> list[str]:
        problems = [r.reason for r in check_outbound(draft, case, self.directory) if not r.ok]
        if draft.recipient_role == "supplier":
            allowed = self._allowed_amounts()
            bad = sorted({a for a in money_amounts(f"{draft.subject}\n{draft.body}") if a not in allowed})
            if bad:
                ok = ", ".join(_fmt(a) for a in sorted(allowed)) or "none"
                problems.append(
                    "draft states amounts not set by the buyer or quoted by the supplier: "
                    + ", ".join(_fmt(a) for a in bad) + f" (allowed: {ok})"
                )
        return problems

    def _propose_draft(self, args: dict) -> dict[str, Any]:
        if self.drafts:
            return _text("a draft has already been proposed for this email; stop", is_error=True)
        if self.attempts >= self.max_attempts:
            return _text("no attempts left; a human will draft this reply", is_error=True)
        self.attempts += 1

        role, subject, body = args.get("recipient_role"), args.get("subject"), args.get("body")
        problems = []
        if role != self.recipient_role:
            problems.append(f"recipient_role must be '{self.recipient_role}' for this agent")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > MAX_SUBJECT:
            problems.append(f"subject must be 1-{MAX_SUBJECT} characters")
        if not isinstance(body, str) or not body.strip() or len(body) > MAX_BODY:
            problems.append(f"body must be 1-{MAX_BODY} characters")
        case = self.store.get_case(self.case_id)
        to = self._recipients(case)
        if not to:
            problems.append("no directory contact for this recipient")

        draft = None
        if not problems:
            draft = Draft(
                draft_id=f"DRAFT-{uuid.uuid4().hex[:8]}",
                case_id=self.case_id,
                recipient_role=self.recipient_role,
                to=to,
                cc=[],
                subject=subject.strip(),
                body=body.strip(),
                status=DraftStatus.proposed,
                created_by=self.agent,
            )
            problems = self._check(draft, case)

        if problems:
            self._event(
                "check_failed",
                {"check": "propose_draft", "reasons": problems, "attempt": self.attempts},
            )
            left = self.max_attempts - self.attempts
            return _text(
                "Draft rejected: " + "; ".join(problems)
                + (f". Revise and call propose_draft again ({left} attempt left)." if left else
                   ". No attempts left; a human will draft this reply."),
                is_error=True,
            )

        self.store.save_draft(draft)
        self.drafts.append(draft)
        self._event(
            "draft_proposed",
            {"draft_id": draft.draft_id, "recipient_role": draft.recipient_role, "subject": draft.subject},
        )
        return _text(f"Draft {draft.draft_id} proposed for human review. Nothing has been sent.")

    def sdk_server(self):
        """The in-process MCP server exposing exactly TOOLS."""
        from claude_agent_sdk import create_sdk_mcp_server, tool

        schemas: dict[str, dict] = {
            "get_case_summary": {},
            "get_validation_results": {},
            "get_buyer_limits": {},
            "propose_draft": {"recipient_role": str, "subject": str, "body": str},
        }
        descriptions = {
            "get_case_summary": "Case requirements, the supplier offer and who to sign as.",
            "get_validation_results": "Results of the code checks on the supplier offer.",
            "get_buyer_limits": "Human-set price target and maximum for this case.",
            "propose_draft": "Propose a reply draft for human review. It is checked, never sent.",
        }

        def bind(name: str):
            async def handler(args: dict[str, Any]) -> dict[str, Any]:
                return await self.call(name, args)

            return tool(name, descriptions[name], schemas[name])(handler)

        return create_sdk_mcp_server(SERVER, tools=[bind(n) for n in TOOLS])
