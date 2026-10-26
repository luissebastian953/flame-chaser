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

So this adapter never speaks GraphQL itself. It delegates the protocol work to
`gallery-dl`, which tracks X's changes as a full-time job and which you can
update with `pip install -U` when something breaks. Our code owns the policy
(who to follow, what to keep, dedupe); the fragile part stays in a library that
is somebody else's problem. Two feeds, both through gallery-dl:

  * `timeline()` -- the media timeline of an artist already found on pixiv.
    Cheap, precise, the default.
  * `search()` -- X's own search for a match term, images only. This is the
    only way a watch with pixiv switched off finds anything, and it is the
    traffic X polices hardest: keep the per-term limit small, keep the rate
    conservative, use a throwaway account.

Auth: export cookies for x.com from a logged-in browser to cookies.txt, or
point gallery-dl at the browser directly (`--cookies-from-browser firefox`).
Use a throwaway account. This is against X's ToS; you are choosing that risk.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote_plus

import httpx
from pydantic import ValidationError

from ..http import METER, SourceClient
from ..models import IllustRecord, Watch
from ..online import WATCH, Offline
from .specs import TWITTER_ENTRY, extract

log = logging.getLogger(__name__)


# gallery-dl paces itself; the panel shows its invocations, not a rate
METER.declare("gallery-dl", "gallery-dl", None)

#: argv[1] that makes the frozen sidecar run gallery-dl instead of the daemon
#: (deliverer/scripts/sidecar_entry.py dispatches on it before anything loads).
GALLERY_DL_FLAG = "--gallery-dl"


def gallery_dl_command() -> list[str] | None:
    """How this process runs gallery-dl. The module we depend on, through this
    interpreter, comes first: in the frozen sidecar that interpreter is the
    dawnmaker executable itself (there is no `gallery-dl` on a user's PATH and
    PyInstaller ships modules, not console scripts); in a venv or Docker it is
    `python -m gallery_dl`. A `gallery-dl` binary on PATH is the fallback.
    None means X is off: no module, no binary."""
    if getattr(sys, "frozen", False):
        return [sys.executable, GALLERY_DL_FLAG]
    if importlib.util.find_spec("gallery_dl") is not None:
        return [sys.executable, "-m", "gallery_dl"]
    found = shutil.which("gallery-dl")
    return [found] if found else None


METER.declare("twitter", "pbs.twimg.com", 2.0)


class GalleryDLError(RuntimeError):
    pass


