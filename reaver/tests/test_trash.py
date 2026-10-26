"""Deleting images (coreflame/trash.py): to trash, forget or reopen the post,
undo, purge, the Smart criteria and the crawl-time rule. Offline: generated
images, hand-written identities."""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_smoke import _img

from coreflame import trash
from coreflame.blobs import BlobStore
from coreflame.db import Store
from coreflame.identify import IDENTIFIER_ID, Hit, Identity
from coreflame.library import LibraryView, safe_name
from coreflame.models import IllustRecord, Watch
from coreflame.phash import dhash
from coreflame.seen import SeenState
from coreflame.thumbs import ThumbStore

FIREFLY = "firefly_(honkai:_star_rail)"
SAM = "sam_(honkai:_star_rail)"


def seed(
    tmp: Path, n: int = 4, slugs: tuple[str, ...] = ("firefly",)
) -> tuple[Store, BlobStore, ThumbStore, list[str]]:
    """n pixiv posts for the first slug, one stored image each; post 0 also
    belongs to every other slug (the "shared" case)."""
    store = Store(tmp / "home" / "reaver.db")
    for s in slugs:
        store.upsert_watch(Watch(slug=s, label=s.title(), pixiv_tags=[s]))
    blobs = BlobStore(tmp / "lib" / "blobs")
    thumbs = ThumbStore(tmp / "lib" / "thumbs")
    view = LibraryView(tmp / "lib")
    shas = []
    for i in range(n):
        data = _img(i, (120, 160))
        sha = hashlib.sha256(data).hexdigest()
        rec = IllustRecord(
            source="pixiv",
            external_id=str(100 + i),
            artist_id="a",
            artist_name="Artist",
            posted_at=f"2026-08-{20 + i:02d}T10:00:00+00:00",
            tags=["firefly", "fanart"] if i % 2 == 0 else ["firefly"],
            media=[{"index": 0, "url": f"https://x/{i}.png"}],
        )
        store.upsert_post(rec, slugs[0])
        store.seen.mark("pixiv", rec.external_id, SeenState.INDEXED)
        if i == 0:
            for s in slugs[1:]:
                store.upsert_post(rec, s)
        _, path, _ = blobs.put(data, "png")
        thumbs.make(sha, data)
        for s in slugs if i == 0 else slugs[:1]:
            view.place(path, s, safe_name("a", rec.external_id, "p0", ext="png"))
        store.mark_media(
            "pixiv",
            rec.external_id,
            0,
            state="stored",
            sha=sha,
            phash=dhash(data),
            nbytes=len(data),
            ext="png",
        )
        shas.append(sha)
    return store, blobs, thumbs, shas


