"""Deleting images from a character's gallery -- to a trash folder first.

A deletion is a *batch*: the images chosen (by hand, by tag, by the Smart
criteria, or everything) become `trash_items`, each carrying its media row as
JSON, and the blob is renamed into `<library>/trash/` (same filesystem as
`blobs/`, so it is a rename, not a copy). The thumbnail stays until the item
is purged, so Undo never has to re-encode anything. Thirty days later --
or at Settings › Storage › Empty trash -- `purge()` unlinks what is left.

Two things make the batch restorable rather than merely recorded:

- `by-character/` names are removed *before* the blob moves. A hardlink is a
  second name for the inode: leave it and the bytes never free.
- A post whose every image went is handled one of two ways, chosen in the
  confirm sheet. *Forget* removes the post with its tags and watch links
  into the batch's snapshot and marks it `skipped/deleted` in the visited
  set, which no config change reopens -- the next run never brings it
  back. *Not forgetting* keeps the post and drops its visited row, so the
  next run re-fetches it and rebuilds its images under the current rules.

`crawl_verdict` is the same Smart criteria applied as a post is stored, when
Settings › Duplicates has the rule switched on.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .blobs import BlobStore
from .db import Store
from .identify import IDENTIFIER_ID, label_of
from .kinds import kept
from .library import LibraryView, safe_name
from .phash import from_signed, hamming
from .seen import SeenState, SkipReason
from .thumbs import ThumbStore

log = logging.getLogger(__name__)

TRASH_DAYS = 30
#: above either, a deletion goes to trash even when asked to be permanent
FORCE_TRASH_IMAGES = 500
FORCE_TRASH_BYTES = 1 << 30
MODES = ("image", "tag", "smart", "all")
#: Smart defaults: the crawl's "sure" score (identify.CAMIE_SURE) is the cutoff
#: the panel shows; the slider starts a little under it
OTHER_FLOOR = 0.30  # under this, the watched character is as good as absent
DUPE_DISTANCE = 6
_CHUNK = 400  # shas per IN (...) -- well under SQLite's variable cap


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrashStore:
    """The folder: `<library>/trash/<sha>.<ext>`, flat -- it is small and short-lived."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, sha: str, ext: str = "") -> Path:
        return self.root / (f"{sha}.{ext}" if ext else sha)

    def bytes_on_disk(self) -> int:
        if not self.root.exists():
            return 0
        return sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())


def _chunks(items: list[str]) -> list[list[str]]:
    return [items[i : i + _CHUNK] for i in range(0, len(items), _CHUNK)]


def _rows_for(store: Store, slug: str, shas: list[str]) -> list[sqlite3.Row]:
    """The stored media rows behind these shas, limited to the character's own
    posts: a sha from another gallery is silently not this gallery's to delete."""
    out: list[sqlite3.Row] = []
    for chunk in _chunks(sorted(set(shas))):
        marks = ",".join("?" * len(chunk))
        out += store.conn.execute(
            f"""SELECT m.*, p.artist_id, p.artist_handle, p.is_r18
                FROM media m
                JOIN posts p ON p.source=m.source AND p.external_id=m.external_id
                JOIN post_watches pw ON pw.source=m.source AND pw.external_id=m.external_id
                WHERE pw.slug=? AND m.state='stored' AND m.sha256 IN ({marks})
                ORDER BY m.rowid""",
            (slug, *chunk),
        ).fetchall()
    return out


def _stored_count(store: Store, slug: str) -> int:
    return int(
        store.conn.execute(
            """SELECT count(*) FROM post_watches pw
               JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
               JOIN media m ON m.source=p.source AND m.external_id=p.external_id
               WHERE pw.slug=? AND m.state='stored' AND p.state='live'""",
            (slug,),
        ).fetchone()[0]
    )


def _slugs_of(store: Store, source: str, external_id: str) -> list[str]:
    return [
        r["slug"]
        for r in store.conn.execute(
            "SELECT slug FROM post_watches WHERE source=? AND external_id=?", (source, external_id)
        )
    ]


