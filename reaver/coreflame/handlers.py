"""Job type -> pipeline function. This is the only place the runner learns
what a "poll" is; the pipeline functions stay callable without a runner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import bundle
from .blobs import BlobStore
from .config import Config
from .db import Store
from .identify import Identifier, Identifies, make_identifier
from .jobs import LANES, Handler, JobContext, JobRunner
from .kinds import Labeler, Labels, make_labeler
from .models import Watch
from .people import Tagger, Tags, make_tagger
from .pipeline import (
    RunStats,
    download_pending,
    identify_pending,
    label_pending,
    people_pending,
    poll_pixiv,
    poll_twitter,
    resolve_artist_links,
    search_to_target,
)
from .sources.pixiv import PixivAdapter
from .sources.twitter import TwitterAdapter
from .thumbs import ThumbStore

TARGET_MAX = 1000  # posts per character per crawl; the UI offers up to this


def _counters(st: RunStats) -> dict[str, Any]:
    d = asdict(st)
    d.pop("notes", None)
    return d


def make_pixiv(cfg: Config, sink: Any = None) -> PixivAdapter:
    """The configured pixiv adapter (session, rate, resolver, proxy) -- shared
    by the job worker and the daemon's form probe so both obey the same config."""
    resolver = None
    if cfg.resolver == "doh":
        from .net import DEFAULT_DOH, DohResolver

        resolver = DohResolver(cfg.doh_endpoints or DEFAULT_DOH)
    return PixivAdapter(
        cfg.pixiv_php_sessid,
        rate=cfg.pixiv_rate,
        resolver=resolver,
        proxy=cfg.proxy_url,
        sink=sink,
    )


class Adapters:
    """Built once per worker thread from config; closed with it."""

    labeler: Labels | None = None  # None: numpy/onnxruntime not installed
    tagger: Tags | None = None  # same deps; the gender filter, and one of the identifier's votes
    identifier: Identifies | None = None  # None: switched off in Settings, or no deps

    def __init__(self, cfg: Config, store: Any) -> None:
        self.pixiv = make_pixiv(cfg, sink=store)
        self.twitter = TwitterAdapter(
            cfg.twitter_cookies_file,
            cfg.twitter_cookies_from_browser,
            proxy=cfg.proxy_url,
            sink=store,
        )
        self.blobs = BlobStore(cfg.blob_root)
        self.labeler = make_labeler(cfg)
        self.tagger = make_tagger(cfg)
        self.identifier = make_identifier(
            cfg, self.tagger if isinstance(self.tagger, Tagger) else None
        )
        self.cfg = cfg

    def labels_for(self, ctx: JobContext) -> Labels | None:
        """The labeler with this job's log bound, so a first-use model
        download shows up in the pipeline instead of as a silent pause."""
        if isinstance(self.labeler, Labeler):
            self.labeler.log = ctx.log
        return self.labeler

    def tags_for(self, ctx: JobContext) -> Tags | None:
        """The tagger with this job's log bound (its first use downloads 467 MB)."""
        if isinstance(self.tagger, Tagger):
            self.tagger.log = ctx.log
        return self.tagger

    def identify_for(self, ctx: JobContext) -> Identifies | None:
        """The identifier with this job's log bound (its first use downloads 789 MB)."""
        if isinstance(self.identifier, Identifier):
            self.identifier.log = ctx.log
            self.identifier.tagger.log = ctx.log
        return self.identifier

    def close(self) -> None:
        self.pixiv.close()
        self.twitter.close()


