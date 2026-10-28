"""Purge the archive: Settings › Storage › Purge all data.

Two scopes, and they are the whole contract:

- `galleries`: every post, image row, classifier verdict, the visited set,
  the watermarks, the raw payloads and the trash -- and every file under
  `blobs/`, `thumbs/`, `by-character/` and `trash/`. The characters (watches),
  the daemon config and the accounts stay, so the next crawl starts each
  character from scratch. The visited set goes with the posts on purpose:
  `seen_posts` says "indexed, never revisit", and keeping it would make the
  next crawl skip everything it just lost.
- `all`: the above, plus the characters, the job history and the queue's
  hold, and the daemon's own files -- `config.json`, `secrets.json` and the X
  cookies file. The caller resets its in-memory config; the webview clears
  its own `curio.*` keys and reloads to first run.

Exported bundles are never touched: they live wherever the user saved them
(or `~/.reaver/exports/`), outside every tree named above.

The database rows go in ONE transaction, then the files. A file that cannot
be removed is reported, never rolled back: the rows are already gone, and an
orphan blob is reclaimed by the next purge or `library gc`.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from .bundle import MERGE_TABLES
from .config import Config
from .db import Store
from .library import _tree_size

log = logging.getLogger(__name__)

Scope = Literal["galleries", "all"]
SCOPES: tuple[str, ...] = ("galleries", "all")
PHRASE = "PLEASE DELETE"  # the webview's type-to-confirm; the daemon re-checks it

# galleries: everything an image left behind; the trash's own tables too
GALLERY_TABLES = (*MERGE_TABLES, "trash_items", "trash_batches")
# all: the characters and this machine's run history on top
ALL_TABLES = (*GALLERY_TABLES, "watches", "job_log", "jobs", "queue_state")
# the library's trees, in removal order; blobs/ carries the progress count
TREES = ("blobs", "thumbs", "by-character", "trash")

Progress = Callable[[int, int], None]


def _noop(_done: int, _total: int) -> None:
    pass


def preview(store: Store, library: Path) -> dict[str, int]:
    """What a purge would remove: the counts the confirm sheet shows."""

    def q(sql: str) -> int:
        return int(store.conn.execute(sql).fetchone()[0])

    nbytes = sum(_tree_size(Path(library) / t)[1] for t in ("blobs", "thumbs", "trash"))
    return {
        "images": q("SELECT count(*) FROM media WHERE state='stored'"),
        "characters": q("SELECT count(*) FROM watches"),
        "posts": q("SELECT count(*) FROM posts"),
        "bytes": nbytes,
    }


def _files(root: Path) -> list[Path]:
    out: list[Path] = []
    if not root.is_dir():
        return out
    for dirpath, _dirs, names in os.walk(root):
        out.extend(Path(dirpath) / n for n in names)
    return out


def _wipe_rows(store: Store, scope: Scope) -> None:
    tables = ALL_TABLES if scope == "all" else GALLERY_TABLES
    with store.tx() as c:
        for t in tables:
            c.execute(f"DELETE FROM {t}")


def _wipe_files(library: Path, progress: Progress) -> tuple[int, int, list[str]]:
    """Unlink every file under the library's trees. (images, bytes, failures)."""
    blobs = _files(library / "blobs")
    total = len(blobs)
    freed = 0
    failed: list[str] = []
    progress(0, total)
    for i, p in enumerate(blobs, 1):
        try:
            freed += p.stat().st_size
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            failed.append(f"{p.name}: {e.strerror or e}")
        if i % 50 == 0 or i == total:
            progress(i, total)
    for tree in TREES[1:]:
        root = library / tree
        for p in _files(root):
            try:
                if tree != "by-character":  # hardlinks: the bytes went with blobs/
                    freed += p.stat().st_size
                p.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                failed.append(f"{tree}/{p.name}: {e.strerror or e}")
    # the emptied directories; the tree roots stay so the stores keep working
    for tree in TREES:
        root = library / tree
        if not root.is_dir():
            continue
        for d in sorted((Path(dp) for dp, _, _ in os.walk(root)), reverse=True):
            if d != root:
                # not empty: a file above failed and is already reported
                with contextlib.suppress(OSError):
                    d.rmdir()
    return total, freed, failed


def _wipe_config(cfg: Config) -> list[str]:
    """The daemon's own files; the caller resets the in-memory config."""
    failed: list[str] = []
    paths = [cfg.home / "config.json", cfg.home / "secrets.json", cfg.home / "twitter-cookies.txt"]
    if cfg.twitter_cookies_file:
        paths.append(Path(cfg.twitter_cookies_file).expanduser())
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            failed.append(f"{p.name}: {e.strerror or e}")
    return failed


def fresh_config(cfg: Config) -> Config:
    """A freshly installed config at the same home and library folder: the
    folder is where the user pointed Curio, not something the archive holds."""
    return Config(home=cfg.home, db_path=cfg.db_path, blob_root=cfg.blob_root)


def purge(store: Store, cfg: Config, scope: Scope, progress: Progress = _noop) -> dict[str, Any]:
    """Rows in one transaction, then files, then (scope `all`) the config
    files. Returns {scope, images, bytes, failed: [names]}; a failed file is
    listed, not raised."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    library = Path(cfg.blob_root).parent
    _wipe_rows(store, scope)
    images, freed, failed = _wipe_files(library, progress)
    if scope == "all":
        failed += _wipe_config(cfg)
    try:
        store.conn.execute("VACUUM")  # give the db file's pages back too
    except Exception as e:  # the purge itself already happened
        log.warning("purge: vacuum failed: %s", e)
    for f in failed:
        log.warning("purge: could not remove %s", f)
    return {"scope": scope, "images": images, "bytes": freed, "failed": failed}
