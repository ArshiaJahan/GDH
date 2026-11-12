"""Scheduled and recurring tasks: each run starts a new session with the task's model,
effort, folder and mode, and sends the prompt. Schedules only fire while the app runs."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from pathlib import Path
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from fastapi import APIRouter, Body, FastAPI, HTTPException

from ..core.types import ABOVE_HIGH, EFFORT_LEVELS, Message, new_id

if TYPE_CHECKING:
    from ..app import AppState


def make_trigger(schedule: str):
    s = schedule.strip()
    if s.startswith("once:"):
        when = dt.datetime.fromisoformat(s[5:])
        if when.tzinfo is None:
            when = when.astimezone()
        return DateTrigger(run_date=when)
    if s.startswith("every:"):  # every:30m / every:2h
        n, unit = int(s[6:-1]), s[-1]
        minutes = n * 60 if unit == "h" else n
        if minutes < 5:
            raise ValueError("Shortest interval is 5 minutes")
        return CronTrigger.from_crontab(f"*/{minutes} * * * *") if minutes < 60 and 60 % minutes == 0 \
            else _interval(minutes)
    return cron_trigger(s)


# Standard cron counts weekdays 0-6 from Sunday (7 is Sunday too); APScheduler 3 counts 0-6 from
# Monday, so CronTrigger.from_crontab("0 8 * * 1-5") fires Tuesday to Saturday. The weekday field is
# translated to day names, which APScheduler reads the same way cron does.
_CRON_DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
_APS_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_NAMES = {**{d: i for i, d in enumerate(_CRON_DAYS)},
              **{d: i for i, d in enumerate(["sunday", "monday", "tuesday", "wednesday", "thursday", "friday",
                                             "saturday"])}}


def _cron_day(token: str, *, end: bool = False) -> int:
    t = token.strip().lower()
    if t.isdigit():
        n = int(t)
        if not 0 <= n <= 7:
            raise ValueError(f'Weekday "{token}" is out of range (0-7, 0 and 7 are Sunday)')
        return n
    n = _DAY_NAMES.get(t)
    if n is None:
        raise ValueError(f'Weekday "{token}" not understood')
    return 7 if end and n == 0 else n  # "sat-sun" reads as Saturday to Sunday


def cron_weekdays(field: str) -> set[int]:
    """The weekdays (0 = Sunday … 6 = Saturday) a standard cron day-of-week field names."""
    days: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("Empty weekday in the list")
        rng, _, step_s = part.partition("/")
        step = 1
        if step_s:
            if not step_s.isdigit() or int(step_s) < 1:
                raise ValueError(f'Weekday step "{step_s}" not understood')
            step = int(step_s)
        if rng == "*":
            lo, hi = 0, 6
        elif "-" in rng:
            a, b = rng.split("-", 1)
            lo, hi = _cron_day(a), _cron_day(b, end=True)
            if hi < lo:
                raise ValueError(f'Weekday range "{rng}" runs backwards')
        else:
            lo = _cron_day(rng)
            hi = max(lo, 6) if step_s else lo  # "1/2" means from Monday on, every other day
        days.update(d % 7 for d in range(lo, hi + 1, step))
    return days


def cron_trigger(expr: str) -> CronTrigger:
    """A CronTrigger for a standard 5-field crontab line, with cron's weekday numbering."""
    values = expr.split()
    if len(values) != 5:
        raise ValueError(f"Wrong number of fields; got {len(values)}, expected 5")
    minute, hour, day, month, dow = values
    days = cron_weekdays(dow)
    day_of_week = "*" if len(days) == 7 else ",".join(d for d in _APS_DAYS if _CRON_DAYS.index(d) in days)
    return CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week)


def _interval(minutes: int):
    from apscheduler.triggers.interval import IntervalTrigger

    return IntervalTrigger(minutes=minutes)


