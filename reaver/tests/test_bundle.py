"""Export / import bundles (coreflame/bundle.py): both codecs round-trip,
inspect names the conflicts, the merge rules, restore, and what happens to a
truncated or bit-flipped file. Offline: generated images, hand-written rows."""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_smoke import _img

from coreflame import bundle
from coreflame.blobs import BlobStore
from coreflame.config import Config
from coreflame.db import Store
from coreflame.models import IllustRecord, Watch
from coreflame.phash import dhash
from coreflame.seen import SeenState, SkipReason
from coreflame.thumbs import ThumbStore

Seed = tuple[Store, BlobStore, ThumbStore, Config, list[str]]


def seed(tmp: Path, n: int = 3, slug: str = "firefly", first_id: int = 100) -> Seed:
    """One character, n pixiv posts with one stored image each (thumbs made),
    plus a skipped, a gone and a failed visited row."""
    cfg = Config(home=tmp / "home", blob_root=tmp / "lib" / "blobs")
    store = Store(cfg.db_path)
    store.upsert_watch(Watch(slug=slug, label=slug.title(), pixiv_tags=[slug, f"{slug}(hsr)"]))
    blobs = BlobStore(cfg.blob_root)
    thumbs = ThumbStore(tmp / "lib" / "thumbs")
    shas = []
    for i in range(n):
        data = _img(first_id + i, (120, 160))
        sha = hashlib.sha256(data).hexdigest()
        eid = str(first_id + i)
        rec = IllustRecord(
            source="pixiv",
            external_id=eid,
            artist_id="a",
            artist_name="Artist",
            posted_at=f"2026-08-{10 + i:02d}T10:00:00+00:00",
            tags=[slug, "fanart"],
            media=[{"index": 0, "url": f"https://x/{eid}.png"}],
        )
        store.upsert_post(rec, slug)
        store.seen.mark("pixiv", eid, SeenState.INDEXED)
        blobs.put(data, "png")
        thumbs.make(sha, data)
        store.mark_media(
            "pixiv", eid, 0, state="stored", sha=sha, phash=dhash(data), nbytes=len(data), ext="png"
        )
        shas.append(sha)
    store.seen.mark(
        "pixiv", "900", SeenState.SKIPPED, reason=SkipReason.BELOW_MIN_BOOKMARKS, threshold=500
    )
    store.seen.mark("pixiv", "901", SeenState.GONE)
    store.seen.mark_failed("pixiv", "902", "500")
    store.set_watermark("pixiv", f"tag:{slug}", "123")
    return store, blobs, thumbs, cfg, shas


def _stored(store: Store) -> int:
    return int(store.conn.execute("SELECT count(*) FROM media WHERE state='stored'").fetchone()[0])


