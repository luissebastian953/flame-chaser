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
from .identify import Identifies, Identity
from .jobs import JobContext
from .kinds import KEEP, Label, LabelError, Labels, ModelError, kept, make_labeler
from .library import LibraryView, safe_name
from .models import DiscoverStats, IllustRecord, Watch
from .online import Offline
from .people import People, Tags, accepts
from .seen import SeenState, SkipReason
from .sources.pixiv import PixivAdapter
from .sources.twitter import GalleryDLError, TwitterAdapter
from .thumbs import ThumbStore, dims
from .trash import crawl_verdict

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
    labeled: int = 0  # images given a kind (coreflame/kinds.py) at ingest
    rejected: int = 0  # labelled as a kind the archive does not keep; never stored
    identified: int = 0  # stored images given character names (coreflame/identify.py)
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
            "labeled",
            "rejected",
            "identified",
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
    def tally(self, key: str, n: int = 1) -> None: ...


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
        c.log("pixiv: no watch has pixiv enabled -- skipped")
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
                    c.tally("posts")
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
        except Offline:
            raise  # the connection, not this artist
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


# -- x: search + follow feed ----------------------------------------------
def _ingest_tweet(
    store: Store,
    tw: TwitterAdapter,
    rec: IllustRecord,
    ws: list[Watch],
    st: RunStats,
    c: JobContext,
    *,
    keep_unmatched: bool,
    label: str,
) -> list[str]:
    """One timeline/search record -> posts + post_watches, or a NO_MATCH skip.
    Returns the slugs it was linked to ([] when gated or skipped)."""
    if not store.seen.should_fetch("twitter", rec.external_id):
        st.gated += 1
        return []
    hits = [w.slug for w in ws if tw.matches(rec, w)]
    if not hits and not keep_unmatched:
        # kept out of `posts` on purpose: the phash pass in the download step
        # can only link images we actually fetched, and fetching every post
        # from every followed artist is a different (much larger) product
        # than a character watcher
        store.seen.mark(
            "twitter", rec.external_id, SeenState.SKIPPED, reason=SkipReason.NO_MATCH.value
        )
        st.skipped += 1
        return []
    is_new = store.upsert_post(rec, hits[0] if hits else None)
    if is_new:
        st.new_posts += 1
    else:
        st.seen_posts += 1
    store.seen.mark("twitter", rec.external_id, SeenState.INDEXED)
    c.item(
        f"{label} {rec.external_id} · @{rec.artist_handle} · {len(rec.media)} image(s)",
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
    return hits


def poll_twitter(
    store: Store,
    tw: TwitterAdapter,
    watches: list[Watch] | None = None,
    limit: int = 200,
    keep_unmatched: bool = False,
    ctx: JobContext | None = None,
    search_limit: int = 50,
) -> RunStats:
    """Two passes, both only for watches with X ticked:

    1. search -- each match term through X search (images only). The only
       discovery X offers; the request X polices hardest, hence the small
       per-term limit. `search_limit=0` disables it.
    2. timelines -- the media feeds of artists linked from pixiv, text-matched
       against every X watch. Cheap and precise; nothing here without a pixiv
       poll + link first.
    """
    st = RunStats()
    c = _ctx(ctx)
    ws = [w for w in (watches or store.watches()) if w.wants("twitter")]
    if not ws:
        c.log("X: no watch has X enabled -- skipped")
        return st

    # ---- 1. search by term
    terms = [(w, t) for w in ws for t in (w.match_terms or [w.slug])] if search_limit else []
    if terms:
        c.stage("discover", source="twitter", mode="search", terms=len(terms))
        for ti, (w, term) in enumerate(terms):
            c.check()
            c.progress(ti, len(terms), term=term)
            feed = f"search:{term.lower()}"
            mark = store.watermark("twitter", feed)
            highest = int(mark or 0)
            c.log(
                f"{w.slug} · search {term!r} · watermark {mark or 'none'}", slug=w.slug, term=term
            )
            try:
                records = list(tw.search(term, mark, search_limit))
            except GalleryDLError as e:
                st.failed += 1
                c.log(f"search {term!r}: {e}", level="warning")
                continue
            for rec in records:
                c.check()
                highest = max(highest, int(rec.external_id))
                st.listed += 1
                _ingest_tweet(
                    store, tw, rec, ws, st, c, keep_unmatched=keep_unmatched, label=f"search {term}"
                )
            if highest:
                store.set_watermark("twitter", feed, str(highest))
        c.progress(len(terms), len(terms))

    # ---- 2. timelines of linked artists
    handles = store.followed_handles()
    c.stage("discover", source="twitter", mode="timelines", handles=len(handles))
    if not handles:
        c.log(
            "no linked X artists yet -- timelines skipped"
            + ("" if terms or not search_limit else "; add a match term or run a pixiv poll first")
        )
        _record_drift(store, tw, "twitter", "twitter_entry", st)
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
            c.log(f"@{handle}: {e}", level="warning")
            continue
        for rec in records:
            c.check()
            highest = max(highest, int(rec.external_id))
            st.listed += 1
            _ingest_tweet(
                store, tw, rec, ws, st, c, keep_unmatched=keep_unmatched, label=f"@{handle}"
            )
        if highest:
            store.set_watermark("twitter", feed, str(highest))
    c.progress(len(handles), len(handles))
    _record_drift(store, tw, "twitter", "twitter_entry", st)
    return st


# -- X search to a target -------------------------------------------------
PAGE_POSTS = 50  # posts per search page: one gallery-dl run, a few X requests
SAFETY_FACTOR = 10  # give up after listing this many times the target
LABELS_OFF = "labels off"  # RunStats note: the classifier failed this run
TAGS_OFF = "people tags off"  # RunStats note: the tagger failed this run
IDENT_OFF = "character names off"  # RunStats note: the identifier failed this run


@dataclass
class _TermWalk:
    """The stretch of X search history one term has covered: every post with
    lo <= id <= hi has been listed. `hi` rises as new posts appear, `lo` falls
    as crawls walk back; lo == 0 means X has nothing older. Snowflake ids, not
    timestamps (decision #5), so there is no gap and no double count."""

    term: str
    hi: int | None
    lo: int | None
    cursor: int | None = None  # max_id for the next page of an unfinished catch-up
    top: int = 0  # newest id this crawl's catch-up has seen
    caught_up: bool = False
    stopped: bool = False  # a page failed: leave the term alone for this crawl

    @property
    def finished(self) -> bool:
        return self.stopped or (self.caught_up and self.lo == 0)


def _load_walk(store: Store, term: str) -> _TermWalk:
    t = term.lower()
    hi = store.watermark("twitter", f"search:{t}")
    lo = store.watermark("twitter", f"search-lo:{t}")
    hi_i = int(hi) if hi and hi.isdigit() else None
    lo_i = int(lo) if lo and lo.isdigit() else None
    if hi_i is None:
        # never searched: the first page from the newest starts the stretch
        return _TermWalk(term, None, None, caught_up=True)
    if lo_i is None:
        lo_i = hi_i  # searched by the old newest-N poll: walk back from its top
    return _TermWalk(term, hi_i, lo_i)


def _fetch_page(
    tw: TwitterAdapter, walk: _TermWalk, page_posts: int
) -> tuple[list[IllustRecord], str, bool]:
    """One page for one term, newest first, trimmed to posts outside the covered
    stretch. Catch up on newer posts until the stretch is reached, else go one
    page further back. Returns (records, direction, reaches_covered)."""
    if not walk.caught_up:
        assert walk.hi is not None
        page = tw.search_page(walk.term, walk.cursor, page_posts)
        ids = [int(r.external_id) for r in page]
        if ids:
            walk.top = max(walk.top, *ids)
        fresh = [
            r
            for r in page
            if int(r.external_id) > walk.hi
            and (walk.cursor is None or int(r.external_id) <= walk.cursor)
        ]
        # nothing left between the cursor and hi (incl. a page that is only X's
        # off-by-one post above max_id) also means caught up -- never re-ask it
        return fresh, "newer", not fresh or min(ids) <= walk.hi
    page = tw.search_page(walk.term, None if walk.lo is None else walk.lo - 1, page_posts)
    fresh = [r for r in page if walk.lo is None or int(r.external_id) < walk.lo]
    return fresh, "older", False


def _commit(store: Store, walk: _TermWalk, direction: str, rec_id: int) -> None:
    """One record fully processed: move the stretch past it, durably. Stopping
    right after this leaves the rest of the page for the next crawl -- listed
    again then, never skipped."""
    t = walk.term.lower()
    if direction == "newer":
        walk.cursor = rec_id - 1
        return
    if walk.hi is None:  # the very first record of a never-searched term
        walk.hi = rec_id
        store.set_watermark("twitter", f"search:{t}", str(rec_id))
    walk.lo = rec_id
    store.set_watermark("twitter", f"search-lo:{t}", str(rec_id))


def _page_done(
    store: Store, walk: _TermWalk, direction: str, reaches_covered: bool, empty: bool
) -> None:
    """A whole page was processed: the catch-up may have met the covered
    stretch, or the walk back may have found nothing older."""
    t = walk.term.lower()
    if direction == "newer":
        if reaches_covered:
            walk.caught_up = True
            if walk.hi is not None and walk.top > walk.hi:
                walk.hi = walk.top
                store.set_watermark("twitter", f"search:{t}", str(walk.hi))
    elif empty:
        walk.lo = 0
        store.set_watermark("twitter", f"search-lo:{t}", "0")


def _drain_downloads(
    store: Store,
    blobs: BlobStore,
    pixiv: PixivAdapter,
    tw: TwitterAdapter,
    labeler: Labels | None,
    threshold: int,
    st: RunStats,
    ctx: JobContext | None,
    tagger: Tags | None = None,
    identifier: Identifies | None = None,
    cleanup: dict[str, Any] | None = None,
) -> tuple[Labels | None, Tags | None, Identifies | None]:
    """Download (and judge) everything pending now. Returns the labeler,
    tagger and identifier, each None once it has proved unusable, so the
    caller stops handing it over."""
    while store.pending_media(1, source="twitter"):
        got = download_pending(
            store,
            blobs,
            pixiv,
            tw,
            threshold=threshold,
            ctx=ctx,
            labeler=labeler,
            announce=False,
            tagger=tagger,
            identifier=identifier,
            source="twitter",  # the X worker never touches pixiv's hosts
            cleanup=cleanup,
        )
        st.merge(got)
        if LABELS_OFF in got.notes:
            labeler = None
        if TAGS_OFF in got.notes:
            tagger = None
        if IDENT_OFF in got.notes:
            identifier = None
        if not (got.downloaded or got.dupes or got.failed or got.rejected):
            break  # nothing moved: never spin
    return labeler, tagger, identifier


def _kept(store: Store, external_id: str) -> bool:
    return (
        store.conn.execute(
            "SELECT 1 FROM media WHERE source='twitter' AND external_id=? AND state='stored' LIMIT 1",
            (external_id,),
        ).fetchone()
        is not None
    )


def search_to_target(
    store: Store,
    tw: TwitterAdapter,
    blobs: BlobStore,
    pixiv: PixivAdapter,
    watch: Watch,
    ws: list[Watch],
    target: int,
    *,
    labeler: Labels | None = None,
    threshold: int = 6,
    ctx: JobContext | None = None,
    page_posts: int = PAGE_POSTS,
    tagger: Tags | None = None,
    identifier: Identifies | None = None,
    cleanup: dict[str, Any] | None = None,
) -> RunStats:
    """Search X for one character until exactly `target` NEW posts are kept --
    posts left holding at least one stored image after the visited gate, the
    text match and the image kinds (kinds.KEEP) have had their say. Newer posts
    first, then further back, one page per term in turn; each post is
    downloaded and judged before the next is counted, so the count is exact.
    Stops at the target, when every term has run out of history, or after
    listing SAFETY_FACTOR x target posts. `ws` = every X-enabled watch, so a
    post naming two characters is linked to both."""
    st = RunStats()
    c = _ctx(ctx)
    walks = [_load_walk(store, t) for t in (watch.match_terms or [watch.slug])]
    cap = SAFETY_FACTOR * target
    kept = 0
    c.stage("discover", source="twitter", mode="target", slug=watch.slug, target=target)
    c.progress(0, target)  # kept posts against the target IS an honest total

    def done() -> bool:
        return kept >= target or st.listed >= cap

    while not done():
        active = [w for w in walks if not w.finished]
        if not active:
            c.log(
                f"{watch.slug}: X has nothing older for any term -- history complete "
                f"({kept}/{target} kept this crawl)"
            )
            break
        for walk in active:  # take turns: one page per term
            c.check()
            try:
                recs, direction, reaches = _fetch_page(tw, walk, page_posts)
            except GalleryDLError as e:
                st.failed += 1
                walk.stopped = True
                c.log(f"search {walk.term!r}: {e}", level="warning")
                continue
            new_here = 0
            for rec in recs:
                if done():  # checked BEFORE a record: a page whose last record hits
                    break  # the target still counts as fully processed below
                c.check()
                st.listed += 1
                hits = _ingest_tweet(
                    store, tw, rec, ws, st, c, keep_unmatched=False, label=f"search {walk.term}"
                )
                if watch.slug in hits:
                    labeler, tagger, identifier = _drain_downloads(
                        store,
                        blobs,
                        pixiv,
                        tw,
                        labeler,
                        threshold,
                        st,
                        ctx,
                        tagger,
                        identifier,
                        cleanup,
                    )
                    if _kept(store, rec.external_id):
                        kept += 1
                        new_here += 1
                        c.tally("posts")
                        c.progress(kept, target)
                _commit(store, walk, direction, int(rec.external_id))
            else:  # the whole page was processed
                _page_done(store, walk, direction, reaches, empty=not recs)
            c.log(
                f"{watch.slug} · {walk.term!r} · {direction} page · {new_here} kept "
                f"· {kept}/{target}",
                slug=watch.slug,
                term=walk.term,
            )
            if done():
                break
    if st.listed >= cap and kept < target:
        c.log(
            f"{watch.slug}: stopped after listing {st.listed} posts with only {kept} kept "
            f"-- a search term probably matches mostly other things",
            level="warning",
        )
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
    labeler: Labels | None = None,
    announce: bool = True,
    tagger: Tags | None = None,
    identifier: Identifies | None = None,
    source: str | None = None,
    cleanup: dict[str, Any] | None = None,
) -> RunStats:
    """`announce=False` when a caller interleaves downloads with its own stage
    (search_to_target): no stage change, and its progress bar is left alone.
    `identifier` names the character in every image that is stored; it never
    rejects one -- unless `cleanup` (Settings › Duplicates' crawl-time rule,
    coreflame/trash.py) says the name is wrong or too unsure. `source`
    downloads only that source's media -- a worker stays on its own hosts
    (coreflame/jobs.py lanes)."""
    st = RunStats()
    primaries: dict[str, str | None] = {}  # each character's name, read once per run
    c = _ctx(ctx)
    thumbs = thumbs or ThumbStore(blobs.root.parent / "thumbs")
    # by-character/<slug>/ is a derived view over blobs/: hardlinks where the
    # filesystem allows, else symlinks, else copies. Rebuildable, never truth.
    view = LibraryView(blobs.root.parent)
    rows = store.pending_media(batch, source)
    if announce:
        c.stage("download", total=len(rows))  # pending count IS an honest total
    for i, row in enumerate(rows):
        c.check()
        if announce:
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
        except Offline:
            raise  # the connection, not this file: it stays pending for the resume
        except Exception as e:
            store.mark_media(source, eid, idx, state="failed", error=str(e)[:300])
            st.failed += 1
            continue

        import hashlib

        sha = hashlib.sha256(data).hexdigest()
        # the size the source handed over, and what the file really measures:
        # the fullscreen viewer shows it at 1:1, so the row says the truth
        variant = str(getattr(pixiv if source == "pixiv" else tw, "last_variant", ""))
        size = dims(data)
        w, h = size if size else (None, None)
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
                width=w,
                height=h,
                variant=variant,
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
        # judged BEFORE a byte is written: a kind the archive does not keep never
        # becomes a blob, a thumbnail or a by-character name
        label = None
        if labeler is not None:
            try:
                label = _label_one(store, labeler, sha, data, c, st)
            except ModelError as e:
                c.log(f"image labels off for this run: {e}", level="warning")
                st.notes.append(LABELS_OFF)  # lets a caller that calls again stop asking too
                labeler = None  # unusable classifier: keep the rest unlabeled, don't retry
        if label is not None and not kept(label.kind) and store.kind_filter_applies(source, eid):
            store.mark_media(
                source,
                eid,
                idx,
                state="rejected",
                sha=sha,
                phash=verdict.phash,
                nbytes=len(data),
                ext=ext,
                error=label.kind,
            )
            st.rejected += 1
            c.item(
                f"{source} {eid}#{idx} not kept ({label.kind})",
                source=source,
                external_id=eid,
                action="rejected",
                image_kind=label.kind,
            )
            continue
        people: People | None = None  # the WD read, shared with the identifier below
        if tagger is not None and any(g != "any" for g, _ in store.gender_rules(source, eid)):
            # who is in it, for the characters that filter on it -- judged before storage
            try:
                people = tagger.people(data)
            except LabelError as e:
                c.log(f"people {sha[:12]}: {e}", level="warning")  # can't judge -> keep
            except ModelError as e:
                c.log(f"gender filter off for this run: {e}", level="warning")
                st.notes.append(TAGS_OFF)
                tagger = None
            if people is not None:
                store.set_people(sha, people)
                if not _passes_gender(
                    store, source, eid, people.girls, people.boys, people.male_focus
                ):
                    reason = _gender_reason(people.girls, people.boys)
                    store.mark_media(
                        source,
                        eid,
                        idx,
                        state="rejected",
                        sha=sha,
                        phash=verdict.phash,
                        nbytes=len(data),
                        ext=ext,
                        error=reason,
                    )
                    st.rejected += 1
                    c.item(
                        f"{source} {eid}#{idx} not kept ({reason})",
                        source=source,
                        external_id=eid,
                        action="rejected",
                    )
                    continue
        _, blob_path, _ = blobs.put(data, ext)
        thumbs.make(sha, data)  # at ingest, never on request
        # one readable name per character the post belongs to
        fname = safe_name(artist_key or source, eid, f"p{idx}", ext=ext)
        for slug in _slugs_of(store, source, eid):
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
            width=w,
            height=h,
            variant=variant,
        )
        st.downloaded += 1
        who = ""
        if identifier is not None:
            identifier, who, ident = _identify_one(store, identifier, sha, data, people, c, st)
            verdict_reason = (
                crawl_verdict(
                    store,
                    _slugs_of(store, source, eid),
                    ident.hits,
                    ident.state == "identified",
                    cleanup,
                    primaries,
                    model=ident.model,
                )
                if ident is not None
                else None
            )
            if verdict_reason:
                # the Smart rule at crawl time: stored a moment ago, thrown away
                # exactly like a kind the archive does not keep
                fresh = {
                    "source": source,
                    "external_id": eid,
                    "idx": idx,
                    "sha256": sha,
                    "ext": ext,
                    "artist_id": post["artist_id"] if post else "",
                    "artist_handle": post["artist_handle"] if post else "",
                }
                _discard_row(store, blobs, thumbs, view, fresh, verdict_reason, c)
                st.downloaded -= 1
                st.rejected += 1
                continue
        c.item(
            f"{source} {eid}#{idx} stored {len(data) // 1024} KB{who}",
            source=source,
            external_id=eid,
            action="stored",
            sha=sha,
        )
    if announce:
        c.progress(len(rows), len(rows))
    return st


