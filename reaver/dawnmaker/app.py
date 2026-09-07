"""The HTTP surface. Imports coreflame; coreflame never imports this.

One Store per worker thread (sqlite connections are thread-bound; FastAPI runs
sync endpoints in a threadpool). Every error is `{"error": {code, message}}`.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from coreflame import __version__, tags
from coreflame.blobs import BlobStore
from coreflame.config import Config
from coreflame.db import Store
from coreflame.jobs import JobRunner
from coreflame.models import Watch
from coreflame.thumbs import ThumbStore

from .auth import Auth
from .events import EventHub
from .probe import Prober
from .security import LoopbackAuth


class Heartbeat:
    """Layer 2 of the sidecar lifecycle: exit after `timeout` without a beat,
    measured on a monotonic clock. A gap over `sleep_grace` is a laptop wake,
    not a dead shell -- grant one grace period instead of dying."""

    def __init__(self, timeout: float = 30.0, sleep_grace: float = 300.0) -> None:
        self.timeout, self.sleep_grace = timeout, sleep_grace
        self.last = time.monotonic()
        self.enabled = True

    def beat(self) -> None:
        self.last = time.monotonic()

    def expired(self) -> bool:
        if not self.enabled:
            return False
        gap = time.monotonic() - self.last
        if gap > self.sleep_grace:  # slept; give the shell one timeout to resume
            self.last = time.monotonic() - self.timeout / 2
            return False
        return gap > self.timeout


def _cursor_enc(posted_at: str, external_id: str) -> str:
    """Opaque on purpose: a raw '+00:00' in a query string decodes to a space."""
    return base64.urlsafe_b64encode(f"{posted_at}|{external_id}".encode()).decode().rstrip("=")


def _cursor_dec(cursor: str) -> tuple[str, str]:
    pad = "=" * (-len(cursor) % 4)
    posted_at, external_id = base64.urlsafe_b64decode(cursor + pad).decode().rsplit("|", 1)
    return posted_at, external_id


class State:
    def __init__(
        self,
        cfg: Config,
        runner: JobRunner,
        hub: EventHub,
        token: str,
        port: int,
        prober: Prober | None = None,
    ) -> None:
        self.cfg, self.runner, self.hub, self.token, self.port = cfg, runner, hub, token, port
        self.heartbeat = Heartbeat()
        self.prober = prober or Prober(cfg)
        self.auth = Auth(cfg)
        self.blobs = BlobStore(cfg.blob_root)
        self.thumbs = ThumbStore(Path(cfg.blob_root).parent / "thumbs")

    def open_store(self) -> Store:
        """A Store for ONE request. A thread-local cache is wrong here: the
        dependency and the endpoint run on different threadpool threads, and
        the SSE stream pins one of them for its whole lifetime."""
        return Store(self.cfg.db_path, check_same_thread=False)


# ---------------------------------------------------------------- schemas
class PixivAuthIn(BaseModel):
    php_sessid: str


class TwitterAuthIn(BaseModel):
    auth_token: str
    ct0: str


class ProbeIn(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=8)
    include_r18: bool = False


class WatchIn(BaseModel):
    slug: str
    label: str = ""
    pixiv_tags: list[str] = Field(default_factory=list)
    match_terms: list[str] = Field(default_factory=list)
    min_bookmarks: int = 0
    include_r18: bool = False


class JobIn(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class TagAction(BaseModel):
    tag: str
    action: str  # watch | ignore


class ConfigIn(BaseModel):
    library_root: str | None = None
    pixiv_rate: float | None = None
    dupe_threshold: int | None = None
    twitter_cookies_file: str | None = None
    twitter_timeline_limit: int | None = None
    resolver: str | None = None
    proxy_url: str | None = None


def create_app(state: State, dev: bool = False) -> FastAPI:
    app = FastAPI(title="dawnmaker", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(LoopbackAuth, token=state.token, port=state.port, dev=dev)

    def store() -> Iterator[Store]:
        s = state.open_store()
        try:
            yield s
        finally:
            s.close()

    @app.exception_handler(HTTPException)
    async def _err(_: Request, e: HTTPException) -> JSONResponse:
        detail = (
            e.detail if isinstance(e.detail, dict) else {"code": "error", "message": str(e.detail)}
        )
        return JSONResponse({"error": detail}, e.status_code)

    def nf(code: str, msg: str) -> HTTPException:
        return HTTPException(404, {"code": code, "message": msg})

    # -- lifecycle -----------------------------------------------------------
    @app.get("/api/health")
    def health(s: Store = Depends(store)) -> dict:
        return {
            "ok": True,
            "version": __version__,
            "library_root": str(state.cfg.blob_root.parent),
            "db_path": str(state.cfg.db_path),
            "schema_version": s.stats()["schema_version"],
            "idle": JobRunner.idle(s),
            "last_event_id": state.hub.last_id,
        }

    @app.post("/api/heartbeat")
    def heartbeat() -> dict:
        state.heartbeat.beat()
        return {"ok": True}

    # -- config & status -----------------------------------------------------
    @app.get("/api/config")
    def get_config() -> dict:
        c = state.cfg
        return {
            "library_root": str(c.blob_root.parent),
            "pixiv_rate": c.pixiv_rate,
            "dupe_threshold": c.dupe_threshold,
            "resolver": c.resolver,
            "proxy_url": c.proxy_url,
            "twitter_timeline_limit": c.twitter_timeline_limit,
            "pixiv_session": bool(c.pixiv_php_sessid),  # redacted to a bool
            "twitter_cookies": bool(c.twitter_cookies_file or c.twitter_cookies_from_browser),
        }

    @app.put("/api/config")
    def put_config(body: ConfigIn) -> dict:
        c = state.cfg
        if body.library_root is not None:
            root = Path(body.library_root).expanduser()
            from coreflame.library import under_sync_root

            if m := under_sync_root(root):
                raise HTTPException(
                    400,
                    {
                        "code": "sync_folder",
                        "message": f"library under a '{m}' sync folder: hardlinks "
                        "get materialised as copies there",
                    },
                )
            c.blob_root = root / "blobs"
            state.blobs = BlobStore(c.blob_root)
            state.thumbs = ThumbStore(root / "thumbs")
        for k in (
            "pixiv_rate",
            "dupe_threshold",
            "twitter_cookies_file",
            "twitter_timeline_limit",
            "resolver",
            "proxy_url",
        ):
            v = getattr(body, k)
            if v is not None:
                setattr(c, k, v)
        c.save()
        return get_config()

    def _sources() -> dict:
        c = state.cfg
        px = state.auth.pixiv_status()
        return {
            "pixiv": {
                "authed": px.authed,
                "user_id": px.user_id,
                "verified": px.verified,
                "checked_at": px.checked_at,
                "error": px.error,
            },
            "twitter": state.auth.twitter_status(),
            "network": {"resolver": c.resolver, "proxy": bool(c.proxy_url)},
        }

    @app.get("/api/sources/status")
    def sources_status() -> dict:
        return _sources()

    # -- auth: sessions arrive from the shell's login window or a paste; the
    #    secret is stored 0600 outside config.json and never echoed back ----
    @app.post("/api/auth/pixiv")
    def auth_pixiv(body: PixivAuthIn) -> dict:
        try:
            state.auth.set_pixiv(body.php_sessid)
        except ValueError as e:
            raise HTTPException(400, {"code": "bad_cookie", "message": str(e)}) from e
        except PermissionError as e:
            raise HTTPException(401, {"code": "session_rejected", "message": str(e)}) from e
        state.prober.reset()
        return _sources()

    @app.post("/api/auth/pixiv/verify")
    def auth_pixiv_verify() -> dict:
        state.auth.verify_pixiv()
        return _sources()

    @app.delete("/api/auth/pixiv", status_code=204)
    def auth_pixiv_clear() -> None:
        state.auth.clear_pixiv()
        state.prober.reset()

    @app.post("/api/auth/twitter")
    def auth_twitter(body: TwitterAuthIn) -> dict:
        try:
            state.auth.set_twitter(body.auth_token, body.ct0)
        except ValueError as e:
            raise HTTPException(400, {"code": "bad_cookie", "message": str(e)}) from e
        return _sources()

    @app.delete("/api/auth/twitter", status_code=204)
    def auth_twitter_clear() -> None:
        state.auth.clear_twitter()

    @app.post("/api/net/diagnose")
    def net_diagnose(host: str = "www.pixiv.net") -> dict:
        from coreflame.net import DEFAULT_DOH, DohResolver, diagnose

        d = diagnose(host, resolver=DohResolver(state.cfg.doh_endpoints or DEFAULT_DOH))
        return {
            "host": d.host,
            "verdict": d.verdict,
            "advice": d.advice,
            "steps": d.steps,
            "system_ip": d.system_ip,
            "doh_ip": d.doh_ip,
        }

    @app.get("/api/stats")
    def stats(s: Store = Depends(store)) -> dict:
        return s.stats()

    # -- watches ---------------------------------------------------------------
    @app.get("/api/watches")
    def list_watches(s: Store = Depends(store)) -> list[dict]:
        out = []
        for w in s.watches():
            r = s.conn.execute(
                """SELECT count(*) n, max(p.posted_at) latest FROM post_watches pw
                   JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
                   WHERE pw.slug=?""",
                (w.slug,),
            ).fetchone()
            cover = s.conn.execute(
                """SELECT m.sha256 FROM post_watches pw
                   JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
                   JOIN media m ON m.source=p.source AND m.external_id=p.external_id
                   WHERE pw.slug=? AND m.state='stored' AND p.state='live'
                   ORDER BY p.posted_at DESC, p.external_id DESC, m.idx LIMIT 1""",
                (w.slug,),
            ).fetchone()
            out.append(
                {
                    **w.model_dump(),
                    "post_count": r["n"],
                    "latest_posted_at": r["latest"],
                    "cover_sha": cover["sha256"] if cover else None,
                }
            )
        return out

    @app.post("/api/watches", status_code=201)
    def create_watch(body: WatchIn, s: Store = Depends(store)) -> dict:
        w = Watch(**body.model_dump())
        reopened = s.upsert_watch(w)
        return {**w.model_dump(), "reopened": reopened}

    @app.patch("/api/watches/{slug}")
    def patch_watch(slug: str, body: WatchIn, s: Store = Depends(store)) -> dict:
        if not any(w.slug == slug for w in s.watches()):
            raise nf("no_watch", slug)
        w = Watch(**{**body.model_dump(), "slug": slug})
        return {**w.model_dump(), "reopened": s.upsert_watch(w)}

    @app.delete("/api/watches/{slug}", status_code=204)
    def delete_watch(slug: str, s: Store = Depends(store)) -> None:
        with s.tx():
            s.conn.execute("DELETE FROM post_watches WHERE slug=?", (slug,))
            s.conn.execute("DELETE FROM tag_stats WHERE slug=?", (slug,))
            s.conn.execute("DELETE FROM watches WHERE slug=?", (slug,))

    # -- character form: live validation, preview, suggestions ---------------
    @app.post("/api/pixiv/probe")
    def pixiv_probe(body: ProbeIn, s: Store = Depends(store)) -> dict:
        """One search page per tag (cached). Spends pixiv requests -- the form
        debounces; the daemon caps it at 8 tags per call."""
        return state.prober.probe(s, body.tags, body.include_r18)

    @app.get("/api/preview/{illust_id}/thumb")
    def preview_thumb(illust_id: str) -> Response:
        if not illust_id.isdigit():
            raise HTTPException(404)
        got = state.prober.thumb(illust_id)
        if got is None:
            raise HTTPException(404, {"code": "not_probed", "message": "not from a probe"})
        data, ctype = got
        return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=900"})

    @app.post("/api/watches/{slug}/tags")
    def watch_tag(slug: str, body: TagAction, s: Store = Depends(store)) -> dict:
        if body.action not in ("watch", "ignore"):
            raise HTTPException(400, {"code": "bad_action", "message": body.action})
        w = tags.set_state(
            s, slug, body.tag, tags.WATCHED if body.action == "watch" else tags.IGNORED
        )
        return w.model_dump()

    # -- jobs & events -----------------------------------------------------------
    @app.post("/api/jobs", status_code=202)
    def submit_job(body: JobIn, s: Store = Depends(store)) -> dict:
        if body.type not in state.runner.handlers:
            raise HTTPException(400, {"code": "bad_type", "message": body.type})
        jid = JobRunner.submit(s, body.type, body.params)
        state.runner.kick()
        return {"job_id": jid}

    @app.get("/api/jobs")
    def list_jobs(
        state_: str | None = Query(None, alias="state"), limit: int = 50, s: Store = Depends(store)
    ) -> list[dict]:
        return [j.__dict__ for j in JobRunner.list_jobs(s, state_, limit)]

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str, s: Store = Depends(store)) -> dict:
        j = JobRunner.get(s, jid)
        if j is None:
            raise nf("no_job", jid)
        return {**j.__dict__, "log": JobRunner.tail(s, jid, 200)}

    @app.post("/api/jobs/{jid}/cancel", status_code=202)
    def cancel_job(jid: str, s: Store = Depends(store)) -> dict:
        if not state.runner.cancel(s, jid):
            raise nf("no_active_job", jid)
        return {"ok": True}

    @app.get("/api/events")
    def events(request: Request, live: bool = True) -> StreamingResponse:
        last = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
        gen: Iterator[str] = state.hub.stream(
            int(last) if last and last.isdigit() else None, live=live
        )
        return StreamingResponse(
            gen,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # -- gallery -----------------------------------------------------------------
    @app.get("/api/gallery")
    def gallery(s: Store = Depends(store)) -> list[dict]:
        return list_watches(s)

    @app.get("/api/gallery/{slug}")
    def gallery_slug(
        slug: str,
        cursor: str | None = None,
        limit: int = Query(100, le=500),
        source: str | None = None,
        r18: str = "exclude",
        s: Store = Depends(store),
    ) -> dict:
        """Keyset on (posted_at, external_id) -- offset pagination duplicates and
        skips rows when a crawl inserts while the user scrolls."""
        where = ["pw.slug=?", "m.state='stored'", "p.state='live'"]
        args: list[Any] = [slug]
        if source:
            where.append("p.source=?")
            args.append(source)
        if r18 == "exclude":
            where.append("p.is_r18=0")
        if cursor:
            try:
                c_posted, c_id = _cursor_dec(cursor)
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(400, {"code": "bad_cursor", "message": cursor}) from None
            where.append("(p.posted_at < ? OR (p.posted_at = ? AND p.external_id < ?))")
            args += [c_posted, c_posted, c_id]
        rows = s.conn.execute(
            f"""SELECT m.sha256, m.source, m.external_id, m.idx, m.width, m.height,
                       p.posted_at, p.artist_name, p.title
                FROM post_watches pw
                JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
                JOIN media m ON m.source=p.source AND m.external_id=p.external_id
                WHERE {" AND ".join(where)}
                ORDER BY p.posted_at DESC, p.external_id DESC, m.idx
                LIMIT ?""",
            (*args, limit + 1),
        ).fetchall()
        items = [{**dict(r), "thumb_url": f"/api/media/{r['sha256']}/thumb"} for r in rows[:limit]]
        nxt = None
        if len(rows) > limit:
            last = rows[limit - 1]
            nxt = _cursor_enc(last["posted_at"], last["external_id"])
        return {"items": items, "next_cursor": nxt}

    @app.get("/api/gallery/{slug}/tags")
    def gallery_tags(
        slug: str,
        state_: str | None = Query(None, alias="state"),
        limit: int = 40,
        s: Store = Depends(store),
    ) -> list[dict]:
        return [t.__dict__ for t in tags.observed(s, slug, state_, limit)]

    @app.get("/api/posts/{source}/{external_id}")
    def post_detail(source: str, external_id: str, s: Store = Depends(store)) -> dict:
        p = s.conn.execute(
            "SELECT * FROM posts WHERE source=? AND external_id=?", (source, external_id)
        ).fetchone()
        if p is None:
            raise nf("no_post", f"{source}/{external_id}")
        media = [
            dict(r)
            for r in s.conn.execute(
                "SELECT * FROM media WHERE source=? AND external_id=? ORDER BY idx",
                (source, external_id),
            )
        ]
        tag_rows = [
            dict(r)
            for r in s.conn.execute(
                "SELECT tag_raw, tag_norm, translated FROM post_tags WHERE source=? AND external_id=?",
                (source, external_id),
            )
        ]
        # the payoff of the phash work: the other source's copy of the same image
        linked = []
        for m in media:
            if m["state"] == "dupe" and m["dupe_of"]:
                o = s.conn.execute(
                    """SELECT m.source, m.external_id, p.permalink, p.posted_at
                       FROM media m JOIN posts p ON p.source=m.source AND p.external_id=m.external_id
                       WHERE m.sha256=? AND m.state='stored' LIMIT 1""",
                    (m["dupe_of"],),
                ).fetchone()
                if o:
                    linked.append({**dict(o), "reason": m["error"]})
            elif m["state"] == "stored" and m["sha256"]:
                for o in s.conn.execute(
                    """SELECT m.source, m.external_id, p.permalink, p.posted_at, m.error reason
                       FROM media m JOIN posts p ON p.source=m.source AND p.external_id=m.external_id
                       WHERE m.dupe_of=? AND NOT (m.source=? AND m.external_id=?)""",
                    (m["sha256"], source, external_id),
                ):
                    linked.append(dict(o))
        return {**dict(p), "media": media, "tags": tag_rows, "linked": linked}

    # -- media ----------------------------------------------------------------------
    IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}

    @app.get("/api/media/{sha}/thumb")
    def media_thumb(sha: str) -> FileResponse:
        p = state.thumbs.path_for(sha)
        if not p.exists():
            raise nf("no_thumb", sha)
        return FileResponse(p, media_type="image/webp", headers=IMMUTABLE)

    @app.get("/api/media/{sha}/full")
    def media_full(sha: str, s: Store = Depends(store)) -> FileResponse:
        r = s.conn.execute(
            "SELECT ext FROM media WHERE sha256=? AND state='stored' LIMIT 1", (sha,)
        ).fetchone()
        if r is None:
            raise nf("no_media", sha)
        p = state.blobs.path_for(sha, r["ext"])
        if not p.exists():
            raise nf("blob_missing", sha)
        return FileResponse(p, headers=IMMUTABLE)  # FileResponse handles Range

    return app