class TwitterAdapter:
    name = "twitter"
    supports_discovery = True  # by search term, through gallery-dl; see docstring

    def __init__(
        self,
        cookies_file: str | None = None,
        cookies_from_browser: str | None = None,
        binary: str | list[str] | None = None,
        rate: float = 0.5,
        extra_args: list[str] | None = None,
        proxy: str | None = None,
        sink=None,
    ) -> None:
        # `binary`: a name or argv prefix to run instead of gallery_dl_command()
        # (tests pass something uninstalled and fake the answers).
        if binary is None:
            self.command = gallery_dl_command()
        else:
            self.command = [binary] if isinstance(binary, str) else list(binary)
        self.proxy = proxy
        self.last_variant = "orig"  # which size the last fetch_media got
        self.sink = sink
        self.extracted: list[dict] = []
        self.cookies_file = cookies_file
        self.cookies_from_browser = cookies_from_browser
        self.extra_args = extra_args or []
        # gallery-dl does its own pacing for metadata; this client is only for
        # pulling pbs.twimg.com bytes, which needs no auth.
        self.client = SourceClient(
            base_headers={},
            rate=rate * 4,
            burst=4.0,
            proxy=proxy,
            meter=("twitter", "pbs.twimg.com"),
        )

    @property
    def binary(self) -> str:
        """What to name in a "not found" message."""
        return self.command[0] if self.command else "gallery-dl"

    def available(self) -> bool:
        return self.command is not None and shutil.which(self.command[0]) is not None

    # -- metadata ---------------------------------------------------------
    def _run(self, url: str, limit: int, by_post: bool = False) -> list[dict]:
        """`limit` counts image FILES (`--range`) unless `by_post`, when it
        counts posts (`--post-range`) -- a 4-image post is one post."""
        if not self.available():
            raise GalleryDLError(f"{self.binary} not found on PATH (pip install gallery-dl)")
        cmd = [
            *(self.command or []),
            "--dump-json",
            "--no-download",
            "-q",
            "--post-range" if by_post else "--range",
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

        METER.hit("gallery-dl")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        if proc.returncode != 0 and not proc.stdout.strip():
            # gallery-dl's stderr is prose; the probe decides whether this was
            # X or the connection, same as a transport error in SourceClient
            if WATCH.failed():
                raise Offline(f"gallery-dl could not reach X: {proc.stderr.strip()[:200]}")
            raise GalleryDLError(
                f"gallery-dl failed ({proc.returncode}): {proc.stderr.strip()[:400]}"
            )
        try:
            payload = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError as e:
            raise GalleryDLError(f"unparseable gallery-dl output: {e}") from e
        # gallery-dl exits 0 and reports refusals INSIDE the json, as
        # [-1, {"error": ...}]. Left to _flatten those look exactly like an
        # empty result -- which is how an expired cookie file spent a month
        # looking like "this character has no art on X". Raise instead.
        if err := self._error(payload):
            raise GalleryDLError(err)
        return self._flatten(payload)

    @staticmethod
    def _error(payload: Any) -> str | None:
        """gallery-dl's own error entries, if any. Cookie problems land here
        as AuthRequired, and its warnings go to stderr, not this list."""
        for entry in payload or []:
            if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[1], dict):
                e = entry[1]
                if "error" in e:
                    msg = str(e.get("message") or "").strip()
                    kind = str(e["error"])
                    if kind == "AuthRequired":
                        return (
                            "X refused: the session is not signed in "
                            "(cookies missing, expired, or logged out elsewhere) -- "
                            "reconnect X in Settings > Accounts"
                        )
                    return f"X refused ({kind}){': ' + msg if msg else ''}"
        return None

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
        yield from self._posts(f"https://x.com/{handle}/media", since_id, limit, handle)

    def search(
        self, term: str, since_id: str | None = None, limit: int = 50
    ) -> Iterator[IllustRecord]:
        """X search for one term, images only, newest first, stopped at the
        watermark. `filter:images` keeps text posts out of the request budget
        entirely; retweets/replies are dropped by the extractor options."""
        q = quote_plus(f"{term} filter:images -filter:retweets")
        yield from self._posts(
            f"https://x.com/search?q={q}&src=typed_query&f=live", since_id, limit, by_post=True
        )

    def search_page(
        self, term: str, max_id: int | None = None, limit: int = 50
    ) -> list[IllustRecord]:
        """One page of X search for `term`, newest first, at or below `max_id`
        (None = from the newest). `limit` counts POSTS. X treats max_id as
        inclusive and has been seen to return the post just above it, so the
        caller filters ids itself; this only narrows the window."""
        q = f"{term} filter:images -filter:retweets"
        if max_id is not None:
            q += f" max_id:{max_id}"
        url = f"https://x.com/search?q={quote_plus(q)}&src=typed_query&f=live"
        return list(self._posts(url, None, limit, by_post=True))

    def _posts(
        self,
        url: str,
        since_id: str | None,
        limit: int,
        handle: str | None = None,
        by_post: bool = False,
    ) -> Iterator[IllustRecord]:
        floor = int(since_id) if since_id and since_id.isdigit() else 0
        # gallery-dl emits one entry per IMAGE with the post fields repeated;
        # regroup into one record per post, then build each record ONCE
        posts: dict[str, dict] = {}
        media: dict[str, list[dict]] = {}
        for meta in self._run(url, limit, by_post):
            fields = extract(TWITTER_ENTRY, meta)
            tid = str(fields.get("external_id") or "")
            if not tid or (floor and int(tid) <= floor):
                continue
            if tid not in posts:
                if self.sink:
                    fields["raw_sha"] = self.sink.put_raw("twitter", "twitter_entry", meta, tid)
                # a timeline knows its author from the url; search results carry it in the entry
                author = fields.get("artist_handle") or handle or str(fields.get("artist_id") or "")
                fields["artist_handle"] = author
                if not fields.get("artist_id"):
                    fields["artist_id"] = author
                fields["permalink"] = f"https://x.com/{author}/status/{tid}"
                posts[tid] = fields
                media[tid] = []
                self.extracted.append(fields)
            url_ = fields.get("_media_url") or ""
            if url_:
                media[tid].append(
                    dict(
                        index=int(fields.get("_media_num") or len(media[tid]) + 1) - 1,
                        url=url_,
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
        """Search every match term of a watch. The pipeline calls search()
        per term so each term keeps its own watermark; this is the
        convenience form for the CLI and tests."""
        for term in watch.match_terms or [watch.slug]:
            yield from self.search(term, since)

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
        """The largest file X serves: `name=orig`. A few media (old uploads,
        some PNG re-encodes) 404 at orig and exist only at `4096x4096`; that
        is the one fallback, and `last_variant` says which one was fetched."""
        if "pbs.twimg.com" in url and "name=" not in url:
            url = url + ("&" if "?" in url else "?") + "name=orig"
        self.last_variant = "orig"
        try:
            return self.client.get(url).content
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404 or "name=orig" not in url:
                raise
            alt = url.replace("name=orig", "name=4096x4096")
            log.info("orig 404 for %s; trying 4096x4096", url)
            data = self.client.get(alt).content
            self.last_variant = "4096x4096"
            return data

    def close(self) -> None:
        self.client.close()