def _identify_one(
    store: Store,
    identifier: Identifies,
    sha: str,
    data: bytes,
    people: People | None,
    c: JobContext,
    st: RunStats,
) -> tuple[Identifies | None, str, Identity | None]:
    """Name the character in one freshly stored image. Returns the identifier
    (None once it proved unusable: the rest stay pending for the label job),
    a suffix for the log line, and the identity (None when it could not be judged)."""
    try:
        ident = identifier.identify(data, people)
    except LabelError as e:
        c.log(f"identify {sha[:12]}: {e}", level="warning")  # stays pending
        return identifier, "", None
    except ModelError as e:
        c.log(f"character names off for this run: {e}", level="warning")
        st.notes.append(IDENT_OFF)
        return None, "", None
    if ident.people is not None:  # the WD read it made: the gender filter needs no re-tag
        store.set_people(sha, ident.people)
    store.set_identity(sha, ident)
    st.identified += 1
    return identifier, " · " + (", ".join(h.name for h in ident.hits) or "unidentified"), ident


def _slugs_of(store: Store, source: str, external_id: str) -> list[str]:
    return [
        r["slug"]
        for r in store.conn.execute(
            "SELECT slug FROM post_watches WHERE source=? AND external_id=?", (source, external_id)
        )
    ]


def _label_one(
    store: Store, labeler: Labels, sha: str, data: bytes, c: JobContext, st: RunStats
) -> Label | None:
    """Give one fresh image its kind. None = this image could not be judged, so
    it is kept unlabeled. A ModelError (classifier unusable) propagates."""
    try:
        lab = labeler.label(data)
    except LabelError as e:
        c.log(f"label {sha[:12]}: {e}", level="warning")
        return None
    store.set_kind(sha, lab.kind, lab.scores, lab.model)
    st.labeled += 1
    return lab


