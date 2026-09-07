"""X (Twitter) adapter -- a follow feed, not a search index.

Read this before writing any X code, because it is the constraint that decides
the whole shape of the pipeline:

  * The free API tier was discontinued in February 2026. New developers get
    pay-per-use credits (recent search only, 7-day window); Basic ($200/mo) and
    Pro ($5,000/mo) are legacy plans closed to new signups. Paying per read to
    watch a fan-art tag is not a thing a personal archive does.
  * The unauthenticated syndication endpoint (cdn.syndication.twimg.com)
    resolves *one known tweet id* and 404s on age-restricted posts. It is not a
    search, so it cannot answer "who posted art of this character".
  * X's own GraphQL `SearchTimeline` is what the website uses. Hitting it needs
    a logged-in `auth_token` + `ct0`, and it is exactly the traffic X's
    anti-automation targets. A hand-rolled client here is a guaranteed
    maintenance treadmill and an account-suspension risk.

So this adapter does not search. It walks the media timelines of artists you
already found on pixiv, and it delegates the actual protocol work to
`gallery-dl`, which tracks X's GraphQL changes as a full-time job and which you
can update with `pip install -U` when something breaks. Our code owns the
policy (who to follow, what to keep, dedupe); the fragile part stays in a
library that is somebody else's problem.

Auth: export cookies for x.com from a logged-in browser to cookies.txt, or
point gallery-dl at the browser directly (`--cookies-from-browser firefox`).
Use a throwaway account. This is against X's ToS; you are choosing that risk.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Iterator
from typing import Any

from pydantic import ValidationError

from ..http import SourceClient
from ..models import IllustRecord, Watch
from .specs import TWITTER_ENTRY, extract

log = logging.getLogger(__name__)


class GalleryDLError(RuntimeError):
    pass


class TwitterAdapter:
    name = "twitter"
    supports_discovery = False  # <- the whole point of the docstring

    def __init__(
        self,
        cookies_file: str | None = None,
        cookies_from_browser: str | None = None,
        binary: str = "gallery-dl",
        rate: float = 0.5,
        extra_args: list[str] | None = None,
        proxy: str | None = None,
        sink=None,
    ) -> None:
        self.binary = binary
        self.proxy = proxy
        self.sink = sink
        self.extracted: list[dict] = []
        self.cookies_file = cookies_file
        self.cookies_from_browser = cookies_from_browser
        self.extra_args = extra_args or []
        # gallery-dl does its own pacing for metadata; this client is only for
        # pulling pbs.twimg.com bytes, which needs no auth.
        self.client = SourceClient(base_headers={}, rate=rate * 4, burst=4.0, proxy=proxy)

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    # -- metadata ---------------------------------------------------------
    def _run(self, url: str, limit: int) -> list[dict]:
        if not self.available():
            raise GalleryDLError(f"{self.binary} not found on PATH (pip install gallery-dl)")
        cmd = [
            self.binary,
            "--dump-json",
            "--no-download",
            "-q",
            "--range",
            f"1-{limit}",
            "-o",
            "extractor.twitter.videos=false",
            "-o",
            "extractor.twitter.retweets=false",
            "-o",
            "extractor.twitter.replies=false",
            "-o",
            "extractor.twitter.text-tweets=false",
            "-o",
            "extractor.twitter.size=orig,large",
        ]
        if self.proxy:
            cmd += ["--proxy", self.proxy]  # gallery-dl cannot use our resolver
        if self.cookies_file:
            cmd += ["--cookies", self.cookies_file]
        elif self.cookies_from_browser:
            cmd += ["--cookies-from-browser", self.cookies_from_browser]
        cmd += [*self.extra_args, url]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        if proc.returncode != 0 and not proc.stdout.strip():
            raise GalleryDLError(
                f"gallery-dl failed ({proc.returncode}): {proc.stderr.strip()[:400]}"
            )
        try:
            return self._flatten(json.loads(proc.stdout or "[]"))
        except json.JSONDecodeError as e:
            raise GalleryDLError(f"unparseable gallery-dl output: {e}") from e

    @staticmethod
    def _flatten(payload: Any) -> list[dict]:
        """gallery-dl --dump-json emits [kind, url, metadata] triples plus
        directory messages. Keep the triples."""
        out: list[dict] = []
        for entry in payload or []:
            if (
                isinstance(entry, list)
                and len(entry) >= 3
                and isinstance(entry[1], str)
                and isinstance(entry[2], dict)
            ):
                meta = dict(entry[2])
                meta["_url"] = entry[1]
                out.append(meta)
        return out

    def timeline(
        self, handle: str, since_id: str | None = None, limit: int = 200
    ) -> Iterator[IllustRecord]:
        """Media timeline of one artist, newest first, stopped at the watermark.

        Snowflake tweet ids are monotonically increasing, so the watermark is
        an integer comparison here too.
        """
        floor = int(since_id) if since_id and since_id.isdigit() else 0
        # gallery-dl emits one entry per IMAGE with the post fields repeated;
        # regroup into one record per post, then build each record ONCE
        posts: dict[str, dict] = {}
        media: dict[str, list[dict]] = {}
        for meta in self._run(f"https://x.com/{handle}/media", limit):
            fields = extract(TWITTER_ENTRY, meta)
            tid = str(fields.get("external_id") or "")
            if not tid or (floor and int(tid) <= floor):
                continue
            if tid not in posts:
                if self.sink:
                    fields["raw_sha"] = self.sink.put_raw("twitter", "twitter_entry", meta, tid)
                fields.setdefault("artist_id", handle)
                fields.setdefault("artist_handle", handle)
                fields["permalink"] = f"https://x.com/{handle}/status/{tid}"
                posts[tid] = fields
                media[tid] = []
                self.extracted.append(fields)
            url = fields.get("_media_url") or ""
            if url:
                media[tid].append(
                    dict(
                        index=int(fields.get("_media_num") or len(media[tid]) + 1) - 1,
                        url=url,
                        width=int(fields.get("_width") or 0),
                        height=int(fields.get("_height") or 0),
                    )
                )
        for tid, fields in posts.items():
            clean = {k: v for k, v in fields.items() if not k.startswith("_")}
            try:
                yield IllustRecord(**clean, media=media[tid])
            except ValidationError as e:
                if self.sink:
                    self.sink.quarantine("twitter", tid, str(e), clean, fields.get("raw_sha"))
                log.warning("tweet %s failed validation: %s", tid, e.errors()[0]["msg"])

    def discover(self, watch: Watch, since: str | None = None) -> Iterator[IllustRecord]:
        raise NotImplementedError("X has no free character search; poll followed artists instead")

    def matches(self, rec: IllustRecord, watch: Watch) -> bool:
        """Text-match a timeline post against a watch.

        Deliberately loose and deliberately not the only filter: X posts carry
        no reliable character metadata, so this catches the ones that say the
        name and misses the ones that don't. The near-duplicate pass in
        dedupe.py is what actually links an X post to the pixiv upload of the
        same picture -- this is only the fast path.
        """
        hay = " ".join([rec.caption, " ".join(rec.tag_raws)]).lower()
        terms = [t.lower() for t in (watch.match_terms or [watch.slug])]
        return any(t in hay for t in terms)

    def fetch_media(self, url: str, referer: str | None = None) -> bytes:
        if "pbs.twimg.com" in url and "name=" not in url:
            url = url + ("&" if "?" in url else "?") + "name=orig"
        return self.client.get(url).content

    def close(self) -> None:
        self.client.close()
