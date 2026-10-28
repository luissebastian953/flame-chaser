"""The HTTP surface. Imports coreflame; coreflame never imports this.

One Store per worker thread (sqlite connections are thread-bound; FastAPI runs
sync endpoints in a threadpool). Every error is `{"error": {code, message}}`.
"""

from __future__ import annotations

import base64
import dataclasses
import shutil
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from coreflame import (
    __version__,
    bundle,
    handlers,
    identify,
    kinds,
    label,
    origin,
    people,
    purge,
    tags,
    trash,
)
from coreflame.blobs import BlobStore
from coreflame.config import Config
from coreflame.db import Store
from coreflame.http import METER
from coreflame.jobs import JobRunner
from coreflame.models import Watch
from coreflame.thumbs import ThumbStore

from .auth import Auth
from .events import EventHub
from .names import NameFinder
from .probe import Prober
from .security import LoopbackAuth
from .speed import SpeedMeter


class Heartbeat:
    """Layer 2 of the sidecar lifecycle: exit after `timeout` without a beat,
    measured on a monotonic clock -- but never on the first silence. A gap is
    as often a laptop that slept or a shell whose clock was throttled as a
    dead shell, and a live shell beats again within seconds of waking: grant
    one grace period of `timeout / 2`, and exit only if that passes in
    silence too. A beat resets the grant."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self.last = time.monotonic()
        self.enabled = True
        self.graced = False

    def beat(self) -> None:
        self.last = time.monotonic()
        self.graced = False

    def expired(self) -> bool:
        if not self.enabled:
            return False
        if time.monotonic() - self.last <= self.timeout:
            return False
        if self.graced:
            return True
        self.graced = True
        self.last = time.monotonic() - self.timeout / 2
        return False


def _free_bytes(path: Path) -> int:
    """Free space on the disk holding the library. The blob folder is made on
    first download, so before that the nearest existing parent answers."""
    while not path.exists():
        if path.parent == path:
            return 0
        path = path.parent
    return shutil.disk_usage(path).free


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
        names: NameFinder | None = None,
        speed: SpeedMeter | None = None,
    ) -> None:
        self.cfg, self.runner, self.hub, self.token, self.port = cfg, runner, hub, token, port

        # the queue's hold changing hands (Pause queue, the internet going
        # away or coming back) is an event, so the pipeline page and the mini
        # window learn it at once rather than on their next 3 s poll
        def announce_hold(on: bool, reason: str | None) -> None:
            hub.publish("pipeline.paused", {"paused": on, "reason": reason})

        runner.on_hold.append(announce_hold)
        self.heartbeat = Heartbeat()
        self.prober = prober or Prober(cfg)
        self.names = names or NameFinder(cfg)
        self.speed = speed or SpeedMeter(cfg)
        self.auth = Auth(cfg)
        self.blobs = BlobStore(cfg.blob_root)
        self.thumbs = ThumbStore(Path(cfg.blob_root).parent / "thumbs")
        # held by an import or a purge: the two rewrite the database and the
        # library wholesale, so neither may start while the other runs
        self.exclusive = threading.Lock()
        self.purge: dict[str, Any] | None = None  # the last purge's progress

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
    sources: list[str] = Field(default_factory=lambda: ["pixiv", "twitter"])
    target: int = Field(100, ge=1, le=1000)
    kind_filter: bool = True
    gender: Literal["any", "female", "male"] = "any"
    gender_mode: Literal["full", "partial"] = "full"


class NamesIn(BaseModel):
    """The display name first, then the character's pixiv tags and X terms."""

    queries: list[str] = Field(default_factory=list, max_length=8)
    refresh: bool = False  # past the day's cache: the form's refresh button