def _fname(row: Any) -> str:
    artist_key = row["artist_handle"] or row["artist_id"] or ""
    return safe_name(
        artist_key or row["source"], row["external_id"], f"p{row['idx']}", ext=row["ext"]
    )


def _posts_touched(rows: list[sqlite3.Row], store: Store) -> tuple[list[tuple[str, str]], int]:
    """(posts these rows belong to, how many of them keep another stored image)."""
    posts = sorted({(r["source"], r["external_id"]) for r in rows})
    going = {(r["source"], r["external_id"], r["idx"]) for r in rows}
    keep_other = 0
    for source, eid in posts:
        others = store.conn.execute(
            "SELECT idx FROM media WHERE source=? AND external_id=? AND state='stored'",
            (source, eid),
        ).fetchall()
        if any((source, eid, o["idx"]) not in going for o in others):
            keep_other += 1
    return posts, keep_other


# ---------------------------------------------------------------- preview
def preview(store: Store, blobs: BlobStore, slug: str, shas: list[str]) -> dict[str, Any]:
    """What the confirm sheet states before anything moves."""
    rows = _rows_for(store, slug, shas)
    posts, keep_other = _posts_touched(rows, store)
    by_source: dict[str, int] = {}
    shared = 0
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        if len(_slugs_of(store, r["source"], r["external_id"])) > 1:
            shared += 1
    total = sum(int(r["bytes"] or 0) for r in rows)
    return {
        "images": len(rows),
        "bytes": total,
        "by_source": by_source,
        "posts": {
            "touched": len(posts),
            "keep_other": keep_other,
            "forget": len(posts) - keep_other,
        },
        "shared": shared,  # also in another character's gallery: the same blob, gone there too
        "whole": bool(rows) and len(rows) >= _stored_count(store, slug),
        "forced_trash": len(rows) > FORCE_TRASH_IMAGES or total > FORCE_TRASH_BYTES,
        "trash": summary(store, blobs),
    }