def test_round_trip(tmp: Path) -> None:
    for fmt in ("curio", "zip"):
        base = tmp / fmt
        store, blobs, thumbs, cfg, shas = seed(base / "a")
        cfg.dupe_threshold = 9
        ui = {"curio.theme.v3": {"preset": "bloodline"}}
        out = base / f"archive.{fmt}"
        stages: list[str] = []
        totals: dict[str, int] = {}

        def note(
            stage: str,
            _done: int,
            _total: int | None,
            into: list[str] = stages,
            tot: dict[str, int] = totals,
            **extra: int,
        ) -> None:
            into.append(stage)
            tot.update(extra)

        got = bundle.export(
            store, blobs, thumbs, cfg, out, bundle.ExportOptions(fmt=fmt, ui=ui), progress=note
        )
        assert out.exists() and not out.with_name(out.name + ".part").exists()
        assert got["images"] == 3 and got["thumbs"] == 3 and got["characters"] == 1
        assert stages[0] == "snapshot" and stages[-1] == "verify"
        assert totals == {"posts": 3, "images": 3, "thumbs": 3, "entries": 10}

        rep = bundle.verify(out)
        assert rep["ok"] and rep["damaged"] == [] and rep["entries"] == 4 + 6
        if fmt == "curio":
            assert rep["trailer_ok"] and rep["file_hash_ok"]
        # no cookie unless asked; never the machine's paths
        r = bundle.open_reader(out)
        names = r.names()
        assert bundle.SECRETS not in names
        cfg_in = json.loads(r.read(bundle.CONFIG))
        assert cfg_in["dupe_threshold"] == 9 and "db_path" not in cfg_in and "home" not in cfg_in
        assert json.loads(r.read(bundle.UI)) == ui
        r.close()

        # into an empty archive
        cfg2 = Config(home=base / "b" / "home", blob_root=base / "b" / "lib" / "blobs")
        s2 = Store(cfg2.db_path)
        b2, t2 = BlobStore(cfg2.blob_root), ThumbStore(base / "b" / "lib" / "thumbs")
        info = bundle.inspect(out, s2)
        assert info["format"] == fmt and info["counts"]["posts"] == 3
        assert info["has"] == {"images": True, "thumbs": True, "secrets": False, "ui": True}
        assert [c["slug"] for c in info["characters"]] == ["firefly"]
        assert info["characters"][0]["new"] and info["characters"][0]["posts"] == 3
        assert info["conflicts"] == []

        res = bundle.import_(s2, b2, t2, cfg2, out, bundle.ImportOptions(settings="take"))
        assert res["characters"] == 1 and res["posts"] == 3 and res["placed"] == 3
        assert res["refetch"] == 0 and res["dupes"] == 0 and res["damaged"] == []
        assert res["ui"] == ui
        assert _stored(s2) == 3
        for sha in shas:
            assert b2.path_for(sha, "png").exists() and t2.path_for(sha).exists()
        assert [w.slug for w in s2.watches()] == ["firefly"]
        assert s2.watches()[0].pixiv_tags == ["firefly", "firefly(hsr)"]
        # settings taken: config.json written with their threshold
        assert cfg2.dupe_threshold == 9
        assert json.loads((cfg2.home / "config.json").read_text())["dupe_threshold"] == 9
        # the visited gate: indexed (with posts), skipped and gone came; failed did not
        assert s2.seen.get("pixiv", "100").state == SeenState.INDEXED
        assert s2.seen.get("pixiv", "900").state == SeenState.SKIPPED
        assert s2.seen.get("pixiv", "901").state == SeenState.GONE
        assert s2.seen.get("pixiv", "902") is None
        assert s2.watermark("pixiv", "tag:firefly") == "123"
        # this machine's runtime state never travelled
        assert s2.conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
        # nothing staged is left behind
        assert not (cfg2.home / "import").exists() or not any((cfg2.home / "import").iterdir())
        print(f"  round trip {fmt:<6}      ok")


def test_merge_policies(tmp: Path) -> None:
    store, blobs, thumbs, cfg, _ = seed(tmp / "a")
    out = tmp / "a.curio"
    bundle.export(store, blobs, thumbs, cfg, out)

    # ours: same slug, different config; plus a character they call by another slug
    cfg2 = Config(home=tmp / "b" / "home", blob_root=tmp / "b" / "lib" / "blobs")
    s2 = Store(cfg2.db_path)
    s2.upsert_watch(
        Watch(
            slug="firefly",
            label="Firefly",
            pixiv_tags=["firefly", "ホタル"],
            min_bookmarks=300,
            gender="female",
            target=50,
        )
    )
    s2.upsert_watch(Watch(slug="sam", pixiv_tags=["sam"]))
    info = bundle.inspect(out, s2)
    assert [c["slug"] for c in info["conflicts"]] == ["firefly"]
    c = info["conflicts"][0]
    assert c["kind"] == "same_slug" and c["mine"]["min_bookmarks"] == 300
    assert c["theirs"]["min_bookmarks"] == 0

    b2, t2 = BlobStore(cfg2.blob_root), ThumbStore(tmp / "b" / "lib" / "thumbs")
    # keep: ours untouched
    bundle.import_(s2, b2, t2, cfg2, out, bundle.ImportOptions(characters={"firefly": "keep"}))
    w = next(x for x in s2.watches() if x.slug == "firefly")
    assert w.min_bookmarks == 300 and w.pixiv_tags == ["firefly", "ホタル"]
    assert _stored(s2) == 3  # posts still came, under the kept config
    # merge (the default): union of tags, the looser gate, the larger target
    bundle.import_(s2, b2, t2, cfg2, out)
    w = next(x for x in s2.watches() if x.slug == "firefly")
    assert w.pixiv_tags == ["firefly", "ホタル", "firefly(hsr)"]
    assert w.min_bookmarks == 0 and w.gender == "any" and w.target == 100
    assert _stored(s2) == 3  # importing twice is idempotent
    # take: theirs wholesale
    bundle.import_(s2, b2, t2, cfg2, out, bundle.ImportOptions(characters={"firefly": "take"}))
    w = next(x for x in s2.watches() if x.slug == "firefly")
    assert w.pixiv_tags == ["firefly", "firefly(hsr)"] and w.label == "Firefly"
    assert [x.slug for x in s2.watches()] == ["firefly", "sam"]

    # same character, another slug: reported with the suggestion, never auto-merged
    s3 = Store(tmp / "c" / "reaver.db")
    s3.upsert_watch(Watch(slug="hotaru", pixiv_tags=["firefly(hsr)"]))
    info = bundle.inspect(out, s3)
    assert info["conflicts"][0]["kind"] == "same_tags"
    assert info["conflicts"][0]["suggest"] == "hotaru"
    print("  merge policies          ok")


