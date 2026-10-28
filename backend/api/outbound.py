"""Approve-time outbound checks on a draft before the send simulator sees it.

Uses N4's leak check (backend.validate.outbound.check_outbound) once it is merged.
"""

from collections.abc import Callable

from contracts.schemas import Case, Draft

try:  # N4: check_outbound(draft, case) -> list[str] of plain-English problems
    from backend.validate.outbound import check_outbound as _leak_check
except ImportError:  # pragma: no cover - depends on N4 being merged
    _leak_check = None


def _stub_leak_check(draft: Draft, case: Case) -> list[str]:
    # TODO(N4): replace with backend.validate leak check. This stub always passes.
    return []


LEAK_CHECK_IS_STUB = _leak_check is None
leak_check: Callable[[Draft, Case], list[str]] = _leak_check or _stub_leak_check


def check_outbound(draft: Draft, case: Case) -> list[str]:
    problems = []
    if not draft.to:
        problems.append("Draft has no recipients.")
    if not draft.body.strip():
        problems.append("Draft body is empty.")
    problems.extend(leak_check(draft, case))
    return problems