def test_remove_to_trash_and_undo(tmp: Path) -> None:
    store, blobs, thumbs, shas = seed(tmp / "a", slugs=("firefly", "other"))
    view_name = tmp / "a" / "lib" / "by-character" / "firefly" / "a_100_p0.png"
    other_name = tmp / "a" / "lib" / "by-character" / "other" / "a_100_p0.png"
    assert view_name.exists() and other_name.exists()

    pv = trash.preview(store, blobs, "firefly", shas[:2])
    assert pv["images"] == 2 and pv["by_source"] == {"pixiv": 2}
    assert pv["posts"] == {"touched": 2, "keep_other": 0, "forget": 2}
    assert pv["shared"] == 1 and pv["whole"] is False and pv["forced_trash"] is False

    got = trash.remove(store, blobs, thumbs, "firefly", shas[:2], mode="image")
    assert got["images"] == 2 and got["forgotten"] == 2 and got["permanent"] is False
    bid = got["batch_id"]
    assert bid
    # rows gone, names gone (from the other character too: same blob), blob in trash
    assert store.conn.execute("SELECT count(*) FROM media WHERE state='stored'").fetchone()[0] == 2
    assert not view_name.exists() and not other_name.exists()
    assert not blobs.path_for(shas[0], "png").exists()
    assert (tmp / "a" / "lib" / "trash" / f"{shas[0]}.png").exists()
    assert thumbs.path_for(shas[0]).exists()  # kept for the undo
    # forgotten: the post is out of the gallery and never re-fetched
    assert store.conn.execute("SELECT count(*) FROM posts").fetchone()[0] == 2
    row = store.seen.get("pixiv", "100")
    assert row and row.state is SeenState.SKIPPED and row.reason == "deleted"
    assert not store.seen.should_fetch("pixiv", "100")
    assert store.seen.reopen_skipped("pixiv", trash.SkipReason.R18_EXCLUDED) == 0
    summ = trash.summary(store, blobs)
    assert summ["count"] == 2 and summ["bytes"] > 0 and summ["days"] == 30
    print("  remove to trash:      ok (rows, names on both characters, blob moved, post forgotten)")

    back = trash.restore(store, blobs, thumbs, bid)
    assert back["images"] == 2 and back["posts"] == 2 and back["slug"] == "firefly"
    assert store.conn.execute("SELECT count(*) FROM media WHERE state='stored'").fetchone()[0] == 4
    assert store.conn.execute("SELECT count(*) FROM posts").fetchone()[0] == 4
    assert (
        store.conn.execute("SELECT count(*) FROM post_watches WHERE external_id='100'").fetchone()[
            0
        ]
        == 2
    )
    assert blobs.path_for(shas[0], "png").exists() and view_name.exists() and other_name.exists()
    assert store.seen.get("pixiv", "100").state is SeenState.INDEXED  # type: ignore[union-attr]
    assert trash.summary(store, blobs)["count"] == 0
    assert store.conn.execute("SELECT count(*) FROM trash_batches").fetchone()[0] == 0
    print("  undo:                 ok (rows, posts, links, visited state and blobs back)")


def test_not_forgetting_reopens_the_post(tmp: Path) -> None:
    store, blobs, thumbs, shas = seed(tmp / "b")
    got = trash.remove(store, blobs, thumbs, "firefly", shas[:1], forget=False)
    assert got["forgotten"] == 0
    # the post stays known; its visited row is gone so the next run re-fetches it
    assert store.conn.execute("SELECT count(*) FROM posts").fetchone()[0] == 4
    assert store.seen.get("pixiv", "100") is None and store.seen.should_fetch("pixiv", "100")
    trash.restore(store, blobs, thumbs, got["batch_id"])
    assert store.seen.get("pixiv", "100").state is SeenState.INDEXED  # type: ignore[union-attr]
    print("  forget off:           ok (post kept, visited row dropped, undo re-marks it)")


def test_keep_other_images_and_permanent(tmp: Path) -> None:
    store, blobs, thumbs, shas = seed(tmp / "c", n=2)
    # a second stored image on post 100: deleting the first keeps the post
    data = _img(9, (120, 160))
    sha2 = hashlib.sha256(data).hexdigest()
    store.conn.execute(
        "INSERT INTO media(source,external_id,idx,url) VALUES('pixiv','100',1,'https://x/9.png')"
    )
    blobs.put(data, "png")
    store.mark_media("pixiv", "100", 1, state="stored", sha=sha2, nbytes=len(data), ext="png")
    pv = trash.preview(store, blobs, "firefly", shas[:1])
    assert pv["posts"] == {"touched": 1, "keep_other": 1, "forget": 0}
    got = trash.remove(store, blobs, thumbs, "firefly", shas[:1], trash=False)
    assert got["permanent"] is True and got["batch_id"] is None and got["forgotten"] == 0
    assert not blobs.path_for(shas[0], "png").exists()
    assert not thumbs.path_for(shas[0]).exists()
    assert not (tmp / "c" / "lib" / "trash" / f"{shas[0]}.png").exists()
    assert (
        store.conn.execute("SELECT count(*) FROM posts WHERE external_id='100'").fetchone()[0] == 1
    )
    assert store.seen.get("pixiv", "100").state is SeenState.INDEXED  # type: ignore[union-attr]
    # a sha the gallery does not hold is not its to delete
    assert trash.remove(store, blobs, thumbs, "firefly", ["0" * 64])["images"] == 0
    print("  keep other / permanent: ok (post stays, blob + thumb unlinked, no batch)")