def discard_unkept(
    store: Store,
    blobs: BlobStore,
    thumbs: ThumbStore | None = None,
    ctx: JobContext | None = None,
) -> int:
    """Throw away stored images labelled as a kind the archive does not keep:
    the bytes, the thumbnail and every by-character name go. The media row
    stays -- `rejected`, kind in `error`, url intact -- so it can be audited and
    undone by re-downloading. One row per step: a cancel lands between rows."""
    c = _ctx(ctx)
    thumbs = thumbs or ThumbStore(blobs.root.parent / "thumbs")
    view = LibraryView(blobs.root.parent)
    rows = store.stored_not_kept(KEEP)
    if not rows:
        return 0
    c.stage("discard", total=len(rows))
    for i, row in enumerate(rows):
        c.check()
        c.progress(i, len(rows))
        _discard_row(store, blobs, thumbs, view, row, row["kind"], c)
    c.progress(len(rows), len(rows))
    return len(rows)


def _discard_row(
    store: Store,
    blobs: BlobStore,
    thumbs: ThumbStore,
    view: LibraryView,
    row: Any,
    reason: str,
    c: JobContext,
) -> None:
    """Throw one stored image away: its by-character names, then (once no
    stored row needs the bytes) blob and thumbnail. The row stays `rejected`
    with `reason` in `error` and its url, so it can be undone by re-downloading."""
    source, eid, idx, sha, ext = (
        row["source"],
        row["external_id"],
        row["idx"],
        row["sha256"],
        row["ext"],
    )
    artist_key = row["artist_handle"] or row["artist_id"] or ""
    fname = safe_name(artist_key or source, eid, f"p{idx}", ext=ext)
    for slug in _slugs_of(store, source, eid):
        view.remove(slug, fname)
    store.mark_media(source, eid, idx, state="rejected", error=reason)
    if not store.sha_exists(sha):  # no other stored row still needs these bytes
        blobs.path_for(sha, ext).unlink(missing_ok=True)
        thumbs.path_for(sha).unlink(missing_ok=True)
    c.item(
        f"{source} {eid}#{idx} removed ({reason})",
        source=source,
        external_id=eid,
        action="rejected",
    )