def test_merge_rules(tmp: Path) -> None:
    """Posts: newer fetched_at wins. Skipped: the lower threshold. Indexed
    without its post: dropped. Media: ours wins, a new image is near-dupe
    checked against the artist's images on disk."""
    store, blobs, thumbs, cfg, shas = seed(tmp / "a")
    # an indexed row with no post (a forgotten one) and a lower skip threshold
    store.seen.mark("pixiv", "777", SeenState.INDEXED)
    store.seen.mark(
        "pixiv", "900", SeenState.SKIPPED, reason=SkipReason.BELOW_MIN_BOOKMARKS, threshold=100
    )
    store.conn.execute("UPDATE posts SET title='theirs', fetched_at='2030-01-01T00:00:00+00:00'")
    out = tmp / "a.curio"
    bundle.export(store, blobs, thumbs, cfg, out)

    s2, b2, t2, cfg2, _ = seed(tmp / "b", n=2)
    s2.conn.execute("UPDATE posts SET title='mine'")
    # a near-duplicate of their third image, already ours, by the same artist
    third = _img(102, (120, 160))
    near = _img(102, (120, 160), quality=40)  # same picture, JPEG: dHash within 6
    sha_near = hashlib.sha256(near).hexdigest()
    rec = IllustRecord(
        source="twitter",
        external_id="555",
        artist_id="a",
        artist_name="Artist",
        posted_at="2026-08-20T10:00:00+00:00",
        media=[{"index": 0, "url": "https://x/555.jpg"}],
    )
    s2.upsert_post(rec, "firefly")
    b2.put(near, "jpg")
    s2.mark_media(
        "twitter", "555", 0, state="stored", sha=sha_near, phash=dhash(near), nbytes=1, ext="jpg"
    )
    assert hashlib.sha256(third).hexdigest() == shas[2]

    res = bundle.import_(s2, b2, t2, cfg2, out)
    titles = {r[0] for r in s2.conn.execute("SELECT title FROM posts WHERE source='pixiv'")}
    assert titles == {"theirs"}  # newer fetched_at
    assert s2.seen.get("pixiv", "777") is None
    assert s2.seen.get("pixiv", "900").threshold == 100
    assert res["dupes"] == 1 and res["placed"] == 0
    row = s2.conn.execute("SELECT state, dupe_of FROM media WHERE external_id='102'").fetchone()
    assert row["state"] == "dupe" and row["dupe_of"] == sha_near
    assert not b2.path_for(shas[2], "png").exists()
    print("  merge rules             ok")


def test_restore(tmp: Path) -> None:
    store, blobs, thumbs, cfg, shas = seed(tmp / "a")
    out = tmp / "a.zip"
    bundle.export(store, blobs, thumbs, cfg, out, bundle.ExportOptions(fmt="zip"))
    s2, b2, t2, cfg2, shas2 = seed(tmp / "b", n=2, slug="sam", first_id=200)
    res = bundle.import_(s2, b2, t2, cfg2, out, bundle.ImportOptions(mode="restore"))
    assert res["mode"] == "restore" and res["characters"] == 1
    assert [w.slug for w in s2.watches()] == ["firefly"]
    assert _stored(s2) == 3 and all(b2.path_for(s, "png").exists() for s in shas)
    # the bytes of what was replaced stay on disk (gc territory), the rows do not
    assert b2.path_for(shas2[0], "png").exists()
    assert s2.conn.execute("SELECT count(*) FROM posts WHERE artist_id='a'").fetchone()[0] == 3
    print("  restore                 ok")


def test_without_images(tmp: Path) -> None:
    store, blobs, thumbs, cfg, _ = seed(tmp / "a")
    out = tmp / "a.curio"
    got = bundle.export(store, blobs, thumbs, cfg, out, bundle.ExportOptions(images=False))
    assert got["images"] == 0 and got["bytes"] < 200_000
    cfg2 = Config(home=tmp / "b" / "home", blob_root=tmp / "b" / "lib" / "blobs")
    s2 = Store(cfg2.db_path)
    info = bundle.inspect(out, s2)
    assert info["has"]["images"] is False
    res = bundle.import_(s2, BlobStore(cfg2.blob_root), ThumbStore(tmp / "b" / "t"), cfg2, out)
    # every image goes back to pending with its url: the next crawl re-downloads
    assert res["refetch"] == 3 and _stored(s2) == 0
    pend = s2.conn.execute("SELECT url FROM media WHERE state='pending' ORDER BY url").fetchall()
    assert [r[0] for r in pend] == ["https://x/100.png", "https://x/101.png", "https://x/102.png"]
    print("  without images          ok")


