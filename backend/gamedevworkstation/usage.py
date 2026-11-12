"""Usage recording and spend limits.

Limits:
- `global_daily_usd`: once today's spend reaches it, every route pauses. The pause lifts by itself
  when the local day changes (checked on every `check`, no timers), when the limit is raised above
  today's spend, or when the user presses "Resume anyway" (`resume_all`), which allows another
  limit's worth of spend today.
- `session_usd`: the same for one session's total spend; "Resume anyway" (`resume_session`) allows
  another limit's worth for that session.
Only API-billed records count (billing = "api"). Claude Code sessions on the user's own Claude
subscription record billing = "subscription": their cost is the CLI's estimate, shown on the Usage
page as "Claude subscription (estimated)" and never counted against these limits.
Pausing and resuming publish `limits.paused` / `limits.resumed` (session-scoped for session limits).
"""
from __future__ import annotations

import json
import time
from typing import Any

from .config import Config
from .core.types import RateLimits, Usage
from .db import DB
from .events import EventBus


BILLING = ("api", "subscription")
# Spend that counts against the limits: API-billed records only (subscription rows are estimates).
BILLED = "billing != 'subscription'"


class BudgetExceeded(RuntimeError):
    pass


def _usd(x: float) -> str:
    return f"${x:.4f}" if 0 < x < 0.01 else f"${x:.2f}"


def _day_start() -> float:
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


