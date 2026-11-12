"""My usage: status strip, per-model cards, ElevenLabs card, comparison, delegation
savings and CSV export. Aggregation runs in Python over usage_records — fine at the
scale of one person's history."""
from __future__ import annotations

import csv
import io
import json
import time
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, FastAPI
from fastapi.responses import PlainTextResponse

from ..core.types import Usage
from ..providers.base import compute_cost
from .status import StatusChecker

if TYPE_CHECKING:
    from ..app import AppState


def _pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


# usage_records.role values written across the app: "main" (orchestrator turns and Codex CLI
# harness), "subagent" (delegated units), and the rest, which are neither: "compact" (context
# summaries), "assistant" (Skills & MCP assistant), "tool" (web search, agent-run ElevenLabs).
DELEGATED_ROLE = "subagent"
CORE_ROLES = ("main", DELEGATED_ROLE)
# Claude Code sessions on the user's own Claude login (usage_records.billing = "subscription"): the cost
# is the CLI's estimate, not money spent, so it gets its own cards and stays out of "Spent".
SUBSCRIPTION = "subscription"
SUBSCRIPTION_LABEL = "Claude subscription (estimated)"


def _sub(r: dict) -> bool:
    return (r.get("billing") or "api") == SUBSCRIPTION


def _visible_output(r: dict) -> int:
    """Output tokens minus reasoning (providers count reasoning inside output_tokens)."""
    return max(0, (r["output_tokens"] or 0) - (r["reasoning_tokens"] or 0))