def test_secrets_opt_in(tmp: Path) -> None:
    store, blobs, thumbs, cfg, _ = seed(tmp / "a")
    cfg.pixiv_php_sessid = "12345_abc"
    out = tmp / "a.curio"
    bundle.export(store, blobs, thumbs, cfg, out, bundle.ExportOptions(images=False))
    assert bundle.SECRETS not in bundle.open_reader(out).names()
    assert b"12345_abc" not in out.read_bytes()
    bundle.export(store, blobs, thumbs, cfg, out, bundle.ExportOptions(images=False, secrets=True))
    cfg2 = Config(home=tmp / "b" / "home", blob_root=tmp / "b" / "lib" / "blobs")
    s2 = Store(cfg2.db_path)
    assert bundle.inspect(out, s2)["has"]["secrets"] is True
    b2, t2 = BlobStore(cfg2.blob_root), ThumbStore(tmp / "b" / "t")
    bundle.import_(s2, b2, t2, cfg2, out)  # not asked: the cookie stays in the file
    assert cfg2.pixiv_php_sessid is None and not (cfg2.home / "secrets.json").exists()
    bundle.import_(s2, b2, t2, cfg2, out, bundle.ImportOptions(secrets=True))
    assert cfg2.pixiv_php_sessid == "12345_abc"
    assert json.loads((cfg2.home / "secrets.json").read_text()) == {"pixiv_php_sessid": "12345_abc"}
    cfg2.save()
    assert "pixiv_php_sessid" not in (cfg2.home / "config.json").read_text()
    print("  secrets opt-in          ok")


def _entry_offset(path: Path, name: str) -> tuple[int, int]:
    r = bundle.CurioReader(path)
    e = next(x for x in r.entries() if x.name == name)
    r.close()
    return e.offset, e.size


