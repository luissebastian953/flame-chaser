"""pixiv adapter -- the discovery source.

Why pixiv is the index and X is not: on pixiv a character is a *first-class
tag* that the artist applies, and `s_mode=s_tag_full` matches it exactly. There
is nothing equivalent on X. So character discovery happens here, and X is
reduced to a per-artist follow feed (see sources/twitter.py).

There is no official public pixiv web API. These are the endpoints the site's
own frontend calls. Consequences that are architectural, not cosmetic:

  * `Referer` is mandatory on i.pximg.net -- without it every image is 403.
  * `PHPSESSID` is the whole auth story; logging out on the website
    invalidates it, so treat a sudden run of empty results as an expired
    cookie, not as "no new art".
  * R-18 requires a logged-in cookie and `mode=r18`/`all`.
  * Shapes are unversioned. Extraction is a glom spec (specs.py), the fetched
    JSON is retained, and validation failures are quarantined -- so a shape
    change is a spec edit plus a re-parse, never a re-crawl.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from ..http import METER, SourceClient
from ..models import DiscoverStats, IllustRecord, Watch
from ..online import Offline
from ..seen import Seen, SeenState, SkipReason
from .specs import PIXIV_DETAIL, PIXIV_LISTING, extract

log = logging.getLogger(__name__)

BASE = "https://www.pixiv.net"

# The Rate budget panel lists pixiv's budgets before the first crawl builds an
# adapter; the adapter re-declares them with the configured rate.
METER.declare("pixiv.search", "pixiv · search", 0.5)
METER.declare("pixiv", "pixiv · ajax", 1.0)
METER.declare("pixiv.pximg", "i.pximg.net", 2.0)


class RawSink(Protocol):
    """What the adapter needs from storage: retain raw, quarantine bad.
    A Protocol so the adapter never imports db.py."""

    def put_raw(
        self, source: str, kind: str, payload: Any, external_id: str | None = None
    ) -> str: ...
    def quarantine(
        self,
        source: str,
        external_id: str,
        error: str,
        extracted: dict | None = None,
        raw_sha: str | None = None,
    ) -> None: ...


class PixivAdapter:
    name = "pixiv"
    supports_discovery = True

    def __init__(
        self,
        php_sessid: str | None = None,
        rate: float = 1.0,
        accept_language: str = "en-US,en;q=0.9,ja;q=0.8",
        resolver=None,
        proxy: str | None = None,
        sink: RawSink | None = None,
    ) -> None:
        self.authed = bool(php_sessid)
        self.sink = sink
        headers = {
            "Referer": f"{BASE}/",
            "Accept": "application/json",
            "Accept-Language": accept_language,
        }
        if php_sessid:
            headers["x-user-id"] = php_sessid.split("_")[0]
        self.client = SourceClient(
            base_headers=headers,
            cookies={"PHPSESSID": php_sessid} if php_sessid else {},
            rate=rate,
            burst=3.0,
            resolver=resolver,
            proxy=proxy,
            meter=("pixiv", "pixiv · ajax"),
        )
        self.client.limit_endpoint("pximg", rate=2.0, burst=4.0, label="i.pximg.net")
        self.client.limit_endpoint("search", rate=0.5, burst=2.0, label="pixiv · search")
        self.extracted: list[dict] = []  # this run's extractions, for drift

    # -- discovery --------------------------------------------------------
    def discover(
        self,
        watch: Watch,
        since: str | None = None,
        seen: Seen | None = None,
        stats: DiscoverStats | None = None,
    ) -> Iterator[IllustRecord]:
        """Artworks for every tag on the watch, newest first, stopped at the
        watermark. pixiv ids are monotonic, so the floor is an int compare; we
        still walk one page past it because a work can go public with an id
        lower than one already seen."""
        floor = int(since) if since and since.isdigit() else 0
        stats = stats if stats is not None else DiscoverStats()
        for tag in watch.pixiv_tags:
            yield from self._search_tag(tag, watch, floor, seen, stats)

    @staticmethod
    def search_url(tag: str, mode: str, page: int) -> str:
        return (
            f"{BASE}/ajax/search/artworks/{quote(tag)}?word={quote(tag)}"
            f"&order=date_d&mode={mode}&p={page}&s_mode=s_tag_full&type=all&lang=en"
        )

    def search_mode(self, include_r18: bool) -> str:
        return "all" if (include_r18 and self.authed) else "safe"

    def probe_tag(self, tag: str, include_r18: bool = False) -> tuple[int, list[dict]]:
        """ONE listing page for a tag: (total, listing rows). This is what the
        character form's validation and preview spend -- a single search
        request per tag, never a detail fetch, nothing marked in seen_posts."""
        payload = self.client.get_json(
            self.search_url(tag, self.search_mode(include_r18), 1), bucket="search"
        )
        if payload.get("error"):
            raise RuntimeError(str(payload.get("message") or "pixiv search error"))
        im = (payload.get("body") or {}).get("illustManga") or {}
        rows = [extract(PIXIV_LISTING, i) for i in (im.get("data") or [])]
        rows = [r for r in rows if r.get("external_id") and not r.get("is_ad")]
        return int(im.get("total") or 0), rows

    def _search_tag(
        self, tag: str, watch: Watch, floor: int, seen: Seen | None, stats: DiscoverStats
    ) -> Iterator[IllustRecord]:
        mode = self.search_mode(watch.include_r18)
        page, overshoot, total = 1, 0, None
        while page <= 100:
            url = self.search_url(tag, mode, page)
            payload = self.client.get_json(url, bucket="search")
            if payload.get("error"):
                log.error("pixiv search error for %r: %s", tag, payload.get("message"))
                return
            body = payload.get("body") or {}
            im = body.get("illustManga") or {}
            if total is None:
                total = im.get("total", 0)
                log.info("pixiv tag %r: %s results total", tag, total)
            items = [extract(PIXIV_LISTING, i) for i in (im.get("data") or [])]
            items = [i for i in items if i.get("external_id") and not i.get("is_ad")]
            if not items:
                return

            for item in items:
                iid = str(item["external_id"])
                stats.listed += 1
                stats.highest_id = max(stats.highest_id, int(iid))
                if int(iid) <= floor:
                    overshoot += 1
                    continue
                # -- the gate: here, where the id cost nothing ------------
                if seen is not None and not seen.should_fetch("pixiv", iid):
                    stats.gated += 1
                    continue
                rec = self._detail(iid, seen, stats)
                if rec is None:
                    continue
                if watch.min_bookmarks and rec.bookmark_count < watch.min_bookmarks:
                    stats.skipped += 1
                    if seen is not None:
                        seen.mark(
                            "pixiv",
                            iid,
                            SeenState.SKIPPED,
                            reason=SkipReason.BELOW_MIN_BOOKMARKS.value,
                            threshold=watch.min_bookmarks,
                        )
                    continue
                yield rec

            if overshoot >= len(items):
                return
            page += 1

    # -- detail: fetch -> retain -> extract -> validate ---------------------
    def _detail(
        self, illust_id: str, seen: Seen | None = None, stats: DiscoverStats | None = None
    ) -> IllustRecord | None:
        ref = f"{BASE}/artworks/{illust_id}"
        stats = stats if stats is not None else DiscoverStats()
        try:
            payload = self.client.get_json(
                f"{BASE}/ajax/illust/{illust_id}?lang=en", headers={"Referer": ref}
            )
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (404, 410):
                stats.gone += 1
                if seen is not None:
                    seen.mark("pixiv", illust_id, SeenState.GONE, reason=f"http_{code}")
                log.info("pixiv illust %s gone (%s)", illust_id, code)
                return None
            raise
        except Offline:
            raise  # the connection, not this artwork: the runner holds the queue
        except Exception as e:
            stats.failed += 1
            if seen is not None:
                seen.mark_failed("pixiv", illust_id, type(e).__name__)
            log.warning("pixiv illust %s failed: %s", illust_id, e)
            return None
        if payload.get("error"):
            stats.gone += 1
            if seen is not None:
                seen.mark("pixiv", illust_id, SeenState.GONE, reason="error_payload")
            return None

        body = payload.get("body") or {}
        raw_sha = self.sink.put_raw("pixiv", "pixiv_detail", body, illust_id) if self.sink else None
        stats.fetched += 1
        fields = extract(PIXIV_DETAIL, body)
        self.extracted.append(fields)

        if fields.get("illust_type") == "ugoira":
            stats.skipped += 1
            if seen is not None:
                seen.mark("pixiv", illust_id, SeenState.SKIPPED, reason=SkipReason.UGOIRA.value)
            return None

        media = self._pages(illust_id, body)
        try:
            return IllustRecord(**fields, media=media, permalink=ref, raw_sha=raw_sha)
        except ValidationError as e:
            # never a crash, never a silent drop: the raw is retained, the
            # failure is recorded, and a spec fix + re-parse recovers it
            stats.failed += 1
            if self.sink:
                self.sink.quarantine("pixiv", illust_id, str(e), fields, raw_sha)
            log.warning("pixiv illust %s failed validation: %s", illust_id, e.errors()[0]["msg"])
            return None

    def _pages(self, illust_id: str, detail: dict) -> list[dict]:
        ref = f"{BASE}/artworks/{illust_id}"
        if int(detail.get("pageCount") or 1) == 1:
            orig = (detail.get("urls") or {}).get("original")
            if orig:
                return [
                    dict(
                        index=0,
                        url=orig,
                        width=int(detail.get("width") or 0),
                        height=int(detail.get("height") or 0),
                        referer=ref,
                    )
                ]
        payload = self.client.get_json(
            f"{BASE}/ajax/illust/{illust_id}/pages?lang=en", headers={"Referer": ref}
        )
        if self.sink:
            self.sink.put_raw("pixiv", "pixiv_pages", payload.get("body") or [], illust_id)
        out = []
        for i, p in enumerate(payload.get("body") or []):
            url = (p.get("urls") or {}).get("original")
            if url:
                out.append(
                    dict(
                        index=i,
                        url=url,
                        width=int(p.get("width") or 0),
                        height=int(p.get("height") or 0),
                        referer=ref,
                    )
                )
        return out

    # -- artist -> X handle ----------------------------------------------
    def twitter_handle(self, user_id: str) -> str | None:
        """The join key between the two sources: most pixiv artists put their
        X account in the profile's social links."""
        payload = self.client.get_json(
            f"{BASE}/ajax/user/{user_id}?full=1&lang=en",
            headers={"Referer": f"{BASE}/users/{user_id}"},
        )
        url = (((payload.get("body") or {}).get("social") or {}).get("twitter") or {}).get(
            "url"
        ) or ""
        if not url:
            return None
        handle = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        return handle.lstrip("@") or None

    # -- media ------------------------------------------------------------
    last_variant = "original"  # pixiv has one full-size url per page; see _pages

    def fetch_media(self, url: str, referer: str | None = None) -> bytes:
        return self.client.get(
            url, bucket="pximg", headers={"Referer": referer or f"{BASE}/"}
        ).content

    def close(self) -> None:
        self.client.close()