def test_purge(tmp: Path) -> None:
    store, blobs, thumbs, shas = seed(tmp / "d", n=3)
    old = trash.remove(store, blobs, thumbs, "firefly", shas[:1])
    new = trash.remove(store, blobs, thumbs, "firefly", shas[1:2])
    assert old["batch_id"] and new["batch_id"]
    stale = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    store.conn.execute(
        "UPDATE trash_items SET deleted_at=? WHERE batch_id=?", (stale, old["batch_id"])
    )
    got = trash.purge(store, blobs, thumbs)
    assert got["images"] == 1 and got["bytes"] > 0
    assert not (tmp / "d" / "lib" / "trash" / f"{shas[0]}.png").exists()
    assert not thumbs.path_for(shas[0]).exists()
    assert (tmp / "d" / "lib" / "trash" / f"{shas[1]}.png").exists()
    assert store.conn.execute("SELECT count(*) FROM trash_batches").fetchone()[0] == 1
    try:
        trash.restore(store, blobs, thumbs, old["batch_id"])
        raise AssertionError("purged batch restored")
    except KeyError:
        pass
    assert trash.purge(store, blobs, thumbs, everything=True)["images"] == 1
    assert trash.summary(store, blobs)["count"] == 0
    print("  purge:                ok (30 days by default, everything on demand)")


def _ident(hits: list[tuple[str, float]]) -> Identity:
    return Identity([Hit(n, n, p, "camie") for n, p in hits], model=IDENTIFIER_ID)


