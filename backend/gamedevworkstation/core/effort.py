"""Backend enforcement of effort limits.

Levels up to "high" are always allowed. "xhigh" and "max" need an approval token that
only the UI can mint (when the user presses Approve on an approval card). A token is
bound to the first run (subagent or chat turn) that uses it, so that run can make
many model calls at the approved level, but no other run can reuse it. Tokens expire.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

from .types import ABOVE_HIGH, EFFORT_LEVELS


class EffortApprovalRequired(PermissionError):
    """Raised when an above-high effort is requested without a valid approval token."""

    def __init__(self, effort: str):
        super().__init__(
            f"Effort '{effort}' is above 'high' and needs the user's approval. "
            "Call request_effort_approval first, then launch with the returned token."
        )
        self.effort = effort


@dataclass
class _Grant:
    approval_id: str
    effort: str
    expires: float
    bound_to: str | None = None


@dataclass
class ApprovalStore:
    ttl_s: int = 6 * 3600
    _secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    _grants: dict[str, _Grant] = field(default_factory=dict)

    def _sign(self, approval_id: str, effort: str) -> str:
        mac = hmac.new(self._secret, f"{approval_id}:{effort}".encode(), hashlib.sha256).hexdigest()[:32]
        return f"apv_{approval_id}_{mac}"

    def issue(self, approval_id: str, effort: str) -> str:
        """Only the UI approval endpoint calls this, after the user clicks Approve."""
        if effort not in EFFORT_LEVELS:
            raise ValueError(f"unknown effort {effort!r}")
        token = self._sign(approval_id, effort)
        self._grants[token] = _Grant(approval_id, effort, time.time() + self.ttl_s)
        return token

    def revoke(self, token: str) -> None:
        self._grants.pop(token, None)

    def allows(self, token: str | None, effort: str, run_id: str) -> bool:
        g = self._grants.get(token or "")
        if not g or g.expires < time.time():
            return False
        if not hmac.compare_digest(token, self._sign(g.approval_id, g.effort)):
            return False
        # A "max" approval also covers "xhigh"; not the other way round.
        if EFFORT_LEVELS.index(effort) > EFFORT_LEVELS.index(g.effort):
            return False
        if g.bound_to is None:
            g.bound_to = run_id
        return g.bound_to == run_id


APPROVALS = ApprovalStore()


def check_effort(effort: str | None, approval_token: str | None, run_id: str = "",
                 store: ApprovalStore | None = None) -> None:
    """Raise unless `effort` is allowed. Every model call goes through this."""
    if effort is None:
        return
    if effort not in EFFORT_LEVELS:
        raise ValueError(f"unknown effort level {effort!r}; use one of {', '.join(EFFORT_LEVELS)}")
    if effort in ABOVE_HIGH and not (store or APPROVALS).allows(approval_token, effort, run_id):
        raise EffortApprovalRequired(effort)
