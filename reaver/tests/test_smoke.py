"""Offline tests. No network: pixiv responses come from fixtures shaped like
the real ajax payloads, and the dedupe test builds its own images."""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from coreflame.blobs import BlobStore
from coreflame.db import Store
from coreflame.dedupe import classify
from coreflame.library import LibraryView, LinkMode, detect_link_mode, safe_name, under_sync_root
from coreflame.models import Watch
from coreflame.phash import dhash, from_signed, hamming, to_signed
from coreflame.sources.pixiv import PixivAdapter
from coreflame.sources.twitter import TwitterAdapter

SEARCH = {
    "error": False,
    "body": {
        "illustManga": {
            "total": 2,
            "data": [
                {
                    "illustId": "1002",
                    "illustTitle": "b",
                    "userId": "77",
                    "userName": "artist",
                    "pageCount": 2,
                    "illustType": 0,
                    "tags": ["甘雨"],
                    "width": 2000,
                    "height": 3000,
                    "url": "https://i.pximg.net/c/250x250_80_a2/img-master/img/2026/1002_square1200.jpg",
                },
                {"isAdContainer": True},
                {
                    "illustId": "1001",
                    "illustTitle": "a",
                    "userId": "77",
                    "userName": "artist",
                    "pageCount": 1,
                    "illustType": 0,
                    "tags": ["甘雨"],
                    "width": 1200,
                    "height": 1600,
                },
            ],
        }
    },
}

DETAIL = {
    "1002": {
        "error": False,
        "body": {
            "illustId": "1002",
            "illustTitle": "b",
            "description": "test",
            "createDate": "2026-08-20T10:00:00+09:00",
            "userId": "77",
            "userName": "artist",
            "pageCount": 2,
            "illustType": 0,
            "xRestrict": 0,
            "bookmarkCount": 900,
            "tags": {"tags": [{"tag": "甘雨", "translation": {"en": "Ganyu"}}]},
            "urls": {"original": "https://i.pximg.net/img-original/1002_p0.png"},
        },
    },
    "1001": {
        "error": False,
        "body": {
            "illustId": "1001",
            "illustTitle": "a",
            "description": "",
            "createDate": "2026-08-19T10:00:00+09:00",
            "userId": "77",
            "userName": "artist",
            "pageCount": 1,
            "illustType": 0,
            "xRestrict": 0,
            "bookmarkCount": 10,
            "tags": {"tags": [{"tag": "甘雨"}]},
            "urls": {"original": "https://i.pximg.net/img-original/1001_p0.jpg"},
        },
    },
}

PAGES = {
    "error": False,
    "body": [
        {
            "urls": {"original": "https://i.pximg.net/img-original/1002_p0.png"},
            "width": 2000,
            "height": 3000,
        },
        {
            "urls": {"original": "https://i.pximg.net/img-original/1002_p1.png"},
            "width": 2000,
            "height": 3000,
        },
    ],
}


def fake_pixiv() -> PixivAdapter:
    a = PixivAdapter(php_sessid="77_fake")  # authed: search requires a session

    def get_json(url, **kw):
        if "/ajax/search/artworks/" in url:
            return (
                SEARCH
                if "&p=1&" in url
                else {"error": False, "body": {"illustManga": {"total": 2, "data": []}}}
            )
        if url.endswith("/pages?lang=en"):
            return PAGES
        if "/ajax/illust/" in url:
            iid = url.split("/ajax/illust/")[1].split("?")[0]
            return DETAIL[iid]
        if "/ajax/user/" in url:
            return {"body": {"social": {"twitter": {"url": "https://twitter.com/some_artist"}}}}
        raise AssertionError(url)

    a.client.get_json = get_json  # type: ignore[assignment]
    return a


def test_pixiv_normalizes_and_paginates(tmp: Path) -> None:
    a = fake_pixiv()
    w = Watch(slug="ganyu", pixiv_tags=["甘雨"], match_terms=["ganyu", "甘雨"])
    recs = list(a.discover(w, since=None))
    assert [r.external_id for r in recs] == ["1002", "1001"]
    r = recs[0]
    assert r.source == "pixiv" and r.artist_id == "77"
    assert r.page_count == 2 and len(r.media) == 2
    assert r.media[1].url.endswith("1002_p1.png")
    assert r.media[0].referer == "https://www.pixiv.net/artworks/1002"
    assert "甘雨" in r.tag_raws and any(t.translated == "Ganyu" for t in r.tags)
    assert r.posted_at is not None and r.posted_at.year == 2026
    assert r.posted_at.utcoffset().total_seconds() == 0  # +09:00 -> timezone.utc
    assert r.source_meta["x_restrict"] == 0
    print("  pixiv normalize:      ok (2 posts, 3 media refs, tags translated, timezone.utc)")

    # watermark: nothing new below the floor
    assert list(a.discover(w, since="1002")) == []
    print("  pixiv watermark:      ok (floor 1002 yields nothing)")

    # min_bookmarks filter uses the detail payload, not the search stub
    w2 = Watch(slug="ganyu", pixiv_tags=["甘雨"], min_bookmarks=500)
    assert [r.external_id for r in a.discover(w2, None)] == ["1002"]
    print("  pixiv min_bookmarks:  ok (filters 10-bookmark post)")

    assert a.twitter_handle("77") == "some_artist"
    print("  pixiv -> X handle:    ok (some_artist)")


