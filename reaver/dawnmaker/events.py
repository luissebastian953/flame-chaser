"""SSE hub: one ring buffer, many subscribers, Last-Event-ID replay.

SSE over WebSocket deliberately: this stream is one-directional, EventSource
reconnects on its own, and cancellation is a normal POST. The ring buffer is
what makes a reconnect during a long crawl lossless -- the pipeline page asks
for everything after the last id it saw and gets it, then goes live.
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
from collections import deque
from collections.abc import Iterator
from typing import Any

RING = 500
KEEPALIVE_S = 15.0


class EventHub:
    def __init__(self, ring: int = RING) -> None:
        self._ring: deque[tuple[int, str, str]] = deque(maxlen=ring)  # (id, type, json)
        self._next = 1
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()

    # -- producer side (job runner thread) ----------------------------------
    def publish(self, type_: str, data: dict[str, Any]) -> int:
        payload = json.dumps(data, ensure_ascii=False, default=str)
        with self._lock:
            eid = self._next
            self._next += 1
            self._ring.append((eid, type_, payload))
            subs = list(self._subs)
        for q in subs:
            # a stalled client loses events; it never blocks the producer
            with contextlib.suppress(queue.Full):
                q.put_nowait((eid, type_, payload))
        return eid

    def from_job_event(self, ev: dict[str, Any]) -> None:
        """Adapter for JobRunner.subscribers: maps job_log rows onto the
        event types the API contract names."""
        kind = ev["kind"]
        d = dict(ev.get("data") or {})
        d.update(job_id=ev["job_id"], at=ev["at"], message=ev["message"])
        if kind == "stage":
            msg = ev["message"]
            if msg == "started":
                self.publish("job.started", d)
            elif msg == "finished":
                self.publish("job.finished", d)
            else:
                d["stage"] = msg
                self.publish("job.stage", d)
        elif kind == "progress":
            self.publish("job.progress", d)
        elif kind == "item":
            self.publish("job.item", d)
        else:
            d["level"] = ev.get("level", "info")
            self.publish("job.log", d)

    # -- consumer side (one generator per SSE client) --------------------------
    def replay(self, last_id: int | None = None) -> list[tuple[int, str, str]]:
        with self._lock:
            return [e for e in self._ring if last_id is None or e[0] > last_id]

    def stream(
        self, last_id: int | None = None, live: bool = True, keepalive: float = KEEPALIVE_S
    ) -> Iterator[str]:
        """Replay after `last_id`, then (if `live`) block on new events with
        keepalive comments. `live=False` ends after the replay -- for tests and
        for a one-shot catch-up request."""
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            replay = [e for e in self._ring if last_id is None or e[0] > last_id]
            if live:
                self._subs.add(q)
        try:
            for eid, typ, payload in replay:
                yield _frame(eid, typ, payload)
            if not live:
                return
            while True:
                try:
                    eid, typ, payload = q.get(timeout=keepalive)
                except queue.Empty:
                    yield ": keepalive\n\n"  # comment frame keeps proxies awake
                    continue
                yield _frame(eid, typ, payload)
        finally:
            with self._lock:
                self._subs.discard(q)

    @property
    def last_id(self) -> int:
        return self._next - 1


def _frame(eid: int, typ: str, payload: str) -> str:
    return f"id: {eid}\nevent: {typ}\ndata: {payload}\n\n"