def test_damage_is_named_and_salvaged(tmp: Path) -> None:
    store, blobs, thumbs, cfg, shas = seed(tmp / "a")
    out = tmp / "a.curio"
    bundle.export(store, blobs, thumbs, cfg, out)
    raw = bytearray(out.read_bytes())

    # one flipped byte inside the second image: that entry, and only that one
    name = f"blobs/{shas[1]}.png"
    off, _ = _entry_offset(out, name)
    hurt = tmp / "hurt.curio"
    body = bytearray(raw)
    body[off + 80] ^= 0xFF
    hurt.write_bytes(body)
    rep = bundle.verify(hurt)
    assert rep["ok"] is False and rep["damaged"] == [name]
    assert rep["trailer_ok"] is True and rep["file_hash_ok"] is False
    cfg2 = Config(home=tmp / "b" / "home", blob_root=tmp / "b" / "lib" / "blobs")
    s2 = Store(cfg2.db_path)
    b2, t2 = BlobStore(cfg2.blob_root), ThumbStore(tmp / "b" / "t")
    try:
        bundle.import_(s2, b2, t2, cfg2, hurt)
        raise AssertionError("damaged bundle imported without salvage")
    except bundle.BundleError as e:
        assert e.code == "damaged"
    assert s2.conn.execute("SELECT count(*) FROM posts").fetchone()[0] == 0  # nothing landed
    res = bundle.import_(s2, b2, t2, cfg2, hurt, bundle.ImportOptions(salvage=True))
    assert res["damaged"] == [name] and res["placed"] == 2 and res["refetch"] == 1
    assert (
        s2.conn.execute("SELECT state FROM media WHERE external_id='101'").fetchone()[0]
        == "pending"
    )
    assert s2.conn.execute("SELECT count(*) FROM posts").fetchone()[0] == 3

    # truncated mid-way (a copy that stopped): no trailer, the scan still
    # yields every complete entry and names the cut one
    cut = tmp / "cut.curio"
    cut.write_bytes(raw[: off + 200])
    rep = bundle.verify(cut)
    assert rep["trailer_ok"] is False and rep["ok"] is False
    assert rep["damaged"] == [name] and rep["entries"] == 1 + 3 + 1 + 1
    r = bundle.open_reader(cut)
    assert bundle.read_manifest(r).counts["posts"] == 3
    assert r.copy(f"blobs/{shas[0]}.png", bundle._Devnull())
    r.close()
    s3 = Store(tmp / "c" / "reaver.db")
    res = bundle.import_(
        s3,
        BlobStore(tmp / "c" / "blobs"),
        ThumbStore(tmp / "c" / "t"),
        Config(home=tmp / "c"),
        cut,
        bundle.ImportOptions(salvage=True),
    )
    assert res["placed"] == 1 and res["refetch"] == 2

    # a damaged trailer alone: the entries are all intact, the import works as is
    bad_tail = tmp / "tail.curio"
    bad_tail.write_bytes(raw[:-3] + b"xyz")
    rep = bundle.verify(bad_tail)
    assert rep["trailer_ok"] is False and rep["damaged"] == [] and rep["entries"] == 10
    s4 = Store(tmp / "d" / "reaver.db")
    res = bundle.import_(
        s4,
        BlobStore(tmp / "d" / "blobs"),
        ThumbStore(tmp / "d" / "t"),
        Config(home=tmp / "d"),
        bad_tail,
    )
    assert res["placed"] == 3 and res["damaged"] == []

    # the database entry hurt: refused outright, even with salvage
    off, _ = _entry_offset(out, bundle.DB)
    body = bytearray(raw)
    body[off + 60] ^= 0xFF
    (tmp / "db.curio").write_bytes(body)
    try:
        bundle.import_(
            s4,
            BlobStore(tmp / "d" / "blobs"),
            ThumbStore(tmp / "d" / "t"),
            Config(home=tmp / "d"),
            tmp / "db.curio",
            bundle.ImportOptions(salvage=True),
        )
        raise AssertionError("hurt database imported")
    except bundle.BundleError as e:
        assert e.code == "damaged"

    # a zip with a flipped byte: the same answer by name
    zout = tmp / "a.zip"
    bundle.export(store, blobs, thumbs, cfg, zout, bundle.ExportOptions(fmt="zip"))
    zraw = bytearray(zout.read_bytes())
    i = zraw.find(bytes.fromhex(shas[2])[:0] + shas[2].encode())  # the local header name
    zraw[i + len(shas[2]) + 4 + 300] ^= 0xFF
    (tmp / "hurt.zip").write_bytes(zraw)
    rep = bundle.verify(tmp / "hurt.zip")
    assert rep["ok"] is False and rep["damaged"] == [f"blobs/{shas[2]}.png"]
    print("  damage named + salvage  ok")


def test_not_ours(tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "x.curio").write_bytes(b"hello world, not a bundle at all")
    for p in (tmp / "x.curio", tmp / "missing.curio"):
        try:
            bundle.open_reader(p)
            raise AssertionError("opened")
        except bundle.BundleError as e:
            assert e.code in ("not_a_bundle", "no_file")
    # a newer format: refused with the code the UI switches on
    newer = bundle.MAGIC + struct.pack("<HHI", 2, 0, 0) + b"\0" * 64
    (tmp / "new.curio").write_bytes(newer)
    try:
        bundle.open_reader(tmp / "new.curio")
        raise AssertionError("opened")
    except bundle.BundleError as e:
        assert e.code == "bundle_too_new"
    # a zip that is not ours
    import zipfile

    with zipfile.ZipFile(tmp / "z.zip", "w") as z:
        z.writestr("a.txt", "x")
    try:
        bundle.open_reader(tmp / "z.zip")
        raise AssertionError("opened")
    except bundle.BundleError as e:
        assert e.code == "not_a_bundle"
    print("  not ours                ok")


def test_export_cancel_leaves_nothing(tmp: Path) -> None:
    store, blobs, thumbs, cfg, _ = seed(tmp / "a")
    out = tmp / "out" / "a.curio"
    calls = {"n": 0}

    def check() -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt

    try:
        bundle.export(store, blobs, thumbs, cfg, out, check=check)
        raise AssertionError("not cancelled")
    except KeyboardInterrupt:
        pass
    assert not out.exists() and not list(out.parent.glob("*"))
    shutil.rmtree(tmp / "a")
    print("  cancel leaves nothing   ok")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("bundle")
        test_round_trip(tmp / "rt")
        test_merge_policies(tmp / "mp")
        test_merge_rules(tmp / "mr")
        test_restore(tmp / "rs")
        test_without_images(tmp / "wi")
        test_secrets_opt_in(tmp / "se")
        test_damage_is_named_and_salvaged(tmp / "dm")
        test_not_ours(tmp / "no")
        test_export_cancel_leaves_nothing(tmp / "cx")
    print("\nall passed")
