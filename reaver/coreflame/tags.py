"""Observed tags: what a character's artworks are actually tagged with, ranked
so the config can learn from the crawl.

Ranking by frequency is wrong, and obviously so once you look at the data:
原神 appears on ~100% of Ganyu artworks -- top of any frequency list, and
useless as a character tag, because watching it means crawling the entire
game's fanart. The tag worth suggesting is frequent for THIS character and
rare for every other one:

    score = share_in_character * log(N / characters_carrying_tag)

That is TF-IDF's shape. 甘雨(原神) has near-1 share and one character -> high;
原神 has share 1.0 across every watched character -> log(N/N) = 0 -> gone from
the top of the list with no hand-maintained stopword list. With a single
watched character plain IDF is log(1) = 0 for everything, so the score
degrades to share alone -- which is the best one character can tell you, and
it says so in the CLI.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from .db import Store
from .models import Watch, norm_tag

WATCHED, SUGGESTED, IGNORED = "watched", "suggested", "ignored"


@dataclass(slots=True)
class TagStat:
    slug: str
    tag_norm: str
    tag_raw: str
    translated: str | None
    posts: int
    share: float
    characters: int
    score: float
    state: str


def _score(share: float, n_characters: int, carrying: int) -> float:
    if n_characters <= 1:
        return share  # no rarity signal exists yet
    return share * math.log(n_characters / max(1, carrying))


# ---------------------------------------------------------------- rebuild
def rebuild(store: Store, slugs: Iterable[str] | None = None) -> int:
    """Recompute tag_stats from post_tags x post_watches. Preserves `state`
    where the user set it (watched follows the watch config; ignored sticks).
    Returns rows written."""
    conn = store.conn
    watches = {w.slug: w for w in store.watches()}
    n_chars = len(watches)
    target = list(slugs) if slugs else list(watches)

    # global: how many watched characters carry each tag_norm at all
    carrying: dict[str, int] = {
        r["tag_norm"]: r["n"]
        for r in conn.execute(
            """SELECT t.tag_norm, count(DISTINCT pw.slug) n
               FROM post_tags t JOIN post_watches pw
                 ON pw.source=t.source AND pw.external_id=t.external_id
               GROUP BY t.tag_norm"""
        )
    }

    prior_state: dict[tuple[str, str], str] = {
        (r["slug"], r["tag_norm"]): r["state"]
        for r in conn.execute("SELECT slug, tag_norm, state FROM tag_stats WHERE state='ignored'")
    }

    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for slug in target:
        w = watches.get(slug)
        watched_norms = {norm_tag(t) for t in (w.pixiv_tags if w else [])}
        total = conn.execute("SELECT count(*) FROM post_watches WHERE slug=?", (slug,)).fetchone()[
            0
        ]
        rows = conn.execute(
            """SELECT t.tag_norm, t.tag_raw, t.translated, count(*) n
               FROM post_tags t JOIN post_watches pw
                 ON pw.source=t.source AND pw.external_id=t.external_id
               WHERE pw.slug=?
               GROUP BY t.tag_norm, t.tag_raw, t.translated""",
            (slug,),
        ).fetchall()
        # pick the most common raw spelling per norm
        per_norm: dict[str, dict] = {}
        raw_counts: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            raw_counts[r["tag_norm"]][r["tag_raw"]] += r["n"]
            e = per_norm.setdefault(r["tag_norm"], {"posts": 0, "translated": None})
            e["posts"] += r["n"]
            e["translated"] = e["translated"] or r["translated"]
        conn.execute("DELETE FROM tag_stats WHERE slug=? AND state<>'ignored'", (slug,))
        for tag_norm, e in per_norm.items():
            share = e["posts"] / total if total else 0.0
            c = carrying.get(tag_norm, 1)
            state = (
                WATCHED
                if tag_norm in watched_norms
                else prior_state.get((slug, tag_norm), SUGGESTED)
            )
            conn.execute(
                """INSERT INTO tag_stats(slug,tag_norm,tag_raw,translated,posts,share,
                                         characters,score,state,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(slug,tag_norm) DO UPDATE SET
                     tag_raw=excluded.tag_raw, translated=excluded.translated,
                     posts=excluded.posts, share=excluded.share,
                     characters=excluded.characters, score=excluded.score,
                     state=CASE WHEN tag_stats.state='ignored' THEN 'ignored'
                                ELSE excluded.state END,
                     updated_at=excluded.updated_at""",
                (
                    slug,
                    tag_norm,
                    raw_counts[tag_norm].most_common(1)[0][0],
                    e["translated"],
                    e["posts"],
                    share,
                    c,
                    _score(share, n_chars, c),
                    state,
                    now,
                ),
            )
            written += 1
    return written


# ---------------------------------------------------------------- queries
def observed(store: Store, slug: str, state: str | None = None, limit: int = 40) -> list[TagStat]:
    where = "slug=?" + (" AND state=?" if state else "")
    args: tuple = (slug, state) if state else (slug,)
    rows = store.conn.execute(
        f"""SELECT * FROM tag_stats WHERE {where}
            ORDER BY CASE state WHEN 'watched' THEN 0 WHEN 'suggested' THEN 1 ELSE 2 END,
                     score DESC, posts DESC LIMIT ?""",
        (*args, limit),
    ).fetchall()
    return [
        TagStat(
            r["slug"],
            r["tag_norm"],
            r["tag_raw"],
            r["translated"],
            r["posts"],
            r["share"],
            r["characters"],
            r["score"],
            r["state"],
        )
        for r in rows
    ]


def set_state(store: Store, slug: str, tag: str, state: str) -> Watch:
    """Watch or ignore an observed tag. `watched` writes back to the watch's
    pixiv_tags (the raw spelling), which is what makes the loop close."""
    assert state in (WATCHED, IGNORED)
    tn = norm_tag(tag)
    watches = {w.slug: w for w in store.watches()}
    w = watches[slug]
    row = store.conn.execute(
        "SELECT tag_raw FROM tag_stats WHERE slug=? AND tag_norm=?", (slug, tn)
    ).fetchone()
    raw = row["tag_raw"] if row else tag
    tags = list(w.pixiv_tags)
    if state == WATCHED and tn not in {norm_tag(t) for t in tags}:
        tags.append(raw)
    if state == IGNORED:
        tags = [t for t in tags if norm_tag(t) != tn]
    w = w.model_copy(update={"pixiv_tags": tags})
    store.upsert_watch(w)
    store.conn.execute(
        """INSERT INTO tag_stats(slug,tag_norm,tag_raw,translated,posts,share,characters,score,state,updated_at)
           VALUES(?,?,?,NULL,0,0,1,0,?,?)
           ON CONFLICT(slug,tag_norm) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at""",
        (slug, tn, raw, state, datetime.now(timezone.utc).isoformat()),
    )
    return w


# ------------------------------------------------- suggestions, no history
def suggest_from_listing(
    store: Store, listing_rows: Iterable[dict], exclude: Iterable[str] = ()
) -> list[TagStat]:
    """Rank co-occurring tags for a character that has NO crawl history yet.

    The pixiv search listing already returns `tags[]` per item, so page 1 of
    the preview search the form fetches for validation is enough. Rarity
    comes from the existing corpus (`tag_stats.characters`), so 原神 is
    demoted even for a brand-new character -- as long as at least one other
    character has been crawled. With an empty corpus this degrades to
    share-only, honestly."""
    rows = list(listing_rows)
    if not rows:
        return []
    n_chars = len(store.watches())
    carrying = {
        r["tag_norm"]: r["n"]
        for r in store.conn.execute(
            "SELECT tag_norm, max(characters) n FROM tag_stats GROUP BY tag_norm"
        )
    }
    excluded = {norm_tag(t) for t in exclude}
    counts: Counter = Counter()
    raws: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        seen = set()
        for t in row.get("tags") or []:
            tn = norm_tag(t)
            if tn in excluded or tn in seen:
                continue
            seen.add(tn)
            counts[tn] += 1
            raws[tn][t] += 1
    out = []
    for tn, n in counts.items():
        share = n / len(rows)
        c = carrying.get(tn, 0) + 1  # +1: this new character carries it
        out.append(
            TagStat(
                "",
                tn,
                raws[tn].most_common(1)[0][0],
                None,
                n,
                share,
                c,
                _score(share, n_chars + 1, c),
                SUGGESTED,
            )
        )
    out.sort(key=lambda s: (-s.score, -s.posts))
    return out
