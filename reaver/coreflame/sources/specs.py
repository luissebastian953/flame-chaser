"""Extraction specs: source-shaped payload -> flat dict, as DATA.

This is layer one of normalization. glom specs are declarative, so a site
changing its JSON is a spec edit, not a code change -- the same rule as
selectors for HTML sources. Layer two (coercion + validation) is
`models.IllustRecord`; these specs only have to produce something it accepts.

Each spec yields the constructor kwargs of IllustRecord. Fields a spec cannot
produce are left out and fall to the model's defaults; `Coalesce(..., default=)`
guards the paths pixiv sometimes omits, so a missing field is a null in the
extraction-rate metric rather than an exception.
"""

from __future__ import annotations

from typing import Any

from glom import Coalesce, glom

_ILLUST_TYPE = {0: "illust", 1: "manga", 2: "ugoira", "0": "illust", "1": "manga", "2": "ugoira"}

# ---------------------------------------------------------------- pixiv
#: /ajax/illust/{id}  (body)
PIXIV_DETAIL = {
    "source": lambda _: "pixiv",
    # required fields still Coalesce with a None default: extraction must
    # never raise -- a missing required field is VALIDATION's failure, which
    # is what routes the record to quarantine with its raw payload retained
    "external_id": Coalesce("illustId", "id", default=None),
    "artist_id": Coalesce("userId", default=None),
    "artist_name": Coalesce("userName", default=""),
    "title": Coalesce("illustTitle", "title", default=""),
    "caption": Coalesce("description", default=""),
    "tags": Coalesce(
        ("tags.tags", [{"tag": "tag", "translated": Coalesce("translation.en", default=None)}]),
        default=[],
    ),
    "page_count": Coalesce("pageCount", default=1),
    "illust_type": (Coalesce("illustType", default=0), lambda v: _ILLUST_TYPE.get(v, "illust")),
    "is_r18": (Coalesce("xRestrict", default=0), lambda v: int(v or 0) > 0),
    "posted_at": Coalesce("createDate", "uploadDate", default=None),
    "bookmark_count": Coalesce("bookmarkCount", default=0),
    "source_meta": {
        "x_restrict": Coalesce("xRestrict", default=0),
        "like_count": Coalesce("likeCount", default=None),
        "view_count": Coalesce("viewCount", default=None),
        "ai_type": Coalesce("aiType", default=None),  # 2 = AI-generated
        "width": Coalesce("width", default=None),
        "height": Coalesce("height", default=None),
    },
}

#: /ajax/search/artworks  (body.illustManga.data[i]) -- the cheap listing row
PIXIV_LISTING = {
    "external_id": Coalesce("illustId", "id", default=""),  # ad rows have none
    "artist_id": Coalesce("userId", default=""),
    "artist_name": Coalesce("userName", default=""),
    "title": Coalesce("illustTitle", "title", default=""),
    "tags": Coalesce("tags", default=[]),  # raw strings only
    "page_count": Coalesce("pageCount", default=1),
    "illust_type": (Coalesce("illustType", default=0), lambda v: _ILLUST_TYPE.get(v, "illust")),
    "is_r18": (Coalesce("xRestrict", default=0), lambda v: int(v or 0) > 0),
    "is_ad": Coalesce("isAdContainer", default=False),
    "thumb_url": Coalesce("url", default=""),  # 250x250 square; needs Referer, probe only
}

# --------------------------------------------------------------- twitter
#: gallery-dl --dump-json metadata for ONE media entry (post fields repeat)
TWITTER_ENTRY = {
    "source": lambda _: "twitter",
    "external_id": Coalesce("tweet_id", "id", default=None),
    "artist_id": Coalesce("author.id", "user.id", default=""),
    "artist_name": Coalesce("author.name", "user.name", default=""),
    "artist_handle": Coalesce("author.nick", "user.nick", default=""),
    "caption": Coalesce("content", default=""),
    "tags": Coalesce("hashtags", default=[]),
    "is_r18": (Coalesce("sensitive", default=False), bool),
    "posted_at": Coalesce("date", default=None),
    "source_meta": {
        "favorite_count": Coalesce("favorite_count", default=None),
        "retweet_count": Coalesce("retweet_count", default=None),
        "reply_count": Coalesce("reply_count", default=None),
        "conversation_id": Coalesce("conversation_id", default=None),
        "lang": Coalesce("lang", default=None),
    },
    "_media_url": Coalesce("_url", default=""),
    "_media_num": Coalesce("num", default=1),
    "_width": Coalesce("width", default=0),
    "_height": Coalesce("height", default=0),
}


def extract(spec: dict, payload: Any) -> dict[str, Any]:
    """Apply a spec. Never raises on a missing path -- that is what the
    Coalesce defaults are for -- so a shape change shows up as nulls."""
    out = glom(payload, spec)
    # drop None so pydantic defaults apply; keep falsy-but-meaningful values
    return {k: v for k, v in out.items() if v is not None}


def null_rate(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    """Per-field share of rows where extraction produced nothing. This is the
    drift alarm: `title` at 4% extracted when it was 99% last run means the
    site changed and the spec needs one line, not a re-crawl."""
    if not rows:
        return {f: 0.0 for f in fields}
    n = len(rows)
    return {f: sum(1 for r in rows if r.get(f) in (None, "", [], {})) / n for f in fields}
