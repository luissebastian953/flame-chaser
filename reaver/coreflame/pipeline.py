"""Orchestration: discover -> persist -> link artists -> follow -> download."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .blobs import BlobStore
from .config import Config
from .db import Store
from .dedupe import classify
from .jobs import JobContext
from .library import LibraryView, safe_name
from .models import DiscoverStats, Watch
from .seen import SeenState, SkipReason
from .sources.pixiv import PixivAdapter
from .sources.twitter import GalleryDLError, TwitterAdapter
from .thumbs import ThumbStore

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    new_posts: int = 0
    seen_posts: int = 0
    downloaded: int = 0
    dupes: int = 0
    failed: int = 0
    listed: int = 0
    gated: int = 0  # requests that never happened
    skipped: int = 0
    gone: int = 0
    notes: list[str] = field(default_factory=list)

    def merge(self, other: RunStats) -> RunStats:
        for f in (
            "new_posts",
            "seen_posts",
            "downloaded",
            "dupes",
            "failed",
            "listed",
            "gated",
            "skipped",
            "gone",
        ):
            setattr(self, f, getattr(self, f) + getattr(other, f))
        self.notes += other.notes
        return self


def _ext_for(url: str) -> str:
    path = urlparse(url).path
    if "." in path.rsplit("/", 1)[-1]:
        return path.rsplit(".", 1)[-1].lower()[:5]
    return "jpg"


# -- pixiv: discovery -----------------------------------------------------
class _NullCtx:
    """Stand-in when no job runner is driving: checks and events are no-ops."""

    def check(self) -> None: ...
    def stage(self, name: str, **data: Any) -> None: ...
    def progress(self, done: int, total: int | None = None, **data: Any) -> None: ...
    def item(self, message: str, **data: Any) -> None: ...
    def log(self, message: str, level: str = "info", **data: Any) -> None: ...


def _ctx(ctx: JobContext | None) -> JobContext:
    return ctx if ctx is not None else _NullCtx()  # type: ignore[return-value]


DRIFT_FIELDS = ["external_id", "artist_id", "title", "tags", "posted_at", "bookmark_count"]


def _record_drift(store: Store, adapter, source: str, kind: str, st: RunStats) -> None:
    """Per-field null rates for this run, and a note if any field's rate
    jumped -- the only signal that catches a silent site-shape change."""
    import uuid

    from .sources.specs import null_rate

    rows = getattr(adapter, "extracted", [])
    if not rows:
        return
    rates = null_rate(rows, DRIFT_FIELDS)
    store.record_extraction(uuid.uuid4().hex[:12], source, kind, rates, len(rows))
    for fname, prev, now in store.extraction_drift(source, kind):
        st.notes.append(
            f"DRIFT {source}.{kind}.{fname}: null rate {prev:.0%} -> {now:.0%} "
            f"-- the site changed shape; fix the spec, then re-parse"
        )
    adapter.extracted.clear()


def poll_pixiv(
    store: Store,
    pixiv: PixivAdapter,
    watches: list[Watch] | None = None,
    ctx: JobContext | None = None,
) -> RunStats:
    st = RunStats()
    c = _ctx(ctx)
    ws = [w for w in (watches or store.watches()) if w.wants("pixiv")]
    if not ws:
        st.notes.append("pixiv: no watch has pixiv enabled -- nothing to discover")
        return st
    if not pixiv.authed:
        # pixiv's search endpoint answers 401 anonymously; say it once, up front
        raise RuntimeError("pixiv: not signed in -- connect it in Settings > Accounts")
    c.stage("discover", source="pixiv")
    for w in ws:
        for tag in w.pixiv_tags:
            c.check()
            feed = f"tag:{tag}"
            mark = store.watermark("pixiv", feed)
            highest = int(mark or 0)
            single = w.model_copy(update={"pixiv_tags": [tag]})
            ds = DiscoverStats()
            c.log(f"{w.slug} · {tag} · watermark {mark or 'none'}", slug=w.slug, tag=tag)
            for rec in pixiv.discover(single, mark, seen=store.seen, stats=ds):
                c.check()  # between records, never inside a write
                is_new = store.upsert_post(rec, w.slug)
                if is_new:
                    st.new_posts += 1
                else:
                    st.seen_posts += 1
                c.item(
                    f"{tag} · {rec.external_id} · {rec.page_count}p",
                    source="pixiv",
                    external_id=rec.external_id,
                    action="new" if is_new else "seen",
                    slug=w.slug,
                )
                # unvisited work is only known as the listing unfolds -> no
                # honest denominator; the UI shows listed/gated instead
                c.progress(ds.fetched, None, listed=ds.listed, gated=ds.gated)
                # indexed is marked here, after the write, not in the adapter:
                # the adapter doesn't know whether storage succeeded
                store.seen.mark("pixiv", rec.external_id, SeenState.INDEXED)
            # the watermark comes from ids LISTED, not yielded -- a page that
            # was entirely gated must still move it, or it is walked forever
            highest = max(highest, ds.highest_id)
            if ds.gone or ds.gated or ds.skipped:
                c.log(
                    f"{tag}: listed {ds.listed}, gated {ds.gated} (no request), "
                    f"gone {ds.gone}, skipped {ds.skipped}",
                    tag=tag,
                )
            st.listed += ds.listed
            st.gated += ds.gated
            st.skipped += ds.skipped
            st.gone += ds.gone
            st.failed += ds.failed
            # advance only after the tag is fully walked; a crash mid-tag then
            # re-reads instead of silently skipping a window
            if highest:
                store.set_watermark("pixiv", feed, str(highest))
    _record_drift(store, pixiv, "pixiv", "pixiv_detail", st)
    from . import tags as _tags

    c.stage("tags")
    st.notes.append(f"tag_stats: {_tags.rebuild(store)} rows")
    for n in st.notes:
        c.log(n, level="warning" if n.startswith("DRIFT") else "info")
    return st


def resolve_artist_links(
    store: Store,
    pixiv: PixivAdapter,
    limit: int = 50,
    autofollow: bool = True,
    ctx: JobContext | None = None,
) -> RunStats:
    """pixiv artist -> X handle. This is the bridge between the two sources."""
    st = RunStats()
    c = _ctx(ctx)
    rows = store.artists_needing_link(limit)
    c.stage("link", total=len(rows))
    for i, row in enumerate(rows):
        c.check()
        c.progress(i, len(rows))
        try:
            handle = pixiv.twitter_handle(row["artist_id"])
        except Exception as e:
            log.warning("link lookup failed for %s: %s", row["artist_id"], e)
            continue
        store.set_twitter_handle(row["artist_id"], handle)
        if handle:
            st.notes.append(f"{row['name'] or row['artist_id']} -> @{handle}")
            c.item(f"{row['name'] or row['artist_id']} -> @{handle}", handle=handle)
            if autofollow:
                store.follow(handle, True)
    c.progress(len(rows), len(rows))
    return st


# -- x: follow feed -------------------------------------------------------
def poll_twitter(
    store: Store,
    tw: TwitterAdapter,
    watches: list[Watch] | None = None,
    limit: int = 200,
    keep_unmatched: bool = False,
    ctx: JobContext | None = None,
) -> RunStats:
    st = RunStats()
    c = _ctx(ctx)
    ws = [w for w in (watches or store.watches()) if w.wants("twitter")]
    if not ws:
        st.notes.append("X: no watch has X enabled -- timelines skipped")
        return st
    handles = store.followed_handles()
    c.stage("discover", source="twitter", handles=len(handles))
    if not handles:
        st.notes.append("no followed X handles yet -- run `coreflame link` after a pixiv poll")
        return st
    for hi, handle in enumerate(handles):
        c.check()
        c.progress(hi, len(handles), handle=handle)  # per-handle IS an honest total
        feed = f"user:{handle}"
        mark = store.watermark("twitter", feed)
        highest = int(mark or 0)
        try:
            records = list(tw.timeline(handle, mark, limit))
        except GalleryDLError as e:
            st.failed += 1
            st.notes.append(f"@{handle}: {e}")
            continue
        for rec in records:
            c.check()
            highest = max(highest, int(rec.external_id))
            st.listed += 1
            if not store.seen.should_fetch("twitter", rec.external_id):
                st.gated += 1
                continue
            hits = [w.slug for w in ws if tw.matches(rec, w)]
            if not hits and not keep_unmatched:
                # kept out of `posts` on purpose: the phash pass in the
                # download step can only link images we actually fetched, and
                # fetching every post from every followed artist is a different
                # (much larger) product than a character watcher
                store.seen.mark(
                    "twitter", rec.external_id, SeenState.SKIPPED, reason=SkipReason.NO_MATCH.value
                )
                st.skipped += 1
                continue
            is_new = store.upsert_post(rec, hits[0] if hits else None)
            if is_new:
                st.new_posts += 1
            else:
                st.seen_posts += 1
            store.seen.mark("twitter", rec.external_id, SeenState.INDEXED)
            c.item(
                f"@{handle} {rec.external_id} · {len(rec.media)} image(s)",
                source="twitter",
                external_id=rec.external_id,
                action="new" if is_new else "seen",
                slug=hits[0] if hits else None,
            )
            for extra in hits[1:]:
                store.conn.execute(
                    "INSERT OR IGNORE INTO post_watches VALUES(?,?,?)",
                    (rec.source, rec.external_id, extra),
                )
        if highest:
            store.set_watermark("twitter", feed, str(highest))
    c.progress(len(handles), len(handles))
    _record_drift(store, tw, "twitter", "twitter_entry", st)
    return st


# -- media ----------------------------------------------------------------
def download_pending(
    store: Store,
    blobs: BlobStore,
    pixiv: PixivAdapter,
    tw: TwitterAdapter,
    batch: int = 200,
    threshold: int = 6,
    ctx: JobContext | None = None,
    thumbs: ThumbStore | None = None,
) -> RunStats:
    st = RunStats()
    c = _ctx(ctx)
    thumbs = thumbs or ThumbStore(blobs.root.parent / "thumbs")
    # by-character/<slug>/ is a derived view over blobs/: hardlinks where the
    # filesystem allows, else symlinks, else copies. Rebuildable, never truth.
    view = LibraryView(blobs.root.parent)
    rows = store.pending_media(batch)
    c.stage("download", total=len(rows))  # pending count IS an honest total
    for i, row in enumerate(rows):
        c.check()
        c.progress(i, len(rows))
        source, eid, idx, url = (row["source"], row["external_id"], row["idx"], row["url"])
        post = store.conn.execute(
            "SELECT artist_id, artist_handle, permalink FROM posts "
            "WHERE source=? AND external_id=?",
            (source, eid),
        ).fetchone()
        artist_key = (post["artist_handle"] or post["artist_id"]) if post else ""
        try:
            if source == "pixiv":
                data = pixiv.fetch_media(url, post["permalink"] if post else None)
            else:
                data = tw.fetch_media(url)
        except Exception as e:
            store.mark_media(source, eid, idx, state="failed", error=str(e)[:300])
            st.failed += 1
            continue

        import hashlib

        sha = hashlib.sha256(data).hexdigest()
        verdict = classify(store, data, sha, artist_key, threshold)
        if verdict.is_dupe:
            store.mark_media(
                source,
                eid,
                idx,
                state="dupe",
                sha=sha,
                phash=verdict.phash,
                nbytes=len(data),
                dupe_of=verdict.dupe_of,
                error=verdict.reason,
            )
            st.dupes += 1
            c.item(
                f"{source} {eid}#{idx} dupe of {(verdict.dupe_of or '')[:12]} ({verdict.reason})",
                source=source,
                external_id=eid,
                action="dupe",
            )
            continue

        ext = _ext_for(url)
        _, blob_path, _ = blobs.put(data, ext)
        thumbs.make(sha, data)  # at ingest, never on request
        # one readable name per character the post belongs to
        slugs = [
            r["slug"]
            for r in store.conn.execute(
                "SELECT slug FROM post_watches WHERE source=? AND external_id=?", (source, eid)
            )
        ]
        fname = safe_name(artist_key or source, eid, f"p{idx}", ext=ext)
        for slug in slugs:
            view.place(blob_path, slug, fname)
        store.mark_media(
            source,
            eid,
            idx,
            state="stored",
            sha=sha,
            phash=verdict.phash,
            nbytes=len(data),
            ext=ext,
        )
        st.downloaded += 1
        c.item(
            f"{source} {eid}#{idx} stored {len(data) // 1024} KB",
            source=source,
            external_id=eid,
            action="stored",
            sha=sha,
        )
    c.progress(len(rows), len(rows))
    return st


def run_all(
    cfg: Config,
    do_pixiv: bool = True,
    do_link: bool = True,
    do_twitter: bool = True,
    do_media: bool = True,
) -> RunStats:
    store = Store(cfg.db_path)
    blobs = BlobStore(cfg.blob_root)
    resolver = None
    if cfg.resolver == "doh":
        from .net import DEFAULT_DOH, DohResolver

        resolver = DohResolver(cfg.doh_endpoints or DEFAULT_DOH)
    pixiv = PixivAdapter(
        cfg.pixiv_php_sessid,
        rate=cfg.pixiv_rate,
        resolver=resolver,
        proxy=cfg.proxy_url,
        sink=store,
    )
    tw = TwitterAdapter(
        cfg.twitter_cookies_file, cfg.twitter_cookies_from_browser, proxy=cfg.proxy_url, sink=store
    )
    total = RunStats()
    try:
        if do_pixiv:
            total.merge(poll_pixiv(store, pixiv))
        if do_link:
            total.merge(resolve_artist_links(store, pixiv))
        if do_twitter and tw.available():
            total.merge(poll_twitter(store, tw, limit=cfg.twitter_timeline_limit))
        elif do_twitter:
            total.notes.append("gallery-dl not installed; skipped X")
        if do_media:
            total.merge(download_pending(store, blobs, pixiv, tw, threshold=cfg.dupe_threshold))
    finally:
        pixiv.close()
        tw.close()
        store.close()
    return total