class UsageTracker:
    def __init__(self, db: DB, bus: EventBus, config: Config):
        self.db, self.bus, self.config = db, bus, config
        self.paused_all = False
        self.paused_sessions: dict[str, dict] = {}
        self._day = _day_start()
        self._global_base = 0.0  # spend already let through today by "Resume anyway"
        self._session_base: dict[str, float] = {}  # same, per session

    def record(self, *, provider: str, model: str, usage: Usage, session_id: str | None = None,
               profile: str = "default", role: str = "main", run_id: str | None = None,
               effort: str | None = None, feature: str = "chat", voice: str | None = None,
               latency_ms: int = 0, ok: bool = True, error_kind: str | None = None,
               context_fill: float | None = None, rate_limits: RateLimits | None = None,
               billing: str = "api") -> dict:
        """billing: "api" (counts against the spend limits) or "subscription" (the user's own Claude
        login through the claude_code harness: cost_usd is an estimate and never counts)."""
        row: dict[str, Any] = {
            "ts": time.time(), "session_id": session_id, "provider": provider, "profile": profile,
            "model": model, "role": role, "run_id": run_id, "effort": effort, "feature": feature, "voice": voice,
            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens, "cache_write_tokens": usage.cache_write_tokens,
            "reasoning_tokens": usage.reasoning_tokens, "characters": usage.characters, "credits": usage.credits,
            "cost_usd": usage.cost_usd, "latency_ms": latency_ms, "ok": int(ok), "error_kind": error_kind,
            "context_fill": context_fill,
            "rate_limits": json.dumps(rate_limits.model_dump(exclude_none=True)) if rate_limits else None,
            "billing": billing if billing in BILLING else "api",
        }
        row["id"] = self.db.insert("usage_records", row)
        self.bus.publish("usage.recorded", row, session_id)
        self._enforce(session_id)
        return row

    # ------------------------------------------------------------------ limits

    def spent_today(self) -> float:
        r = self.db.one(f"SELECT COALESCE(SUM(cost_usd),0) AS c FROM usage_records WHERE ts >= ? AND {BILLED}", [_day_start()])
        return r["c"]

    def spent_session(self, sid: str) -> float:
        r = self.db.one(f"SELECT COALESCE(SUM(cost_usd),0) AS c FROM usage_records WHERE session_id=? AND {BILLED}", [sid])
        return r["c"]

    def spent_run(self, run_id: str) -> float:
        r = self.db.one(f"SELECT COALESCE(SUM(cost_usd),0) AS c FROM usage_records WHERE run_id=? AND {BILLED}", [run_id])
        return r["c"]

    def _roll_day(self) -> None:
        """A new local day lifts the daily pause and forgets yesterday's "Resume anyway"."""
        d = _day_start()
        if d == self._day:
            return
        self._day = d
        self._global_base = 0.0
        if self.paused_all:
            self.paused_all = False
            self.bus.publish("limits.resumed", {"scope": "global", "reason": "new_day"})

    def global_info(self) -> dict:
        g = float(self.config.limits.get("global_daily_usd") or 0)
        spent = self.spent_today()
        return {"scope": "global", "limit_usd": g, "spent_usd": round(spent, 4),
                "allowed_usd": round(g + self._global_base, 4) if g else None, "resumed": self._global_base > 0,
                "reason": f"Daily spend limit reached: {_usd(spent)} of {_usd(g)} today."}

    def session_info(self, sid: str) -> dict:
        s = float(self.config.limits.get("session_usd") or 0)
        spent = self.spent_session(sid)
        base = self._session_base.get(sid, 0.0)
        return {"scope": "session", "session_id": sid, "limit_usd": s, "spent_usd": round(spent, 4),
                "allowed_usd": round(s + base, 4) if s else None, "resumed": base > 0,
                "reason": f"Session spend limit reached: {_usd(spent)} of {_usd(s)} in this session."}

    def _sync_global(self) -> bool:
        """Re-evaluate the daily pause and publish when it changes. Returns whether it is paused."""
        self._roll_day()
        g = float(self.config.limits.get("global_daily_usd") or 0)
        over = bool(g) and self.spent_today() >= g + self._global_base
        if over and not self.paused_all:
            self.paused_all = True
            self.bus.publish("limits.paused", self.global_info())
        elif not over and self.paused_all:
            self.paused_all = False
            self.bus.publish("limits.resumed", {"scope": "global", "reason": "limit_raised"})
        return over

    def _sync_session(self, sid: str) -> bool:
        s = float(self.config.limits.get("session_usd") or 0)
        over = bool(s) and self.spent_session(sid) >= s + self._session_base.get(sid, 0.0)
        if over and sid not in self.paused_sessions:
            self.paused_sessions[sid] = info = self.session_info(sid)
            self.bus.publish("limits.paused", info, sid)
        elif not over and sid in self.paused_sessions:
            self.paused_sessions.pop(sid, None)
            self.bus.publish("limits.resumed", {"scope": "session", "session_id": sid, "reason": "limit_raised"}, sid)
        return over

    def _enforce(self, sid: str | None) -> None:
        self._sync_global()
        if sid:
            self._sync_session(sid)

    def status(self) -> dict:
        """Current pauses for the UI banner (re-evaluated, so a new day or a raised limit lifts them)."""
        self._sync_global()
        for sid in list(self.paused_sessions):
            self._sync_session(sid)
        return {"global": self.global_info() if self.paused_all else None,
                "sessions": {sid: self.session_info(sid) for sid in self.paused_sessions}}

    def check(self, sid: str | None = None, run_id: str | None = None, run_cap: float | None = None) -> None:
        """Raise before starting any paid call if a limit has been hit."""
        lim = self.config.limits
        if self._sync_global():
            g = float(lim.get("global_daily_usd") or 0)
            raise BudgetExceeded(f"Daily spend limit ({_usd(g)}) reached; all agents are paused. "
                                 "Raise it in Settings, press Resume anyway, or wait until tomorrow.")
        if sid and self._sync_session(sid):
            s = float(lim.get("session_usd") or 0)
            raise BudgetExceeded(f"Session spend limit ({_usd(s)}) reached for this session. "
                                 "Raise it in Settings or press Resume anyway.")
        if run_id and run_cap and self.spent_run(run_id) >= run_cap:
            raise BudgetExceeded(f"Subagent spend cap (${run_cap:.2f}) reached.")

    def headroom(self, sid: str | None = None, run_id: str | None = None,
                 run_cap: float | None = None) -> float | None:
        """Dollars that may still be spent before a limit pauses this work: the smallest of the
        session allowance (incl. "Resume anyway"), the daily allowance (incl. its resume allowance)
        and the run cap. None when no limit applies. Can be <= 0 (already over)."""
        self._roll_day()
        lefts: list[float] = []
        g = float(self.config.limits.get("global_daily_usd") or 0)
        if g:
            lefts.append(g + self._global_base - self.spent_today())
        if sid:
            s = float(self.config.limits.get("session_usd") or 0)
            if s:
                lefts.append(s + self._session_base.get(sid, 0.0) - self.spent_session(sid))
        if run_id and run_cap:
            lefts.append(run_cap - self.spent_run(run_id))
        return min(lefts) if lefts else None

    def resume_all(self) -> None:
        """"Resume anyway": allow another daily limit's worth of spend today. No-op when not paused."""
        if not self._sync_global():
            return
        self._global_base = max(self.spent_today(), self._global_base)
        self.paused_all = False
        self.bus.publish("limits.resumed", {"scope": "global", "reason": "user"})

    def resume_session(self, sid: str) -> None:
        """"Resume anyway" for one session: allow another session limit's worth. No-op when not paused."""
        if not self._sync_session(sid):
            return
        self._session_base[sid] = self.spent_session(sid)
        self.paused_sessions.pop(sid, None)
        self.bus.publish("limits.resumed", {"scope": "session", "session_id": sid, "reason": "user"}, sid)
