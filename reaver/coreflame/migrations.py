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


# ---------------------------------------------------------------- v4
@migration(4, "watch_sources")
def _v4() -> str:
    # per-watch source selection; existing watches keep crawling both
    return """
ALTER TABLE watches ADD COLUMN sources TEXT NOT NULL DEFAULT '["pixiv","twitter"]';
"""


# ---------------------------------------------------------------- v5
@migration(5, "image_kinds")
def _v5() -> str:
    # what an image IS (illustration, photo, 3D render...), keyed by the blob's
    # sha: reposts share one row, and a new model is a re-label, not a re-fetch.
    # No row = not labeled yet, which the gallery shows rather than hides.
    return """
CREATE TABLE IF NOT EXISTS image_kinds (
    sha256     TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    scores     TEXT NOT NULL,
    model      TEXT NOT NULL,
    labeled_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS image_kinds_kind ON image_kinds(kind);
"""


# ---------------------------------------------------------------- v6
@migration(6, "watch_target_kind_filter")
def _v6() -> str:
    # posts per run and the image-kind filter, per character; existing
    # characters get the defaults the app already used (100, filter on)
    return """
ALTER TABLE watches ADD COLUMN target INTEGER NOT NULL DEFAULT 100;
ALTER TABLE watches ADD COLUMN kind_filter INTEGER NOT NULL DEFAULT 1;
"""


# ---------------------------------------------------------------- v7
@migration(7, "gender_filter")
def _v7() -> str:
    # who is in each image (coreflame/people.py), keyed by the blob's sha like
    # image_kinds; and each character's gender filter, off for existing ones
    return """
CREATE TABLE IF NOT EXISTS image_people (
    sha256     TEXT PRIMARY KEY,
    girls      INTEGER NOT NULL,
    boys       INTEGER NOT NULL,
    male_focus INTEGER NOT NULL,
    scores     TEXT NOT NULL,
    characters TEXT NOT NULL,
    model      TEXT NOT NULL,
    tagged_at  TEXT NOT NULL
);
ALTER TABLE watches ADD COLUMN gender TEXT NOT NULL DEFAULT 'any';
ALTER TABLE watches ADD COLUMN gender_mode TEXT NOT NULL DEFAULT 'full';
"""


@migration(8, "character_identity")
def _v8() -> str:
    # who the character in each image is (coreflame/identify.py), keyed by the
    # blob's sha like image_kinds: the verdict + both models' candidates, and one
    # row per character named -- what the gallery's character filter reads
    return """
CREATE TABLE IF NOT EXISTS image_identity (
    sha256        TEXT PRIMARY KEY,
    state         TEXT NOT NULL CHECK (state IN ('identified','unidentified')),
    candidates    TEXT NOT NULL,
    model         TEXT NOT NULL,
    identified_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS image_characters (
    sha256 TEXT NOT NULL,
    name   TEXT NOT NULL,
    tag    TEXT NOT NULL,
    score  REAL NOT NULL,
    by     TEXT NOT NULL,
    PRIMARY KEY (sha256, name)
);
CREATE INDEX IF NOT EXISTS image_characters_name ON image_characters(name)
"""


@migration(9, "job_lanes")
def _v9() -> str:
    # one worker per source (coreflame/jobs.py): the lane a job may run on,
    # the lane that ran it, its place in the queue (reorder / run now), and a
    # pause flag that, like cancel_requested, any process can set
    return """
ALTER TABLE jobs ADD COLUMN lane TEXT NOT NULL DEFAULT 'pixiv';
ALTER TABLE jobs ADD COLUMN worker TEXT;
ALTER TABLE jobs ADD COLUMN position REAL NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN pause_requested INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(state, lane, position)
"""


@migration(10, "trash")
def _v10() -> str:
    # deleting images from a gallery (coreflame/trash.py): every deletion is a
    # batch, each trashed image keeps its media row as JSON so Undo can put it
    # back exactly, and a forgotten post rides along in the batch's snapshot
    return """
CREATE TABLE IF NOT EXISTS trash_batches (
    id          TEXT PRIMARY KEY,
    slug        TEXT NOT NULL,
    mode        TEXT NOT NULL,              -- image | tag | smart | all
    created_at  TEXT NOT NULL,
    images      INTEGER NOT NULL,
    bytes       INTEGER NOT NULL,
    forgotten   INTEGER NOT NULL DEFAULT 0,
    snapshot    TEXT NOT NULL DEFAULT '{}'  -- forgotten posts + reopened visited rows, JSON
);
CREATE TABLE IF NOT EXISTS trash_items (
    source      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    ext         TEXT NOT NULL DEFAULT '',
    bytes       INTEGER,
    batch_id    TEXT NOT NULL,
    row         TEXT NOT NULL,              -- the media row, JSON
    deleted_at  TEXT NOT NULL,
    PRIMARY KEY (source, external_id, idx)
);
CREATE INDEX IF NOT EXISTS trash_items_batch ON trash_items(batch_id);
CREATE INDEX IF NOT EXISTS trash_items_age ON trash_items(deleted_at)
"""


@migration(11, "media_variant")
def _v11() -> str:
    # which size the source handed over (pixiv `original`; X `orig`, or
    # `4096x4096` when orig 404s) so a later pass can find rows worth
    # refetching. Older rows keep '' and the detail route derives it from the url.
    return "ALTER TABLE media ADD COLUMN source_variant TEXT NOT NULL DEFAULT ''"


@migration(12, "queue_state")
def _v12() -> str:
    # the queue's own state, outside any job row: today only `held` ("1" while
    # the queue is paused). It is what makes a pause survive a restart -- the
    # runner reads it at boot, and a crawl that died while the queue was held
    # goes back to the front of the queue instead of being marked interrupted.
    return """
CREATE TABLE IF NOT EXISTS queue_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""


@migration(13, "image_origin")
def _v13() -> str:
    # how each image was made (coreflame/origin.py), keyed by the blob's sha
    # like image_kinds: ai or human, and what said so - the artist's pixiv flag,
    # an AI hashtag, or the detector (with its score, so the cut can move).
    # No row = not judged yet, which the gallery shows rather than hides.
    return """
CREATE TABLE IF NOT EXISTS image_origin (
    sha256    TEXT PRIMARY KEY,
    state     TEXT NOT NULL CHECK (state IN ('ai','human')),
    by        TEXT NOT NULL CHECK (by IN ('declared','tags','model')),
    score     REAL,
    model     TEXT NOT NULL DEFAULT '',
    judged_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS image_origin_state ON image_origin(state)
"""


@migration(14, "image_label")
def _v14() -> str:
    # a label set by hand (coreflame/label.py), keyed by the blob's sha: it
    # wins over every classifier verdict and survives re-labelling. A row with
    # a NULL label is "no label", chosen by hand; no row = the fold decides.
    return """
CREATE TABLE IF NOT EXISTS image_label (
    sha256 TEXT PRIMARY KEY,
    label  TEXT CHECK (label IS NULL OR label IN ('ai','non_illust','unidentified')),
    set_at TEXT NOT NULL
)
"""
