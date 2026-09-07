"""Forward-only schema migrations. Thirty lines, not Alembic.

Each migration runs in its own transaction. The db file is backed up before
any migration applies -- it is small, migrations are rare, and the backup is
the only undo that exists. `min_app_version` lets an older daemon refuse a
newer schema instead of half-reading it (§8b.4 of the design doc).
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

Migration = tuple[int, str, str]  # (version, name, sql)

MIGRATIONS: list[Migration] = []


def migration(version: int, name: str) -> Callable[[Callable[[], str]], None]:
    def reg(fn: Callable[[], str]) -> None:
        MIGRATIONS.append((version, name, fn()))

    return reg


def _statements(sql: str) -> list[str]:
    out, buf = [], []
    for line in sql.splitlines():
        stripped = line.split("--", 1)[0]  # DDL only; no ';' in strings
        buf.append(stripped)
        if stripped.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt.strip(";").strip():
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail.strip(";").strip():
        out.append(tail)
    return out


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL,
        min_app_version TEXT)""")
    row = conn.execute("SELECT max(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def apply(conn: sqlite3.Connection, db_path: Path, app_version: str) -> list[str]:
    have = current_version(conn)
    pending = sorted((m for m in MIGRATIONS if m[0] > have), key=lambda m: m[0])
    if not pending:
        return []
    if have > 0 and db_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(
            db_path, db_path.with_name(f"{db_path.name}.pre-v{pending[-1][0]}.{stamp}.bak")
        )
    applied = []
    for version, name, sql in pending:
        # executescript() COMMITs before it runs, which would break the
        # one-transaction-per-migration guarantee; run statements ourselves
        conn.execute("BEGIN")
        try:
            for stmt in _statements(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_version(version,name,applied_at,min_app_version) VALUES(?,?,?,?)",
                (version, name, datetime.now(timezone.utc).isoformat(), app_version),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(f"v{version} {name}")
    return applied


# ---------------------------------------------------------------- v1
@migration(1, "initial")
def _v1() -> str:
    return """
CREATE TABLE IF NOT EXISTS watches (
    slug          TEXT PRIMARY KEY,
    label         TEXT NOT NULL DEFAULT '',
    pixiv_tags    TEXT NOT NULL DEFAULT '[]',
    match_terms   TEXT NOT NULL DEFAULT '[]',
    min_bookmarks INTEGER NOT NULL DEFAULT 0,
    include_r18   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS artists (
    source          TEXT NOT NULL,
    artist_id       TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    handle          TEXT NOT NULL DEFAULT '',
    twitter_handle  TEXT,
    followed        INTEGER NOT NULL DEFAULT 0,
    checked_at      TEXT,
    PRIMARY KEY (source, artist_id)
);

CREATE TABLE IF NOT EXISTS posts (
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    artist_id     TEXT NOT NULL,
    artist_name   TEXT NOT NULL DEFAULT '',
    artist_handle TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL DEFAULT '',
    caption       TEXT NOT NULL DEFAULT '',
    page_count    INTEGER NOT NULL DEFAULT 1,
    illust_type   TEXT NOT NULL DEFAULT 'illust',
    is_r18        INTEGER NOT NULL DEFAULT 0,
    posted_at     TEXT,
    fetched_at    TEXT NOT NULL,
    permalink     TEXT NOT NULL DEFAULT '',
    bookmark_count INTEGER NOT NULL DEFAULT 0,
    source_meta   TEXT NOT NULL DEFAULT '{}',   -- per-source extras, JSON
    raw_sha       TEXT,                          -- -> raw_payloads
    state         TEXT NOT NULL DEFAULT 'live',  -- live | gone
    PRIMARY KEY (source, external_id)
);
CREATE INDEX IF NOT EXISTS posts_artist ON posts(source, artist_id);
CREATE INDEX IF NOT EXISTS posts_posted ON posts(posted_at DESC, external_id DESC);

CREATE TABLE IF NOT EXISTS post_watches (
    source      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    slug        TEXT NOT NULL,
    PRIMARY KEY (source, external_id, slug)
);
CREATE INDEX IF NOT EXISTS post_watches_slug ON post_watches(slug);

-- two forms on purpose: raw is what pixiv's exact-tag search matches on,
-- norm (NFKC+casefold) is what grouping, dedupe and ranking use
CREATE TABLE IF NOT EXISTS post_tags (
    source      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    tag_raw     TEXT NOT NULL,
    tag_norm    TEXT NOT NULL,
    translated  TEXT,
    PRIMARY KEY (source, external_id, tag_norm)
);
CREATE INDEX IF NOT EXISTS post_tags_norm ON post_tags(tag_norm);

CREATE TABLE IF NOT EXISTS media (
    source      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    sha256      TEXT,
    phash       INTEGER,
    bytes       INTEGER,
    width       INTEGER NOT NULL DEFAULT 0,
    height      INTEGER NOT NULL DEFAULT 0,
    ext         TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL DEFAULT 'pending',
    dupe_of     TEXT,
    error       TEXT,
    PRIMARY KEY (source, external_id, idx)
);
CREATE INDEX IF NOT EXISTS media_sha   ON media(sha256);
CREATE INDEX IF NOT EXISTS media_state ON media(state);
CREATE INDEX IF NOT EXISTS media_phash ON media(phash);

-- the JSON as fetched, zlib'd, content-addressed. Re-normalising after a
-- spec fix is a re-parse, never a re-fetch.
CREATE TABLE IF NOT EXISTS raw_payloads (
    sha256      TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL,        -- pixiv_detail | pixiv_pages | twitter_entry ...
    external_id TEXT,
    body        BLOB NOT NULL,        -- zlib(json)
    bytes_raw   INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS raw_by_post ON raw_payloads(source, external_id);

-- a record that fails validation lands here, never crashes and never vanishes
CREATE TABLE IF NOT EXISTS quarantine (
    source      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    raw_sha     TEXT,
    error       TEXT NOT NULL,
    extracted   TEXT,                 -- the dict that failed, JSON
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (source, external_id)
);

CREATE TABLE IF NOT EXISTS poll_state (
    source     TEXT NOT NULL,
    feed       TEXT NOT NULL,
    watermark  TEXT,
    updated_at TEXT,
    PRIMARY KEY (source, feed)
);

-- one row per (character, run) per field: the drift alarm's history
CREATE TABLE IF NOT EXISTS extraction_stats (
    run_id      TEXT NOT NULL,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    field       TEXT NOT NULL,
    rows        INTEGER NOT NULL,
    null_rate   REAL NOT NULL,
    at          TEXT NOT NULL,
    PRIMARY KEY (run_id, source, kind, field)
);
"""


# ---------------------------------------------------------------- v2
@migration(2, "tag_stats")
def _v2() -> str:
    return """
-- derived from post_tags x post_watches; rebuildable. `state` is the only
-- column that carries user intent and survives a rebuild.
CREATE TABLE IF NOT EXISTS tag_stats (
    slug        TEXT NOT NULL,
    tag_norm    TEXT NOT NULL,
    tag_raw     TEXT NOT NULL,       -- most common raw spelling, for re-crawl
    translated  TEXT,
    posts       INTEGER NOT NULL,    -- posts of this character carrying it
    share       REAL NOT NULL,       -- posts / posts_for_character
    characters  INTEGER NOT NULL,    -- watched characters carrying it at all
    score       REAL NOT NULL,       -- share * log(N/characters); share if N=1
    state       TEXT NOT NULL DEFAULT 'suggested',   -- watched | suggested | ignored
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (slug, tag_norm)
);
CREATE INDEX IF NOT EXISTS tag_stats_rank ON tag_stats(slug, state, score DESC);
"""


# ---------------------------------------------------------------- v3
@migration(3, "jobs")
def _v3() -> str:
    return """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,          -- poll | link | media | backfill | reindex | tags
    params        TEXT NOT NULL DEFAULT '{}',
    state         TEXT NOT NULL,          -- queued | running | succeeded | failed
                                          -- | cancelled | interrupted
    stage         TEXT,
    done          INTEGER NOT NULL DEFAULT 0,
    total         INTEGER,                -- NULL = no honest denominator
    counters      TEXT NOT NULL DEFAULT '{}',
    error         TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,   -- set from any process
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, created_at);

-- per-job log ring; the daemon streams these as SSE and the UI shows the tail
CREATE TABLE IF NOT EXISTS job_log (
    job_id  TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    at      TEXT NOT NULL,
    level   TEXT NOT NULL,
    kind    TEXT NOT NULL,           -- stage | item | progress | log
    message TEXT NOT NULL,
    data    TEXT,                    -- JSON
    PRIMARY KEY (job_id, seq)
);
"""