def test_twitter_flatten_and_match() -> None:
    tw = TwitterAdapter()
    payload = [
        ["directory", {"x": 1}],
        [
            3,
            "https://pbs.twimg.com/media/AAA.jpg",
            {
                "tweet_id": 555,
                "num": 1,
                "content": "Ganyu sketch",
                "date": "2026-08-21 03:00:00",
                "hashtags": ["原神"],
                "author": {"id": 9, "name": "Artist", "nick": "artist_x"},
                "width": 2048,
                "height": 2732,
            },
        ],
        [
            3,
            "https://pbs.twimg.com/media/BBB.jpg",
            {
                "tweet_id": 555,
                "num": 2,
                "content": "Ganyu sketch",
                "date": "2026-08-21 03:00:00",
                "author": {"id": 9, "name": "Artist", "nick": "artist_x"},
            },
        ],
    ]
    metas = TwitterAdapter._flatten(payload)
    assert len(metas) == 2 and metas[0]["_url"].endswith("AAA.jpg")
    tw._run = lambda url, limit: metas  # type: ignore[assignment]
    recs = list(tw.timeline("artist_x"))
    assert len(recs) == 1 and recs[0].page_count == 2
    assert recs[0].permalink == "https://x.com/artist_x/status/555"
    print("  x flatten/group:      ok (2 media -> 1 post)")

    w = Watch(slug="ganyu", match_terms=["ganyu", "甘雨"])
    assert tw.matches(recs[0], w) is True
    assert tw.matches(recs[0], Watch(slug="nahida", match_terms=["nahida"])) is False
    print("  x text match:         ok")

    assert list(tw.timeline("artist_x", since_id="555")) == []
    print("  x watermark:          ok")


def _img(seed: int, size=(400, 500), quality=None) -> bytes:
    import random

    rnd = random.Random(seed)
    im = Image.new("RGB", (40, 50))
    im.putdata(
        [(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(40 * 50)]
    )
    im = im.resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    if quality:
        im.save(buf, "JPEG", quality=quality)
    else:
        im.save(buf, "PNG")
    return buf.getvalue()


def test_dedupe(tmp: Path) -> None:
    store = Store(tmp / "d.db")
    blobs = BlobStore(tmp / "blobs")

    hi_res = _img(7, (1600, 2000))  # "pixiv original"
    x_copy = _img(7, (1200, 1500), quality=82)  # "X re-encode"
    other = _img(99, (1600, 2000))

    d1, d2, d3 = dhash(hi_res), dhash(x_copy), dhash(other)
    assert hamming(d1, d2) <= 6, hamming(d1, d2)
    assert hamming(d1, d3) > 12, hamming(d1, d3)
    print(f"  dhash rescale+jpeg:   ok (d={hamming(d1, d2)} same, d={hamming(d1, d3)} different)")

    assert from_signed(to_signed(d1)) == d1
    print("  phash int64 wrap:     ok")

    from coreflame.models import IllustRecord, MediaRef

    rec = IllustRecord(
        source="pixiv",
        external_id="1",
        artist_id="77",
        artist_handle="artist_x",
        media=[MediaRef(index=0, url="https://x/a.png")],
    )
    store.upsert_post(rec, "ganyu")
    import hashlib

    sha1 = hashlib.sha256(hi_res).hexdigest()
    blobs.put(hi_res, "png")
    store.mark_media(
        "pixiv", "1", 0, state="stored", sha=sha1, phash=d1, nbytes=len(hi_res), ext="png"
    )

    rec2 = IllustRecord(
        source="twitter",
        external_id="555",
        artist_id="9",
        artist_handle="artist_x",
        media=[MediaRef(index=0, url="https://pbs/b.jpg")],
    )
    store.upsert_post(rec2, "ganyu")
    sha2 = hashlib.sha256(x_copy).hexdigest()
    v = classify(store, x_copy, sha2, "artist_x")
    assert v.is_dupe and v.dupe_of == sha1, v
    print(f"  cross-source dedupe:  ok (X copy -> pixiv original, {v.reason})")

    v3 = classify(store, other, hashlib.sha256(other).hexdigest(), "artist_x")
    assert not v3.is_dupe
    print("  distinct image kept:  ok")

    assert classify(store, hi_res, sha1, "artist_x").reason == "exact"
    print("  exact sha dedupe:     ok")

    s = store.stats()
    assert s["posts"] == 2 and s["media_stored"] == 1
    print(f"  store stats:          ok {s['posts']} posts / {s['media_stored']} stored")


def test_library_view(tmp: Path) -> None:
    root = tmp / "lib"
    mode = detect_link_mode(root)
    assert mode in (LinkMode.HARD, LinkMode.SYMLINK, LinkMode.COPY)
    print(f"  link mode probe:      ok ({mode.value})")

    blobs = BlobStore(root / "blobs")
    data = _img(3, (200, 200))
    _, path, _ = blobs.put(data, "png")

    view = LibraryView(root, mode)
    name = safe_name("artist", "1234567", "p0", ext="png")
    dest = view.place(path, "ganyu", name)
    assert dest is not None and dest.exists()
    assert dest.read_bytes() == data
    print(f"  by-character place:   ok ({dest.relative_to(root)})")

    if mode is LinkMode.HARD:
        assert dest.stat().st_ino == path.stat().st_ino
        assert dest.stat().st_nlink == 2
        print("  same inode, 2 links:  ok (zero extra bytes)")

    assert view.place(path, "ganyu", name) == dest  # idempotent
    print("  reindex idempotent:   ok")

    assert safe_name("a/b", "c:d", ext="jpg") == "a-b_c-d.jpg"
    assert under_sync_root(Path("/Users/x/Dropbox/art")) == "dropbox"
    assert under_sync_root(root) is None
    print("  name + sync guards:   ok")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("pixiv adapter")
        test_pixiv_normalizes_and_paginates(tmp)
        print("twitter adapter")
        test_twitter_flatten_and_match()
        print("dedupe + store")
        test_dedupe(tmp)
        print("library view")
        test_library_view(tmp)
    print("\nall passed")
