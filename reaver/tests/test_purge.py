"""Purge all data (coreflame/purge.py): preview counts, the galleries scope
keeps characters and config, the all scope removes them too, exported
bundles survive both, and a file that cannot go is reported, not raised."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_trash import seed

from coreflame import purge, trash
from coreflame.config import Config
from coreflame.db import Store


def _cfg(tmp: Path) -> Config:
    cfg = Config(home=tmp / "home", blob_root=tmp / "lib" / "blobs")
    cfg.pixiv_php_sessid = "123_abc"
    cfg.pixiv_rate = 0.5
    cfg.save()
    cfg.save_secrets()
    (cfg.home / "twitter-cookies.txt").write_text("# cookies\n")
    (cfg.home / "exports").mkdir()
    (cfg.home / "exports" / "curio-1.curio").write_bytes(b"bundle")
    return cfg


def _count(store: Store, table: str) -> int:
    return int(store.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_preview(tmp: Path) -> None:
    store, *_ = seed(tmp / "p", n=3, slugs=("firefly", "kafka"))
    got = purge.preview(store, tmp / "p" / "lib")
    assert got["images"] == 3 and got["characters"] == 2 and got["posts"] == 3
    assert got["bytes"] > 0
    print("  preview:              ok (images, characters, posts, bytes)")


def test_galleries_keeps_characters_and_config(tmp: Path) -> None:
    store, blobs, thumbs, shas = seed(tmp / "g", n=4)
    trash.remove(store, blobs, thumbs, "firefly", shas[:1])  # one image in the trash
    cfg = _cfg(tmp / "g")
    lib = tmp / "g" / "lib"
    seen: list[tuple[int, int]] = []

    out = purge.purge(store, cfg, "galleries", lambda d, t: seen.append((d, t)))

    assert out["scope"] == "galleries" and out["failed"] == [] and out["images"] == 3
    assert out["bytes"] > 0
    assert seen[0] == (0, 3) and seen[-1] == (3, 3)
    for t in ("posts", "media", "seen_posts", "trash_items", "post_watches"):
        assert _count(store, t) == 0, t
    assert _count(store, "watches") == 1
    for tree in ("blobs", "thumbs", "by-character", "trash"):
        root = lib / tree
        assert not root.exists() or not any(p.is_file() for p in root.rglob("*")), tree
    assert (lib / "blobs").is_dir()  # the store's root stays
    assert (cfg.home / "config.json").exists() and (cfg.home / "secrets.json").exists()
    assert (cfg.home / "exports" / "curio-1.curio").read_bytes() == b"bundle"
    print("  galleries:            ok (rows + trees gone; characters, config, bundles stay)")


def test_all_removes_characters_and_config(tmp: Path) -> None:
    store, *_ = seed(tmp / "a", n=2, slugs=("firefly", "kafka"))
    cfg = _cfg(tmp / "a")
    out = purge.purge(store, cfg, "all")
    assert out["failed"] == []
    assert _count(store, "watches") == 0 and _count(store, "posts") == 0
    for f in ("config.json", "secrets.json", "twitter-cookies.txt"):
        assert not (cfg.home / f).exists(), f
    assert (cfg.home / "exports" / "curio-1.curio").exists()
    assert (cfg.home / "reaver.db").exists()  # emptied, never deleted
    fresh = purge.fresh_config(cfg)
    assert fresh.pixiv_php_sessid is None and fresh.pixiv_rate == Config().pixiv_rate
    assert fresh.blob_root == cfg.blob_root and fresh.home == cfg.home
    print("  all:                  ok (characters + config files gone; library folder kept)")


def test_failed_file_is_reported(tmp: Path) -> None:
    if os.geteuid() == 0:
        print("  failed file:          skipped (root ignores permissions)")
        return
    store, *_ = seed(tmp / "f", n=2)
    cfg = _cfg(tmp / "f")
    sub = next(p for p in (tmp / "f" / "lib" / "blobs").rglob("*") if p.is_file()).parent
    sub.chmod(0o500)  # its files cannot be unlinked
    try:
        out = purge.purge(store, cfg, "galleries")
    finally:
        sub.chmod(0o700)
    assert out["failed"], out
    assert _count(store, "media") == 0  # the rows are not rolled back
    print("  failed file:          ok (listed, rows stay purged)")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("purge")
        test_preview(tmp)
        test_galleries_keeps_characters_and_config(tmp)
        test_all_removes_characters_and_config(tmp)
        test_failed_file_is_reported(tmp)
        print("all passed")