def _gender_reason(girls: int, boys: int) -> str:
    return f"gender:girls={girls},boys={boys}"


def _passes_gender(store: Store, source: str, eid: str, girls: int, boys: int, focus: bool) -> bool:
    """Kept unless EVERY character the post belongs to rejects it (a
    character without a gender filter accepts everything)."""
    rules = store.gender_rules(source, eid)
    return not rules or any(accepts(girls, boys, focus, g, m) for g, m in rules)


def people_pending(
    store: Store,
    blobs: BlobStore,
    tagger: Tags,
    limit: int | None = None,
    ctx: JobContext | None = None,
) -> dict[str, int]:
    """Tag who is in each stored image of a gender-filtered character (from
    disk, never a re-fetch), then throw away what no character accepts."""
    c = _ctx(ctx)
    rows = store.untagged_people(tagger.model, limit)
    out = {"tagged": 0, "tag_failed": 0}
    if rows:
        c.stage("people", total=len(rows))
        for i, row in enumerate(rows):
            c.check()
            c.progress(i, len(rows))
            sha = row["sha256"]
            try:
                p = tagger.people(blobs.path_for(sha, row["ext"]).read_bytes())
            except (OSError, LabelError) as e:
                out["tag_failed"] += 1
                c.log(f"people {sha[:12]}: {e}", level="warning")
                continue
            store.set_people(sha, p)
            out["tagged"] += 1
        c.progress(len(rows), len(rows))
    out["removed_gender"] = discard_by_gender(store, blobs, ctx=ctx)
    return out