def build_handlers(make_adapters: Callable[[JobContext], Adapters]) -> dict[str, Handler]:
    """`make_adapters` is called per job so tests can inject fakes and the
    daemon can rebuild on config change."""

    def _download(ctx: JobContext, a: Adapters, source: str | None) -> RunStats:
        return download_pending(
            ctx.store,
            a.blobs,
            a.pixiv,
            a.twitter,
            threshold=a.cfg.dupe_threshold,
            ctx=ctx,
            labeler=a.labels_for(ctx),
            tagger=a.tags_for(ctx),
            identifier=a.identify_for(ctx),
            cleanup=a.cfg.cleanup_rule,
            source=source,
        )

    def _x_search(ctx: JobContext, a: Adapters, watches: list[Watch]) -> RunStats:
        """Search each character until its posts-per-run are KEPT (params.target
        overrides every character's own)."""
        st = RunStats()
        override = ctx.job.params.get("target")
        every_x = [w for w in ctx.store.watches() if w.wants("twitter")]
        for w in [w for w in watches if w.wants("twitter")]:
            target = max(1, min(int(override or w.target), TARGET_MAX))
            st.merge(
                search_to_target(
                    ctx.store,
                    a.twitter,
                    a.blobs,
                    a.pixiv,
                    w,
                    every_x,
                    target,
                    labeler=a.labels_for(ctx),
                    threshold=a.cfg.dupe_threshold,
                    ctx=ctx,
                    tagger=a.tags_for(ctx),
                    identifier=a.identify_for(ctx),
                    cleanup=a.cfg.cleanup_rule,
                )
            )
        return st

    def _x_ready(ctx: JobContext, a: Adapters) -> bool:
        if not a.twitter.available():
            ctx.log(
                f"X: skipped -- {a.twitter.binary} not found on PATH (pip install gallery-dl)",
                level="warning",
            )
            return False
        return True

    def poll(ctx: JobContext) -> dict[str, Any]:
        """`params.source` = pixiv | twitter: one source's half of a crawl, on that
        source's worker (plan_poll makes these). Without it: the whole crawl in one
        job -- the CLI's synchronous run, never two at once."""
        a = make_adapters(ctx)
        try:
            source = ctx.job.params.get("source")
            slugs = ctx.job.params.get("watches")
            watches = [w for w in ctx.store.watches() if not slugs or w.slug in slugs]
            if source == "pixiv":
                st = poll_pixiv(ctx.store, a.pixiv, watches, ctx=ctx)
                if ctx.job.params.get("link", True):
                    st.merge(resolve_artist_links(ctx.store, a.pixiv, ctx=ctx))
                if ctx.job.params.get("media", True):
                    st.merge(_download(ctx, a, "pixiv"))
                return _counters(st)
            if source == "twitter":
                st = RunStats()
                if not _x_ready(ctx, a):
                    return _counters(st)
                if a.cfg.twitter_search_limit == 0:
                    ctx.log("X search is off (search limit 0 in Settings)")
                else:
                    st.merge(_x_search(ctx, a, watches))
                if ctx.job.params.get("media", True):
                    st.merge(_download(ctx, a, "twitter"))
                return _counters(st)
            st = poll_pixiv(ctx.store, a.pixiv, watches, ctx=ctx)
            if ctx.job.params.get("link", True):
                st.merge(resolve_artist_links(ctx.store, a.pixiv, ctx=ctx))
            if not ctx.job.params.get("twitter", True):
                ctx.log("X: disabled for this job (params.twitter=false)")
            elif not a.twitter.available():
                ctx.log(
                    f"X: skipped -- {a.twitter.binary} not found on PATH (pip install gallery-dl)",
                    level="warning",
                )
            elif a.cfg.twitter_search_limit == 0:
                ctx.log("X search is off (search limit 0 in Settings) -- timelines only")
                st.merge(
                    poll_twitter(
                        ctx.store,
                        a.twitter,
                        watches,
                        limit=a.cfg.twitter_timeline_limit,
                        search_limit=0,
                        ctx=ctx,
                    )
                )
            else:
                # search each character to its posts-per-run, then linked artists' timelines
                st.merge(_x_search(ctx, a, watches))
                st.merge(
                    poll_twitter(
                        ctx.store,
                        a.twitter,
                        watches,
                        limit=a.cfg.twitter_timeline_limit,
                        search_limit=0,
                        ctx=ctx,
                    )
                )
            if ctx.job.params.get("media", True):
                st.merge(_download(ctx, a, None))
            return _counters(st)
        finally:
            a.close()

    def timelines(ctx: JobContext) -> dict[str, Any]:
        """The media feeds of every artist linked from pixiv, matched against
        every X character -- the X worker's last job of a crawl."""
        a = make_adapters(ctx)
        try:
            st = RunStats()
            if not _x_ready(ctx, a):
                return _counters(st)
            st.merge(
                poll_twitter(
                    ctx.store,
                    a.twitter,
                    ctx.store.watches(),
                    limit=a.cfg.twitter_timeline_limit,
                    search_limit=0,
                    ctx=ctx,
                )
            )
            if ctx.job.params.get("media", True):
                st.merge(_download(ctx, a, "twitter"))
            return _counters(st)
        finally:
            a.close()

    def link(ctx: JobContext) -> dict[str, Any]:
        a = make_adapters(ctx)
        try:
            return _counters(
                resolve_artist_links(
                    ctx.store, a.pixiv, limit=int(ctx.job.params.get("limit", 50)), ctx=ctx
                )
            )
        finally:
            a.close()

    def media(ctx: JobContext) -> dict[str, Any]:
        a = make_adapters(ctx)
        try:
            source = ctx.job.params.get("source")
            return _counters(
                download_pending(
                    ctx.store,
                    a.blobs,
                    a.pixiv,
                    a.twitter,
                    batch=int(ctx.job.params.get("batch", 200)),
                    threshold=a.cfg.dupe_threshold,
                    ctx=ctx,
                    labeler=a.labels_for(ctx),
                    tagger=a.tags_for(ctx),
                    identifier=a.identify_for(ctx),
                    cleanup=a.cfg.cleanup_rule,
                    source=source if source in LANES else None,
                )
            )
        finally:
            a.close()

    def tags(ctx: JobContext) -> dict[str, Any]:
        from . import tags as _tags

        ctx.stage("tags")
        return {"rows": _tags.rebuild(ctx.store)}

    def label(ctx: JobContext) -> dict[str, Any]:
        """Label the backlog: images stored before labels existed, or by an
        older model -- their kind, who is in them (gender-filtered characters)
        and the character's name. Blobs are read from disk; no source is contacted."""
        a = make_adapters(ctx)
        try:
            labeler = a.labels_for(ctx)
            if labeler is None:
                raise RuntimeError(
                    "image labels need numpy + onnxruntime: pip install 'reaver[classify]'"
                )
            limit = ctx.job.params.get("limit")
            out: dict[str, Any] = dict(
                label_pending(ctx.store, a.blobs, labeler, int(limit) if limit else None, ctx=ctx)
            )
            tagger = a.tags_for(ctx)
            if tagger is not None:  # the gender filter's backlog, same deps as labels
                out.update(
                    people_pending(
                        ctx.store, a.blobs, tagger, int(limit) if limit else None, ctx=ctx
                    )
                )
            identifier = a.identify_for(ctx)
            if identifier is not None:  # names for what was stored before (or unnamed)
                out.update(
                    identify_pending(
                        ctx.store, a.blobs, identifier, int(limit) if limit else None, ctx=ctx
                    )
                )
            return out
        finally:
            a.close()

    def export(ctx: JobContext) -> dict[str, Any]:
        """The archive as one file (coreflame/bundle.py). Reads a consistent
        db snapshot and immutable blobs, so it runs beside a crawl. Params:
        path, format (curio | zip), images, thumbs, secrets, ui."""
        a = make_adapters(ctx)
        try:
            p = ctx.job.params
            opts = bundle.ExportOptions(
                images=bool(p.get("images", True)),
                thumbs=bool(p.get("thumbs", True)),
                secrets=bool(p.get("secrets", False)),
                fmt=str(p.get("format", "curio")),
                ui=p.get("ui") if isinstance(p.get("ui"), dict) else None,
            )
            thumbs = ThumbStore(a.cfg.blob_root.parent / "thumbs")
            return bundle.export(
                ctx.store,
                a.blobs,
                thumbs,
                a.cfg,
                Path(str(p["path"])),
                opts,
                progress=_stage_progress(ctx),
                check=ctx.check,
            )
        finally:
            a.close()

    return {
        "poll": poll,
        "timelines": timelines,
        "link": link,
        "media": media,
        "tags": tags,
        "label": label,
        "export": export,
    }


