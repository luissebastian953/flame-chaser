"""Job queue: one worker per source, cooperative cancel and pause, persisted state.

One worker thread per SOURCE, never two on the same one: the constraint is the
remote rate limit, not local CPU. Two workers on pixiv doubles the ban risk and
halves each one's budget. pixiv and X are different hosts with separate budgets,
so each gets its own lane -- the `pixiv` worker owns www.pixiv.net and
i.pximg.net, the `twitter` worker owns gallery-dl and pbs.twimg.com. Each site
still sees exactly one request stream. A job's `lane` says which worker may take
it; `any` (tags, labels: no remote request) goes to whichever is free.

The queue is ordered by `position` (reorder, run now), then created_at. A job is
claimed with a conditional UPDATE, so two workers never take the same `any` job.
Pausing the queue stops workers taking new jobs AND holds what they are running;
pausing one job holds it at its next check() -- the same record boundary a cancel
uses -- still holding its lane.

Cancellation is cooperative. `JobContext.check()` is called between records,
never inside a write, so a cancel lands at a record boundary and the db is
always consistent. The flag lives in the `jobs` row, so `coreflame jobs cancel`
from another process works too.

A job left `running` when the process starts was killed mid-flight -- it is
marked `interrupted`, not forgotten. That row is how you learn a crawl died.
The exception is a queue that was paused when the process died: the pause is
persisted (`queue_state`), the daemon comes back paused, and that job goes back
to the front of the queue as `queued` -- what the user paused is what they see.
A crawl re-runs safely (the visited gate skips what it already indexed), so
`retry()` turns any finished job into a fresh queued copy.

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
from .http import METER
from .online import WATCH, NetWatch, Offline

log = logging.getLogger(__name__)

#: why the queue is held: the user asked, or the internet went away
HOLD_USER, HOLD_OFFLINE = "user", "offline"

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED, INTERRUPTED = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
)
TERMINAL = {SUCCEEDED, FAILED, CANCELLED, INTERRUPTED}

LANES = ("pixiv", "twitter")  # one worker thread each, in this order
ANY = "any"  # a job that sends no remote request: either worker may run it
# type -> lane when params do not say. poll / media name their source; one
# without (the CLI's whole-archive run) is the legacy single job -> pixiv lane.
_LANE_BY_TYPE = {"poll": "pixiv", "media": "pixiv", "link": "pixiv", "timelines": "twitter"}


def lane_of(type_: str, params: dict[str, Any] | None = None) -> str:
    src = (params or {}).get("source")
    if type_ in ("poll", "media") and src in LANES:
        return str(src)
    return _LANE_BY_TYPE.get(type_, ANY)


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
    lane: str = "pixiv"
    worker: str | None = None  # the lane that ran it; None until claimed
    position: float = 0
    paused: bool = False

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
            lane=r["lane"],
            worker=r["worker"],
            position=r["position"],
            paused=bool(r["pause_requested"]),
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
        # a job that runs again (back from the front of the queue after a
        # lost connection or a paused restart) keeps its log: continue the
        # sequence rather than collide with the first run's rows
        r = store.conn.execute(
            "SELECT COALESCE(max(seq),0) FROM job_log WHERE job_id=?", (job.id,)
        ).fetchone()
        self._seq = int(r[0]) if r else 0
        self._check_every = check_every
        self._since_check = check_every  # first check() consults the db, not the 5th
        self._cancel = threading.Event()
        self._pause = threading.Event()
        # running tallies (item actions, progress extras, tally()), written to
        # jobs.counters as they move so the pipeline shows them mid-run; the
        # handler's own counters are merged over them at the end
        self.live: dict[str, Any] = {}

    # -- cancellation and pause ------------------------------------------------
    def request_cancel(self) -> None:
        self._cancel.set()

    def request_pause(self, on: bool) -> None:
        if on:
            self._pause.set()
        else:
            self._pause.clear()

    def _db_flags(self) -> tuple[bool, bool]:
        r = self.store.conn.execute(
            "SELECT cancel_requested, pause_requested FROM jobs WHERE id=?", (self.job.id,)
        ).fetchone()
        return (bool(r and r["cancel_requested"]), bool(r and r["pause_requested"]))

    def _hold(self) -> None:
        """Paused: wait here -- a record boundary -- until resumed or cancelled.
        The db is the truth, so a resume from another process works too."""
        self.log("paused")
        while True:
            if self._cancel.is_set():
                raise Cancelled()
            cancel, pause = self._db_flags()
            if cancel:
                self._cancel.set()
                raise Cancelled()
            if not pause:
                self._pause.clear()
                break
            time.sleep(0.25)
        self.log("resumed")

    def check(self) -> None:
        """Call between records. Raises Cancelled; holds while paused. Polls the
        db flags on the first call and every `check_every` after, so a cancel or
        pause from another process is seen even by a job of two records."""
        if self._cancel.is_set():
            raise Cancelled()
        self._since_check += 1
        if self._since_check >= self._check_every:
            self._since_check = 0
            cancel, pause = self._db_flags()
            if cancel:
                self._cancel.set()
                raise Cancelled()
            if pause:
                self._pause.set()
        if self._pause.is_set():
            self._hold()

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
        # a stage boundary is always a safe place to stop (or pause)
        cancel, pause = self._db_flags()
        if self._cancel.is_set() or cancel:
            self._cancel.set()
            raise Cancelled()
        if pause or self._pause.is_set():
            self._pause.set()
            self._hold()
        self.job.stage = name
        self.store.conn.execute("UPDATE jobs SET stage=? WHERE id=?", (name, self.job.id))
        self.emit("stage", name, **data)

    def progress(self, done: int, total: int | None = None, **data: Any) -> None:
        self.job.done, self.job.total = done, total
        # numeric extras (listed, gated) are running totals: kept, not summed
        self.live.update({k: v for k, v in data.items() if isinstance(v, int)})
        self.store.conn.execute(
            "UPDATE jobs SET done=?, total=?, counters=? WHERE id=?",
            (done, total, json.dumps(self.live), self.job.id),
        )
        self.emit(
            "progress",
            f"{done}/{total if total is not None else '?'}",
            done=done,
            total=total,
            **data,
        )

    def item(self, message: str, **data: Any) -> None:
        action = data.get("action")
        if isinstance(action, str):
            self.tally(action)
        self.emit("item", message, **data)

    def tally(self, key: str, n: int = 1) -> None:
        """Count something mid-run (an item's action does it for you)."""
        self.live[key] = int(self.live.get(key, 0)) + n
        self.store.conn.execute(
            "UPDATE jobs SET counters=? WHERE id=?", (json.dumps(self.live), self.job.id)
        )

    def log(self, message: str, level: str = "info", **data: Any) -> None:
        self.emit("log", message, level=level, **data)


class JobRunner:
    """Owns the worker threads, one per lane. `store_factory` opens a store PER
    THREAD -- sqlite connections are not shared across threads."""

    def __init__(
        self,
        store_factory: Callable[[], Store],
        handlers: dict[str, Handler],
        lanes: tuple[str, ...] = LANES,
        watch: NetWatch | None = None,
    ) -> None:
        self._factory = store_factory
        self.handlers = handlers
        self.lanes = lanes
        self.watch = watch or WATCH
        self.subscribers: list[Callable[[Event], None]] = []
        #: told (paused, reason) whenever the queue's hold changes, from any thread
        self.on_hold: list[Callable[[bool, str | None], None]] = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._held = threading.Event()  # the queue is paused: take nothing new
        self._reason: str | None = None  # HOLD_USER | HOLD_OFFLINE while held
        self._threads: dict[str, threading.Thread] = {}
        self._current: dict[str, JobContext] = {}
        self._lock = threading.Lock()
        store = self._factory()
        try:
            self.interrupted = self.requeued = 0
            if self.read_hold(store):
                # paused when the process died: come back paused, with what was
                # running back at the front -- the queue the user left (or the
                # one the lost connection left: the watch lifts that hold)
                self._held.set()
                self._reason = self.read_hold_reason(store)
                self.requeued = self.requeue_running(store)
            else:
                self.interrupted = self.mark_interrupted(store)
        finally:
            store.close()

    # -- boot ----------------------------------------------------------------
    @staticmethod
    def mark_interrupted(store: Store) -> int:
        cur = store.conn.execute(
            "UPDATE jobs SET state='interrupted', finished_at=?, pause_requested=0, "
            "error=COALESCE(error,'process exited while running') WHERE state='running'",
            (_now(),),
        )
        return cur.rowcount

    @staticmethod
    def requeue_running(store: Store) -> int:
        """Every `running` row back to the front of the queue, as if never
        claimed. Safe because a crawl is idempotent: the visited gate skips
        what the first attempt already indexed."""
        cur = store.conn.execute(
            "UPDATE jobs SET state='queued', started_at=NULL, worker=NULL, stage=NULL, "
            "done=0, total=NULL, error=NULL, pause_requested=0, cancel_requested=0, "
            "position=(SELECT COALESCE(min(position),0)-1 FROM jobs WHERE state='queued') "
            "WHERE state='running'"
        )
        return cur.rowcount

    @staticmethod
    def requeue_one(store: Store, jid: str) -> bool:
        """One running job back to the front of the queue, as if never claimed
        (what the connection interrupted is what runs first when it is back)."""
        cur = store.conn.execute(
            "UPDATE jobs SET state='queued', started_at=NULL, worker=NULL, stage=NULL, "
            "done=0, total=NULL, error=NULL, pause_requested=0, cancel_requested=0, "
            "position=(SELECT COALESCE(min(position),0)-1 FROM jobs WHERE state='queued') "
            "WHERE id=? AND state='running'",
            (jid,),
        )
        return cur.rowcount == 1

    @staticmethod
    def read_hold(store: Store) -> bool:
        r = store.conn.execute("SELECT value FROM queue_state WHERE key='held'").fetchone()
        return bool(r and r["value"] == "1")

    @staticmethod
    def read_hold_reason(store: Store) -> str | None:
        r = store.conn.execute("SELECT value FROM queue_state WHERE key='held_reason'").fetchone()
        return str(r["value"]) if r and r["value"] in (HOLD_USER, HOLD_OFFLINE) else HOLD_USER

    @staticmethod
    def write_hold(store: Store, on: bool, reason: str | None = None) -> None:
        with store.tx():
            for key, value in (("held", "1" if on else "0"), ("held_reason", reason or "")):
                store.conn.execute(
                    "INSERT INTO queue_state(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )

    # -- submit / query / cancel (any thread) ---------------------------------
    @staticmethod
    def submit(
        store: Store, type_: str, params: dict[str, Any] | None = None, lane: str | None = None
    ) -> str:
        """Queued at the back. `lane` defaults to lane_of(type_, params)."""
        jid = uuid.uuid4().hex[:12]
        store.conn.execute(
            "INSERT INTO jobs(id,type,params,state,created_at,lane,position) "
            "VALUES(?,?,?,'queued',?,?,(SELECT COALESCE(max(position),0)+1 FROM jobs))",
            (
                jid,
                type_,
                json.dumps(params or {}, ensure_ascii=False),
                _now(),
                lane or lane_of(type_, params),
            ),
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

    def _running_ctx(self, jid: str) -> JobContext | None:
        with self._lock:
            return next((c for c in self._current.values() if c.job.id == jid), None)

    def cancel(self, store: Store, jid: str) -> bool:
        """Queued -> cancelled immediately. Running -> flag; the worker stops at
        the next record boundary (a paused one too)."""
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
        if ctx := self._running_ctx(jid):
            ctx.request_cancel()
        return True

    def pause(self, store: Store, jid: str, on: bool) -> bool:
        """Hold (or release) a RUNNING job at its next record boundary. It keeps
        its lane while held -- that is what pausing a worker means."""
        cur = store.conn.execute(
            "UPDATE jobs SET pause_requested=? WHERE id=? AND state='running'", (int(on), jid)
        )
        if cur.rowcount == 0:
            return False
        if ctx := self._running_ctx(jid):
            ctx.request_pause(on)
        return True

    @staticmethod
    def reorder(store: Store, ids: list[str]) -> list[str]:
        """The queue in this order: `ids` first (queued ones; others ignored),
        then every queued job not named, in its current order. Returns the order."""
        queued = [
            r["id"]
            for r in store.conn.execute(
                "SELECT id FROM jobs WHERE state='queued' ORDER BY position, created_at"
            ).fetchall()
        ]
        named = [i for i in dict.fromkeys(ids) if i in queued]
        order = named + [i for i in queued if i not in named]
        with store.tx():
            for pos, jid in enumerate(order, 1):
                store.conn.execute("UPDATE jobs SET position=? WHERE id=?", (pos, jid))
        return order

    @staticmethod
    def retry(store: Store, jid: str) -> str | None:
        """A finished job (failed, cancelled, interrupted -- or succeeded) again:
        a fresh queued copy with the same type, params and lane. None if the job
        is unknown or not finished. Re-running is safe: the visited gate skips
        what the first attempt already indexed, so this is how an interrupted
        crawl resumes."""
        j = JobRunner.get(store, jid)
        if j is None or j.state not in TERMINAL:
            return None
        return JobRunner.submit(store, j.type, j.params, lane=j.lane)

    @staticmethod
    def run_now(store: Store, jid: str) -> bool:
        """To the front of the queue. It starts when its lane's worker is free --
        a running job is never pre-empted."""
        cur = store.conn.execute(
            "UPDATE jobs SET position=(SELECT COALESCE(min(position),0)-1 FROM jobs "
            "WHERE state='queued') WHERE id=? AND state='queued'",
            (jid,),
        )
        return cur.rowcount == 1

    @staticmethod
    def idle(store: Store) -> bool:
        r = store.conn.execute(
            "SELECT count(*) FROM jobs WHERE state IN ('queued','running')"
        ).fetchone()
        return bool(r[0] == 0)

    # -- the queue as a whole -------------------------------------------------
    @property
    def held(self) -> bool:
        return self._held.is_set()

    @property
    def held_reason(self) -> str | None:
        """`user` or `offline` while the queue is held, else None."""
        return self._reason if self._held.is_set() else None

    def hold(self, on: bool, reason: str = HOLD_USER) -> None:
        """Pause / resume the queue: workers take nothing new, and what they are
        running holds at its next record boundary (keeping its lane) until the
        queue resumes -- "pause" means everything stops. Persisted with its
        reason, so a restarted daemon comes back the way it was left. A user's
        pause outranks the connection's: pausing by hand while held for being
        offline makes it the user's, and only the user lifts it."""
        with self._lock:
            if on and self._held.is_set() and self._reason == HOLD_USER:
                reason = HOLD_USER
            self._reason = reason if on else None
        store = self._factory()
        try:
            self.write_hold(store, on, self._reason)
            running = store.conn.execute("SELECT id FROM jobs WHERE state='running'").fetchall()
            for r in running:
                self.pause(store, r["id"], on)
        finally:
            store.close()
        if on:
            self._held.set()
        else:
            self._held.clear()
            self._wake.set()
        for fn in list(self.on_hold):
            try:
                fn(on, self._reason)
            except Exception:
                log.exception("hold listener failed")

    def _on_connectivity(self, online: bool) -> None:
        """The watch's verdict changed. Gone: hold everything (a request in
        flight ends in Offline and its job goes back to the front). Back: lift
        the hold, unless the user made it theirs in the meantime."""
        if not online:
            if not self._held.is_set():
                self.hold(True, HOLD_OFFLINE)
        elif self._held.is_set() and self._reason == HOLD_OFFLINE:
            self.hold(False)

    def _watch_active(self) -> bool:
        """When the watch should probe unprompted: a worker is busy, or the
        queue is waiting for the connection to come back."""
        with self._lock:
            busy = bool(self._current)
        return busy or (self._held.is_set() and self._reason == HOLD_OFFLINE)

    def workers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"lane": lane, "job_id": c.job.id if (c := self._current.get(lane)) else None}
                for lane in self.lanes
            ]

    # -- workers -------------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        if self._on_connectivity not in self.watch.listeners:
            self.watch.listeners.append(self._on_connectivity)
        self.watch.start(self._watch_active)
        for lane in self.lanes:
            t = self._threads.get(lane)
            if t and t.is_alive():
                continue
            t = threading.Thread(
                target=self._loop, args=(lane,), name=f"coreflame-worker-{lane}", daemon=True
            )
            self._threads[lane] = t
            t.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        self._wake.set()
        self.watch.stop()
        if self._on_connectivity in self.watch.listeners:
            self.watch.listeners.remove(self._on_connectivity)
        for t in self._threads.values():
            t.join(timeout)

    def kick(self) -> None:
        self._wake.set()

    def run_pending(self, store: Store) -> int:
        """Synchronous: run every queued job, any lane, in THIS thread, in queue
        order. For the CLI and for tests; the daemon uses start()."""
        n = 0
        while not self._held.is_set() and (job := self._take(store, None)) is not None:
            self._run_one(store, job)
            n += 1
        return n

    def _take(self, store: Store, lane: str | None) -> Job | None:
        """The next job this lane may run (None = any lane), claimed. The claim
        is a conditional UPDATE: of two workers racing for an `any` job, one wins
        and the other looks again."""
        while True:
            if lane is None:
                r = store.conn.execute(
                    "SELECT * FROM jobs WHERE state='queued' ORDER BY position, created_at LIMIT 1"
                ).fetchone()
            else:
                r = store.conn.execute(
                    "SELECT * FROM jobs WHERE state='queued' AND lane IN (?, ?) "
                    "ORDER BY position, created_at LIMIT 1",
                    (lane, ANY),
                ).fetchone()
            if r is None:
                return None
            job = Job.from_row(r)
            worker = lane or (job.lane if job.lane != ANY else self.lanes[0])
            started = _now()
            cur = store.conn.execute(
                "UPDATE jobs SET state='running', started_at=?, worker=? "
                "WHERE id=? AND state='queued'",
                (started, worker, job.id),
            )
            if cur.rowcount == 1:
                job.state, job.started_at, job.worker = RUNNING, started, worker
                return job

    def _loop(self, lane: str) -> None:
        """One lane's worker thread. It must not die: a job's own failure is
        caught in _run_one, but an error around it -- the queue query, the
        bookkeeping, a database the container lost its grip on ("disk I/O
        error") -- used to end the thread silently, leaving every later job
        queued forever while the API still answered "idle". Now it is logged,
        the job it was on is marked failed, the connection is reopened, and the
        loop backs off."""
        store = self._factory()
        backoff = 2.0
        try:
            while not self._stop.is_set():
                job: Job | None = None
                try:
                    job = None if self._held.is_set() else self._take(store, lane)
                    if job is None:
                        self._wake.wait(timeout=2.0)
                        self._wake.clear()
                    else:
                        self._run_one(store, job)
                        self._wake.set()  # the other lane may be waiting on an `any` job
                    backoff = 2.0
                except Exception:
                    log.exception(
                        "worker %s: error outside a job; retrying in %.0fs", lane, backoff
                    )
                    store = self._recover(store, job)
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 30.0)
        finally:
            store.close()

    def _recover(self, store: Store, job: Job | None) -> Store:
        """A fresh connection (one that hit an I/O error can stay broken), and the
        job the error interrupted marked failed rather than left `running`."""
        try:
            store.close()
        except Exception as e:  # already broken; the fresh one below is what matters
            log.debug("worker: closing the broken connection: %s", e)
        fresh = self._factory()
        if job is not None:
            try:
                fresh.conn.execute(
                    "UPDATE jobs SET state=?, error=?, finished_at=? WHERE id=? AND state IN (?,?)",
                    (
                        FAILED,
                        "worker error outside the job; see the daemon log",
                        _now(),
                        job.id,
                        QUEUED,
                        RUNNING,
                    ),
                )
            except Exception:
                log.exception("worker: could not mark job %s failed", job.id)
        return fresh

    def _run_one(self, store: Store, job: Job) -> None:
        """`job` is already claimed (state running, worker set) by _take."""
        handler = self.handlers.get(job.type)
        lane = job.worker or job.lane
        ctx = JobContext(store, job, self.subscribers)
        with self._lock:
            self._current[lane] = ctx
        METER.bind(job.id)  # this thread's requests count as this job's
        ctx.emit("stage", "started", type=job.type, params=job.params, worker=lane)
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
        offline: str | None = None
        t0 = time.monotonic()
        try:
            if handler is None:
                raise ValueError(f"no handler for job type {job.type!r}")
            counters = handler(ctx) or {}
        except Cancelled:
            state = CANCELLED
        except Offline as e:
            offline = str(e)[:500]
        except Exception as e:
            state, error = FAILED, f"{type(e).__name__}: {e}"[:2000]
            log.exception("job %s failed", job.id)
        finally:
            METER.bind(None)
            with self._lock:
                self._current.pop(lane, None)
        if offline is not None:
            # not a failure: the internet went away under the job. It goes back
            # to the front of the queue and the queue holds until the watch
            # sees the connection again (a re-run is safe: the visited gate).
            if not self._held.is_set():
                self.hold(True, HOLD_OFFLINE)
            self.requeue_one(store, job.id)
            job.state = QUEUED
            ctx.emit("stage", "offline", level="warning", error=offline, lane=lane)
            log.warning("job %s: internet unreachable; back at the front of the queue", job.id)
            return
        counters = {**ctx.live, **counters}
        store.conn.execute(
            "UPDATE jobs SET state=?, error=?, counters=?, finished_at=?, pause_requested=0 "
            "WHERE id=?",
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
