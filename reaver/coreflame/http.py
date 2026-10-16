"""Polite HTTP layer: per-host token buckets, honest retries, 429 handling.

Two layers of bucket on purpose: a global one per source so a burst of image
downloads can't starve the metadata endpoint, and a per-endpoint one for the
endpoints that are documented (or observed) to be stricter than the rest.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from typing import Any

import httpx

if False:  # typing only; net imports httpx, not this module
    from .net import DohResolver

log = logging.getLogger(__name__)

# A real UA. Not spoofing a bot as a browser to defeat a block -- these sites
# serve JSON only to browser-shaped clients, and an honest contact string is
# what makes a rate-limited client identifiable instead of anonymous noise.
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 "
    "reaver/0.1 (personal archive; contact: you@example.com)"
)


class TokenBucket:
    def __init__(self, rate: float, burst: float | None = None) -> None:
        self.rate = rate
        self.capacity = burst if burst is not None else max(1.0, rate)
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def take(self, n: float = 1.0) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                deficit = (n - self._tokens) / self.rate
            time.sleep(deficit)


class Meter:
    """Requests actually sent, per budget, over the last minute -- what the
    pipeline's Rate budget panel and each worker's req/min read. Process-wide
    because adapters are built per job; a budget is declared once with its
    configured rate and re-declared when a later adapter is built with another.
    A hit is tagged with the job bound to the sending thread, so a worker's
    req/min is its own requests, not its lane's neighbour's."""

    WINDOW = 60.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._budgets: dict[str, tuple[str, float | None]] = {}
        self._hits: deque[tuple[float, str, str | None]] = deque()
        self._local = threading.local()

    def declare(self, key: str, label: str, rate: float | None) -> None:
        """`rate` is requests per second; None = paced by something else (gallery-dl)."""
        with self._lock:
            self._budgets[key] = (label, rate)

    def bind(self, job_id: str | None) -> None:
        self._local.job = job_id

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._hits.append((now, key, getattr(self._local, "job", None)))
            self._trim(now)

    def _trim(self, now: float) -> None:
        while self._hits and now - self._hits[0][0] > self.WINDOW:
            self._hits.popleft()

    def snapshot(self) -> list[dict[str, Any]]:
        """Every declared budget, in declaration order, with its last minute."""
        with self._lock:
            self._trim(time.monotonic())
            counts: dict[str, int] = {}
            for _, key, _ in self._hits:
                counts[key] = counts.get(key, 0) + 1
            return [
                {"key": k, "label": label, "rate": rate, "per_min": counts.get(k, 0)}
                for k, (label, rate) in self._budgets.items()
            ]

    def per_job(self) -> dict[str, int]:
        with self._lock:
            self._trim(time.monotonic())
            out: dict[str, int] = {}
            for _, _, job in self._hits:
                if job is not None:
                    out[job] = out.get(job, 0) + 1
            return out


METER = Meter()


class RetryableError(RuntimeError):
    pass


class SourceClient:
    """One per source. Owns cookies, headers and the rate budget."""

    def __init__(
        self,
        base_headers: dict[str, str],
        cookies: dict[str, str] | None = None,
        rate: float = 1.0,
        burst: float = 3.0,
        timeout: float = 30.0,
        max_retries: int = 4,
        resolver: DohResolver | None = None,
        proxy: str | None = None,
        meter: tuple[str, str] | None = None,
    ) -> None:
        """`meter` = (key, label) under which METER counts this client's
        requests; an endpoint limited later is counted as `key.endpoint`."""
        headers = {"User-Agent": DEFAULT_UA, **base_headers}
        # Layer 1: DoH resolver (defeats DNS hijacking). Layer 2: a proxy
        # (the only thing that survives SNI/DPI, and the only setting shared
        # with gallery-dl). With a proxy the proxy resolves, so DoH is moot.
        transport = None
        if resolver is not None and not proxy:
            from .net import DohTransport

            transport = DohTransport(resolver)
        self._client = httpx.Client(
            headers=headers,
            cookies=cookies or {},
            timeout=timeout,
            follow_redirects=True,
            http2=False,
            transport=transport,
            proxy=proxy,
        )
        self._global = TokenBucket(rate, burst)
        self._endpoint: dict[str, TokenBucket] = {}
        self.max_retries = max_retries
        self._meter = meter[0] if meter else None
        if meter:
            METER.declare(meter[0], meter[1], rate)

    def limit_endpoint(
        self, name: str, rate: float, burst: float = 1.0, label: str | None = None
    ) -> None:
        self._endpoint[name] = TokenBucket(rate, burst)
        if self._meter:
            METER.declare(f"{self._meter}.{name}", label or name, rate)

    def get(self, url: str, *, bucket: str | None = None, **kw: Any) -> httpx.Response:
        if bucket and bucket in self._endpoint:
            self._endpoint[bucket].take()
        self._global.take()

        metered = None
        if self._meter:
            metered = f"{self._meter}.{bucket}" if bucket in self._endpoint else self._meter
        last: Exception | None = None
        for attempt in range(self.max_retries):
            if metered:
                METER.hit(metered)  # every attempt is a request the site sees
            try:
                r = self._client.get(url, **kw)
            except httpx.TransportError as e:  # DNS, TLS, timeouts
                last = e
            else:
                # 4xx other than 429 is a bug in our request, not weather.
                # Retrying it is how an IP ban happens.
                if r.status_code == 429:
                    wait = float(r.headers.get("Retry-After", 0) or 0)
                    wait = wait or min(60.0, 2**attempt)
                    log.warning("429 on %s, sleeping %.1fs", url, wait)
                    time.sleep(wait + random.uniform(0, 1))
                    last = RetryableError("429")
                    continue
                if 500 <= r.status_code < 600:
                    last = RetryableError(f"{r.status_code}")
                elif r.status_code >= 400:
                    r.raise_for_status()
                else:
                    return r
            time.sleep(min(30.0, 2**attempt) + random.uniform(0, 0.5))
        raise RetryableError(f"giving up on {url}: {last}")

    def get_json(self, url: str, *, bucket: str | None = None, **kw: Any) -> Any:
        return self.get(url, bucket=bucket, **kw).json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SourceClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
