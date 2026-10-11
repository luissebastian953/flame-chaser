"""Job queue: one worker, cooperative cancel, persisted state.

One worker thread, not a pool: the constraint is the remote rate limit, not
local CPU. Two workers on pixiv doubles the ban risk and halves each one's
budget.

Cancellation is cooperative. `JobContext.check()` is called between records,
never inside a write, so a cancel lands at a record boundary and the db is
always consistent. The flag lives in the `jobs` row, so `coreflame jobs cancel`
from another process works too.

A job left `running` when the process starts was killed mid-flight -- it is
marked `interrupted`, not forgotten. That row is how you learn a crawl died.

Progress denominators are honest or absent. `total=None` means "no honest
number exists"; the UI shows indeterminate rather than a lying percentage.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .db import Store

log = logging.getLogger(__name__)

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED, INTERRUPTED = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
)
TERMINAL = {SUCCEEDED, FAILED, CANCELLED, INTERRUPTED}

Event = dict[str, Any]
Handler = Callable[["JobContext"], dict[str, Any]]  # returns counters


_ENGINE_STARTED = time.time()  # import time of this module = process start


def _human_age(sec: float) -> str:
    if sec < 90:
        return f"{int(sec)}s"
    if sec < 5400:
        return f"{int(sec // 60)}m"
    return f"{sec / 3600:.1f}h"


def _stamp(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M:%S")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Cancelled(Exception):
    """Raised by JobContext.check() when a cancel was requested."""


@dataclass
class Job:
    id: str
    type: str
    params: dict[str, Any]
    state: str
    stage: str | None = None
    done: int = 0
    total: int | None = None
    counters: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_row(cls, r: Any) -> Job:
        return cls(
            id=r["id"],
            type=r["type"],
            params=json.loads(r["params"]),
            state=r["state"],
            stage=r["stage"],
            done=r["done"],
            total=r["total"],
            counters=json.loads(r["counters"]),
            error=r["error"],
            created_at=r["created_at"],
            started_at=r["started_at"],
            finished_at=r["finished_at"],
        )


class JobContext:
    """What a handler gets: the store, the params, emit(), and check()."""

    def __init__(
        self,
        store: Store,
        job: Job,
        subscribers: list[Callable[[Event], None]],
        check_every: int = 5,
    ) -> None:
        self.store = store
        self.job = job
        self._subs = subscribers
        self._seq = 0
        self._check_every = check_every
        self._since_check = check_every  # first check() consults the db, not the 5th
        self._cancel = threading.Event()

    # -- cancellation ----------------------------------------------------
    def request_cancel(self) -> None:
        self._cancel.set()

    def _db_flag(self) -> bool:
        r = self.store.conn.execute(
            "SELECT cancel_requested FROM jobs WHERE id=?", (self.job.id,)
        ).fetchone()
        return bool(r and r["cancel_requested"])

    def check(self) -> None:
        """Call between records. Raises Cancelled. Polls the db flag on the
        first call and every `check_every` after, so a cancel from another
        process is seen even by a job of two records."""
        if self._cancel.is_set():
            raise Cancelled()
        self._since_check += 1
        if self._since_check >= self._check_every:
            self._since_check = 0
            if self._db_flag():
                self._cancel.set()
                raise Cancelled()

    # -- events -------------------------------------------------------------
    def emit(self, kind: str, message: str, level: str = "info", **data: Any) -> None:
        self._seq += 1
        row = {
            "job_id": self.job.id,
            "seq": self._seq,
            "at": _now(),
            "level": level,
            "kind": kind,
            "message": message,
            "data": data,
        }
        self.store.conn.execute(
            "INSERT INTO job_log(job_id,seq,at,level,kind,message,data) VALUES(?,?,?,?,?,?,?)",
            (
                self.job.id,
                self._seq,
                row["at"],
                level,
                kind,
                message,
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
        for s in list(self._subs):
            try:
                s(row)
            except Exception:  # a bad subscriber never kills a job
                log.exception("job event subscriber failed")

    def stage(self, name: str, **data: Any) -> None:
        # a stage boundary is always a safe place to stop
        if self._cancel.is_set() or self._db_flag():
            self._cancel.set()
            raise Cancelled()
        self.job.stage = name
        self.store.conn.execute("UPDATE jobs SET stage=? WHERE id=?", (name, self.job.id))
        self.emit("stage", name, **data)

    def progress(self, done: int, total: int | None = None, **data: Any) -> None:
        self.job.done, self.job.total = done, total
        self.store.conn.execute(
            "UPDATE jobs SET done=?, total=? WHERE id=?", (done, total, self.job.id)
        )
        self.emit(
            "progress",
            f"{done}/{total if total is not None else '?'}",
            done=done,
            total=total,
            **data,
        )

    def item(self, message: str, **data: Any) -> None:
        self.emit("item", message, **data)

    def log(self, message: str, level: str = "info", **data: Any) -> None:
        self.emit("log", message, level=level, **data)


class JobRunner:
    """Owns the worker thread. `store_factory` opens a store PER THREAD --
    sqlite connections are not shared across threads."""

    def __init__(self, store_factory: Callable[[], Store], handlers: dict[str, Handler]) -> None:
        self._factory = store_factory
        self.handlers = handlers
        self.subscribers: list[Callable[[Event], None]] = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._current: JobContext | None = None
        self._lock = threading.Lock()
        store = self._factory()
        try:
            self.interrupted = self.mark_interrupted(store)
        finally:
            store.close()

    # -- boot ----------------------------------------------------------------
    @staticmethod
    def mark_interrupted(store: Store) -> int:
        cur = store.conn.execute(
            "UPDATE jobs SET state='interrupted', finished_at=?, "
            "error=COALESCE(error,'process exited while running') WHERE state='running'",
            (_now(),),
        )
        return cur.rowcount

    # -- submit / query / cancel (any thread) ---------------------------------
    @staticmethod
    def submit(store: Store, type_: str, params: dict[str, Any] | None = None) -> str:
        jid = uuid.uuid4().hex[:12]
        store.conn.execute(
            "INSERT INTO jobs(id,type,params,state,created_at) VALUES(?,?,?,'queued',?)",
            (jid, type_, json.dumps(params or {}, ensure_ascii=False), _now()),
        )
        return jid

    @staticmethod
    def get(store: Store, jid: str) -> Job | None:
        r = store.conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return Job.from_row(r) if r else None

    @staticmethod
    def list_jobs(store: Store, state: str | None = None, limit: int = 50) -> list[Job]:
        if state:
            rows = store.conn.execute(
                "SELECT * FROM jobs WHERE state=? ORDER BY created_at DESC LIMIT ?", (state, limit)
            ).fetchall()
        else:
            rows = store.conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Job.from_row(r) for r in rows]

    @staticmethod
    def tail(store: Store, jid: str, limit: int = 200) -> list[Event]:
        rows = store.conn.execute(
            "SELECT * FROM job_log WHERE job_id=? ORDER BY seq DESC LIMIT ?", (jid, limit)
        ).fetchall()
        return [{**dict(r), "data": json.loads(r["data"] or "{}")} for r in reversed(rows)]

    def cancel(self, store: Store, jid: str) -> bool:
        """Queued -> cancelled immediately. Running -> flag; the worker stops at
        the next record boundary."""
        j = self.get(store, jid)
        if j is None or j.state in TERMINAL:
            return False
        if j.state == QUEUED:
            store.conn.execute(
                "UPDATE jobs SET state='cancelled', finished_at=? WHERE id=? AND state='queued'",
                (_now(), jid),
            )
            return True
        store.conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (jid,))
        with self._lock:
            if self._current and self._current.job.id == jid:
                self._current.request_cancel()
        return True

    @staticmethod
    def idle(store: Store) -> bool:
        r = store.conn.execute(
            "SELECT count(*) FROM jobs WHERE state IN ('queued','running')"
        ).fetchone()
        return bool(r[0] == 0)

    # -- worker ------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="coreflame-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def kick(self) -> None:
        self._wake.set()

    def run_pending(self, store: Store) -> int:
        """Synchronous: run every queued job in THIS thread. For the CLI and
        for tests; the daemon uses start()."""
        n = 0
        while (job := self._next(store)) is not None:
            self._run_one(store, job)
            n += 1
        return n

    def _next(self, store: Store) -> Job | None:
        r = store.conn.execute(
            "SELECT * FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        return Job.from_row(r) if r else None

    def _loop(self) -> None:
        store = self._factory()
        try:
            while not self._stop.is_set():
                job = self._next(store)
                if job is None:
                    self._wake.wait(timeout=2.0)
                    self._wake.clear()
                    continue
                self._run_one(store, job)
        finally:
            store.close()

    def _run_one(self, store: Store, job: Job) -> None:
        handler = self.handlers.get(job.type)
        started = _now()
        store.conn.execute(
            "UPDATE jobs SET state='running', started_at=? WHERE id=?", (started, job.id)
        )
        job.state, job.started_at = RUNNING, started
        ctx = JobContext(store, job, self.subscribers)
        with self._lock:
            self._current = ctx
        ctx.emit("stage", "started", type=job.type, params=job.params)
        # The running process's own age. A daemon older than the code on disk is
        # running the old code -- invisible otherwise, and the cause of every
        # "I changed it and nothing happened" during development.
        age = time.time() - _ENGINE_STARTED
        ctx.log(
            f"engine up {_human_age(age)} (started {_stamp(_ENGINE_STARTED)}) · "
            f"restart the daemon to pick up edited code",
            engine_started_at=_ENGINE_STARTED,
            engine_uptime_s=round(age),
        )
        state, error, counters = SUCCEEDED, None, {}
        t0 = time.monotonic()
        try:
            if handler is None:
                raise ValueError(f"no handler for job type {job.type!r}")
            counters = handler(ctx) or {}
        except Cancelled:
            state = CANCELLED
        except Exception as e:
            state, error = FAILED, f"{type(e).__name__}: {e}"[:2000]
            log.exception("job %s failed", job.id)
        finally:
            with self._lock:
                self._current = None
        store.conn.execute(
            "UPDATE jobs SET state=?, error=?, counters=?, finished_at=? WHERE id=?",
            (state, error, json.dumps(counters, default=str), _now(), job.id),
        )
        job.state, job.error, job.counters = state, error, counters
        ctx.emit(
            "stage",
            "finished",
            state=state,
            error=error,
            counters=counters,
            seconds=round(time.monotonic() - t0, 1),
        )
