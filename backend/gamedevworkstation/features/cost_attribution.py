"""Group recorded spend without expanding the ledger through current task links."""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, FastAPI, Query

from ..usage import BILLED

if TYPE_CHECKING:
    from ..app import AppState


Grouping = Literal["task", "session", "role", "run", "model"]
GROUP_FIELDS: dict[Grouping, dict[str, str]] = {
    "task": {
        "task_id": "u.task_id",
        "task_attribution": "CASE WHEN u.task_id IS NULL THEN u.task_attribution END",
        "task_code": "CASE WHEN t.id IS NOT NULL THEN printf('Task%05d', t.num) END",
        "task_title": "t.title",
    },
    "session": {"session_id": "u.session_id", "session_title": "s.title"},
    "role": {"role": "u.role"},
    "run": {"run_id": "u.run_id"},
    "model": {"provider": "u.provider", "model": "u.model"},
}
GROUP_JOINS = {
    "task": "LEFT JOIN board_tasks AS t ON t.id = u.task_id",
    "session": "LEFT JOIN sessions AS s ON s.id = u.session_id",
}
METRICS = f"""
    COALESCE(SUM(CASE WHEN {BILLED} THEN u.cost_usd END), 0.0) AS ledger_usd,
    COALESCE(SUM(CASE WHEN u.billing = 'subscription' THEN u.cost_usd END), 0.0) AS subscription_estimated_usd,
    COALESCE(SUM(COALESCE(u.input_tokens, 0) + COALESCE(u.output_tokens, 0) +
                 COALESCE(u.cache_read_tokens, 0) + COALESCE(u.cache_write_tokens, 0)), 0) AS tokens,
    COALESCE(SUM(u.credits), 0.0) AS credits,
    COUNT(*) AS attempts,
    COUNT(CASE WHEN u.ok = 0 THEN 1 END) AS failures
"""


def register(app: FastAPI, api: APIRouter, S: "AppState") -> None:
    @api.get("/usage/attribution")
    def attribution(group_by: Grouping = "task", since: float | None = None, until: float | None = None,
                    task_id: str | None = None, session_id: str | None = None, role: str | None = None,
                    run_id: str | None = None, provider: str | None = None, model: str | None = None,
                    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=2**63 - 1)) -> dict:
        filters = (("u.ts >= ?", since), ("u.ts <= ?", until), ("u.task_id = ?", task_id),
                   ("u.session_id = ?", session_id), ("u.role = ?", role), ("u.run_id = ?", run_id),
                   ("u.provider = ?", provider), ("u.model = ?", model))
        clauses = [clause for clause, value in filters if value is not None]
        params = [value for _, value in filters if value is not None]
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        fields = GROUP_FIELDS[group_by]
        columns = ", ".join(f"{expr} AS {name}" for name, expr in fields.items())
        empty_columns = ", ".join(f"NULL AS {name}" for name in fields)
        ordering = "ledger_usd DESC, " + ", ".join(fields)

        # Read the page and the unpaginated totals against one ledger snapshot.
        totals, *rows = S.db.all(f"""
            WITH page AS (
                SELECT {columns}, {METRICS}
                FROM usage_records AS u {GROUP_JOINS.get(group_by, '')}
                {where}
                GROUP BY {', '.join(fields.values())}
                ORDER BY {ordering}
                LIMIT ? OFFSET ?
            )
            SELECT 1 AS is_total, {empty_columns}, {METRICS} FROM usage_records AS u {where}
            UNION ALL
            SELECT 0 AS is_total, page.* FROM page
            ORDER BY is_total DESC, {ordering}
        """, [*params, limit + 1, offset, *params])
        totals.pop("is_total")
        for name in fields:
            totals.pop(name)
        for row in rows:
            row.pop("is_total")
            if group_by == "model":
                row["key"] = [row["provider"], row["model"]]
        return {"group_by": group_by, "rows": rows[:limit], "totals": totals,
                "next_offset": offset + limit if len(rows) > limit else None}