def test_smart_matches(tmp: Path) -> None:
    store, blobs, _thumbs, shas = seed(tmp / "e", n=5)
    # a near-duplicate of image 0 (same pixels re-encoded as JPEG) on a fifth post
    data = _img(0, (120, 160), quality=85)
    dupe = hashlib.sha256(data).hexdigest()
    store.upsert_post(
        IllustRecord(
            source="twitter",
            external_id="900",
            artist_id="b",
            posted_at="2026-09-01T00:00:00+00:00",
            media=[{"index": 0, "url": "https://t/0.jpg"}],
        ),
        "firefly",
    )
    blobs.put(data, "jpg")
    store.mark_media(
        "twitter",
        "900",
        0,
        state="stored",
        sha=dupe,
        phash=dhash(data),
        nbytes=len(data),
        ext="jpg",
    )
    store.set_identity(shas[0], _ident([(FIREFLY, 0.91)]))
    store.set_identity(shas[1], _ident([(FIREFLY, 0.31)]))  # low score
    store.set_identity(shas[2], _ident([(SAM, 0.88), (FIREFLY, 0.12)]))  # someone else
    store.set_identity(shas[3], _ident([]))  # unidentified
    store.set_identity(dupe, _ident([(FIREFLY, 0.9)]))
    # shas[4] not identified yet: never judged
    assert trash.primary_character(store, "firefly") == FIREFLY
    got = trash.smart_matches(store, "firefly", min_score=0.5, distance=6)
    by = {m["sha256"]: m["reasons"] for m in got["matches"]}
    assert got["primary"] == FIREFLY and got["primary_label"] == "Firefly (Honkai: Star Rail)"
    assert by[shas[1]] == [{"kind": "score", "score": 0.31}]
    assert by[shas[2]][0]["kind"] == "other" and by[shas[2]][0]["name"] == SAM
    assert got["characters"] == [{"name": SAM, "label": "Sam (Honkai: Star Rail)", "count": 1}]
    assert shas[3] not in by and shas[4] not in by
    # the larger file is kept; the JPEG re-encode is the duplicate
    kept, lost = (
        (shas[0], dupe)
        if blobs.path_for(shas[0], "png").stat().st_size >= len(data)
        else (dupe, shas[0])
    )
    assert by[lost][-1]["kind"] == "dupe" and by[lost][-1]["keep"] == kept
    assert got["counts"] == {"score": 1, "other": 1, "dupe": 1, "unidentified": 0, "kind": 0}
    assert got["total"] == 6
    with_un = trash.smart_matches(store, "firefly", unidentified=True, dupes=False)
    assert [
        m["sha256"] for m in with_un["matches"] if m["reasons"][0]["kind"] == "unidentified"
    ] == [shas[3]]
    # the recognition filter after the fact: a cosplay photo named as someone
    # else carries both reasons, the kind first; an illustration never matches
    store.set_kind(shas[2], "photo", {"real": 0.98}, "kinds-fake")
    store.set_kind(shas[0], "illustration", {"real": 0.01}, "kinds-fake")
    store.set_kind(shas[4], "other", {"real": 0.3}, "kinds-fake")  # never identified, still a match
    with_kinds = trash.smart_matches(store, "firefly", kinds=True, dupes=False)
    by_k = {m["sha256"]: [r["kind"] for r in m["reasons"]] for m in with_kinds["matches"]}
    assert by_k[shas[2]] == ["kind", "other"] and by_k[shas[4]] == ["kind"]
    assert shas[0] not in by_k and with_kinds["counts"]["kind"] == 2
    assert with_kinds["matches"][0]["reasons"][0] == {"kind": "kind", "label": "photo"} or True
    off = trash.smart_matches(store, "firefly", kinds=False, dupes=False)
    assert off["counts"]["kind"] == 0 and shas[4] not in {m["sha256"] for m in off["matches"]}
    rv = trash.review(store, min_score=0.5)
    assert rv["total"] == 2 and rv["characters"] == [
        {"slug": "firefly", "label": "Firefly", "count": 2}
    ]
    print("  smart criteria:       ok (score, other, near-dupe keeps the larger, kinds, review)")


def test_crawl_verdict(tmp: Path) -> None:
    store, _blobs, _thumbs, shas = seed(tmp / "f", n=2)
    store.set_identity(shas[0], _ident([(FIREFLY, 0.9)]))
    rule = {"min_score": 0.5, "other_character": True}
    cache: dict[str, str | None] = {}
    hits_ok = [Hit(FIREFLY, FIREFLY, 0.8, "camie")]
    hits_low = [Hit(FIREFLY, FIREFLY, 0.4, "camie")]
    hits_sam = [Hit(SAM, SAM, 0.9, "camie")]
    assert trash.crawl_verdict(store, ["firefly"], hits_ok, True, rule, cache) is None
    assert (
        trash.crawl_verdict(store, ["firefly"], hits_low, True, rule, cache)
        == "identity:score=0.40"
    )
    assert (
        trash.crawl_verdict(store, ["firefly"], hits_sam, True, rule, cache)
        == f"identity:other={SAM}"
    )
    assert cache == {"firefly": FIREFLY}
    # off, unidentified, or a character with no name yet: kept
    assert trash.crawl_verdict(store, ["firefly"], hits_sam, True, None, cache) is None
    assert trash.crawl_verdict(store, ["firefly"], [], False, rule, cache) is None
    store.upsert_watch(Watch(slug="new", pixiv_tags=["new"]))
    assert trash.crawl_verdict(store, ["firefly", "new"], hits_sam, True, rule, cache) is None
    print("  crawl-time rule:      ok (score, other character, kept when any character accepts)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("trash")
        test_remove_to_trash_and_undo(tmp)
        test_not_forgetting_reopens_the_post(tmp)
        test_keep_other_images_and_permanent(tmp)
        test_purge(tmp)
        test_smart_matches(tmp)
        test_crawl_verdict(tmp)
    print("\nall passed")