def discard_by_gender(
    store: Store, blobs: BlobStore, thumbs: ThumbStore | None = None, ctx: JobContext | None = None
) -> int:
    """Throw away stored images that no character they belong to accepts
    under its gender filter. Same removal as discard_unkept."""
    c = _ctx(ctx)
    thumbs = thumbs or ThumbStore(blobs.root.parent / "thumbs")
    view = LibraryView(blobs.root.parent)
    doomed = [
        r
        for r in store.stored_people()
        if not _passes_gender(
            store, r["source"], r["external_id"], r["girls"], r["boys"], bool(r["male_focus"])
        )
    ]
    if doomed:
        c.stage("discard", total=len(doomed))
        for i, row in enumerate(doomed):
            c.check()
            c.progress(i, len(doomed))
            _discard_row(
                store, blobs, thumbs, view, row, _gender_reason(row["girls"], row["boys"]), c
            )
        c.progress(len(doomed), len(doomed))
    return len(doomed)


def identify_pending(
    store: Store,
    blobs: BlobStore,
    identifier: Identifies,
    limit: int | None = None,
    ctx: JobContext | None = None,
) -> dict[str, int]:
    """Name the character in stored images not identified yet (or by an older
    model). Reads each blob from disk; never removes an image. A ModelError
    propagates: nothing in the backlog can be identified without it."""
    c = _ctx(ctx)
    rows = store.unidentified_media(identifier.model, limit)
    out = {"identified": 0, "unidentified": 0, "identify_failed": 0}
    if not rows:
        return out
    c.stage("identify", total=len(rows))  # the backlog count IS an honest total
    for i, row in enumerate(rows):
        c.check()
        c.progress(i, len(rows))
        sha = row["sha256"]
        try:
            ident = identifier.identify(blobs.path_for(sha, row["ext"]).read_bytes())
        except (OSError, LabelError) as e:
            out["identify_failed"] += 1
            c.log(f"identify {sha[:12]}: {e}", level="warning")
            continue
        if ident.people is not None:
            store.set_people(sha, ident.people)
        store.set_identity(sha, ident)
        out[ident.state] += 1
        names = ", ".join(h.name for h in ident.hits) or "unidentified"
        c.item(f"{sha[:12]} {names}", sha=sha, action=ident.state)
    c.progress(len(rows), len(rows))
    return out


