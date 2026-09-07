"""The character form's live validation: one pixiv search page per tag.

Everything the form shows before a character exists -- "8,412 artworks", the
preview strip, the suggested tags, the backfill estimate -- comes from this one
request per tag. Rules that keep it cheap and honest:

* page 1 only, never a detail fetch, nothing written to seen_posts or blobs;
* cached per (tag, mode) for a few minutes, so retyping costs nothing;
* preview thumbs are proxied (i.pximg.net 403s without a Referer and the
  webview's CSP only allows 127.0.0.1) but only for ids a probe returned --
  this is not a general image proxy.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import httpx

from coreflame import tags as tagstats
from coreflame.config import Config
from coreflame.db import Store
from coreflame.handlers import make_pixiv
from coreflame.sources.pixiv import PixivAdapter

FULLWIDTH = "（）"
PROBE_TTL = 600.0
THUMB_TTL = 900.0
THUMB_MAX = 256
PREVIEW_N = 12
SUGGEST_N = 12


@dataclass
class TagProbe:
    tag: str
    total: int = 0
    ok: bool = False
    warning: str | None = None
    error: str | None = None
    rows: list[dict] = field(default_factory=list)


def _http_error(status: int) -> str:
    """Short, actionable; the form has ~30 characters, not a URL's worth."""
    if status in (401, 403):
        return f"pixiv {status} — search needs a signed-in session (PIXIV_PHPSESSID)"
    if status == 404:
        return "pixiv 404 — endpoint moved?"
    if status == 429:
        return "pixiv 429 — rate limited, wait a minute"
    return f"pixiv HTTP {status}"


class Prober:
    def __init__(self, cfg: Config, pixiv: PixivAdapter | None = None) -> None:
        self.cfg = cfg
        self._pixiv = pixiv
        self._lock = threading.Lock()
        self._probes: dict[tuple[str, bool], tuple[float, TagProbe]] = {}
        self._thumb_urls: dict[str, str] = {}  # illust id -> square thumb url
        self._thumbs: OrderedDict[str, tuple[float, bytes, str]] = OrderedDict()

    @property
    def pixiv(self) -> PixivAdapter:
        if self._pixiv is None:
            self._pixiv = make_pixiv(self.cfg)
        return self._pixiv

    # -- tags ---------------------------------------------------------------
    def probe_tag(self, tag: str, include_r18: bool) -> TagProbe:
        key = (tag, include_r18)
        now = time.monotonic()
        with self._lock:
            hit = self._probes.get(key)
            if hit and now - hit[0] < PROBE_TTL:
                return hit[1]
        p = TagProbe(tag=tag)
        if any(c in tag for c in FULLWIDTH):
            # pixiv's exact-tag search will not match these; say so without
            # spending a request -- the crawl would otherwise silently find 0
            p.warning = "fullwidth（）won't match; use ( )"
        else:
            try:
                p.total, p.rows = self.pixiv.probe_tag(tag, include_r18)
                p.ok = p.total > 0
                if not p.ok:
                    p.warning = "no artworks carry this exact tag"
            except httpx.HTTPStatusError as e:  # surfaced to the form as a row error
                p.error = _http_error(e.response.status_code)
            except Exception as e:
                p.error = f"{type(e).__name__}: {str(e)[:120]}"
        with self._lock:
            self._probes[key] = (now, p)
            for r in p.rows:
                if r.get("thumb_url"):
                    self._thumb_urls[str(r["external_id"])] = r["thumb_url"]
        return p

    def probe(self, store: Store, tags: list[str], include_r18: bool) -> dict:
        probes = [self.probe_tag(t.strip(), include_r18) for t in tags if t.strip()]
        # newest first across tags, deduped on id -- the same work often
        # carries several of the character's tags
        seen: set[str] = set()
        rows: list[dict] = []
        for p in probes:
            for r in p.rows:
                iid = str(r["external_id"])
                if iid not in seen:
                    seen.add(iid)
                    rows.append(r)
        rows.sort(key=lambda r: int(r["external_id"]), reverse=True)
        preview = [
            {
                "illust_id": str(r["external_id"]),
                "title": r.get("title") or "",
                "artist_name": r.get("artist_name") or "",
                "thumb": f"/api/preview/{r['external_id']}/thumb" if r.get("thumb_url") else None,
            }
            for r in rows[:PREVIEW_N]
        ]
        suggestions = [
            {
                "tag_raw": t.tag_raw,
                "tag_norm": t.tag_norm,
                "posts": t.posts,
                "share": round(t.share, 3),
                "characters": t.characters,
                "score": round(t.score, 3),
            }
            for t in tagstats.suggest_from_listing(store, rows, exclude=[p.tag for p in probes])[
                :SUGGEST_N
            ]
        ]
        artworks = sum(p.total for p in probes if p.ok)
        rate = max(self.cfg.pixiv_rate, 0.05)
        return {
            "tags": [
                {"tag": p.tag, "total": p.total, "ok": p.ok, "warning": p.warning, "error": p.error}
                for p in probes
            ],
            "preview": preview,
            "suggestions": suggestions,
            # upper bound: tags overlap and the visited set is subtracted at crawl time
            "estimate": {"artworks": artworks, "seconds": int(artworks / rate)},
        }

    # -- thumbs -------------------------------------------------------------
    def thumb(self, illust_id: str) -> tuple[bytes, str] | None:
        """Bytes + content type for a preview thumb, or None if this id never
        came back from a probe (so the route can 404 rather than proxy)."""
        now = time.monotonic()
        with self._lock:
            hit = self._thumbs.get(illust_id)
            if hit and now - hit[0] < THUMB_TTL:
                self._thumbs.move_to_end(illust_id)
                return hit[1], hit[2]
            url = self._thumb_urls.get(illust_id)
        if not url:
            return None
        data = self.pixiv.fetch_media(url)
        ctype = "image/png" if url.lower().endswith(".png") else "image/jpeg"
        with self._lock:
            self._thumbs[illust_id] = (now, data, ctype)
            while len(self._thumbs) > THUMB_MAX:
                self._thumbs.popitem(last=False)
        return data, ctype

    def reset(self) -> None:
        """After a session change: drop the adapter (it carries the cookie)
        and every cached verdict, which may have been an anonymous 401."""
        with self._lock:
            px, self._pixiv = self._pixiv, None
            self._probes.clear()
        if px is not None:
            px.close()

    def close(self) -> None:
        if self._pixiv is not None:
            self._pixiv.close()
