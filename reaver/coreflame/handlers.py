"""Job type -> pipeline function. This is the only place the runner learns
what a "poll" is; the pipeline functions stay callable without a runner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from .blobs import BlobStore
from .config import Config
from .identify import Identifier, Identifies, make_identifier
from .jobs import Handler, JobContext, JobRunner
from .kinds import Labeler, Labels, make_labeler
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

    def poll(ctx: JobContext) -> dict[str, Any]:
        a = make_adapters(ctx)
        try:
            slugs = ctx.job.params.get("watches")
            watches = [w for w in ctx.store.watches() if not slugs or w.slug in slugs]
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
                # search each character until its posts-per-run are KEPT (params.target
                # overrides every character's own), then linked artists' timelines
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
                        )
                    )
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
                st.merge(
                    download_pending(
                        ctx.store,
                        a.blobs,
                        a.pixiv,
                        a.twitter,
                        threshold=a.cfg.dupe_threshold,
                        ctx=ctx,
                        labeler=a.labels_for(ctx),
                        tagger=a.tags_for(ctx),
                        identifier=a.identify_for(ctx),
                    )
                )
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

    return {"poll": poll, "link": link, "media": media, "tags": tags, "label": label}


def default_runner(cfg: Config) -> JobRunner:
    """The runner the CLI and the daemon share."""
    from .db import Store

    def factory() -> Store:
        return Store(cfg.db_path)

    def make(ctx: JobContext) -> Adapters:
        return Adapters(cfg, ctx.store)

    return JobRunner(factory, build_handlers(make))
