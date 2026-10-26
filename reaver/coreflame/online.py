"""Is the internet there? The pipeline pauses itself when it is not.

A request that fails at the transport layer (DNS, connect, TLS, timeout) is
either the site having a bad moment or the connection being gone. The first
is weather: `SourceClient` retries with backoff and the job goes on. The
second used to be a disaster in slow motion: every retry burned its backoff,
the job ended `failed`, the next job did the same, and a laptop that lost its
Wi-Fi at 3am woke up to a queue of failures with nothing to resume.

So a transport failure asks `WATCH.failed()`: a cheap probe decides whether
the internet is reachable at all. Reachable -> ordinary retry. Not -> the
request raises `Offline`, the runner puts the job back at the front of the
queue, holds the whole queue with reason "offline", and a monitor thread
probes until the connection returns, when the hold lifts on its own (unless
the user paused the queue in the meantime: a user's pause is theirs to lift).

The probe is a TCP connect to a few anycast addresses on 443 -- no DNS, no
request a source sees, and any one answering means "online". It runs on a
transport failure, every 10 s while a worker is busy (so a connection that
dies between requests is seen before the next 30 s timeout), and every 5 s
while offline. The daemon's own probe path (`speed.py`) is for the rail's
signal bars; this one is for the queue, and it must work with no config.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

log = logging.getLogger(__name__)

#: well-known anycast resolvers; the probe only connects, it never speaks
PROBES: tuple[tuple[str, int], ...] = (("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443))
PROBE_TIMEOUT = 3.0
#: while a worker runs: how often the monitor asks, unprompted
EVERY = 10.0
#: while offline: how often it asks again
RETRY = 5.0
#: two failures within this window share one probe
FRESH = 1.0


class Offline(RuntimeError):
    """A request failed while the internet was unreachable. Not a job
    failure: the runner requeues the job and holds the queue."""


def _connects(ip: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def reachable(probes: tuple[tuple[str, int], ...] = PROBES, timeout: float = PROBE_TIMEOUT) -> bool:
    """True when any probe target accepts a TCP connection. The targets are
    tried together, so a dead connection answers in one timeout, not three."""
    if not probes:
        return True
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        futures = {pool.submit(_connects, ip, port, timeout) for ip, port in probes}
        pending = set(futures)
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            if any(f.result() for f in done):
                for f in pending:
                    f.cancel()
                return True
    return False


class NetWatch:
    """The connection's state as the queue sees it, and the thread that keeps
    it current. `listeners` are called with the new state on every change,
    on whichever thread noticed (a worker's, or the monitor's)."""

    def __init__(
        self,
        probe: Callable[[], bool] = reachable,
        every: float = EVERY,
        retry: float = RETRY,
        fresh: float = FRESH,
    ) -> None:
        self._probe = probe
        self._every, self._retry, self._fresh = every, retry, fresh
        self.online = True  # assumed until a probe says otherwise
        self.since: float | None = None  # when it went offline (epoch seconds)
        self.listeners: list[Callable[[bool], None]] = []
        self._lock = threading.Lock()
        self._checked_at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active: Callable[[], bool] = lambda: False

    # -- asking --------------------------------------------------------------
    def check(self) -> bool:
        """Probe now. Returns online; tells the listeners if that changed."""
        with self._lock:
            try:
                online = bool(self._probe())
            except Exception:  # a broken probe must never take the queue down
                log.exception("connectivity probe failed; assuming online")
                online = True
            self._checked_at = time.monotonic()
            changed = online != self.online
            self.online = online
            if changed:
                self.since = None if online else time.time()
        if changed:
            log.warning("internet %s", "back" if online else "unreachable")
            for fn in list(self.listeners):
                try:
                    fn(online)
                except Exception:
                    log.exception("connectivity listener failed")
        return online

    def failed(self) -> bool:
        """A request just failed at the transport layer. True = the internet is
        unreachable, so the caller should raise `Offline` rather than retry.
        A verdict younger than `fresh` is reused, so a burst of failures
        across workers costs one probe."""
        with self._lock:
            recent = time.monotonic() - self._checked_at < self._fresh
            if recent:
                return not self.online
        return not self.check()

    # -- the monitor thread ----------------------------------------------------
    def start(self, active: Callable[[], bool]) -> None:
        """Probe unprompted every `every` seconds while `active()` (a worker is
        busy, or the queue is held for being offline) and every `retry` while
        offline, so the hold lifts without waiting for a request to fail."""
        if self._thread is not None:
            return
        self._active = active
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="net-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=PROBE_TIMEOUT + 1)
            self._thread = None

    def _loop(self) -> None:
        while True:
            if self._stop.wait(self._retry if not self.online else self._every):
                return
            try:
                if not self.online or self._active():
                    self.check()
            except Exception:
                log.exception("net watch tick failed")


#: the one the engine's clients and the runner share (like http.METER)
WATCH = NetWatch()