def label_pending(
    store: Store,
    blobs: BlobStore,
    labeler: Labels,
    limit: int | None = None,
    ctx: JobContext | None = None,
) -> dict[str, int]:
    """Label stored images that have no kind yet, or one from an older model,
    then throw away every stored image whose kind the archive does not keep.
    Reads each blob from disk -- a label never costs a request to a source. A
    ModelError propagates: nothing in the backlog can be labelled without it."""
    c = _ctx(ctx)
    rows = store.unlabeled_media(labeler.model, limit)
    c.stage("label", total=len(rows))  # unlabeled count IS an honest total
    out: dict[str, int] = {"labeled": 0, "failed": 0}
    for i, row in enumerate(rows):
        c.check()
        c.progress(i, len(rows))
        sha = row["sha256"]
        try:
            lab = labeler.label(blobs.path_for(sha, row["ext"]).read_bytes())
        except (OSError, LabelError) as e:
            out["failed"] += 1
            c.log(f"label {sha[:12]}: {e}", level="warning")
            continue
        store.set_kind(sha, lab.kind, lab.scores, lab.model)
        out["labeled"] += 1
        out[lab.kind] = out.get(lab.kind, 0) + 1
        c.item(f"{sha[:12]} {lab.kind}", sha=sha, action="labeled", image_kind=lab.kind)
    c.progress(len(rows), len(rows))
    out["removed"] = discard_unkept(store, blobs, ctx=ctx)
    return out


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
            total.merge(
                download_pending(
                    store,
                    blobs,
                    pixiv,
                    tw,
                    threshold=cfg.dupe_threshold,
                    labeler=make_labeler(cfg),
                )
            )
    finally:
        pixiv.close()
        tw.close()
        store.close()
    return total