def _stage_progress(ctx: JobContext) -> bundle.Progress:
    """bundle's (stage, done, total) callback onto the job's stage + progress."""
    last: dict[str, str | None] = {"stage": None}

    def on(stage: str, done: int, total: int | None, **totals: int) -> None:
        if stage != last["stage"]:
            last["stage"] = stage
            ctx.stage(stage)
        ctx.progress(done, total, **totals)

    return on


def plan(store: Store, type_: str, params: dict[str, Any] | None = None) -> list[tuple[str, dict]]:
    """What one request becomes in the queue. A crawl (`poll`) is split so each
    source's worker gets its own jobs: per character a pixiv poll (discover ->
    tags -> link -> download) and an X poll (search to the character's posts per
    run), then one X `timelines` job for the linked artists. `media` without a
    source becomes one per source. Everything else, and anything that already
    names its source, is one job as asked."""
    params = dict(params or {})
    if type_ == "media" and params.get("source") not in LANES:
        return [("media", {**params, "source": s}) for s in LANES]
    if type_ != "poll" or params.get("source") in LANES:
        return [(type_, params)]
    slugs = params.pop("watches", None)
    watches = [w for w in store.watches() if not slugs or w.slug in slugs]
    want_x = params.pop("twitter", True)
    out: list[tuple[str, dict]] = []
    for w in watches:
        if w.wants("pixiv"):
            out.append(("poll", {**params, "watches": [w.slug], "source": "pixiv"}))
    if want_x:
        for w in watches:
            if w.wants("twitter"):
                target = max(1, min(int(params.get("target") or w.target), TARGET_MAX))
                x = {k: v for k, v in params.items() if k != "link"}
                out.append(
                    ("poll", {**x, "watches": [w.slug], "source": "twitter", "target": target})
                )
        if any(w.wants("twitter") for w in watches):
            media = {"media": params["media"]} if "media" in params else {}
            out.append(("timelines", {**media, "accounts": len(store.followed_handles())}))
    return out


def submit(store: Store, type_: str, params: dict[str, Any] | None = None) -> list[str]:
    """Plan, then queue -- in order, so a source's jobs run in the order planned."""
    return [JobRunner.submit(store, t, p) for t, p in plan(store, type_, params)]


def default_runner(cfg: Config) -> JobRunner:
    """The runner the CLI and the daemon share."""

    def factory() -> Store:
        return Store(cfg.db_path)

    def make(ctx: JobContext) -> Adapters:
        return Adapters(cfg, ctx.store)

    return JobRunner(factory, build_handlers(make))