class UsageQueries:
    def __init__(self, app: "AppState"):
        self.app = app

    def rows(self, f: dict[str, Any]) -> list[dict]:
        where, p = ["1=1"], []
        if f.get("since"):
            where.append("u.ts >= ?")
            p.append(float(f["since"]))
        if f.get("until"):
            where.append("u.ts <= ?")
            p.append(float(f["until"]))
        for col in ("session_id", "provider", "model"):
            if f.get(col):
                where.append(f"u.{col} = ?")
                p.append(f[col])
        if f.get("role") in CORE_ROLES:
            where.append("u.role = ?")
            p.append(f["role"])
        elif f.get("role") == "other":
            where.append(f"u.role NOT IN ({', '.join('?' for _ in CORE_ROLES)})")
            p.extend(CORE_ROLES)
        return self.app.db.all(
            "SELECT u.*, s.title AS session_title FROM usage_records u LEFT JOIN sessions s ON s.id = u.session_id "
            f"WHERE {' AND '.join(where)} ORDER BY u.ts", p)

    def models(self, f: dict[str, Any]) -> list[dict]:
        rows = [r for r in self.rows(f) if r["provider"] != "elevenlabs"]
        by: dict[tuple[str, bool], list[dict]] = defaultdict(list)
        for r in rows:
            by[(r["model"], _sub(r))].append(r)
        status = StatusChecker(self.app).model_status()
        out = []
        for (model, sub), rs in by.items():
            days: dict[str, dict] = defaultdict(lambda: {"input": 0, "output": 0, "cached": 0, "reasoning": 0,
                                                         "cache_write": 0, "cost": 0.0, "requests": 0})
            for r in rs:
                d = days[_day(r["ts"])]
                d["input"] += r["input_tokens"]
                d["output"] += _visible_output(r)
                d["reasoning"] += r["reasoning_tokens"]
                d["cached"] += r["cache_read_tokens"]
                d["cache_write"] += r["cache_write_tokens"]
                d["cost"] += r["cost_usd"]
                d["requests"] += 1
            ok = [r for r in rs if r["ok"]]
            lat = [r["latency_ms"] for r in ok if r["latency_ms"]]
            total_in = sum(r["input_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"] for r in rs)
            fills = [r["context_fill"] for r in rs if r["context_fill"] is not None]
            sessions = Counter()
            titles = {}
            for r in rs:
                if r["session_id"]:
                    sessions[r["session_id"]] += r["cost_usd"]
                    titles[r["session_id"]] = r["session_title"] or r["session_id"]
            latest_rl = next((json.loads(r["rate_limits"]) for r in reversed(rs) if r["rate_limits"]), None)
            main_cost = sum(r["cost_usd"] for r in rs if r["role"] == "main")
            total_cost = sum(r["cost_usd"] for r in rs)
            name = self.app.config.display_name(model)
            out.append({
                "key": f"{model}|{SUBSCRIPTION}" if sub else model, "billing": SUBSCRIPTION if sub else "api",
                "model": model, "display_name": f"{SUBSCRIPTION_LABEL} · {name}" if sub else name,
                "provider": rs[0]["provider"],
                "tier": self.app.config.tier_of(model),
                "status": status.get(model, {"status": "unknown"}),
                "series": [{"day": k, **v} for k, v in sorted(days.items())],
                "requests": len(rs), "errors": sum(1 for r in rs if not r["ok"]),
                "error_rate": sum(1 for r in rs if not r["ok"]) / len(rs),
                "rate_limit_rate": sum(1 for r in rs if r["error_kind"] == "rate_limit") / len(rs),
                "latency_p50": _pct(lat, 50), "latency_p95": _pct(lat, 95),
                "cache_hit_rate": (sum(r["cache_read_tokens"] for r in rs) / total_in) if total_in else 0,
                "effort": dict(Counter(r["effort"] or "default" for r in rs)),
                "avg_context_fill": (sum(fills) / len(fills)) if fills else None,
                "share_main": (main_cost / total_cost) if total_cost else
                (sum(1 for r in rs if r["role"] == "main") / len(rs)),
                "cost": total_cost,
                # Same split as the daily series: "output" is visible output, reasoning is shown on its
                # own (providers bill it as output; output + reasoning = billed output tokens).
                "tokens": {"input": sum(r["input_tokens"] for r in rs), "output": sum(_visible_output(r) for r in rs),
                           "cached": sum(r["cache_read_tokens"] for r in rs),
                           "reasoning": sum(r["reasoning_tokens"] for r in rs)},
                "top_sessions": [{"session_id": s, "title": titles[s], "cost": c} for s, c in sessions.most_common(5)],
                "rate_limits": latest_rl,
            })
        return sorted(out, key=lambda m: m["cost"], reverse=True)

    def elevenlabs_quotas(self) -> list[dict]:
        """The subscription (credits used / left) of every configured ElevenLabs profile, in
        profile order. The subscription is re-read after generations (ElevenLabsService.refresh_quota)
        as well as by the 15-minute auth check; whichever ran last stamped subscription_checked_at."""
        rows = {r["profile"]: r for r in self.app.db.all(
            "SELECT profile, extra, status, checked_at FROM auth_status WHERE provider='elevenlabs'")}
        out = []
        for prof in self.app.config.profiles("elevenlabs"):
            st = rows.get(prof)
            extra = json.loads(st["extra"]) if st else {}
            quota = extra.get("subscription")
            checked = (extra.get("subscription_checked_at") or st["checked_at"]) if quota else None
            out.append({"profile": prof, "quota": quota, "status": st["status"] if st else "unknown",
                        "quota_checked_at": checked})
        return out

    def elevenlabs(self, f: dict[str, Any], profile: str | None = None) -> dict:
        rows = [r for r in self.rows({**f, "provider": "elevenlabs"})]
        by_day: dict[str, dict] = defaultdict(lambda: {"characters": 0, "credits": 0.0})
        by_feature: Counter = Counter()
        by_voice: Counter = Counter()
        for r in rows:
            d = by_day[_day(r["ts"])]
            d["characters"] += r["characters"]
            d["credits"] += r["credits"]
            by_feature[r["feature"] or "other"] += r["credits"] or r["characters"]
            if r["voice"]:
                by_voice[r["voice"]] += r["credits"] or r["characters"]
        # One account's quota (the picked profile, else the first), never "whichever row was checked
        # last", which could label account A's credits as fresh right after generating on B.
        quotas = self.elevenlabs_quotas()
        shown = next((q for q in quotas if q["profile"] == profile), quotas[0] if quotas else None) or {
            "profile": profile, "quota": None, "quota_checked_at": None, "status": "unknown"}
        return {"series": [{"day": k, **v} for k, v in sorted(by_day.items())],
                "by_feature": [{"feature": k, "amount": v} for k, v in by_feature.most_common()],
                "by_voice": [{"voice": k, "amount": v} for k, v in by_voice.most_common(10)],
                "profile": shown["profile"], "quota": shown["quota"], "quota_checked_at": shown["quota_checked_at"],
                "status": shown["status"], "quotas": quotas,
                "total_characters": sum(r["characters"] for r in rows),
                "total_credits": sum(r["credits"] for r in rows)}

    def delegation_stats(self, f: dict[str, Any]) -> list[dict]:
        """delegation_stats rows under the same filters as rows(). Every row is a delegated
        unit, so a role filter other than subagents leaves none."""
        if f.get("role") and f["role"] != DELEGATED_ROLE:
            return []
        where, p = ["1=1"], []
        if f.get("since"):
            where.append("ts >= ?")
            p.append(float(f["since"]))
        if f.get("until"):
            where.append("ts <= ?")
            p.append(float(f["until"]))
        for col in ("session_id", "provider", "model"):
            if f.get(col):
                where.append(f"{col} = ?")
                p.append(f[col])
        return self.app.db.all(f"SELECT * FROM delegation_stats WHERE {' AND '.join(where)}", p)

    def comparison(self, f: dict[str, Any]) -> list[dict]:
        rows = self.rows(f)
        stats = self.delegation_stats(f)
        out: dict[str, dict] = {}
        for r in rows:
            m = out.setdefault(r["model"], {"model": r["model"], "provider": r["provider"], "cost": 0.0, "tokens": 0,
                                            "characters": 0, "credits": 0.0,
                                            "requests": 0, "tasks": 0, "successes": 0, "by_job_type": {}})
            m["cost"] += r["cost_usd"]
            m["tokens"] += r["input_tokens"] + r["output_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"]
            m["characters"] += r["characters"] or 0  # ElevenLabs bills characters and credits, not tokens
            m["credits"] += r["credits"] or 0
            m["requests"] += 1
        for s in stats:
            m = out.setdefault(s["model"] or "?", {"model": s["model"], "provider": s["provider"], "cost": 0.0,
                                                   "tokens": 0, "characters": 0, "credits": 0.0, "requests": 0,
                                                   "tasks": 0, "successes": 0, "by_job_type": {}})
            m["tasks"] += 1
            m["successes"] += s["success"]
            jt = m["by_job_type"].setdefault(s["job_type"], {"count": 0, "cost": 0.0})
            jt["count"] += 1
            jt["cost"] += s["cost_usd"]
        for m in out.values():
            m["success_rate"] = (m["successes"] / m["tasks"]) if m["tasks"] else None
            for jt in m["by_job_type"].values():
                jt["avg_cost"] = jt["cost"] / jt["count"]
        return sorted(out.values(), key=lambda m: m["cost"], reverse=True)

    def savings(self, f: dict[str, Any]) -> dict:
        """Actual cost vs. the estimate if the orchestrator model had done all subagent
        work itself (same tokens, orchestrator prices). An estimate: a bigger model at its
        own effort would usually think more, so the real gap tends to be larger.

        Only role == "subagent" rows are re-priced. Main turns and the other roles (compact,
        assistant, tool) would cost the same either way, so they count at actual cost on both
        sides and never move "saved"."""
        orch = self.app.config.model(self.app.config.orchestrator.get("model", "claude-opus-5-5"))
        actual = estimated = delegated = other = subscription = 0.0
        for r in self.rows(f):
            if r["provider"] == "elevenlabs":
                continue
            if _sub(r):  # an estimate on the user's Claude plan, not money spent
                subscription += r["cost_usd"]
                continue
            actual += r["cost_usd"]
            if r["role"] == DELEGATED_ROLE:
                delegated += r["cost_usd"]
                u = Usage(input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
                          cache_read_tokens=r["cache_read_tokens"], cache_write_tokens=r["cache_write_tokens"])
                estimated += compute_cost(orch, u)
            else:
                estimated += r["cost_usd"]
                if r["role"] != "main":
                    other += r["cost_usd"]
        return {"actual": actual, "estimated_without_delegation": estimated, "saved": estimated - actual,
                "delegated_actual": delegated, "other_actual": other, "orchestrator_model": orch.id,
                "subscription_estimated": subscription}


