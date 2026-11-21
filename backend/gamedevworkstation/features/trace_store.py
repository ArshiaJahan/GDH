"""Keep trace I/O off the turn path and outside the application ledger.

For Phoenix, point otlp_endpoint at a Collector's OTLP/HTTP JSON receiver (its full
/v1/traces URL) and configure the Collector to forward via OTLP/HTTP protobuf.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import NamedTuple
from urllib.parse import urlsplit

import httpx

from .. import config

log = logging.getLogger(__name__)

QUEUE_SIZE = 2_048
BATCH_SIZE = 128
MAX_SPANS = 100_000
RESPONSE_BYTES = 16_384
SHUTDOWN_S = 1.0
DAY_NS = 86_400 * 10**9
_RETRYABLE = {429, 502, 503, 504}
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_TRANSPORT_HEADERS = {"accept-encoding", "connection", "content-encoding", "content-length",
                      "content-type", "host", "transfer-encoding"}


class TraceRow(NamedTuple):
    trace_id: str
    span_id: str
    parent_span_id: str | None
    session_id: str | None
    run_id: str | None
    name: str
    category: str
    kind: int
    start_ns: int
    end_ns: int
    status: int
    attrs_json: str
    dropped_attributes: int


# Append migrations so older trace files can be opened without changing the application DB.
MIGRATIONS = [(1, (
    """CREATE TABLE trace_spans (
        trace_id TEXT NOT NULL, span_id TEXT NOT NULL, parent_span_id TEXT,
        session_id TEXT, run_id TEXT, name TEXT NOT NULL, category TEXT NOT NULL,
        kind INTEGER NOT NULL, start_ns INTEGER NOT NULL, end_ns INTEGER NOT NULL,
        status INTEGER NOT NULL, attrs_json TEXT NOT NULL, dropped_attributes INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (trace_id, span_id)
    )""",
    "CREATE INDEX trace_spans_session ON trace_spans(session_id, start_ns, span_id)",
    "CREATE INDEX trace_spans_expiry ON trace_spans(end_ns)",
    "CREATE INDEX trace_spans_root ON trace_spans(start_ns, span_id) WHERE parent_span_id IS NULL",
    "CREATE INDEX trace_spans_order ON trace_spans(trace_id, start_ns, span_id)",
))]
_INSERT = (f"INSERT INTO trace_spans ({', '.join(TraceRow._fields)}) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")


def _path() -> Path:
    return config.data_dir() / "traces.sqlite3"


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > MIGRATIONS[-1][0]:
        raise sqlite3.DatabaseError("unsupported trace schema")
    for target, statements in MIGRATIONS:
        if version < target:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("PRAGMA user_version").fetchone()[0] >= target:
                    continue
                for statement in statements:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version={target}")


def _endpoint(value: object) -> str | None:
    # Reject parser ambiguities before giving a URL and auth headers to HTTPX.
    if type(value) is not str or not value or re.search(r"[\s\x00-\x1f\x7f\\?#]", value):
        return None
    try:
        url = urlsplit(value)
        host = url.hostname
        if not host or "@" in url.netloc or "%" in url.netloc or url.port == 0:
            return None
        parsed = httpx.URL(value)
        if parsed.userinfo or parsed.scheme != url.scheme:
            return None
        if parsed.scheme == "https" and parsed.host:
            return value
        if parsed.scheme == "http" and parsed.host == host:
            if host in {"localhost", "localhost."} or ip_address(host).is_loopback:
                return value
    except (ValueError, httpx.InvalidURL):
        pass
    return None


def _headers(names: dict) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
    for name, env in names.items():
        if (type(name) is str and _HEADER_NAME.fullmatch(name) and name.lower() not in _TRANSPORT_HEADERS
                and type(env) is str and _ENV_NAME.fullmatch(env)):
            if value := os.environ.get(env):
                headers[name] = value
    return headers


def _any_value(value):
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"arrayValue": {"values": [_any_value(item) for item in value]}}


def _otlp_json(batch: list[TraceRow]) -> dict:
    spans = []
    for row in batch:
        span = {"traceId": row.trace_id, "spanId": row.span_id, "name": row.name, "kind": row.kind,
                "startTimeUnixNano": str(row.start_ns), "endTimeUnixNano": str(row.end_ns),
                "status": {"code": row.status}, "droppedAttributesCount": row.dropped_attributes,
                "attributes": [{"key": key, "value": _any_value(value)}
                               for key, value in json.loads(row.attrs_json).items()]}
        if row.parent_span_id is not None:
            span["parentSpanId"] = row.parent_span_id
        spans.append(span)
    return {"resourceSpans": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "gamedevworkstation"}}]},
        # OpenTelemetry GenAI semantic conventions v0.1.0 (including MCP).
        "scopeSpans": [{"scope": {"name": "gamedevworkstation.gen_ai", "version": "0.1.0"}, "spans": spans}],
    }]}


def _retry_delay(retry_after: str) -> float:
    try:
        if retry_after.isdecimal():
            return float(retry_after)
        delay = parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)
        return max(0.0, delay.total_seconds())
    except (ValueError, TypeError, OverflowError):
        return random.uniform(0.05, 0.15)


async def _send(client: httpx.AsyncClient, endpoint: str, payload: dict, headers: dict,
                batch_size: int, timeout: float) -> int:
    """Return rejected spans, keeping body text and header values out of diagnostics."""
    for attempt in range(2):
        retry_after = ""
        try:
            async with asyncio.timeout(timeout):
                async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                    if response.status_code == 200:
                        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                            return batch_size
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=RESPONSE_BYTES):
                            if len(body) + len(chunk) > RESPONSE_BYTES:
                                return batch_size
                            body.extend(chunk)
                        reply = json.loads(body.decode("utf-8")) if body else {}
                        partial = reply.get("partialSuccess") or {}
                        rejected = partial.get("rejectedSpans") or 0
                        return max(0, min(batch_size, int(rejected)))
                    if response.status_code not in _RETRYABLE:
                        return batch_size
                    retry_after = response.headers.get("Retry-After", "")
        except (httpx.TransportError, TimeoutError):
            pass  # The receiver may have accepted the batch. Keep the same span IDs on retry.
        if attempt == 0:
            delay = _retry_delay(retry_after)
            if delay > timeout:
                break
            await asyncio.sleep(delay)
    return batch_size


def _batch(queue: Queue[TraceRow], stopping: bool) -> list[TraceRow]:
    batch = []
    try:
        batch.append(queue.get(block=not stopping, timeout=0.05 if not stopping else None))
        while len(batch) < BATCH_SIZE:
            batch.append(queue.get_nowait())
    except Empty:
        pass
    return batch


class TraceStore:
    def __init__(self, settings: dict):
        self.enabled = settings.get("enabled", True) is True
        self._endpoint = _endpoint(settings.get("otlp_endpoint"))
        names = settings.get("otlp_headers_env")
        self._header_names = dict(names) if isinstance(names, dict) else {}
        timeout = settings.get("otlp_timeout_s", 2.0)
        self._timeout = float(timeout) if type(timeout) in (int, float) and 0 < timeout < math.inf else 2.0
        days = settings.get("retention_days", 7)
        self._retention_ns = (days if type(days) is int and days > 0 else 7) * DAY_NS
        cap = settings.get("max_spans", MAX_SPANS)
        self._max_spans = min(cap, MAX_SPANS) if type(cap) is int and cap > 0 else MAX_SPANS
        self._queue: Queue[TraceRow] = Queue(QUEUE_SIZE)
        self._export_queue: Queue[TraceRow] = Queue(QUEUE_SIZE)
        self._ready = Event()
        self._stopping = Event()
        self._export_stop = Event()
        self._writer: Thread | None = None
        self._exporter: Thread | None = None
        self._export_task: tuple[asyncio.AbstractEventLoop, asyncio.Task] | None = None
        self._drain_until = 0.0
        self.accepting = False
        self._diagnostic = "invalid_export_endpoint" if settings.get("otlp_endpoint") and not self._endpoint else None
        self._counts = dict.fromkeys(("sampled_out", "dropped_spans", "sqlite_errors", "export_dropped_spans",
                                      "export_failures", "export_rejected_spans"), 0)
        self._counts_lock = Lock()

    @property
    def available(self) -> bool:
        return self._ready.is_set()

    def count(self, key: str, amount: int = 1) -> None:
        with self._counts_lock:
            self._counts[key] += amount

    def health(self) -> dict:
        with self._counts_lock:
            return {"enabled": self.enabled, "available": self.available,
                    "export_enabled": bool(self._endpoint and self._exporter and self._exporter.is_alive()),
                    "diagnostic": self._diagnostic, **self._counts}

    def enqueue(self, row: TraceRow) -> None:
        with self._counts_lock:
            if self.accepting:
                try:
                    self._queue.put_nowait(row)
                    return
                except Full:
                    pass
            self._counts["dropped_spans"] += 1

    async def astart(self) -> None:
        if not self.enabled or self._writer is not None or self._stopping.is_set():
            return
        self.accepting = True
        try:
            self._writer = Thread(target=self._write, name="gdw-trace-sqlite", daemon=True)
            self._writer.start()
        except Exception:
            self._disable_writer()

    async def aclose(self) -> None:
        with self._counts_lock:
            self.accepting = False
        self._drain_until = time.monotonic() + SHUTDOWN_S
        self._stopping.set()
        try:
            while self._writer and self._writer.is_alive() and time.monotonic() < self._drain_until:
                await asyncio.sleep(0.01)
        finally:
            self._export_stop.set()
            if export_task := self._export_task:
                loop, task = export_task
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass  # The exporter's loop has already closed.

    def _disable_writer(self) -> None:
        with self._counts_lock:
            self.accepting = False
            self._diagnostic = "trace_store_unavailable"
            self._counts["sqlite_errors"] += 1
        log.warning("Trace storage unavailable")

    def _prune(self, conn: sqlite3.Connection) -> int:
        cutoff = max(0, time.time_ns() - self._retention_ns)
        delete = "DELETE FROM trace_spans WHERE rowid IN (SELECT rowid FROM trace_spans "
        expired = conn.execute(delete + "WHERE end_ns < ? ORDER BY end_ns LIMIT ?)", (cutoff, BATCH_SIZE)).rowcount
        total = conn.execute("SELECT count(*) FROM trace_spans").fetchone()[0]
        excess = min(BATCH_SIZE, total - self._max_spans)
        if excess > 0:
            conn.execute(delete + "ORDER BY end_ns LIMIT ?)", (excess,))
        return expired + max(0, excess)

    def _persist(self, conn: sqlite3.Connection, batch: list[TraceRow]) -> None:
        with conn:
            conn.executemany(_INSERT, batch)
            self._prune(conn)

    def _maintain(self, conn: sqlite3.Connection) -> None:
        while not self._stopping.is_set():
            with conn:
                if self._prune(conn) == 0:
                    return

    def _write(self) -> None:
        try:
            with closing(sqlite3.connect(_path(), timeout=0.25)) as conn:
                _migrate(conn)
                conn.execute("PRAGMA journal_mode=WAL")
                self._maintain(conn)
                self._ready.set()
                self._start_exporter()
                prune_at = time.monotonic() + 60
                while not self._stopping.is_set() or time.monotonic() < self._drain_until:
                    stopping = self._stopping.is_set()
                    batch = _batch(self._queue, stopping)
                    try:
                        if batch:
                            self._persist(conn, batch)
                            self._offer_export(batch)
                        elif stopping:
                            return
                        elif time.monotonic() >= prune_at:
                            prune_at = time.monotonic() + 60
                            self._maintain(conn)
                    except sqlite3.Error:
                        self.count("sqlite_errors")
                        self.count("dropped_spans", len(batch))
        except Exception:
            self._disable_writer()
        finally:
            self._ready.clear()
            while batch := _batch(self._queue, True):
                self.count("dropped_spans", len(batch))

    def _start_exporter(self) -> None:
        if self._endpoint and not self._export_stop.is_set():
            try:
                self._exporter = Thread(target=self._export, name="gdw-trace-otlp", daemon=True)
                self._exporter.start()
            except Exception:
                self.count("export_failures")

    def _offer_export(self, batch: list[TraceRow]) -> None:
        if not self._endpoint:
            return
        if self._exporter and self._exporter.is_alive() and not self._export_stop.is_set():
            for index, row in enumerate(batch):
                try:
                    self._export_queue.put_nowait(row)
                except Full:
                    break
            else:
                return
            self.count("export_dropped_spans", len(batch) - index)
        else:
            self.count("export_dropped_spans", len(batch))

    def _export(self) -> None:
        try:
            asyncio.run(self._export_loop())
        except asyncio.CancelledError:
            pass
        except Exception:
            self.count("export_failures")
        finally:
            self._export_task = None
            self._export_stop.set()
            while batch := _batch(self._export_queue, True):
                self.count("export_dropped_spans", len(batch))

    async def _export_loop(self) -> None:
        self._export_task = (asyncio.get_running_loop(), asyncio.current_task())
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False, trust_env=False) as client:
            while not self._export_stop.is_set():
                batch = _batch(self._export_queue, False)
                if not batch:
                    continue
                if self._export_stop.is_set():
                    self.count("export_dropped_spans", len(batch))
                    return
                try:
                    rejected = await _send(client, self._endpoint, _otlp_json(batch),
                                           _headers(self._header_names), len(batch), self._timeout)
                except asyncio.CancelledError:
                    self.count("export_dropped_spans", len(batch))
                    raise
                except Exception:
                    rejected = len(batch)
                if rejected:
                    self.count("export_failures")
                    self.count("export_rejected_spans", rejected)

    def page(self, *, session_id: str | None, trace_id: str | None,
             cursor: tuple[int, str] | None, limit: int) -> list[dict]:
        """Read on a separate connection so a page cannot hold up the writer."""
        where, args = [], []
        query = "SELECT s.* FROM trace_spans s"
        order = "DESC"
        if trace_id is not None:
            where.append("s.trace_id = ?")
            args.append(trace_id)
            order = "ASC"
            query = ("SELECT s.*, s.parent_span_id IS NOT NULL AND NOT EXISTS "
                     "(SELECT 1 FROM trace_spans p WHERE p.trace_id = s.trace_id "
                     "AND p.span_id = s.parent_span_id) AS missing_parent FROM trace_spans s")
        else:
            where.append("s.parent_span_id IS NULL")
            if session_id is not None:
                where.append("s.session_id = ?")
                args.append(session_id)
        if cursor is not None:
            comparison = ">" if order == "ASC" else "<"
            where.append(f"(s.start_ns, s.span_id) {comparison} (?, ?)")
            args.extend(cursor)
        args.append(limit + 1)
        try:
            path = _path()
            if not path.is_file() or self._diagnostic == "trace_store_unavailable":
                return []
            with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=0.1)) as conn:
                conn.row_factory = sqlite3.Row
                rows = [dict(row) for row in conn.execute(
                    f"{query} WHERE {' AND '.join(where)} ORDER BY s.start_ns {order}, s.span_id {order} LIMIT ?", args)]
            for row in rows:
                row["attrs"] = json.loads(row.pop("attrs_json"))
                if trace_id is not None:
                    row["missing_parent"] = bool(row["missing_parent"])
            return rows
        except (OSError, sqlite3.Error, ValueError):
            self.count("sqlite_errors")
            return []
