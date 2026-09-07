"""Job type -> pipeline function. This is the only place the runner learns
what a "poll" is; the pipeline functions stay callable without a runner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from .blobs import BlobStore
from .config import Config
from .jobs import Handler, JobContext, JobRunner
from .pipeline import (
    RunStats,
    download_pending,
    poll_pixiv,
    poll_twitter,
    resolve_artist_links,
)
from .sources.pixiv import PixivAdapter
from .sources.twitter import TwitterAdapter


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

    def __init__(self, cfg: Config, store: Any) -> None:
        self.pixiv = make_pixiv(cfg, sink=store)
        self.twitter = TwitterAdapter(
            cfg.twitter_cookies_file,
            cfg.twitter_cookies_from_browser,
            proxy=cfg.proxy_url,
            sink=store,
        )
        self.blobs = BlobStore(cfg.blob_root)
        self.cfg = cfg

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
            if ctx.job.params.get("twitter", True) and a.twitter.available():
                st.merge(
                    poll_twitter(
                        ctx.store, a.twitter, watches, limit=a.cfg.twitter_timeline_limit, ctx=ctx
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
                )
            )
        finally:
            a.close()

    def tags(ctx: JobContext) -> dict[str, Any]:
        from . import tags as _tags

        ctx.stage("tags")
        return {"rows": _tags.rebuild(ctx.store)}

    return {"poll": poll, "link": link, "media": media, "tags": tags}


def default_runner(cfg: Config) -> JobRunner:
    """The runner the CLI and the daemon share."""
    from .db import Store

    def factory() -> Store:
        return Store(cfg.db_path)

    def make(ctx: JobContext) -> Adapters:
        return Adapters(cfg, ctx.store)

    return JobRunner(factory, build_handlers(make))