# ---------------------------------------------------------------- remove
def remove(
    store: Store,
    blobs: BlobStore,
    thumbs: ThumbStore,
    slug: str,
    shas: list[str],
    *,
    mode: str = "image",
    trash: bool = True,
    forget: bool = True,
) -> dict[str, Any]:
    """Delete these images from this character. Rows and the visited set change
    in one transaction; files move after it commits, so a crash in between
    leaves an orphan blob (harmless, gc'd) rather than a row with no bytes."""
    if mode not in MODES:
        raise ValueError(f"bad mode: {mode}")
    rows = _rows_for(store, slug, shas)
    if not rows:
        return {"batch_id": None, "images": 0, "bytes": 0, "forgotten": 0, "permanent": not trash}
    total = sum(int(r["bytes"] or 0) for r in rows)
    permanent = not trash and not (len(rows) > FORCE_TRASH_IMAGES or total > FORCE_TRASH_BYTES)
    view = LibraryView(blobs.root.parent)
    tdir = TrashStore(blobs.root.parent / "trash")
    batch_id = uuid.uuid4().hex[:12]
    now = _now()
    posts, _ = _posts_touched(rows, store)
    moves: list[tuple[Path, Path | None, str]] = []  # (blob, trash path or None, sha)
    names: list[tuple[list[str], str]] = []
    snapshot: dict[str, Any] = {"forgotten": [], "reopened": []}
    forgotten = 0
    with store.tx() as c:
        for r in rows:
            names.append((_slugs_of(store, r["source"], r["external_id"]), _fname(r)))
            # sqlite3.Row is not a dict: iterate its keys() explicitly
            row = {k: r[k] for k in r.keys() if k not in ("artist_id", "artist_handle", "is_r18")}  # noqa: SIM118
            if not permanent:
                c.execute(
                    """INSERT OR REPLACE INTO trash_items
                       (source,external_id,idx,sha256,ext,bytes,batch_id,row,deleted_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        r["source"],
                        r["external_id"],
                        r["idx"],
                        r["sha256"],
                        r["ext"],
                        r["bytes"],
                        batch_id,
                        json.dumps(row),
                        now,
                    ),
                )
            c.execute(
                "DELETE FROM media WHERE source=? AND external_id=? AND idx=?",
                (r["source"], r["external_id"], r["idx"]),
            )
            moves.append(
                (
                    blobs.path_for(r["sha256"], r["ext"]),
                    None if permanent else tdir.path_for(r["sha256"], r["ext"]),
                    r["sha256"],
                )
            )
        for source, eid in posts:
            left = c.execute(
                "SELECT 1 FROM media WHERE source=? AND external_id=? AND state='stored' LIMIT 1",
                (source, eid),
            ).fetchone()
            if left is not None:
                continue  # keeps another image: the post stays as it is
            if forget:
                snapshot["forgotten"].append(_snapshot_post(c, source, eid))
                for table in ("post_tags", "post_watches", "media", "posts"):
                    c.execute(
                        f"DELETE FROM {table} WHERE source=? AND external_id=?", (source, eid)
                    )
                store.seen.mark(source, eid, SeenState.SKIPPED, reason=SkipReason.DELETED.value)
                forgotten += 1
            else:
                prior = store.seen.get(source, eid)
                snapshot["reopened"].append([source, eid, prior.state.value if prior else None])
                c.execute("DELETE FROM seen_posts WHERE source=? AND external_id=?", (source, eid))
        if not permanent:
            c.execute(
                """INSERT INTO trash_batches(id,slug,mode,created_at,images,bytes,forgotten,snapshot)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (batch_id, slug, mode, now, len(rows), total, forgotten, json.dumps(snapshot)),
            )
    # files, after the rows are safe
    for slugs, fname in names:
        for s in slugs:
            view.remove(s, fname)
    tdir.root.mkdir(parents=True, exist_ok=True)
    for blob, dest, sha in moves:
        try:
            if dest is None:
                blob.unlink(missing_ok=True)
                if not store.sha_exists(sha):
                    thumbs.path_for(sha).unlink(missing_ok=True)
            elif blob.exists():
                blob.replace(dest)
        except OSError as e:
            log.warning("trash: could not move %s: %s", blob.name, e)
    purge(store, blobs, thumbs)  # the thirty-day sweep rides on every deletion
    return {
        "batch_id": None if permanent else batch_id,
        "images": len(rows),
        "bytes": total,
        "forgotten": forgotten,
        "permanent": permanent,
    }


def _snapshot_post(c: sqlite3.Connection, source: str, eid: str) -> dict[str, Any]:
    def rows(table: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in c.execute(
                f"SELECT * FROM {table} WHERE source=? AND external_id=?", (source, eid)
            )
        ]

    return {
        "posts": rows("posts"),
        "post_tags": rows("post_tags"),
        "post_watches": rows("post_watches"),
        "media": rows("media"),
    }


def _insert(
    c: sqlite3.Connection, table: str, row: dict[str, Any], *, replace: bool = False
) -> None:
    cols = ",".join(row)
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    c.execute(
        f"{verb} INTO {table}({cols}) VALUES({','.join('?' * len(row))})", tuple(row.values())
    )


