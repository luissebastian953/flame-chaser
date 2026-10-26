from __future__ import annotations

import argparse
import json
import logging
import sys

from .blobs import BlobStore
from .config import Config
from .db import Store
from .models import Watch
from .pipeline import download_pending, resolve_artist_links, run_all
from .sources.pixiv import PixivAdapter
from .sources.twitter import TwitterAdapter


def _log(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_watch_add(args, cfg: Config) -> int:
    store = Store(cfg.db_path)
    w = Watch(
        slug=args.slug,
        label=args.label or args.slug,
        pixiv_tags=args.pixiv_tag or [],
        match_terms=args.term or [args.slug],
        min_bookmarks=args.min_bookmarks,
        include_r18=args.r18,
    )
    reopened = store.upsert_watch(w)
    print(f"watching {w.slug}: pixiv tags {w.pixiv_tags or '(none!)'}, X terms {w.match_terms}")
    if reopened:
        print(f"  reopened {reopened} previously skipped artworks for re-evaluation")
    if not w.pixiv_tags:
        print(
            "  note: with no pixiv tag there is no discovery source at all; "
            "add the JP character tag, e.g. --pixiv-tag 甘雨",
            file=sys.stderr,
        )
    return 0


def cmd_watch_list(args, cfg: Config) -> int:
    for w in Store(cfg.db_path).watches():
        print(
            f"{w.slug:<20} tags={w.pixiv_tags} terms={w.match_terms} "
            f"min_bm={w.min_bookmarks} r18={w.include_r18}"
        )
    return 0


def cmd_poll(args, cfg: Config) -> int:
    st = run_all(
        cfg,
        do_pixiv=not args.no_pixiv,
        do_link=not args.no_link,
        do_twitter=not args.no_twitter,
        do_media=not args.no_media,
    )
    print(
        f"listed={st.listed} gated={st.gated} (no request) new={st.new_posts} "
        f"seen={st.seen_posts} skipped={st.skipped} gone={st.gone} "
        f"downloaded={st.downloaded} dupes={st.dupes} failed={st.failed}"
    )
    for n in st.notes:
        print("  -", n)
    return 0


def cmd_link(args, cfg: Config) -> int:
    store, pixiv = Store(cfg.db_path), PixivAdapter(cfg.pixiv_php_sessid)
    try:
        st = resolve_artist_links(store, pixiv, args.limit, autofollow=not args.no_follow)
    finally:
        pixiv.close()
    print(f"resolved {len(st.notes)} handles")
    for n in st.notes:
        print("  -", n)
    return 0


def cmd_media(args, cfg: Config) -> int:
    store, blobs = Store(cfg.db_path), BlobStore(cfg.blob_root)
    pixiv = PixivAdapter(cfg.pixiv_php_sessid, rate=cfg.pixiv_rate)
    tw = TwitterAdapter(cfg.twitter_cookies_file, cfg.twitter_cookies_from_browser)
    try:
        st = download_pending(store, blobs, pixiv, tw, args.batch, cfg.dupe_threshold)
    finally:
        pixiv.close()
        tw.close()
    print(f"downloaded={st.downloaded} dupes={st.dupes} failed={st.failed}")
    return 0


def cmd_status(args, cfg: Config) -> int:
    store = Store(cfg.db_path)
    if store.applied:
        print("applied migrations:", ", ".join(store.applied))
    print(json.dumps(store.stats(), indent=2))
    rows = store.conn.execute(
        "SELECT source, feed, watermark, updated_at FROM poll_state "
        "ORDER BY updated_at DESC LIMIT 15"
    ).fetchall()
    if rows:
        print("\nwatermarks:")
        for r in rows:
            print(f"  {r['source']:<8} {r['feed']:<28} {r['watermark']} ({r['updated_at']})")
    return 0


def cmd_net(args, cfg: Config) -> int:
    from .net import DEFAULT_DOH, DohResolver, diagnose

    resolver = DohResolver(cfg.doh_endpoints or DEFAULT_DOH)
    worst = 0
    for host in args.hosts:
        d = diagnose(host, resolver=resolver, timeout=args.timeout)
        print(f"{host}")
        for line in d.steps:
            print(f"  {line}")
        print(f"  => {d.verdict}: {d.advice}\n")
        worst = max(worst, 0 if d.verdict == "ok" else 2 if d.verdict == "interception" else 1)
    return worst


def cmd_tags(args, cfg: Config) -> int:
    from . import tags

    store = Store(cfg.db_path)
    if args.watch or args.ignore:
        w = tags.set_state(
            store,
            args.slug,
            args.watch or args.ignore,
            tags.WATCHED if args.watch else tags.IGNORED,
        )
        print(f"{args.slug}: pixiv tags now {w.pixiv_tags}")
        if args.watch:
            print("  run `poll` to backfill the new tag")
        return 0
    if args.rebuild:
        print(f"rebuilt {tags.rebuild(store)} rows")
    rows = tags.observed(store, args.slug, limit=args.limit)
    if not rows:
        print(f"no observed tags for {args.slug} (crawl first, or --rebuild)")
        return 0
    print(f"{'state':<9} {'score':>6} {'share':>6} {'posts':>6} {'chars':>5}  tag")
    for t in rows:
        tr = f"  ({t.translated})" if t.translated else ""
        print(
            f"{t.state:<9} {t.score:>6.2f} {t.share:>6.0%} {t.posts:>6} {t.characters:>5}  {t.tag_raw}{tr}"
        )
    return 0


def cmd_suggest(args, cfg: Config) -> int:
    """LIVE: one pixiv search page for the tag, ranked co-occurring tags."""
    from . import tags
    from .handlers import make_pixiv

    store = Store(cfg.db_path)
    pixiv = make_pixiv(cfg)
    try:
        total, rows = pixiv.probe_tag(args.tag)
    finally:
        pixiv.close()
    print(f"{args.tag}: {total:,} artworks; ranking co-occurring tags from {len(rows)} on page 1")
    for t in tags.suggest_from_listing(store, rows, exclude=[args.tag])[: args.limit]:
        print(f"  {t.score:>5.2f} {t.share:>5.0%}  {t.tag_raw}")
    return 0


def _print_event(ev: dict) -> None:
    d = ev.get("data") or {}
    kind, msg = ev["kind"], ev["message"]
    if kind == "stage":
        extra = f"  [{d['state']}]" if "state" in d else ""
        print(f"== {msg}{extra}")
    elif kind == "progress":
        tail = " ".join(f"{k}={v}" for k, v in d.items() if k not in ("done", "total"))
        print(f"   {msg} {tail}".rstrip(), end="\r")
    elif kind == "item":
        print(f"   {d.get('action', '·'):<6} {msg}")
    else:
        lvl = "!" if ev.get("level") in ("warning", "error") else " "
        print(f"  {lvl} {msg}")


def cmd_bundle(args, cfg: Config) -> int:
    from pathlib import Path

    from . import bundle
    from .thumbs import ThumbStore

    path = Path(args.path).expanduser()
    store = Store(cfg.db_path)
    blobs, thumbs = BlobStore(cfg.blob_root), ThumbStore(cfg.blob_root.parent / "thumbs")

    def show(stage: str, done: int, total: int | None) -> None:
        print(f"\r{stage:<9} {done}/{total if total is not None else '?'}   ", end="", flush=True)

    try:
        if args.action == "export":
            fmt = args.format or ("zip" if path.suffix == ".zip" else "curio")
            opts = bundle.ExportOptions(
                images=not args.no_images, thumbs=not args.no_thumbs, secrets=args.secrets, fmt=fmt
            )
            out = bundle.export(store, blobs, thumbs, cfg, path, opts, progress=show)
            print()
            print(json.dumps(out, indent=2))
        elif args.action == "inspect":
            print(json.dumps(bundle.inspect(path, store), indent=2, ensure_ascii=False))
        elif args.action == "verify":
            rep = bundle.verify(path)
            print(json.dumps(rep, indent=2))
            return 0 if rep["ok"] else 1
        else:
            iopts = bundle.ImportOptions(
                mode="restore" if args.restore else "merge",
                settings=args.settings,
                secrets=args.secrets,
                default_policy=args.policy,
                salvage=args.salvage,
            )
            out = bundle.import_(store, blobs, thumbs, cfg, path, iopts, progress=show)
            print()
            out.pop("ui", None)
            print(json.dumps(out, indent=2))
    except bundle.BundleError as e:
        print(f"\n{e.code}: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_jobs(args, cfg: Config) -> int:
    from .handlers import default_runner
    from .jobs import JobRunner

    store = Store(cfg.db_path)
    if args.action == "list":
        for j in JobRunner.list_jobs(store, limit=args.limit):
            fin = (j.finished_at or "")[:19].replace("T", " ")
            print(
                f"{j.id}  {j.type:<6} {j.state:<11} {j.stage or '':<9} "
                f"{j.done}/{j.total if j.total is not None else '?':<6} {fin}  {j.error or ''}"
            )
        return 0
    if args.action == "cancel":
        runner = default_runner(cfg)
        print("cancel requested" if runner.cancel(store, args.job_id) else "no such active job")
        return 0
    if args.action == "tail":
        for ev in JobRunner.tail(store, args.job_id, args.limit):
            _print_event(ev)
        return 0
    # run: submit, then drain the queue synchronously in this process
    runner = default_runner(cfg)
    if runner.interrupted:
        print(f"marked {runner.interrupted} job(s) interrupted from a previous run")
    params = {"watches": args.watch or None}
    jid = JobRunner.submit(store, args.job_type, params)
    print(f"job {jid} ({args.job_type}) queued")
    runner.subscribers.append(_print_event)
    runner.run_pending(store)
    job = JobRunner.get(store, jid)
    print()
    if job is None:
        print(f"job {jid}: vanished")
        return 1
    print(f"job {jid}: {job.state}" + (f" -- {job.error}" if job.error else ""))
    if job.counters:
        print("  " + "  ".join(f"{k}={v}" for k, v in job.counters.items() if v))
    return 0 if job.state == "succeeded" else 1


def cmd_doctor(args, cfg: Config) -> int:
    ok = True
    print(f"home:        {cfg.home}")
    print(f"db:          {cfg.db_path}")
    print(f"blobs:       {cfg.blob_root}")
    has_cookie = bool(cfg.pixiv_php_sessid)
    print(
        f"pixiv auth:  {'PHPSESSID set' if has_cookie else 'anonymous'}"
        f"{'' if has_cookie else '  (no R-18, stricter limits)'}"
    )
    print(
        f"resolver:    {cfg.resolver}"
        + ("" if cfg.resolver == "doh" else "  (run `coreflame net pixiv.net` if requests fail)")
    )
    print(f"proxy:       {cfg.proxy_url or 'none'}")
    tw = TwitterAdapter(cfg.twitter_cookies_file, cfg.twitter_cookies_from_browser)
    if tw.available():
        print("gallery-dl:  found")
    else:
        print("gallery-dl:  MISSING -- `pip install gallery-dl`; X polling disabled")
        ok = False
    if not (cfg.twitter_cookies_file or cfg.twitter_cookies_from_browser):
        print("x cookies:   none configured -- X timelines will be login-walled")
        ok = False
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="coreflame",
        description="Personal watcher for illustrations of specific characters "
        "(pixiv discovery + X follow feed).",
    )
    p.add_argument("-c", "--config")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("watch", help="add a character to watch")
    a.add_argument("slug")
    a.add_argument("--label", default="")
    a.add_argument(
        "--pixiv-tag", action="append", help="exact pixiv tag; repeatable (use the JP tag)"
    )
    a.add_argument("--term", action="append", help="text term for matching X posts; repeatable")
    a.add_argument("--min-bookmarks", type=int, default=0)
    a.add_argument("--r18", action="store_true")
    a.set_defaults(func=cmd_watch_add)

    b = sub.add_parser("watches", help="list watches")
    b.set_defaults(func=cmd_watch_list)

    c = sub.add_parser("poll", help="run the full cycle")
    c.add_argument("--no-pixiv", action="store_true")
    c.add_argument("--no-link", action="store_true")
    c.add_argument("--no-twitter", action="store_true")
    c.add_argument("--no-media", action="store_true")
    c.set_defaults(func=cmd_poll)

    d = sub.add_parser("link", help="resolve pixiv artists to X handles")
    d.add_argument("--limit", type=int, default=50)
    d.add_argument("--no-follow", action="store_true")
    d.set_defaults(func=cmd_link)

    e = sub.add_parser("media", help="download pending media only")
    e.add_argument("--batch", type=int, default=200)
    e.set_defaults(func=cmd_media)

    f = sub.add_parser("status", help="counts and watermarks")
    f.set_defaults(func=cmd_status)

    g = sub.add_parser("doctor", help="check auth and dependencies")
    g.set_defaults(func=cmd_doctor)

    t = sub.add_parser("tags", help="observed tags for a character; watch/ignore one")
    t.add_argument("slug")
    t.add_argument("--watch", metavar="TAG", help="add this observed tag to the watch")
    t.add_argument("--ignore", metavar="TAG", help="never suggest this tag again")
    t.add_argument("--rebuild", action="store_true")
    t.add_argument("--limit", type=int, default=30)
    t.set_defaults(func=cmd_tags)

    u = sub.add_parser("suggest", help="LIVE: rank co-occurring tags for a pixiv tag")
    u.add_argument("tag")
    u.add_argument("--limit", type=int, default=15)
    u.set_defaults(func=cmd_suggest)

    j = sub.add_parser("jobs", help="run / list / tail / cancel jobs")
    js = j.add_subparsers(dest="action", required=True)
    jr = js.add_parser("run", help="submit a job and run the queue in this process")
    jr.add_argument("job_type", choices=["poll", "link", "media", "tags"])
    jr.add_argument("--watch", action="append", help="restrict to these slugs")
    jl = js.add_parser("list")
    jl.add_argument("--limit", type=int, default=20)
    jt = js.add_parser("tail")
    jt.add_argument("job_id")
    jt.add_argument("--limit", type=int, default=200)
    jc = js.add_parser("cancel")
    jc.add_argument("job_id")
    j.set_defaults(func=cmd_jobs)

    bu = sub.add_parser("bundle", help="export the archive as one file, inspect or import one")
    bs = bu.add_subparsers(dest="action", required=True)
    be = bs.add_parser("export", help="write a .curio (or .zip) bundle")
    be.add_argument("path")
    be.add_argument("--format", choices=["curio", "zip"], default=None, help="from the extension")
    be.add_argument("--no-images", action="store_true")
    be.add_argument("--no-thumbs", action="store_true")
    be.add_argument("--secrets", action="store_true", help="include the pixiv session cookie")
    bi = bs.add_parser("inspect", help="what a bundle holds and where it collides")
    bi.add_argument("path")
    bv = bs.add_parser("verify", help="re-hash every entry; name the damaged ones")
    bv.add_argument("path")
    bm = bs.add_parser("import", help="merge (default) or restore from a bundle")
    bm.add_argument("path")
    bm.add_argument("--restore", action="store_true", help="replace the archive with the bundle")
    bm.add_argument("--settings", choices=["keep", "take"], default="keep")
    bm.add_argument("--secrets", action="store_true", help="take the bundle's session cookie")
    bm.add_argument("--policy", choices=["merge", "keep", "take"], default="merge")
    bm.add_argument("--salvage", action="store_true", help="go on past damaged entries")
    bu.set_defaults(func=cmd_bundle)

    h = sub.add_parser("net", help="diagnose which network layer blocks a host")
    h.add_argument("hosts", nargs="*", default=["www.pixiv.net", "i.pximg.net", "x.com"])
    h.add_argument("--timeout", type=float, default=5.0)
    h.set_defaults(func=cmd_net)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _log(args.verbose)
    cfg = Config.load(args.config)
    return int(args.func(args, cfg))


if __name__ == "__main__":
    raise SystemExit(main())