def register(app: FastAPI, api: APIRouter, S: "AppState") -> None:
    checker = StatusChecker(S)
    S.extensions["status"] = checker
    q = UsageQueries(S)

    def filters(since: float | None = None, until: float | None = None, session_id: str | None = None,
                provider: str | None = None, model: str | None = None, role: str | None = None) -> dict:
        return {"since": since, "until": until, "session_id": session_id, "provider": provider, "model": model,
                "role": role}

    @api.get("/status")
    async def status() -> dict:
        return checker.snapshot()

    @api.post("/status/refresh")
    async def refresh() -> dict:
        await checker.check_all()
        return checker.snapshot()

    @api.get("/usage/models")
    async def usage_models(since: float | None = None, until: float | None = None, session_id: str | None = None,
                           provider: str | None = None, model: str | None = None, role: str | None = None) -> list:
        return q.models(filters(since, until, session_id, provider, model, role))

    @api.get("/usage/elevenlabs")
    async def usage_el(since: float | None = None, until: float | None = None, session_id: str | None = None,
                       profile: str | None = None) -> dict:
        return q.elevenlabs(filters(since, until, session_id), profile)

    @api.get("/usage/comparison")
    async def usage_cmp(since: float | None = None, until: float | None = None, session_id: str | None = None,
                        provider: str | None = None, model: str | None = None, role: str | None = None) -> list:
        return q.comparison(filters(since, until, session_id, provider, model, role))

    @api.get("/usage/savings")
    async def usage_savings(since: float | None = None, until: float | None = None, session_id: str | None = None,
                            provider: str | None = None, model: str | None = None, role: str | None = None) -> dict:
        return q.savings(filters(since, until, session_id, provider, model, role))

    @api.get("/usage/session/{sid}")
    async def usage_session(sid: str) -> dict:
        rows = q.rows({"session_id": sid})
        per: dict[str, dict] = {}
        for r in rows:
            key = f"{r['model']}|{SUBSCRIPTION}" if _sub(r) else r["model"]
            m = per.setdefault(key, {"model": r["model"], "billing": SUBSCRIPTION if _sub(r) else "api",
                                     "input": 0, "output": 0, "cached": 0,
                                     "reasoning": 0, "characters": 0, "credits": 0.0, "cost": 0.0,
                                     "requests": 0})
            m["input"] += r["input_tokens"] + r["cache_write_tokens"]
            m["output"] += r["output_tokens"]
            m["cached"] += r["cache_read_tokens"]
            m["reasoning"] += r["reasoning_tokens"]
            m["characters"] += r["characters"]
            m["credits"] += r["credits"] or 0
            m["cost"] += r["cost_usd"]
            m["requests"] += 1
        return {"models": list(per.values()),
                "total_cost": sum(m["cost"] for m in per.values() if m["billing"] != SUBSCRIPTION),
                "subscription_estimated": sum(m["cost"] for m in per.values() if m["billing"] == SUBSCRIPTION)}

    @api.get("/usage/export.csv")
    async def export_csv(since: float | None = None, until: float | None = None, session_id: str | None = None,
                         provider: str | None = None, model: str | None = None, role: str | None = None):
        rows = q.rows(filters(since, until, session_id, provider, model, role))
        buf = io.StringIO()
        cols = ["ts", "session_id", "session_title", "provider", "profile", "model", "role", "run_id", "effort",
                "feature", "voice", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                "reasoning_tokens", "characters", "credits", "cost_usd", "latency_ms", "ok", "error_kind",
                "context_fill", "billing"]
        w = csv.writer(buf)
        w.writerow(["time", *cols[1:]])
        for r in rows:
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])), *[r.get(c) for c in cols[1:]]])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"content-disposition": 'attachment; filename="gamedevworkstation-usage.csv"'})