class JobIn(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class PauseIn(BaseModel):
    paused: bool


class ReorderIn(BaseModel):
    ids: list[str]


class TagAction(BaseModel):
    tag: str
    action: str  # watch | ignore


IDENT_STATES = ("identified", "unidentified", "pending")  # gallery `ident` filter
# a stale model verdict reads as pending; a declared or tagged one never goes stale
ORIGIN_JOIN = "LEFT JOIN image_origin o ON o.sha256=m.sha256 AND (o.by<>'model' OR o.model=?)"
# the one badge per image (coreflame/label.py): the fold over k, o, i and the hand-set l
LABEL_JOIN = label.MANUAL_JOIN
LABEL_COLS = f"({label.LABEL_SQL}) AS label, {label.SOURCE_SQL} AS label_source"


class LabelIn(BaseModel):
    label: str | None  # ai | non_illust | unidentified | null = "no label", by hand


class CleanupRuleIn(BaseModel):
    """Settings › Duplicates: the Smart criteria applied at crawl time (coreflame/trash.py)."""

    active: bool = True
    min_score: float | None = Field(None, ge=0, le=1)
    other_character: bool = True


class ShasIn(BaseModel):
    shas: list[str] = Field(default_factory=list, max_length=20000)


class DeleteIn(ShasIn):
    mode: Literal["image", "tag", "smart", "all"] = "image"
    trash: bool = True
    forget: bool = True
    confirm: str | None = None  # mode=all: the character's name, typed


class SmartIn(BaseModel):
    min_score: float | None = Field(None, ge=0, le=1)
    other_character: bool = True
    dupes: bool = True
    distance: int = Field(trash.DUPE_DISTANCE, ge=0, le=16)
    unidentified: bool = False
    kinds: bool = False  # photos, 3D renders, screenshots: anything but kinds.KEEP


class PurgeIn(BaseModel):
    everything: bool = False


class StoragePurgeIn(BaseModel):
    """Settings › Storage › Purge all data. `confirm` is the phrase the user
    typed; the daemon re-checks it so no stray request can wipe the archive."""

    scope: Literal["galleries", "all"]
    confirm: str


class SpeedIn(BaseModel):
    full: bool = False  # download + upload, the modal's long probe


class BundleExportIn(BaseModel):
    """Settings › Storage › Export. `path` is where the shell's save dialog
    pointed; without one (browser mode) the daemon picks ~/.reaver/exports."""

    path: str | None = None
    format: Literal["curio", "zip"] = "curio"
    images: bool = True
    thumbs: bool = True
    secrets: bool = False
    ui: dict[str, Any] = Field(default_factory=dict)  # the webview's localStorage, opaque


class BundlePathIn(BaseModel):
    path: str


class BundleImportIn(BundlePathIn):
    mode: Literal["merge", "restore"] = "merge"
    settings: Literal["keep", "take"] = "keep"
    secrets: bool = False
    characters: dict[str, Literal["keep", "take", "merge"]] = Field(default_factory=dict)
    salvage: bool = False


class ConfigIn(BaseModel):
    library_root: str | None = None
    pixiv_rate: float | None = None
    dupe_threshold: int | None = None
    twitter_cookies_file: str | None = None
    twitter_timeline_limit: int | None = None
    twitter_search_limit: int | None = None
    resolver: str | None = None
    proxy_url: str | None = None
    identify_characters: bool | None = None
    cleanup_rule: CleanupRuleIn | None = None


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
            "library_free_bytes": _free_bytes(state.cfg.blob_root),
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
            "twitter_search_limit": c.twitter_search_limit,
            "identify_characters": c.identify_characters,
            "cleanup_rule": c.cleanup_rule,
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
            "twitter_search_limit",
            "resolver",
            "proxy_url",
            "identify_characters",
        ):
            v = getattr(body, k)
            if v is not None:
                setattr(c, k, v)
        if body.cleanup_rule is not None:
            r = body.cleanup_rule
            c.cleanup_rule = (
                {"min_score": r.min_score, "other_character": r.other_character}
                if r.active
                else None
            )
        c.save()
        if body.resolver is not None or body.proxy_url is not None:
            state.speed.reset()  # the next probe measures the new path
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
        state.names.reset()
        return _sources()

    @app.post("/api/auth/pixiv/verify")
    def auth_pixiv_verify() -> dict:
        state.auth.verify_pixiv()
        return _sources()

    @app.delete("/api/auth/pixiv", status_code=204)
    def auth_pixiv_clear() -> None:
        state.auth.clear_pixiv()
        state.prober.reset()
        state.names.reset()

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

    @app.get("/api/net/speed")
    def net_speed() -> dict:
        """The last measurement, the sample tape and the local side; no request."""
        return state.speed.snapshot()

    @app.post("/api/net/speed")
    def net_speed_run(body: SpeedIn) -> dict:
        """Measure now: latency + a short download, or with `full` the long
        download and an upload too (dawnmaker/speed.py)."""
        return state.speed.run(body.full)

    @app.get("/api/stats")
    def stats(s: Store = Depends(store)) -> dict:
        return s.stats()

    @app.get("/api/storage")
    def storage_usage(s: Store = Depends(store)) -> dict:
        """Settings › Storage: the library's trees, the db file and the disk."""
        from coreflame.library import usage

        return usage(state.cfg.blob_root.parent, state.cfg.db_path, s)

    # -- purge all data (coreflame/purge.py) -------------------------------------
    @app.get("/api/storage/purge/preview")
    def purge_preview(s: Store = Depends(store)) -> dict:
        """The counts the confirm sheet shows: one answer serves both scopes."""
        return purge.preview(s, state.cfg.blob_root.parent)

    @app.post("/api/storage/purge", status_code=202)
    def purge_start(body: StoragePurgeIn, s: Store = Depends(store)) -> dict:
        """Runs on its own thread, not the job queue: it needs the queue held
        and empty. 409 `busy` while a crawl, export or import runs."""
        if body.confirm.strip() != purge.PHRASE:
            raise HTTPException(
                400, {"code": "confirm", "message": f"type {purge.PHRASE} to confirm"}
            )
        if not JobRunner.idle(s) or not state.exclusive.acquire(blocking=False):
            raise HTTPException(
                409, {"code": "busy", "message": "a crawl, export or import is running"}
            )
        before = purge.preview(s, state.cfg.blob_root.parent)
        was_held = state.runner.held
        state.runner.hold(True)  # nothing starts while the rows and files go
        jid = uuid.uuid4().hex
        job: dict[str, Any] = {
            "id": jid,
            "scope": body.scope,
            "state": "running",
            "done": 0,
            "total": before["images"],
            "error": None,
            "result": None,
        }
        state.purge = job

        def progress(done: int, total: int) -> None:
            job["done"], job["total"] = done, total

        def run() -> None:
            ps = state.open_store()
            try:
                if body.scope == "all":
                    state.auth.clear_pixiv()
                    state.auth.clear_twitter()
                out = purge.purge(ps, state.cfg, body.scope, progress)
                if body.scope == "all":
                    fresh = purge.fresh_config(state.cfg)
                    for f in dataclasses.fields(fresh):  # in place: every holder sees it
                        setattr(state.cfg, f.name, getattr(fresh, f.name))
                    state.speed.reset()
                out["images"] = before["images"]
                job["result"], job["state"] = out, "succeeded"
            except Exception as e:  # reported verbatim to the sheet
                job["error"], job["state"] = str(e) or type(e).__name__, "failed"
            finally:
                ps.close()
                # a full purge starts unpaused, as a fresh install does
                state.runner.hold(False if body.scope == "all" else was_held)
                state.exclusive.release()
                state.hub.publish("storage.purged", {"id": jid, "state": job["state"]})

        threading.Thread(target=run, name="storage-purge", daemon=True).start()
        return {"job_id": jid}

    @app.get("/api/storage/purge/{jid}")
    def purge_status(jid: str) -> dict:
        if not state.purge or state.purge["id"] != jid:
            raise HTTPException(404, {"code": "not_found", "message": jid})
        return state.purge

    # -- watches ---------------------------------------------------------------
    @app.get("/api/watches")
    def list_watches(s: Store = Depends(store)) -> list[dict]:
        out = []
        for w in s.watches():
            # a post whose every image was thrown away (coreflame/kinds.py KEEP)
            # is not something the archive holds, so it is not counted
            r = s.conn.execute(
                """SELECT count(*) n, max(p.posted_at) latest FROM post_watches pw
                   JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
                   WHERE pw.slug=? AND NOT (
                     EXISTS (SELECT 1 FROM media m WHERE m.source=p.source
                               AND m.external_id=p.external_id)
                     AND NOT EXISTS (SELECT 1 FROM media m WHERE m.source=p.source
                               AND m.external_id=p.external_id AND m.state<>'rejected'))""",
                (w.slug,),
            ).fetchone()
            # newest illustration (or not-yet-labelled image); a screencap only
            # when there is no illustration at all
            cover = s.conn.execute(
                """SELECT m.sha256 FROM post_watches pw
                   JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
                   JOIN media m ON m.source=p.source AND m.external_id=p.external_id
                   LEFT JOIN image_kinds k ON k.sha256=m.sha256
                   WHERE pw.slug=? AND m.state='stored' AND p.state='live'
                   ORDER BY COALESCE(k.kind,'illustration')<>'illustration',
                            p.posted_at DESC, p.external_id DESC, m.idx LIMIT 1""",
                (w.slug,),
            ).fetchone()
            artists = s.conn.execute(
                """SELECT count(DISTINCT p.source || ':' || p.artist_id) FROM post_watches pw
                   JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
                   WHERE pw.slug=? AND p.state='live'""",
                (w.slug,),
            ).fetchone()[0]
            out.append(
                {
                    **w.model_dump(),
                    "post_count": r["n"],
                    "artist_count": artists,
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

    @app.post("/api/names")
    def names(body: NamesIn) -> dict:
        """Names and forms from Danbooru and Wikidata for the character form's
        suggestions -- no pixiv session needed. Sources that fail are listed in
        `errors`; the rest still answer (coreflame/names.py)."""
        return state.names.find(body.queries, refresh=body.refresh)

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
        # a crawl becomes one job per source per character (coreflame/handlers.plan)
        ids = handlers.submit(s, body.type, body.params)
        if not ids:
            raise HTTPException(400, {"code": "nothing_to_run", "message": "no character matches"})
        state.runner.kick()
        return {"job_id": ids[0], "job_ids": ids}

    def job_out(j: Any, rates: dict[str, int]) -> dict:
        return {**j.__dict__, "req_per_min": rates.get(j.id, 0)}

    @app.get("/api/jobs")
    def list_jobs(
        state_: str | None = Query(None, alias="state"), limit: int = 50, s: Store = Depends(store)
    ) -> list[dict]:
        rates = METER.per_job()
        return [job_out(j, rates) for j in JobRunner.list_jobs(s, state_, limit)]

    @app.get("/api/pipeline")
    def pipeline_state() -> dict:
        """The workers (one per source lane), whether the queue is paused, and the
        rate budgets with what each sent in the last minute."""
        budgets = METER.snapshot()
        return {
            "paused": state.runner.held,
            # `user` (Pause queue) or `offline` (the internet went away: the
            # queue holds itself and resumes when it is back) while paused
            "pause_reason": state.runner.held_reason,
            "online": state.runner.watch.online,
            "workers": state.runner.workers(),
            "budgets": budgets,
            "req_per_min": sum(b["per_min"] for b in budgets),
        }

    @app.post("/api/pipeline/pause")
    def pause_queue(body: PauseIn) -> dict:
        state.runner.hold(body.paused)  # by hand: the user's, whatever held it before
        return {"paused": state.runner.held, "pause_reason": state.runner.held_reason}

    @app.post("/api/jobs/reorder")
    def reorder_jobs(body: ReorderIn, s: Store = Depends(store)) -> dict:
        return {"order": JobRunner.reorder(s, body.ids)}

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str, s: Store = Depends(store)) -> dict:
        j = JobRunner.get(s, jid)
        if j is None:
            raise nf("no_job", jid)
        return {**job_out(j, METER.per_job()), "log": JobRunner.tail(s, jid, 200)}

    @app.post("/api/jobs/{jid}/cancel", status_code=202)
    def cancel_job(jid: str, s: Store = Depends(store)) -> dict:
        if not state.runner.cancel(s, jid):
            raise nf("no_active_job", jid)
        return {"ok": True}

    @app.post("/api/jobs/{jid}/pause", status_code=202)
    def pause_job(jid: str, body: PauseIn, s: Store = Depends(store)) -> dict:
        """Hold a running job at its next record boundary (it keeps its worker)."""
        if not state.runner.pause(s, jid, body.paused):
            raise HTTPException(409, {"code": "not_running", "message": jid})
        return {"paused": body.paused}

    @app.post("/api/jobs/{jid}/retry", status_code=202)
    def retry_job(jid: str, s: Store = Depends(store)) -> dict:
        """A finished job again, as a fresh queued copy (same type, params, lane).
        How an interrupted or cancelled crawl resumes: the visited gate skips
        what the first attempt already did."""
        new = JobRunner.retry(s, jid)
        if new is None:
            raise HTTPException(409, {"code": "not_finished", "message": jid})
        state.runner.kick()
        return {"job_id": new}

    @app.post("/api/jobs/{jid}/run-now", status_code=202)
    def run_job_now(jid: str, s: Store = Depends(store)) -> dict:
        """To the front of the queue; it starts as soon as its worker is free."""
        if not JobRunner.run_now(s, jid):
            raise HTTPException(409, {"code": "not_queued", "message": jid})
        state.runner.kick()
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

    @app.get("/api/gallery/review")
    def gallery_review(s: Store = Depends(store)) -> dict:
        """The Gallery page's quiet card: images the Smart criteria would flag
        today, per character."""
        rule = state.cfg.cleanup_rule or {}
        min_score = rule.get("min_score") or round(identify.CAMIE_SURE - 0.08, 2)
        return trash.review(s, min_score=float(min_score))

    @app.get("/api/gallery/{slug}")
    def gallery_slug(
        slug: str,
        cursor: str | None = None,
        limit: int = Query(100, le=500),
        source: str | None = None,
        r18: str = "exclude",
        kinds_: str | None = Query(None, alias="kinds"),
        ident: str | None = None,
        character: str | None = None,
        origin_: str | None = Query(None, alias="origin"),
        label_: str | None = Query(None, alias="label"),
        artist: str | None = None,
        order: str = "newest",
        s: Store = Depends(store),
    ) -> dict:
        """Keyset on (posted_at, external_id) -- offset pagination duplicates and
        skips rows when a crawl inserts while the user scrolls. `kinds` is a
        comma list of image kinds to show (plus `unlabeled`); absent = all.
        `ident` is a comma list of identified / unidentified / pending (not
        identified yet); `character` keeps the images naming that character;
        `origin` a comma list of ai / human / pending (coreflame/origin.py);
        `label` one of ai / non_illust / unidentified, the folded badge
        (coreflame/label.py); `artist` = `source:artist_id` keeps one artist's
        images. `order` is newest (default) or oldest first; a cursor only
        continues the order it came from."""
        if order not in ("newest", "oldest"):
            raise HTTPException(400, {"code": "bad_order", "message": order})
        cmp, direction = ("<", "DESC") if order == "newest" else (">", "ASC")
        where = ["pw.slug=?", "m.state='stored'", "p.state='live'"]
        # the JOINs' ? come first, in JOIN order
        args: list[Any] = [identify.IDENTIFIER_ID, origin.DETECTOR_ID, slug]
        if source:
            where.append("p.source=?")
            args.append(source)
        if kinds_ is not None:
            want = [k for k in kinds_.split(",") if k]
            bad = [k for k in want if k not in (*kinds.KINDS, kinds.UNLABELED)]
            if bad or not want:
                raise HTTPException(400, {"code": "bad_kind", "message": kinds_})
            where.append(f"COALESCE(k.kind,'unlabeled') IN ({','.join('?' * len(want))})")
            args += want
        if ident is not None:
            states = [x for x in ident.split(",") if x]
            if not states or any(x not in IDENT_STATES for x in states):
                raise HTTPException(400, {"code": "bad_ident", "message": ident})
            where.append(f"COALESCE(i.state,'pending') IN ({','.join('?' * len(states))})")
            args += states
        if character:
            where.append(
                "i.state='identified' AND EXISTS (SELECT 1 FROM image_characters ic "
                "WHERE ic.sha256=m.sha256 AND ic.name=?)"
            )
            args.append(character)
        if origin_ is not None:
            where.append(_origin_in(origin_))
            args += [x for x in origin_.split(",") if x]
        if label_ is not None:
            where.append(_label_is(label_))
            args.append(label_)
        if artist is not None:
            where.append("p.source=? AND p.artist_id=?")
            args += _artist_key(artist)
        if r18 == "exclude":
            where.append("p.is_r18=0")
        if cursor:
            try:
                c_posted, c_id = _cursor_dec(cursor)
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(400, {"code": "bad_cursor", "message": cursor}) from None
            where.append(f"(p.posted_at {cmp} ? OR (p.posted_at = ? AND p.external_id {cmp} ?))")
            args += [c_posted, c_posted, c_id]
        rows = s.conn.execute(
            f"""SELECT m.sha256, m.source, m.external_id, m.idx, m.width, m.height,
                       p.posted_at, p.artist_name, p.title, k.kind,
                       COALESCE(i.state,'pending') AS identity,
                       COALESCE(o.state,'pending') AS origin, o.by AS origin_by,
                       {LABEL_COLS}
                FROM post_watches pw
                JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
                JOIN media m ON m.source=p.source AND m.external_id=p.external_id
                LEFT JOIN image_kinds k ON k.sha256=m.sha256
                LEFT JOIN image_identity i ON i.sha256=m.sha256 AND i.model=?
                {ORIGIN_JOIN}
                {LABEL_JOIN}
                WHERE {" AND ".join(where)}
                ORDER BY p.posted_at {direction}, p.external_id {direction}, m.idx
                LIMIT ?""",
            (*args, limit + 1),
        ).fetchall()
        items = [{**dict(r), "thumb_url": f"/api/media/{r['sha256']}/thumb"} for r in rows[:limit]]
        nxt = None
        if len(rows) > limit:
            last = rows[limit - 1]
            nxt = _cursor_enc(last["posted_at"], last["external_id"])
        return {"items": items, "next_cursor": nxt}

    @app.get("/api/gallery/{slug}/kinds")
    def gallery_kinds(slug: str, r18: str = "exclude", s: Store = Depends(store)) -> dict:
        """Image count per kind (what the gallery's filter chips show) and
        whether this install can label at all."""
        counts = s.kind_counts(slug, include_r18=r18 != "exclude")
        return {
            "counts": {k: counts.get(k, 0) for k in (*kinds.KINDS, kinds.UNLABELED)},
            "labeler": {
                "available": kinds.runtime_available(),
                "models": kinds.models_present(state.cfg.home),
            },
            # images its gender filter still has to judge (coreflame/people.py)
            "people": {"pending": s.people_pending(slug, people.TAGGER_ID)},
        }

    @app.get("/api/gallery/{slug}/characters")
    def gallery_characters(slug: str, r18: str = "exclude", s: Store = Depends(store)) -> dict:
        """Who is in this character's images (coreflame/identify.py): how many
        are identified / unidentified / not yet, each character named with its
        image count, and whether this install identifies at all."""
        got = s.identity_counts(slug, identify.IDENTIFIER_ID, include_r18=r18 != "exclude")
        return {
            "counts": got["counts"],
            "characters": [
                {"name": n, "label": identify.label_of(n), "count": c} for n, c in got["characters"]
            ],
            "identifier": {
                "enabled": state.cfg.identify_characters,
                "available": kinds.runtime_available(),
                "models": identify.models_present(state.cfg.home),
            },
        }

    @app.get("/api/gallery/{slug}/origins")
    def gallery_origins(slug: str, r18: str = "exclude", s: Store = Depends(store)) -> dict:
        """How this character's images were made (coreflame/origin.py): how
        many are AI-made / by hand / not judged yet, and whether this install
        can run the detector at all."""
        return {
            "counts": s.origin_counts(slug, origin.DETECTOR_ID, include_r18=r18 != "exclude"),
            "detector": {
                "available": kinds.runtime_available(),
                "models": origin.models_present(state.cfg.home),
            },
        }

    @app.put("/api/images/{sha}/label")
    def set_image_label(sha: str, body: LabelIn, s: Store = Depends(store)) -> dict:
        """The badge, chosen by hand (coreflame/label.py): ai / non_illust /
        unidentified, or null for "no label". Wins over every classifier and
        survives re-labelling. The image must be one the archive holds."""
        if body.label is not None and body.label not in label.LABELS:
            raise HTTPException(400, {"code": "bad_label", "message": str(body.label)})
        if s.conn.execute("SELECT 1 FROM media WHERE sha256=? LIMIT 1", (sha,)).fetchone() is None:
            raise nf("no_image", sha)
        with s.tx():
            s.set_label(sha, body.label)
        return {"sha256": sha, "label": body.label, "label_source": "manual"}

    @app.delete("/api/images/{sha}/label")
    def clear_image_label(sha: str, s: Store = Depends(store)) -> dict:
        """Back to the classifiers' fold; answers what it now reads."""
        with s.tx():
            s.clear_label(sha)
        got = s.image_label(sha, identify.IDENTIFIER_ID, origin.DETECTOR_ID)
        if got is None:
            raise nf("no_image", sha)
        return {"sha256": sha, **got}

    # -- deletion (coreflame/trash.py) ------------------------------------------
    def _watch(s: Store, slug: str) -> Watch:
        w = next((w for w in s.watches() if w.slug == slug), None)
        if w is None:
            raise nf("no_watch", slug)
        return w

    def _grid_where(
        slug: str,
        source: str | None,
        kinds_: str | None,
        ident: str | None,
        character: str | None,
        r18: str,
        origin_: str | None = None,
        label_: str | None = None,
        artist: str | None = None,
    ) -> tuple[list[str], list[Any]]:
        """The grid's own visibility rules, shared with the selection lists:
        what the user cannot see is never selected for deletion."""
        where = ["pw.slug=?", "m.state='stored'", "p.state='live'"]
        args: list[Any] = [slug]
        if source:
            where.append("p.source=?")
            args.append(source)
        if kinds_ is not None:
            want = [k for k in kinds_.split(",") if k]
            bad = [k for k in want if k not in (*kinds.KINDS, kinds.UNLABELED)]
            if bad or not want:
                raise HTTPException(400, {"code": "bad_kind", "message": kinds_})
            where.append(f"COALESCE(k.kind,'unlabeled') IN ({','.join('?' * len(want))})")
            args += want
        if ident is not None:
            states = [x for x in ident.split(",") if x]
            if not states or any(x not in IDENT_STATES for x in states):
                raise HTTPException(400, {"code": "bad_ident", "message": ident})
            where.append(f"COALESCE(i.state,'pending') IN ({','.join('?' * len(states))})")
            args += states
        if character:
            where.append(
                "i.state='identified' AND EXISTS (SELECT 1 FROM image_characters ic "
                "WHERE ic.sha256=m.sha256 AND ic.name=?)"
            )
            args.append(character)
        if origin_ is not None:
            where.append(_origin_in(origin_))
            args += [x for x in origin_.split(",") if x]
        if label_ is not None:
            where.append(_label_is(label_))
            args.append(label_)
        if artist is not None:
            where.append("p.source=? AND p.artist_id=?")
            args += _artist_key(artist)
        if r18 == "exclude":
            where.append("p.is_r18=0")
        return where, args

    def _artist_key(key: str) -> list[str]:
        """`source:artist_id` -> [source, artist_id]; the id may itself hold a colon."""
        src, sep, aid = key.partition(":")
        if not sep or not src or not aid:
            raise HTTPException(400, {"code": "bad_artist", "message": key})
        return [src, aid]

    def _label_is(label_: str) -> str:
        if label_ not in label.LABELS:
            raise HTTPException(400, {"code": "bad_label", "message": label_})
        return f"({label.LABEL_SQL}) = ?"

    def _origin_in(origin_: str) -> str:
        want = [x for x in origin_.split(",") if x]
        if not want or any(x not in origin.STATES for x in want):
            raise HTTPException(400, {"code": "bad_origin", "message": origin_})
        return f"COALESCE(o.state,'pending') IN ({','.join('?' * len(want))})"

    @app.get("/api/gallery/{slug}/images")
    def gallery_images(
        slug: str,
        source: str | None = None,
        r18: str = "exclude",
        kinds_: str | None = Query(None, alias="kinds"),
        ident: str | None = None,
        character: str | None = None,
        origin_: str | None = Query(None, alias="origin"),
        label_: str | None = Query(None, alias="label"),
        artist: str | None = None,
        tag: str | None = None,
        sel_artist: str | None = None,
        sel_kind: str | None = None,
        sel_ident: str | None = None,
        sel_character: str | None = None,
        sel_origin: str | None = None,
        sel_label: str | None = None,
        s: Store = Depends(store),
    ) -> dict:
        """Every image of this gallery (its shas, in grid order) that carries
        one *term*: a tag (`tag_norm`), an artist (`sel_artist` =
        `source:artist_id`), a kind, an identification state, a character, an
        origin or a label -- what By tag and All select with. The grid's own
        filters (`source kinds ident character origin label artist`) still
        apply, so a hidden image is never picked. No term = everything shown."""
        where, args = _grid_where(
            slug, source, kinds_, ident, character, r18, origin_, label_, artist
        )
        args = [identify.IDENTIFIER_ID, origin.DETECTOR_ID, *args]
        if tag:
            where.append(
                "EXISTS (SELECT 1 FROM post_tags t WHERE t.source=p.source "
                "AND t.external_id=p.external_id AND t.tag_norm=?)"
            )
            args.append(tag)
        if sel_artist:
            where.append("p.source=? AND p.artist_id=?")
            args += _artist_key(sel_artist)
        if sel_kind:
            if sel_kind not in (*kinds.KINDS, kinds.UNLABELED):
                raise HTTPException(400, {"code": "bad_kind", "message": sel_kind})
            where.append("COALESCE(k.kind,'unlabeled')=?")
            args.append(sel_kind)
        if sel_ident:
            if sel_ident not in IDENT_STATES:
                raise HTTPException(400, {"code": "bad_ident", "message": sel_ident})
            where.append("COALESCE(i.state,'pending')=?")
            args.append(sel_ident)
        if sel_character:
            where.append(
                "EXISTS (SELECT 1 FROM image_characters ic WHERE ic.sha256=m.sha256 AND ic.name=?)"
            )
            args.append(sel_character)
        if sel_origin:
            if sel_origin not in origin.STATES:
                raise HTTPException(400, {"code": "bad_origin", "message": sel_origin})
            where.append("COALESCE(o.state,'pending')=?")
            args.append(sel_origin)
        if sel_label:
            where.append(_label_is(sel_label))
            args.append(sel_label)
        rows = s.conn.execute(
            f"""SELECT m.sha256, m.source FROM post_watches pw
                JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
                JOIN media m ON m.source=p.source AND m.external_id=p.external_id
                LEFT JOIN image_kinds k ON k.sha256=m.sha256
                LEFT JOIN image_identity i ON i.sha256=m.sha256 AND i.model=?
                {ORIGIN_JOIN}
                {LABEL_JOIN}
                WHERE {" AND ".join(where)}
                ORDER BY p.posted_at DESC, p.external_id DESC, m.idx""",
            args,
        ).fetchall()
        # `sources` lets the selection bar count pixiv / X without the grid's pages loaded
        return {
            "shas": [r["sha256"] for r in rows],
            "sources": {r["sha256"]: r["source"] for r in rows},
        }

    @app.get("/api/gallery/{slug}/artists")
    def gallery_artists(slug: str, limit: int = 40, s: Store = Depends(store)) -> list[dict]:
        """Who drew this character's images, most images first -- the Artists
        row By tag selects with."""
        rows = s.conn.execute(
            """SELECT p.source, p.artist_id, max(p.artist_name) AS name,
                      max(p.artist_handle) AS handle, count(*) AS n
               FROM post_watches pw
               JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
               JOIN media m ON m.source=p.source AND m.external_id=p.external_id
               WHERE pw.slug=? AND m.state='stored' AND p.state='live' AND p.is_r18=0
               GROUP BY p.source, p.artist_id ORDER BY n DESC, name LIMIT ?""",
            (slug, limit),
        ).fetchall()
        return [
            {
                "source": r["source"],
                "artist_id": r["artist_id"],
                "name": r["name"] or r["handle"] or r["artist_id"],
                "handle": r["handle"],
                "count": r["n"],
            }
            for r in rows
        ]

    @app.post("/api/gallery/{slug}/smart")
    def gallery_smart(slug: str, body: SmartIn, s: Store = Depends(store)) -> dict:
        """Smart · AI identifier: the images the criteria flag, each with its
        reasons (low score / other character / near-duplicate / unidentified /
        not an illustration)."""
        _watch(s, slug)
        got = trash.smart_matches(
            s,
            slug,
            min_score=body.min_score,
            other_character=body.other_character,
            dupes=body.dupes,
            distance=body.distance,
            unidentified=body.unidentified,
            kinds=body.kinds,
        )
        rule = state.cfg.cleanup_rule
        return {
            **got,
            "cutoff": identify.CAMIE_SURE,
            "rule": rule,
            "identifier": {"enabled": state.cfg.identify_characters},
        }

    @app.post("/api/gallery/{slug}/delete/preview")
    def delete_preview(slug: str, body: ShasIn, s: Store = Depends(store)) -> dict:
        _watch(s, slug)
        return trash.preview(s, state.blobs, slug, body.shas)

    @app.post("/api/gallery/{slug}/delete")
    def delete_images(slug: str, body: DeleteIn, s: Store = Depends(store)) -> dict:
        """Images only: the character, its tags, X terms, schedule and visited
        index stay. `mode=all` needs the character's name typed back."""
        w = _watch(s, slug)
        if body.mode == "all" and (body.confirm or "").strip() not in {w.label, w.slug} - {""}:
            raise HTTPException(400, {"code": "confirm_mismatch", "message": w.label or w.slug})
        if not body.shas:
            raise HTTPException(400, {"code": "nothing_selected", "message": slug})
        return trash.remove(
            s,
            state.blobs,
            state.thumbs,
            slug,
            body.shas,
            mode=body.mode,
            trash=body.trash,
            forget=body.forget,
        )

    @app.get("/api/trash")
    def trash_summary(s: Store = Depends(store)) -> dict:
        trash.purge(s, state.blobs, state.thumbs)  # the thirty-day sweep
        return trash.summary(s, state.blobs)

    @app.post("/api/trash/purge")
    def trash_purge(body: PurgeIn, s: Store = Depends(store)) -> dict:
        return trash.purge(s, state.blobs, state.thumbs, everything=body.everything)

    @app.post("/api/trash/{batch_id}/restore")
    def trash_restore(batch_id: str, s: Store = Depends(store)) -> dict:
        try:
            return trash.restore(s, state.blobs, state.thumbs, batch_id)
        except KeyError:
            raise nf("no_batch", batch_id) from None

    # -- bundles: export / import the whole archive (coreflame/bundle.py) -------
    def bundle_err(e: bundle.BundleError) -> HTTPException:
        return HTTPException(400, {"code": e.code, "message": str(e)})

    @app.post("/api/bundle/export", status_code=202)
    def bundle_export(body: BundleExportIn, s: Store = Depends(store)) -> dict:
        """A job on the `any` lane: it reads a db snapshot and immutable
        blobs, so it runs beside a crawl. Progress shows in the pipeline."""
        ext = bundle.EXTENSIONS[body.format]
        if body.path:
            path = Path(body.path).expanduser()
            if path.suffix != ext:
                path = path.with_name(path.name + ext)
        else:
            stamp = time.strftime("%Y%m%d-%H%M")
            path = Path(state.cfg.home) / "exports" / f"curio-{stamp}{ext}"
        if not path.parent.is_dir() and body.path:
            raise HTTPException(400, {"code": "no_folder", "message": str(path.parent)})
        params = body.model_dump()
        params["path"] = str(path)
        jid = JobRunner.submit(s, "export", params)
        state.runner.kick()
        return {"job_id": jid, "path": str(path)}

    @app.post("/api/bundle/inspect")
    def bundle_inspect(body: BundlePathIn, s: Store = Depends(store)) -> dict:
        try:
            return bundle.inspect(Path(body.path).expanduser(), s)
        except bundle.BundleError as e:
            raise bundle_err(e) from None

    @app.post("/api/bundle/import")
    def bundle_import(body: BundleImportIn, s: Store = Depends(store)) -> dict:
        """Runs in the request, not as a job: nothing else may touch the
        database while the merge transaction and the blob placement run, so
        the queue must be paused and empty (409 `busy` otherwise)."""
        if not state.runner.held or not JobRunner.idle(s):
            raise HTTPException(
                409, {"code": "busy", "message": "pause the pipeline and let it drain first"}
            )
        if not state.exclusive.acquire(blocking=False):
            raise HTTPException(409, {"code": "busy", "message": "a purge is running"})
        try:
            return _bundle_import(body, s)
        finally:
            state.exclusive.release()

    def _bundle_import(body: BundleImportIn, s: Store) -> dict:
        opts = bundle.ImportOptions(
            mode=body.mode,
            settings=body.settings,
            secrets=body.secrets,
            characters=dict(body.characters),
            salvage=body.salvage,
        )
        try:
            out = bundle.import_(
                s, state.blobs, state.thumbs, state.cfg, Path(body.path).expanduser(), opts
            )
        except bundle.BundleError as e:
            raise bundle_err(e) from None
        if out.get("ui") is not None:
            state.speed.reset()  # settings taken: resolver / proxy may have changed
        return out

    @app.get("/api/gallery/{slug}/tags")
    def gallery_tags(
        slug: str,
        state_: str | None = Query(None, alias="state"),
        limit: int = 40,
        s: Store = Depends(store),
    ) -> list[dict]:
        return [t.__dict__ for t in tags.observed(s, slug, state_, limit)]

    def _variant_of(row: dict) -> str:
        """Rows stored before v11 carry '' -- the url says which size it was."""
        if row.get("source_variant"):
            return str(row["source_variant"])
        url = row.get("url") or ""
        if "img-original" in url:
            return "original"
        for v in ("orig", "4096x4096"):
            if f"name={v}" in url:
                return v
        return ""

    def _media_rows(s: Store, source: str, external_id: str) -> list[dict]:
        """Every image row of a post, in page order, with the blob's absolute
        path when it is stored (the desktop app's Reveal) and the size variant.
        A `dupe` row has no blob of its own: the UI shows `dupe_of`'s."""
        out = []
        for r in s.conn.execute(
            "SELECT * FROM media WHERE source=? AND external_id=? ORDER BY idx",
            (source, external_id),
        ):
            m = dict(r)
            path = None
            if m["state"] == "stored" and m["sha256"]:
                p = state.blobs.path_for(m["sha256"], m["ext"])
                if p.exists():
                    path = str(p)
            m["path"] = path
            m["source_variant"] = _variant_of(m)
            out.append(m)
        return out

    @app.get("/api/posts/{source}/{external_id}")
    def post_detail(source: str, external_id: str, s: Store = Depends(store)) -> dict:
        p = s.conn.execute(
            "SELECT * FROM posts WHERE source=? AND external_id=?", (source, external_id)
        ).fetchone()
        if p is None:
            raise nf("no_post", f"{source}/{external_id}")
        media = _media_rows(s, source, external_id)
        shas = [m["sha256"] for m in media if m["sha256"]]
        # how each image was made (coreflame/origin.py); null = not judged yet
        made = s.origins(shas, origin.DETECTOR_ID)
        for m in media:
            m["origin"] = made.get(m["sha256"] or "")
            # the one badge (coreflame/label.py), folded from every verdict + a hand-set one
            got_label = (
                s.image_label(m["sha256"], identify.IDENTIFIER_ID, origin.DETECTOR_ID)
                if m["sha256"]
                else None
            )
            m["label"] = got_label["label"] if got_label else None
            m["label_source"] = got_label["label_source"] if got_label else "auto"
        # who each image shows (coreflame/identify.py); null = not identified yet
        found = s.identities(shas)
        for m in media:
            got = found.get(m["sha256"] or "")
            if got is None or got["model"] != identify.IDENTIFIER_ID:
                m["identity"] = None
                continue
            m["identity"] = {
                "state": got["state"],
                "characters": [
                    {**c, "label": identify.label_of(c["name"])} for c in got["characters"]
                ],
            }
        tag_rows = [
            dict(r)
            for r in s.conn.execute(
                "SELECT tag_raw, tag_norm, translated FROM post_tags WHERE source=? AND external_id=?",
                (source, external_id),
            )
        ]
        # the payoff of the phash work: the other source's post holding the same
        # image -- with all of that post's images, so the detail panel and the
        # viewer can walk this post's pages and then the sibling post's
        linked: list[dict] = []
        seen: set[tuple[str, str]] = set()

        def link(o_source: str, o_eid: str, reason: str | None) -> None:
            if (o_source, o_eid) in seen or (o_source, o_eid) == (source, external_id):
                return
            seen.add((o_source, o_eid))
            op = s.conn.execute(
                """SELECT artist_handle, artist_name, title, permalink, posted_at
                   FROM posts WHERE source=? AND external_id=?""",
                (o_source, o_eid),
            ).fetchone()
            if op is None:
                return
            linked.append(
                {
                    "source": o_source,
                    "external_id": o_eid,
                    **dict(op),
                    "reason": reason,
                    "media": _media_rows(s, o_source, o_eid),
                }
            )

        for m in media:
            if m["state"] == "dupe" and m["dupe_of"]:
                o = s.conn.execute(
                    "SELECT source, external_id FROM media WHERE sha256=? AND state='stored' LIMIT 1",
                    (m["dupe_of"],),
                ).fetchone()
                if o:
                    link(o["source"], o["external_id"], m["error"])
            elif m["state"] == "stored" and m["sha256"]:
                for o in s.conn.execute(
                    "SELECT source, external_id, error FROM media WHERE dupe_of=?",
                    (m["sha256"],),
                ):
                    link(o["source"], o["external_id"], o["error"])
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