class TaskScheduler:
    def __init__(self, app: "AppState"):
        self.app = app
        self.sched = AsyncIOScheduler()

    def tasks(self) -> list[dict]:
        rows = self.app.db.all("SELECT * FROM scheduled_tasks ORDER BY created_at DESC")
        for r in rows:
            r["enabled"] = bool(r["enabled"])
            job = self.sched.get_job(r["id"]) if self.sched.running else None
            r["next_run"] = job.next_run_time.timestamp() if job and job.next_run_time else None
            r["runs"] = self.app.db.all(
                "SELECT tr.*, s.title AS session_title FROM task_runs tr LEFT JOIN sessions s ON s.id = tr.session_id "
                "WHERE task_id=? ORDER BY started_at DESC LIMIT 20", [r["id"]])
        return rows

    def _schedule(self, t: dict) -> None:
        if self.sched.get_job(t["id"]):
            self.sched.remove_job(t["id"])
        if t["enabled"]:
            self.sched.add_job(self.run, make_trigger(t["schedule"]), id=t["id"], args=[t["id"]],
                               misfire_grace_time=300, coalesce=True, max_instances=1)

    def save(self, body: dict, tid: str | None = None, current_model: str | None = None) -> dict:
        try:
            make_trigger(body["schedule"])
        except Exception as e:
            raise HTTPException(400, f"Schedule not understood: {e}") from e
        if body.get("model") and body["model"] != current_model:  # the same check as PATCH /sessions
            try:
                self.app.config.resolve_known(str(body["model"]))
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        effort = body.get("effort", "low")
        if effort not in EFFORT_LEVELS or effort in ABOVE_HIGH:
            raise HTTPException(400, "Scheduled tasks run at high effort or below (nobody is there to approve more).")
        if body.get("folder") and not Path(body["folder"]).expanduser().is_dir():
            raise HTTPException(400, "Folder not found")
        row = {"name": body["name"], "prompt": body["prompt"], "schedule": body["schedule"],
               "model": self.app.config.resolve(body.get("model") or self.app.config.orchestrator.get("model")),
               "effort": effort, "folder": str(Path(body["folder"]).expanduser()) if body.get("folder") else None,
               "mode": body.get("mode", "ask"), "enabled": int(body.get("enabled", True))}
        if tid:
            self.app.db.update("scheduled_tasks", "id", tid, row)
        else:
            tid = new_id("tsk_")
            self.app.db.insert("scheduled_tasks", {"id": tid, "created_at": time.time(), **row})
        t = self.app.db.one("SELECT * FROM scheduled_tasks WHERE id=?", [tid])
        if self.sched.running:
            self._schedule(t)  # type: ignore[arg-type]
        self.app.bus.publish("tasks.updated", {"id": tid})
        return t  # type: ignore[return-value]

    def delete(self, tid: str) -> None:
        if self.sched.running and self.sched.get_job(tid):
            self.sched.remove_job(tid)
        self.app.db.execute("DELETE FROM scheduled_tasks WHERE id=?", [tid])
        self.app.bus.publish("tasks.updated", {"id": tid})

    async def run(self, tid: str) -> str:
        t = self.app.db.one("SELECT * FROM scheduled_tasks WHERE id=?", [tid])
        if not t:
            raise HTTPException(404)
        title = f"{t['name']} · {time.strftime('%b %d %H:%M')}"
        s = self.app.store.create(title=title, folder=t["folder"], model=t["model"], effort=t["effort"], mode=t["mode"],
                                  scheduled_task=tid)
        rid = new_id("run_")
        self.app.db.insert("task_runs", {"id": rid, "task_id": tid, "session_id": s["id"], "started_at": time.time(),
                                         "status": "running"})
        jid = self.app.jobs.start(s["id"], "scheduled", f"Scheduled: {t['name']}", {"task": tid, "run": rid})
        self.app.store.add_message(s["id"], Message.user(t["prompt"]))
        task = self.app.runner.start(s["id"])

        async def watch() -> None:
            status = "done"
            try:
                await task
                last = self.app.store.messages(s["id"])[-1]
                if last.meta.get("error"):
                    status = "failed"
            except Exception:  # noqa: BLE001
                status = "failed"
            self.app.db.update("task_runs", "id", rid, {"status": status, "ended_at": time.time()})
            self.app.jobs.finish(jid, status)
            self.app.bus.publish("tasks.updated", {"id": tid})

        asyncio.create_task(watch())
        self.app.bus.publish("tasks.updated", {"id": tid})
        return s["id"]

    async def astart(self) -> None:
        self.sched.start()
        for t in self.app.db.all("SELECT * FROM scheduled_tasks WHERE enabled=1"):
            try:
                self._schedule(t)
            except Exception:  # noqa: BLE001 — a bad schedule shouldn't stop the app
                pass

    async def aclose(self) -> None:
        if self.sched.running:
            self.sched.shutdown(wait=False)


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    ts = TaskScheduler(S)
    S.extensions["tasks"] = ts

    @api.get("/tasks")
    async def list_tasks() -> dict:
        running = [j for j in S.jobs.list(limit=200) if j["status"] in ("running", "queued")]
        titles = {s["id"]: s["title"] for s in S.store.list(view="all")}
        for j in running:
            j["session_title"] = titles.get(j["session_id"])
        return {"tasks": ts.tasks(), "running": running, "scheduler_running": ts.sched.running}

    @api.post("/tasks")
    async def create(body: dict = Body(...)) -> dict:
        return ts.save(body)

    @api.patch("/tasks/{tid}")
    async def update(tid: str, body: dict = Body(...)) -> dict:
        cur = S.db.one("SELECT * FROM scheduled_tasks WHERE id=?", [tid])
        if not cur:
            raise HTTPException(404)
        return ts.save({**cur, **body}, tid, current_model=cur.get("model"))

    @api.delete("/tasks/{tid}")
    async def delete(tid: str) -> dict:
        ts.delete(tid)
        return {"ok": True}

    @api.post("/tasks/{tid}/run")
    async def run_now(tid: str) -> dict:
        return {"session_id": await ts.run(tid)}