# ---------------------------------------------------------------- restore
def restore(store: Store, blobs: BlobStore, thumbs: ThumbStore, batch_id: str) -> dict[str, Any]:
    """Undo one batch: rows back exactly as they were, forgotten posts and
    their visited state back, blobs renamed out of the trash. A blob the next
    run re-downloaded meanwhile wins; the trashed copy is dropped."""
    batch = store.conn.execute("SELECT * FROM trash_batches WHERE id=?", (batch_id,)).fetchone()
    if batch is None:
        raise KeyError(batch_id)
    items = store.conn.execute(
        "SELECT * FROM trash_items WHERE batch_id=? ORDER BY rowid", (batch_id,)
    ).fetchall()
    snapshot = json.loads(batch["snapshot"] or "{}")
    view = LibraryView(blobs.root.parent)
    tdir = TrashStore(blobs.root.parent / "trash")
    placed: list[tuple[str, str, str, str]] = []  # (sha, ext, slug, fname)
    with store.tx() as c:
        for post in snapshot.get("forgotten", []):
            for table in ("posts", "post_tags", "post_watches", "media"):
                for row in post.get(table, []):
                    _insert(c, table, row)
            for p in post.get("posts", []):
                store.seen.mark(p["source"], p["external_id"], SeenState.INDEXED)
        for source, eid, _prior in snapshot.get("reopened", []):
            store.seen.mark(source, eid, SeenState.INDEXED)
        for it in items:
            row = json.loads(it["row"])
            _insert(c, "media", row, replace=True)
            p = c.execute(
                "SELECT artist_id, artist_handle FROM posts WHERE source=? AND external_id=?",
                (it["source"], it["external_id"]),
            ).fetchone()
            if p is not None:
                key = p["artist_handle"] or p["artist_id"] or it["source"]
                fname = safe_name(key, it["external_id"], f"p{it['idx']}", ext=it["ext"])
                for s in _slugs_of(store, it["source"], it["external_id"]):
                    placed.append((it["sha256"], it["ext"], s, fname))
        c.execute("DELETE FROM trash_items WHERE batch_id=?", (batch_id,))
        c.execute("DELETE FROM trash_batches WHERE id=?", (batch_id,))
    for it in items:
        src, dest = tdir.path_for(it["sha256"], it["ext"]), blobs.path_for(it["sha256"], it["ext"])
        try:
            if dest.exists():
                src.unlink(missing_ok=True)
            elif src.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dest)
        except OSError as e:
            log.warning("trash: could not restore %s: %s", src.name, e)
    for sha, ext, s, fname in placed:
        blob = blobs.path_for(sha, ext)
        if blob.exists():
            view.place(blob, s, fname)
    return {
        "images": len(items),
        "posts": len(snapshot.get("forgotten", [])) + len(snapshot.get("reopened", [])),
        "slug": batch["slug"],
    }


# ---------------------------------------------------------------- purge
def purge(
    store: Store,
    blobs: BlobStore,
    thumbs: ThumbStore,
    *,
    days: int = TRASH_DAYS,
    everything: bool = False,
) -> dict[str, int]:
    """Unlink trashed blobs older than `days` (or all of them) and forget
    their batches; the thumbnail goes too unless a stored row still shows it."""
    tdir = TrashStore(blobs.root.parent / "trash")
    if everything:
        items = store.conn.execute("SELECT * FROM trash_items").fetchall()
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        items = store.conn.execute(
            "SELECT * FROM trash_items WHERE deleted_at < ?", (cutoff,)
        ).fetchall()
    if not items:
        return {"images": 0, "bytes": 0}
    freed = 0
    with store.tx() as c:
        for it in items:
            c.execute(
                "DELETE FROM trash_items WHERE source=? AND external_id=? AND idx=?",
                (it["source"], it["external_id"], it["idx"]),
            )
        c.execute(
            "DELETE FROM trash_batches WHERE id NOT IN (SELECT DISTINCT batch_id FROM trash_items)"
        )
    for it in items:
        p = tdir.path_for(it["sha256"], it["ext"])
        try:
            if p.exists():
                freed += p.stat().st_size
                p.unlink()
            if not store.sha_exists(it["sha256"]):
                thumbs.path_for(it["sha256"]).unlink(missing_ok=True)
        except OSError as e:
            log.warning("trash: could not purge %s: %s", p.name, e)
    return {"images": len(items), "bytes": freed}


def summary(store: Store, blobs: BlobStore) -> dict[str, Any]:
    r = store.conn.execute(
        "SELECT count(*) n, COALESCE(sum(bytes),0) b, min(deleted_at) oldest FROM trash_items"
    ).fetchone()
    return {"count": int(r["n"]), "bytes": int(r["b"]), "oldest": r["oldest"], "days": TRASH_DAYS}


