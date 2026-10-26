---
name: add-source-adapter
description: Add a new illustration source to reaver (Misskey, Mastodon/pawoo, Bluesky, DeviantArt, Tumblr, an HTML site). Use when adding, evaluating or debugging a source adapter, or when asked to "crawl <site>" or "support <site>".
---

# Add a source adapter

## Before writing any code

1. **Verify access against primary sources, today.** Official API? What does it
   cost *now*? Documented rate limits? Auth? Response shape? Free tiers get
   removed - X's did in Feb 2026. Put the date on every figure you record.
2. **Rank the source honestly:** official API > permitted/community API >
   the site's own frontend endpoints > HTML. Say which tier it lands in.
3. **Decide discovery or follow.** This is the question that shapes everything:

   > Can this source answer *"find art of character X"*, or only
   > *"show me this artist's posts"*?

   Sources with real character tags (pixiv) are discovery. Sources with only
   hashtags or free-text (X, Bluesky, Misskey) are weaker - decide deliberately
   whether the adapter sets `supports_discovery = True`, and if not, make
   `discover()` raise with a message saying why. Do NOT fake discovery with
   text search that will quietly miss most of the corpus.
4. **Prefer protocol adapters over site adapters.** One Mastodon adapter covers
   pawoo, baraag and every future instance from a config field. One Misskey
   adapter covers misskey.io and the rest. Check whether the "new source" is
   really a new instance of a protocol already supported.
5. **Delegate protocol layers that are somebody else's full-time job.** For
   aggressively defended sites, wrap a maintained tool (`gallery-dl`) behind the
   adapter interface rather than hand-rolling a client that dies in a month.

## Writing it

- One file in `reaver/coreflame/sources/`. Implement the `Adapter` protocol:
  `name`, `supports_discovery`, `discover()`, `fetch_media()`.
- **Normalize at the edge.** Return `IllustRecord` (`coreflame/models.py`);
  nothing downstream may see a source-shaped dict. Field extraction is a glom
  spec in `coreflame/sources/specs.py` where every path is
  `Coalesce(..., default=None)` - a shape change becomes a validation
  failure routed to quarantine and a DRIFT note, not silent nulls or a crash.
- **Wire the visited gate.** Check `seen_posts` from the cheapest point in the
  listing - before any per-item detail request. Record `gone` on 404/410 or the
  crawl re-fetches deleted posts forever.
- **Watermark on a monotonic id** if the source has one (most post ids are), and
  walk one full page past the floor before stopping.
- **Timestamps tz-aware UTC. IDs `str`. Tags keep `tag_raw` + NFKC `tag_norm`.**
- Mapping specs and selectors go in config, not code.
- Rate limits: give the adapter its own bucket. Retry 429 and 5xx only.
- Media host quirks (a required `Referer`, a size suffix) belong in
  `fetch_media()`, set per request.

## Then

- **Fixtures, always.** Fixture payloads live inline in
  `reaver/tests/test_smoke.py` (see `fake_pixiv()`); add one shaped like a
  real response and assert the normalizer against it offline. Tests are plain
  `python3 tests/test_x.py` files run by `reaver/check.sh`. No test may hit
  the network.
- Test the watermark at the boundary (an item exactly at the floor) and dedupe
  with a re-encoded copy, not a byte-identical one.
- Add the source to `doctor` so auth/dependency state is visible before a run
  burns requests.
- Note the ToS position in the adapter docstring: which endpoints are official,
  what the terms require architecturally, what risk the user is accepting.

## Adding a source multiplies dedupe load

The same illustration on four sources is four copies, and the artist-scoped
phash only catches them if artist identity links across all four. Beyond a third
source, the single `pixiv profile → X handle` hop is not enough - it needs to
become an identity graph (union-find over asserted edges). Raise this rather
than quietly letting dedupe degrade.

## Verification

- Offline fixture test passes for the new normalizer
- `supports_discovery` matches what the source can actually do
- A second poll of an unchanged feed makes near-zero detail requests (the gate)
- A deleted post is recorded `gone` and not retried on the next poll
- Rate-limit bucket present; no 4xx retried
- `doctor` reports the new source's auth state (`coreflame doctor`)
- `cd reaver && ./check.sh` is green
