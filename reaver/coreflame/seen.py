"""The visited set -- mark before you spend a request.

`posts` cannot be the gate: it only holds artworks we KEPT. The visited set is
the superset: everything ever observed in a listing, including what we rejected
and what no longer exists. It is consulted from the search listing, where the
id is free, before any per-item detail request is spent.

Four states, four retry policies. Collapsing them is the bug:

    indexed  kept; a posts row exists          never revisit
    skipped  rejected by config                 only if THAT config changes
    gone     404/410 -- deleted or privated     never revisit
    failed   5xx / timeout / reset              after retry_after, with backoff
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class SeenState(str, Enum):
    INDEXED = "indexed"
    SKIPPED = "skipped"
    GONE = "gone"
    FAILED = "failed"


class SkipReason(str, Enum):
    BELOW_MIN_BOOKMARKS = "below_min_bookmarks"
    R18_EXCLUDED = "r18_excluded"
    UGOIRA = "ugoira"
    NO_MATCH = "no_match"  # X: followed artist's post named no watch
    DELETED = "deleted"  # the user deleted every image and chose to forget the post;
    # no config change reopens it (coreflame/trash.py)


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_posts (
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    state         TEXT NOT NULL,
    reason        TEXT,
    threshold     INTEGER,        -- the config value that caused a skip
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    retry_after   TEXT,           -- transient failures only
    failures      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, external_id)
);
CREATE INDEX IF NOT EXISTS seen_state ON seen_posts(state, retry_after);
"""

_BACKOFF = (timedelta(minutes=30), timedelta(hours=6), timedelta(days=1), timedelta(days=7))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SeenRow:
    state: SeenState
    reason: str | None
    threshold: int | None
    retry_after: str | None
    failures: int


class Seen:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        conn.executescript(SCHEMA)

    # -- the gate ---------------------------------------------------------
    def should_fetch(self, source: str, external_id: str) -> bool:
        """True if this id has never been observed, or its failure backoff
        has elapsed. Everything else is a request that never happens."""
        r = self.conn.execute(
            "SELECT state, retry_after FROM seen_posts WHERE source=? AND external_id=?",
            (source, external_id),
        ).fetchone()
        if r is None:
            return True
        state, retry_after = r[0], r[1]
        if state == SeenState.FAILED:
            return retry_after is None or retry_after <= _now()
        return False

    def get(self, source: str, external_id: str) -> SeenRow | None:
        r = self.conn.execute(
            "SELECT state, reason, threshold, retry_after, failures "
            "FROM seen_posts WHERE source=? AND external_id=?",
            (source, external_id),
        ).fetchone()
        return SeenRow(SeenState(r[0]), r[1], r[2], r[3], r[4]) if r else None

    # -- marking ----------------------------------------------------------
    def mark(
        self,
        source: str,
        external_id: str,
        state: SeenState,
        *,
        reason: str | None = None,
        threshold: int | None = None,
    ) -> None:
        now = _now()
        self.conn.execute(
            """INSERT INTO seen_posts(source,external_id,state,reason,threshold,
                                      first_seen,last_seen,retry_after,failures)
               VALUES(?,?,?,?,?,?,?,NULL,0)
               ON CONFLICT(source,external_id) DO UPDATE SET
                 state=excluded.state, reason=excluded.reason,
                 threshold=excluded.threshold, last_seen=excluded.last_seen,
                 retry_after=NULL, failures=0""",
            (source, external_id, state.value, reason, threshold, now, now),
        )

    def mark_failed(self, source: str, external_id: str, reason: str) -> str:
        """Transient failure: schedule a retry with escalating backoff.
        Returns the retry_after timestamp."""
        row = self.get(source, external_id)
        n = (row.failures if row and row.state == SeenState.FAILED else 0) + 1
        delay = _BACKOFF[min(n, len(_BACKOFF)) - 1]
        retry_after = (datetime.now(timezone.utc) + delay).isoformat()
        now = _now()
        self.conn.execute(
            """INSERT INTO seen_posts(source,external_id,state,reason,threshold,
                                      first_seen,last_seen,retry_after,failures)
               VALUES(?,?,'failed',?,NULL,?,?,?,?)
               ON CONFLICT(source,external_id) DO UPDATE SET
                 state='failed', reason=excluded.reason,
                 last_seen=excluded.last_seen,
                 retry_after=excluded.retry_after, failures=excluded.failures""",
            (source, external_id, reason, now, now, retry_after, n),
        )
        return retry_after

    # -- invalidation -----------------------------------------------------
    def reopen_skipped(
        self, source: str, reason: SkipReason, new_threshold: int | None = None
    ) -> int:
        """Config changed: forget skips it caused so they get re-evaluated.

        For BELOW_MIN_BOOKMARKS only skips whose recorded threshold is above
        the new value are reopened -- lowering 500 -> 100 reopens posts skipped
        at 500; raising 100 -> 500 reopens nothing. Reason-only skips
        (R18_EXCLUDED, NO_MATCH) reopen wholesale.
        """
        if new_threshold is not None:
            cur = self.conn.execute(
                "DELETE FROM seen_posts WHERE source=? AND state='skipped' "
                "AND reason=? AND (threshold IS NULL OR threshold > ?)",
                (source, reason.value, new_threshold),
            )
        else:
            cur = self.conn.execute(
                "DELETE FROM seen_posts WHERE source=? AND state='skipped' AND reason=?",
                (source, reason.value),
            )
        return cur.rowcount

    def stats(self, source: str | None = None) -> dict[str, int]:
        where, args = ("WHERE source=?", (source,)) if source else ("", ())
        rows = self.conn.execute(
            f"SELECT state, count(*) FROM seen_posts {where} GROUP BY state", args
        ).fetchall()
        out = {s.value: 0 for s in SeenState}
        for state, n in rows:
            out[state] = n
        out["total"] = sum(out.values())
        return out