# ---------------------------------------------------------------- smart
def primary_character(store: Store, slug: str, model: str = IDENTIFIER_ID) -> str | None:
    """The character this gallery is of, as the identifier sees it: the name
    most of its images carry. A watch holds pixiv tags and X terms, not a
    Danbooru name, so this is read off the images rather than stored."""
    got = store.identity_counts(slug, model, include_r18=True)["characters"]
    return got[0][0] if got else None


def _dupe_groups(hashes: list[tuple[str, int, int]], distance: int) -> list[list[str]]:
    """Connected groups of (sha, phash, bytes) within `distance`. Two 64-bit
    hashes at Hamming <= 7 share at least one of eight byte chunks, so chunk
    buckets give the candidate pairs without the n² scan."""
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, (_, h, _) in enumerate(hashes):
        for k in range(8):
            buckets.setdefault((k, (h >> (8 * k)) & 0xFF), []).append(i)
    parent = list(range(len(hashes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen_pairs: set[tuple[int, int]] = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for a_i, a in enumerate(members):
            for b in members[a_i + 1 :]:
                pair = (a, b) if a < b else (b, a)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if hamming(hashes[a][1], hashes[b][1]) <= distance:
                    parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for i in range(len(hashes)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for g in groups.values():
        if len(g) > 1:
            # keep the largest file; the rest are the duplicates
            g.sort(key=lambda i: (-(hashes[i][2]), hashes[i][0]))
            out.append([hashes[i][0] for i in g])
    return out


def smart_matches(
    store: Store,
    slug: str,
    *,
    model: str = IDENTIFIER_ID,
    min_score: float | None = None,
    other_character: bool = True,
    dupes: bool = True,
    distance: int = DUPE_DISTANCE,
    unidentified: bool = False,
    kinds: bool = False,
    include_r18: bool = False,
) -> dict[str, Any]:
    """The Smart · AI identifier mode: which of this gallery's images match
    the criteria and why. Every match carries its reasons so the panel can
    badge the tile; counts are per criterion.

    `kinds` is the recognition filter after the fact: an image the kind
    classifier labelled as anything but KEEP (a photo -- a cosplayer, a
    figure, a person -- a 3D render, a screenshot) that got in while a
    character's filter was off. Its own axis: a cosplay photo named as
    another character carries both reasons."""
    r18 = "" if include_r18 else "AND p.is_r18=0"
    rows = store.conn.execute(
        f"""SELECT m.sha256, m.phash, m.bytes, m.source, COALESCE(i.state,'pending') AS ident,
                   k.kind AS kind
            FROM post_watches pw
            JOIN posts p ON p.source=pw.source AND p.external_id=pw.external_id
            JOIN media m ON m.source=p.source AND m.external_id=p.external_id
            LEFT JOIN image_identity i ON i.sha256=m.sha256 AND i.model=?
            LEFT JOIN image_kinds k ON k.sha256=m.sha256
            WHERE pw.slug=? AND m.state='stored' AND p.state='live' {r18}
            GROUP BY m.sha256""",
        (model, slug),
    ).fetchall()
    primary = primary_character(store, slug, model)
    found: dict[str, dict[str, Any]] = {}
    for chunk in _chunks([r["sha256"] for r in rows]):
        found.update(store.identities(chunk))
    reasons: dict[str, list[dict[str, Any]]] = {}
    counts = {"score": 0, "other": 0, "dupe": 0, "unidentified": 0, "kind": 0}
    others: dict[str, int] = {}

    def add(sha: str, reason: dict[str, Any]) -> None:
        reasons.setdefault(sha, []).append(reason)
        counts[reason["kind"]] += 1

    for r in rows:
        sha = r["sha256"]
        if kinds and r["kind"] is not None and not kept(r["kind"]):
            add(sha, {"kind": "kind", "label": r["kind"]})
        ident = found.get(sha)
        if ident is None or ident.get("model") != model:
            continue  # not identified yet: nothing to judge
        chars = ident["characters"]
        mine = next((c for c in chars if c["name"] == primary), None) if primary else None
        if ident["state"] == "unidentified":
            if unidentified:
                add(sha, {"kind": "unidentified"})
            continue
        # someone else first: an image of another character is not "a low
        # score", so one reason per image on the identity axis
        top = next((c for c in chars if c["name"] != primary), None) if primary else None
        is_other = (
            other_character and top is not None and (mine is None or mine["score"] < OTHER_FLOOR)
        )
        if is_other and top is not None:
            others[top["name"]] = others.get(top["name"], 0) + 1
            add(
                sha,
                {
                    "kind": "other",
                    "name": top["name"],
                    "label": label_of(top["name"]),
                    "score": round(top["score"], 2),
                },
            )
        elif min_score is not None and mine is not None and mine["score"] < min_score:
            add(sha, {"kind": "score", "score": round(mine["score"], 2)})
    if dupes:
        hashes = [
            (r["sha256"], from_signed(r["phash"]), int(r["bytes"] or 0))
            for r in rows
            if r["phash"] is not None
        ]
        for group in _dupe_groups(hashes, distance):
            keep = group[0]
            kh = next(h for s, h, _ in hashes if s == keep)
            for sha in group[1:]:
                sh = next(h for s, h, _ in hashes if s == sha)
                add(sha, {"kind": "dupe", "distance": hamming(kh, sh), "keep": keep})
    return {
        "matches": [{"sha256": sha, "reasons": rs} for sha, rs in reasons.items()],
        "counts": counts,
        "primary": primary,
        "primary_label": label_of(primary) if primary else None,
        "characters": sorted(
            ({"name": n, "label": label_of(n), "count": c} for n, c in others.items()),
            key=lambda x: (-x["count"], x["name"]),
        ),
        "total": len(rows),
    }


def review(
    store: Store, *, min_score: float, model: str = IDENTIFIER_ID, include_r18: bool = False
) -> dict[str, Any]:
    """The Gallery page's quiet card: per character, how many images the Smart
    criteria would flag today (low score or another character)."""
    out: list[dict[str, Any]] = []
    for w in store.watches():
        got = smart_matches(
            store,
            w.slug,
            model=model,
            min_score=min_score,
            other_character=True,
            dupes=False,
            include_r18=include_r18,
        )
        if got["matches"]:
            out.append({"slug": w.slug, "label": w.label or w.slug, "count": len(got["matches"])})
    out.sort(key=lambda x: -x["count"])
    return {"min_score": min_score, "total": sum(x["count"] for x in out), "characters": out}


# ---------------------------------------------------------------- at crawl time
def crawl_verdict(
    store: Store,
    slugs: list[str],
    hits: list[Any],
    identified: bool,
    rule: dict[str, Any] | None,
    primaries: dict[str, str | None],
    model: str = IDENTIFIER_ID,
) -> str | None:
    """Settings › Duplicates' crawl-time rule over a freshly identified image:
    a reason to throw it away, or None. `primaries` caches each character's
    name for the run. An image is kept unless EVERY character it belongs to
    would reject it."""
    if not rule or not identified or not slugs:
        return None
    min_score = rule.get("min_score")
    other = bool(rule.get("other_character"))
    verdicts: list[str | None] = []
    for slug in slugs:
        if slug not in primaries:
            primaries[slug] = primary_character(store, slug, model)
        primary = primaries[slug]
        if not primary:
            verdicts.append(None)  # nothing to compare against yet: keep
            continue
        mine = next((h for h in hits if h.name == primary), None)
        if other and (mine is None or mine.score < OTHER_FLOOR):
            top = next((h for h in hits if h.name != primary), None)
            verdicts.append(f"identity:other={top.name}" if top else None)
        elif min_score is not None and mine is not None and mine.score < min_score:
            verdicts.append(f"identity:score={mine.score:.2f}")
        else:
            verdicts.append(None)
    return None if any(v is None for v in verdicts) else verdicts[0]
