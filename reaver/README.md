# reaver

A personal watcher/archive for illustrations of **specific characters**, from
pixiv and X.

```
pip install -r requirements.txt
export PIXIV_PHPSESSID='12345_AaBb...'          # from a logged-in pixiv cookie
export TWITTER_COOKIES=~/.reaver/x_cookies.txt

python3 -m coreflame watch ganyu --pixiv-tag 甘雨 --pixiv-tag '甘雨(原神)' \
        --term ganyu --term 甘雨 --min-bookmarks 500
python3 -m coreflame doctor
python3 -m coreflame poll
python3 -m coreflame status
```

## The one design decision everything follows from

**pixiv is the discovery index. X is a follow feed. They are not symmetric.**

On pixiv a character is a first-class tag the artist applies, and
`s_mode=s_tag_full` matches it exactly - "every artwork tagged 甘雨, newest
first" is one cheap paged request. X has no equivalent: no character metadata,
inconsistent hashtags, and as of February 2026 no free API tier at all
(pay-per-use credits with a 7-day recent-search window; Basic/Pro are legacy
plans closed to new signups).

So the pipeline is:

```
pixiv tag search  ──► artworks  ──► artists
                                      │
                       /ajax/user/{id}?full=1  →  X handle
                                      │
                                      ▼
                       X media timelines of those artists
                                      │
                    text match + perceptual-hash dedupe
```

Characters find artists on pixiv; artists are then followed on X. The artist is
the join key, and it is the only free path from "a character I like" to "that
character on X".

## Watermarks

Both sources hand out monotonically increasing ids (pixiv illust ids, X
snowflake ids), so the watermark is an integer comparison - no timezone
parsing, no clock skew. The pixiv poller walks one full page *past* the
watermark before stopping, because an artwork can become public with an id
lower than one already seen.

## Dedupe

Two levels, because the same picture on both sources is not the same file - X
re-encodes and rescales, so sha256 never matches.

1. `sha256` - re-downloads and repeats. Free.
2. `dHash` (64-bit) with Hamming distance ≤ 6, **scoped to one artist**. This
   is what links the pixiv 4096px PNG to the X 2048px JPEG. Scoping keeps it
   O(hundreds) per image instead of O(entire archive), and a cross-post is by
   definition by the same artist.

dHash survives re-encode and rescale. It does *not* survive crops, mirroring or
heavy recolouring - accepted false negatives, because the alternative (CNN
embeddings) is three orders of magnitude more machinery than a personal
archive needs.

## Why gallery-dl for X and not our own client

X's GraphQL endpoints (`SearchTimeline`, `UserMedia`) need a logged-in
`auth_token` + `ct0` and change without notice. `gallery-dl` tracks them as a
maintained project. This code owns the *policy* - who to follow, what to keep,
how to dedupe; the fragile protocol layer stays something you fix with
`pip install -U gallery-dl`.

## Things that will bite you

| Symptom | Cause | Fix |
|---|---|---|
| Every pixiv image 403s | Missing `Referer` on i.pximg.net | Already set per-request; don't strip it |
| pixiv results suddenly empty | `PHPSESSID` invalidated (you logged out on the site) | Re-export the cookie |
| No R-18 results | Anonymous session, or `mode=safe` | Log in **and** `--r18` on the watch |
| X polling does nothing | No followed handles yet | `coreflame poll` (pixiv first) then `coreflame link` |
| gallery-dl errors on every handle | Cookies missing/expired | Re-export x.com cookies; use a throwaway account |
| Ugoira skipped | Animations are a frame zip behind `/ugoira_meta` | Out of scope by design |

## Legal / ToS

pixiv's web ajax endpoints are not a public API, and automated access to X is
against its terms. This is a private archive of publicly posted work for
personal viewing - don't redistribute, don't strip artist attribution
(`permalink` is stored on every post for a reason), don't monetise, and keep
the request rates where they are. Deleted or privated works should be removed
from your archive too.

## Tests

```
python tests/test_smoke.py     # fully offline: fixtures + generated images
```
