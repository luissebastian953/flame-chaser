"""The rail's network signal: coreflame.speed behind one lock and a 30-sample tape.

The card asks every 30 s (a short probe); the modal asks for the long one with
upload. Both land here: one measurement at a time, the last answer kept, and
the per-second samples appended to a tape of thirty for each direction so the
modal's chart shows the recent history, streaming while a test runs (GET
returns the tape as it grows). The local side (Wi-Fi/Ethernet, SSID) is asked
of the OS once a minute; the ISP once per public IP.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx

from coreflame import speed
from coreflame.config import Config

KEEP = 30
CONNECTION_TTL = 60.0
#: a second caller inside this window gets the last answer, not a new run
FRESH = 2.0


class SpeedMeter:
    def __init__(
        self,
        cfg: Config,
        client: httpx.Client | None = None,
        connection: Callable[[], speed.Connection] = speed.local_connection,
        clock: speed.Clock = time.perf_counter,
    ) -> None:
        self.cfg = cfg
        self._client = client
        self._connection = connection
        self._clock = clock
        self._lock = threading.Lock()
        self._tape: dict[str, deque[float]] = {
            "download": deque(maxlen=KEEP),
            "upload": deque(maxlen=KEEP),
        }
        self.last: speed.Measurement | None = None
        self.last_upload: float | None = None  # a short probe has none; keep the long one's
        self.last_server: dict[str, Any] | None = None  # offline has none; the modal says "last …"
        self.testing = False
        self.live: dict[str, float | None] = {}  # this run's legs so far, over the last answer
        self._conn: tuple[float, speed.Connection] | None = None
        self._isp: dict[str, tuple[str | None, str | None]] = {}

    def reset(self) -> None:
        """Network settings changed: a new client on the new path."""
        with self._lock:
            if self._client is not None:
                self._client.close()
            self._client = None
            self._isp.clear()

    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = speed.make_client(self.cfg)
        return self._client

    def _sample(self, kind: str, mbps: float) -> None:
        self._tape[kind].append(round(mbps, 2))

    def run(self, full: bool = False) -> dict[str, Any]:
        with self._lock:
            last = self.last
            if last and not full and time.time() - last.measured_at < FRESH:
                return self.snapshot()
            self.testing = True
            try:
                m = speed.measure(
                    self.client(), full=full, clock=self._clock, on_sample=self._sample
                )
            finally:
                self.testing = False
            self.last = m
            if m.upload_mbps is not None:
                self.last_upload = m.upload_mbps
            if m.colo:
                self.last_server = speed.to_json(m)["server"]
            if m.client_ip and m.client_ip not in self._isp:
                self._isp[m.client_ip] = speed.isp_lookup(self.client())
        return self.snapshot()

    def connection(self) -> speed.Connection:
        now = time.monotonic()
        if self._conn is None or now - self._conn[0] > CONNECTION_TTL:
            self._conn = (now, self._connection())
        return self._conn[1]

    def snapshot(self) -> dict[str, Any]:
        m = self.last
        base: dict[str, Any] = (
            speed.to_json(m)
            if m
            else {
                "measured_at": None,
                "online": False,
                "latency_ms": None,
                "download_mbps": None,
                "upload_mbps": None,
                "server": {"colo": None, "location": None, "ip_version": None},
                "error": None,
            }
        )
        if base["upload_mbps"] is None:
            base["upload_mbps"] = self.last_upload
        if self.testing:  # a leg that has landed replaces the last answer's figure at once
            base.update(self.live)
        if base["server"]["colo"] is None and self.last_server:
            base["server"] = self.last_server
        asn, isp = self._isp.get(m.client_ip or "", (None, None)) if m else (None, None)
        conn = self.connection()
        base["testing"] = self.testing
        base["samples"] = {k: list(v) for k, v in self._tape.items()}
        base["connection"] = {**speed.connection_dict(conn), "isp": isp, "asn": asn}
        return base
