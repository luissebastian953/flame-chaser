"""The character form's name suggestions: coreflame.names behind a cache.

A lookup costs ~4 requests to Danbooru and ~2 to Wikidata (a few seconds at
their polite 1 req/s), and the form asks again whenever a name changes, so
answers are cached per set of queries for a day. An answer with a source
error is not cached: the next keystroke retries it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict

from coreflame import __version__
from coreflame.config import Config
from coreflame.names import Fetch, lookup, make_fetchers, norm

NAMES_TTL = 24 * 3600.0
# Wikimedia's robot policy (https://w.wiki/4wJS) wants contact info in the
# User-Agent, and only a real URL counts: "github.com/..." without the scheme
# got 403 "Please respect our robot policy"; with https:// it gets 200.
USER_AGENT = (
    f"Curio/{__version__} (https://github.com/luissebastian953/flame-chaser; personal art archive)"
)


class NameFinder:
    def __init__(self, cfg: Config, fetchers: tuple[Fetch, Fetch] | None = None) -> None:
        self.cfg = cfg
        self._fetchers = fetchers
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, ...], tuple[float, dict]] = {}

    def reset(self) -> None:
        """Network settings changed: new clients, and forget what they said."""
        with self._lock:
            self._fetchers = None
            self._cache.clear()

    def _clients(self) -> tuple[Fetch, Fetch]:
        with self._lock:
            if self._fetchers is None:
                self._fetchers = make_fetchers(self.cfg, USER_AGENT)
            return self._fetchers

    def find(self, queries: list[str]) -> dict:
        key = tuple(dict.fromkeys(norm(q) for q in queries if q and q.strip()))
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < NAMES_TTL:
                return hit[1]
        danbooru, wikidata = self._clients()
        result = asdict(lookup(queries, danbooru, wikidata))
        if not result["errors"]:
            with self._lock:
                self._cache[key] = (now, result)
        return result
