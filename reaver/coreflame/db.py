"""SQLite store. Every write is an idempotent upsert on a natural key, which is
what makes the poller's deliberate overlap window safe instead of a duplicate
factory. Schema lives in migrations.py; this file is the repository."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__, migrations
from .models import IllustRecord, Watch
from .phash import from_signed, to_signed
from .seen import Seen, SkipReason


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path, *, check_same_thread: bool = True) -> None:
        """`check_same_thread=False` is for a connection that lives exactly one
        request and is used sequentially: FastAPI runs a sync dependency and
        the endpoint it feeds on different threadpool threads. Never share such
        a Store between requests -- one connection, one caller at a time."""
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=check_same_thread
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.applied = migrations.apply(self.conn, self.path, __version__)
        self.seen = Seen(self.conn)

    # ------------------------------------------------------------ watches
    def upsert_watch(self, w: Watch) -> int:
        """Returns how many previously-skipped artworks the new config
        reopens (lowered min_bookmarks, or R-18 newly included)."""
        old = self.conn.execute(
            "SELECT min_bookmarks, include_r18 FROM watches WHERE slug=?", (w.slug,)
        ).fetchone()
        reopened = 0
        if old is not None:
            if w.min_bookmarks < old["min_bookmarks"]:
                reopened += self.seen.reopen_skipped(
                    "pixiv", SkipReason.BELOW_MIN_BOOKMARKS, w.min_bookmarks
                )
            if w.include_r18 and not old["include_r18"]:
                reopened += self.seen.reopen_skipped("pixiv", SkipReason.R18_EXCLUDED)
        self.conn.execute(
            """INSERT INTO watches(slug,label,pixiv_tags,match_terms,min_bookmarks,include_r18)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(slug) DO UPDATE SET
                 label=excluded.label, pixiv_tags=excluded.pixiv_tags,
                 match_terms=excluded.match_terms,
                 min_bookmarks=excluded.min_bookmarks, include_r18=excluded.include_r18""",
            (
                w.slug,
                w.label,
                json.dumps(w.pixiv_tags, ensure_ascii=False),
                json.dumps(w.match_terms, ensure_ascii=False),
                w.min_bookmarks,
                int(w.include_r18),
            ),
        )
        return reopened

    def watches(self) -> list[Watch]:
        rows = self.conn.execute("SELECT * FROM watches ORDER BY slug").fetchall()
        return [
            Watch(
                slug=r["slug"],
                label=r["label"],
                pixiv_tags=json.loads(r["pixiv_tags"]),
                match_terms=json.loads(r["match_terms"]),
                min_bookmarks=r["min_bookmarks"],
                include_r18=bool(r["include_r18"]),
            )
            for r in rows
        ]

    # -------------------------------------------------------- raw payloads
    def put_raw(self, source: str, kind: str, payload: Any, external_id: str | None = None) -> str:
        """Retain the fetched JSON, content-addressed and zlib'd. Idempotent."""
        body = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        sha = hashlib.sha256(body).hexdigest()
        self.conn.execute(
            """INSERT OR IGNORE INTO raw_payloads(sha256,source,kind,external_id,body,bytes_raw,fetched_at)
               VALUES(?,?,?,?,?,?,?)""",
            (sha, source, kind, external_id, zlib.compress(body, 6), len(body), _now()),
        )
        return sha

    def get_raw(self, sha: str) -> Any | None:
        r = self.conn.execute("SELECT body FROM raw_payloads WHERE sha256=?", (sha,)).fetchone()
        return json.loads(zlib.decompress(r["body"])) if r else None

    def raws_for(self, source: str, kind: str) -> Iterator[tuple[str, str | None, Any]]:
        """(sha, external_id, payload) for every retained payload of a kind --
        this is what re-normalisation after a spec fix iterates over."""
        cur = self.conn.execute(
            "SELECT sha256, external_id, body FROM raw_payloads WHERE source=? AND kind=?",
            (source, kind),
        )
        for r in cur:
            yield r["sha256"], r["external_id"], json.loads(zlib.decompress(r["body"]))

    # ---------------------------------------------------------- quarantine
    def quarantine(
        self,
        source: str,
        external_id: str,
        error: str,
        extracted: dict | None = None,
        raw_sha: str | None = None,
    ) -> None:
        now = _now()
        self.conn.execute(
            """INSERT INTO quarantine(source,external_id,raw_sha,error,extracted,first_seen,last_seen,attempts)
               VALUES(?,?,?,?,?,?,?,1)
               ON CONFLICT(source,external_id) DO UPDATE SET
                 raw_sha=COALESCE(excluded.raw_sha, quarantine.raw_sha),
                 error=excluded.error, extracted=excluded.extracted,
                 last_seen=excluded.last_seen, attempts=quarantine.attempts+1""",
            (
                source,
                external_id,
                raw_sha,
                error[:2000],
                json.dumps(extracted, ensure_ascii=False, default=str) if extracted else None,
                now,
                now,
            ),
        )

    def release_quarantine(self, source: str, external_id: str) -> None:
        self.conn.execute(
            "DELETE FROM quarantine WHERE source=? AND external_id=?", (source, external_id)
        )

    # --------------------------------------------------------------- posts
    def upsert_post(self, rec: IllustRecord, slug: str | None = None) -> bool:
        """Returns True if this post was not already known. Atomic: the post,
        its tags, media rows and artist land together or not at all, so a
        cancel between records can never leave a half-written record."""
        with self.tx():
            return self._upsert_post(rec, slug)

    def _upsert_post(self, rec: IllustRecord, slug: str | None = None) -> bool:
        is_new = (
            self.conn.execute(
                "SELECT 1 FROM posts WHERE source=? AND external_id=?", rec.key
            ).fetchone()
            is None
        )
        self.conn.execute(
            """INSERT INTO posts(source,external_id,artist_id,artist_name,artist_handle,
                   title,caption,page_count,illust_type,is_r18,posted_at,fetched_at,
                   permalink,bookmark_count,source_meta,raw_sha)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source,external_id) DO UPDATE SET
                 artist_name=excluded.artist_name, artist_handle=excluded.artist_handle,
                 title=excluded.title, caption=excluded.caption,
                 page_count=excluded.page_count, illust_type=excluded.illust_type,
                 is_r18=excluded.is_r18,
                 posted_at=COALESCE(excluded.posted_at, posts.posted_at),
                 permalink=excluded.permalink, bookmark_count=excluded.bookmark_count,
                 source_meta=excluded.source_meta,
                 raw_sha=COALESCE(excluded.raw_sha, posts.raw_sha)""",
            (
                rec.source,
                rec.external_id,
                rec.artist_id,
                rec.artist_name,
                rec.artist_handle,
                rec.title,
                rec.caption,
                rec.page_count,
                rec.illust_type,
                int(rec.is_r18),
                _iso(rec.posted_at),
                _iso(rec.fetched_at),
                rec.permalink,
                rec.bookmark_count,
                json.dumps(rec.source_meta, ensure_ascii=False, default=str),
                rec.raw_sha,
            ),
        )
        if slug:
            self.conn.execute(
                "INSERT OR IGNORE INTO post_watches VALUES(?,?,?)",
                (rec.source, rec.external_id, slug),
            )
        # tags: replace the set, both forms
        self.conn.execute("DELETE FROM post_tags WHERE source=? AND external_id=?", rec.key)
        self.conn.executemany(
            "INSERT OR IGNORE INTO post_tags(source,external_id,tag_raw,tag_norm,translated) VALUES(?,?,?,?,?)",
            [(rec.source, rec.external_id, t.raw, t.norm, t.translated) for t in rec.tags],
        )
        for m in rec.media:
            self.conn.execute(
                """INSERT INTO media(source,external_id,idx,url,width,height) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(source,external_id,idx) DO UPDATE SET url=excluded.url""",
                (rec.source, rec.external_id, m.index, m.url, m.width, m.height),
            )
        self.conn.execute(
            """INSERT INTO artists(source,artist_id,name,handle) VALUES(?,?,?,?)
               ON CONFLICT(source,artist_id) DO UPDATE SET
                 name=excluded.name,
                 handle=CASE WHEN excluded.handle<>'' THEN excluded.handle ELSE artists.handle END""",
            (rec.source, rec.artist_id, rec.artist_name, rec.artist_handle),
        )
        self.release_quarantine(rec.source, rec.external_id)
        return is_new

    def mark_post_gone(self, source: str, external_id: str) -> bool:
        cur = self.conn.execute(
            "UPDATE posts SET state='gone' WHERE source=? AND external_id=? AND state<>'gone'",
            (source, external_id),
        )
        return cur.rowcount > 0

    # --------------------------------------------------------------- media
    def pending_media(self, limit: int = 200) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM media WHERE state='pending' LIMIT ?", (limit,)
        ).fetchall()

    def mark_media(
        self,
        source: str,
        external_id: str,
        idx: int,
        *,
        state: str,
        sha: str | None = None,
        phash: int | None = None,
        nbytes: int | None = None,
        ext: str = "",
        dupe_of: str | None = None,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """UPDATE media SET state=?, sha256=COALESCE(?,sha256), phash=COALESCE(?,phash),
                 bytes=COALESCE(?,bytes), ext=CASE WHEN ?<>'' THEN ? ELSE ext END,
                 dupe_of=?, error=?
               WHERE source=? AND external_id=? AND idx=?""",
            (
                state,
                sha,
                to_signed(phash) if phash is not None else None,
                nbytes,
                ext,
                ext,
                dupe_of,
                error,
                source,
                external_id,
                idx,
            ),
        )

    def phashes_for_artist(self, artist_id: str) -> list[tuple[str, int]]:
        """Candidate set for near-dupe search, scoped to one artist -- what
        keeps this O(hundreds) instead of O(archive)."""
        rows = self.conn.execute(
            """SELECT m.sha256, m.phash FROM media m
               JOIN posts p ON p.source=m.source AND p.external_id=m.external_id
               WHERE m.phash IS NOT NULL AND m.sha256 IS NOT NULL
                 AND (p.artist_id=? OR p.artist_handle=?)""",
            (artist_id, artist_id),
        ).fetchall()
        return [(r["sha256"], from_signed(r["phash"])) for r in rows]

    def sha_exists(self, sha: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM media WHERE sha256=? AND state='stored' LIMIT 1", (sha,)
            ).fetchone()
            is not None
        )

    # ------------------------------------------------------------- artists
    def set_twitter_handle(self, pixiv_user_id: str, handle: str | None) -> None:
        self.conn.execute(
            "UPDATE artists SET twitter_handle=?, checked_at=? WHERE source='pixiv' AND artist_id=?",
            (handle, _now(), pixiv_user_id),
        )

    def artists_needing_link(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM artists WHERE source='pixiv' AND checked_at IS NULL LIMIT ?", (limit,)
        ).fetchall()

    def followed_handles(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT twitter_handle FROM artists WHERE twitter_handle IS NOT NULL "
            "AND twitter_handle<>'' AND followed=1"
        ).fetchall()
        return [r["twitter_handle"] for r in rows]

    def follow(self, handle: str, on: bool = True) -> None:
        self.conn.execute("UPDATE artists SET followed=? WHERE twitter_handle=?", (int(on), handle))

    # ----------------------------------------------------------- watermarks
    def watermark(self, source: str, feed: str) -> str | None:
        r = self.conn.execute(
            "SELECT watermark FROM poll_state WHERE source=? AND feed=?", (source, feed)
        ).fetchone()
        return r["watermark"] if r else None

    def set_watermark(self, source: str, feed: str, value: str) -> None:
        self.conn.execute(
            """INSERT INTO poll_state(source,feed,watermark,updated_at) VALUES(?,?,?,?)
               ON CONFLICT(source,feed) DO UPDATE SET
                 watermark=excluded.watermark, updated_at=excluded.updated_at""",
            (source, feed, value, _now()),
        )

    # ---------------------------------------------------------------- drift
    def record_extraction(
        self, run_id: str, source: str, kind: str, rates: dict[str, float], rows: int
    ) -> None:
        now = _now()
        self.conn.executemany(
            "INSERT OR REPLACE INTO extraction_stats VALUES(?,?,?,?,?,?,?)",
            [(run_id, source, kind, f, rows, r, now) for f, r in rates.items()],
        )

    def extraction_drift(
        self, source: str, kind: str, threshold: float = 0.25
    ) -> list[tuple[str, float, float]]:
        """Fields whose null rate rose by more than `threshold` between the
        last two runs -- (field, previous, latest)."""
        rows = self.conn.execute(
            """SELECT field, null_rate, run_id FROM extraction_stats
               WHERE source=? AND kind=? ORDER BY at DESC""",
            (source, kind),
        ).fetchall()
        by_run: dict[str, dict[str, float]] = {}
        order: list[str] = []
        for r in rows:
            if r["run_id"] not in by_run:
                by_run[r["run_id"]] = {}
                order.append(r["run_id"])
            by_run[r["run_id"]][r["field"]] = r["null_rate"]
        if len(order) < 2:
            return []
        latest, prev = by_run[order[0]], by_run[order[1]]
        return [
            (f, prev.get(f, 0.0), latest[f])
            for f in latest
            if latest[f] - prev.get(f, 0.0) > threshold
        ]

    # ---------------------------------------------------------------- stats
    def stats(self) -> dict[str, int]:
        def q(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0])

        return {
            "schema_version": migrations.current_version(self.conn),
            "watches": q("SELECT count(*) FROM watches"),
            "posts": q("SELECT count(*) FROM posts"),
            "posts_pixiv": q("SELECT count(*) FROM posts WHERE source='pixiv'"),
            "posts_twitter": q("SELECT count(*) FROM posts WHERE source='twitter'"),
            "posts_gone": q("SELECT count(*) FROM posts WHERE state='gone'"),
            "media_total": q("SELECT count(*) FROM media"),
            "media_stored": q("SELECT count(*) FROM media WHERE state='stored'"),
            "media_pending": q("SELECT count(*) FROM media WHERE state='pending'"),
            "media_dupe": q("SELECT count(*) FROM media WHERE state='dupe'"),
            "media_failed": q("SELECT count(*) FROM media WHERE state='failed'"),
            "artists": q("SELECT count(*) FROM artists"),
            "linked_to_x": q("SELECT count(*) FROM artists WHERE twitter_handle IS NOT NULL"),
            "raw_payloads": q("SELECT count(*) FROM raw_payloads"),
            "raw_bytes": q("SELECT COALESCE(sum(length(body)),0) FROM raw_payloads"),
            "quarantined": q("SELECT count(*) FROM quarantine"),
            **{f"seen_{k}": v for k, v in self.seen.stats().items()},
        }

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()
