"""The normalization boundary.

Every adapter converts its source payload into these at its own edge, and
nothing downstream ever sees a source-shaped dict. Pydantic does the second of
the three normalization layers -- coercion and validation -- for every source
at once; extraction (source-shaped -> flat) is per source in `sources/specs.py`,
and semantic reconciliation (which fields mean the same thing across sources)
is deliberately NOT done here: pixiv `bookmarkCount` and X `favorite_count` are
both engagement and are not the same number, so they stay in `source_meta`.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Source = Literal["pixiv", "twitter"]
ALL_SOURCES: tuple[Source, ...] = ("pixiv", "twitter")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def norm_tag(tag: str) -> str:
    """NFKC + trim + casefold. Folds fullwidth parens, halfwidth kana and
    fullwidth latin so 申鶴（原神） and 申鶴(原神) group together. The RAW form
    is kept alongside because pixiv's exact-tag search needs it."""
    return unicodedata.normalize("NFKC", tag).strip().casefold()


class MediaRef(BaseModel):
    """One image within a post. `url` still needs source-specific headers."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    url: str = Field(min_length=1)
    width: int = 0
    height: int = 0
    referer: str | None = None  # pximg 403s without this
    filename_hint: str = ""


class Tag(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw: str
    norm: str
    translated: str | None = None  # pixiv's EN translation, when present

    @classmethod
    def of(cls, raw: str, translated: str | None = None) -> Tag:
        return cls(raw=raw.strip(), norm=norm_tag(raw), translated=translated)


class IllustRecord(BaseModel):
    """A post, not an image. A pixiv artwork with 12 pages is one record."""

    model_config = ConfigDict(extra="forbid")

    source: Source
    external_id: str  # pixiv illustId / tweet id -- ALWAYS str
    artist_id: str
    artist_name: str = ""
    artist_handle: str = ""  # twitter screen_name, when known
    title: str = ""
    caption: str = Field(default="", max_length=4000)
    tags: list[Tag] = Field(default_factory=list)
    page_count: int = Field(default=1, ge=1)
    illust_type: Literal["illust", "manga", "ugoira", "video"] = "illust"
    is_r18: bool = False
    posted_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=utcnow)
    permalink: str = ""
    bookmark_count: int = 0  # pixiv only; 0 elsewhere. NOT comparable
    # with X likes -- those live in source_meta
    media: list[MediaRef] = Field(default_factory=list)
    source_meta: dict[str, Any] = Field(default_factory=dict)
    raw_sha: str | None = None  # content address of the payload this
    # came from, when retained

    # -- coercion at the edge -------------------------------------------
    @field_validator("external_id", "artist_id", mode="before")
    @classmethod
    def _ids_are_str(cls, v: Any) -> str:
        # snowflakes exceed JS safe-integer range; an int that reaches the
        # webview is a rounding bug waiting to happen
        if v is None or v == "":
            raise ValueError("id is required")
        return str(v)

    @field_validator("posted_at", "fetched_at", mode="before")
    @classmethod
    def _tz_aware_utc(cls, v: Any) -> datetime | None:
        if v is None or v == "":
            return None
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v, tz=timezone.utc)
        if isinstance(v, str):
            s = v.strip().replace("Z", "+00:00")
            for fmt in ("%Y-%m-%d %H:%M:%S", "%a %b %d %H:%M:%S %z %Y"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    dt = None
            if dt is None:
                dt = datetime.fromisoformat(s)
        elif isinstance(v, datetime):
            dt = v
        else:
            raise ValueError(f"unparseable datetime: {v!r}")
        # naive datetimes compare fine and sort wrong; gallery-dl emits timezone.utc
        # without an offset, pixiv emits +09:00. Both are normalised to timezone.utc,
        # not just made aware: the db stores ISO strings and keyset pagination
        # compares them lexically, so mixed offsets would mis-order.
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, v: Any) -> list[Tag]:
        out: list[Tag] = []
        seen: set[str] = set()
        for t in v or []:
            if isinstance(t, Tag):
                tag = t
            elif isinstance(t, dict):
                tag = Tag.of(t.get("raw") or t.get("tag") or "", t.get("translated"))
            else:
                tag = Tag.of(str(t))
            if tag.raw and tag.norm not in seen:
                seen.add(tag.norm)
                out.append(tag)
        return out

    @field_validator("caption", mode="before")
    @classmethod
    def _clip(cls, v: Any) -> str:
        return (v or "")[:4000]

    @model_validator(mode="before")
    @classmethod
    def _page_count_matches_media(cls, data: Any) -> Any:
        # records are built ONCE at the adapter edge with media in hand; the
        # page count is reconciled here rather than trusted from the source
        if isinstance(data, dict) and data.get("media"):
            data["page_count"] = max(int(data.get("page_count") or 1), len(data["media"]))
        return data

    # -- convenience ------------------------------------------------------
    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.external_id)

    @property
    def tag_raws(self) -> list[str]:
        return [t.raw for t in self.tags]


class Watch(BaseModel):
    """One character being tracked, and how each source names it."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    label: str = ""
    pixiv_tags: list[str] = Field(default_factory=list)  # 甘雨, 甘雨(原神)
    match_terms: list[str] = Field(default_factory=list)  # X text matching
    min_bookmarks: int = Field(default=0, ge=0)
    include_r18: bool = False
    # which sources this character is crawled from; both by default. pixiv
    # discovers, X only filters the timelines of artists already found, so an
    # X-only watch matches against whoever the other watches have surfaced.
    sources: list[Source] = Field(default_factory=lambda: list(ALL_SOURCES))
    # posts per run: how many NEW kept posts one crawl collects for this
    # character (pipeline.search_to_target); the next run continues further back
    target: int = Field(default=100, ge=1, le=1000)
    # the image-kind filter (kinds.KEEP) for this character's posts: off keeps
    # photos, cosplay, 3D and screenshots too
    kind_filter: bool = True
    # who may be in the picture (coreflame/people.py): any, or female / male
    # with full = only that gender, partial = the other one as a minority
    gender: Literal["any", "female", "male"] = "any"
    gender_mode: Literal["full", "partial"] = "full"

    @field_validator("sources", mode="before")
    @classmethod
    def _sources(cls, v: Any) -> list[Source]:
        if v is None:
            return list(ALL_SOURCES)
        out = [s for s in ALL_SOURCES if s in (v or [])]
        if not out:
            raise ValueError("a watch needs at least one source: pixiv, twitter")
        return out

    def wants(self, source: Source) -> bool:
        return source in self.sources

    @field_validator("pixiv_tags", "match_terms", mode="before")
    @classmethod
    def _strip_dedupe(cls, v: Any) -> list[str]:
        out, seen = [], set()
        for item in v or []:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return out


@dataclass(slots=True)
class DiscoverStats:
    """Filled by an adapter during discover(). `highest_id` is the highest id
    LISTED, not yielded -- gated ids must still advance the watermark, or a
    feed whose newest page was all seen via another tag never moves."""

    listed: int = 0
    gated: int = 0  # skipped by the visited set; no request spent
    fetched: int = 0
    skipped: int = 0  # rejected by config after a fetch
    gone: int = 0
    failed: int = 0
    highest_id: int = 0
