"""The human-browsable view over the content-addressed store.

Content addressing is what makes dedupe, atomic writes and db/disk consistency
work. It is also unreadable in Finder. The usual fix is a symlink tree, and it
is a bad one: symlinks break when copied, don't survive a zip round-trip, and
on Windows need developer mode or an elevation prompt.

Hardlinks give both. `blobs/69/9a/<sha>.png` and
`by-character/ganyu/artist_123_p0.png` are two names for one inode -- zero extra
bytes, and each name is a real file to every other program on the machine.
Both trees live inside one library root, so the same-filesystem constraint is
satisfied by construction.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Sync clients generally materialise each hardlink as an independent copy,
#: silently doubling the archive; some break the link outright.
SYNC_MARKERS = (
    "dropbox",
    "onedrive",
    "google drive",
    "googledrive",
    "icloud",
    "mobile documents",
    "pcloud",
    "mega",
    "syncthing",
    "nextcloud",
    "yandex",
)

_SAFE = re.compile(r"[^-\w.]+", re.UNICODE)


class LinkMode(str, Enum):
    HARD = "hard"
    SYMLINK = "symlink"
    COPY = "copy"


def detect_link_mode(root: Path) -> LinkMode:
    """Probe the filesystem once, at library init.

    exFAT and FAT32 external drives -- a plausible place to keep an art archive
    -- have no hardlinks. The fallback must be a recorded decision, not an
    exception trace three weeks later.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".reaver-linkprobe"
    target = root / ".reaver-linkprobe.lnk"
    try:
        probe.write_bytes(b"x")
        for mode, fn in ((LinkMode.HARD, os.link), (LinkMode.SYMLINK, os.symlink)):
            try:
                fn(probe, target)
            except (OSError, NotImplementedError, AttributeError):
                continue
            target.unlink()
            return mode
        return LinkMode.COPY
    finally:
        for path in (target, probe):
            with contextlib.suppress(OSError):
                path.unlink()


def under_sync_root(path: Path) -> str | None:
    """Return the matched marker if the path looks like it's inside a sync
    client's folder. Warn at folder-pick time -- do not silently proceed."""
    low = str(Path(path).expanduser().resolve()).lower()
    return next((m for m in SYNC_MARKERS if m in low), None)


def safe_name(*parts: str, ext: str = "", maxlen: int = 120) -> str:
    stem = "_".join(_SAFE.sub("-", p.strip()) for p in parts if p)[:maxlen]
    ext = ("." + ext.lstrip(".")) if ext else ""
    return f"{stem or 'untitled'}{ext}"


class LibraryView:
    """Derived, rebuildable, safe to delete. Never the source of truth."""

    def __init__(self, root: Path, mode: LinkMode | None = None) -> None:
        self.root = Path(root).expanduser()
        self.view = self.root / "by-character"
        self.mode = mode or detect_link_mode(self.root)

    def place(self, blob: Path, slug: str, filename: str) -> Path | None:
        """Give one blob a readable second name. Idempotent."""
        dest_dir = self.view / _SAFE.sub("-", slug)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        if dest.exists():
            return dest
        try:
            if self.mode is LinkMode.HARD:
                os.link(blob, dest)
            elif self.mode is LinkMode.SYMLINK:
                os.symlink(os.path.relpath(blob, dest_dir), dest)
            else:
                shutil.copy2(blob, dest)
        except FileExistsError:
            pass
        except OSError as e:
            log.warning("could not place %s in %s: %s", blob.name, slug, e)
            return None
        return dest

    def remove(self, slug: str, filename: str) -> None:
        """Drop one readable name. A hardlink outlives its blob, so a thrown-away
        image must lose its names here explicitly. Idempotent."""
        (self.view / _SAFE.sub("-", slug) / filename).unlink(missing_ok=True)

    def clear(self) -> None:
        shutil.rmtree(self.view, ignore_errors=True)

    def orphans(self, live: Iterable[Path]) -> list[Path]:
        keep = {p.resolve() for p in live}
        return [p for p in self.view.rglob("*") if p.is_file() and p.resolve() not in keep]


def _tree_size(root: Path) -> tuple[int, int]:
    """(files, bytes) under `root`; (0, 0) when it does not exist. Counts
    every name once, so a hardlinked file is counted where it is listed."""
    files = total = 0
    if not root.is_dir():
        return 0, 0
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(Path(e.path))
                    elif e.is_file(follow_symlinks=False) and not e.name.endswith(".part"):
                        files += 1
                        total += e.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return files, total


def _nearest(path: Path) -> Path:
    while not path.exists():
        if path.parent == path:
            break
        path = path.parent
    return path


def _mount_of(path: Path) -> Path:
    p = _nearest(path).resolve()
    while not os.path.ismount(p) and p.parent != p:
        p = p.parent
    return p


def usage(root: Path, db_path: Path, store: Any) -> dict[str, Any]:
    """Settings › Storage: what the library holds and the disk it sits on.
    Blobs and thumbs come from a walk of their trees (an archive of a few
    thousand files is a few milliseconds); the hardlink view costs no extra
    bytes, so it reports characters only."""
    root, db_path = Path(root).expanduser(), Path(db_path).expanduser()
    blob_files, blob_bytes = _tree_size(root / "blobs")
    thumb_files, thumb_bytes = _tree_size(root / "thumbs")
    _, trash_bytes = _tree_size(root / "trash")
    characters = 0
    view = root / "by-character"
    if view.is_dir():
        with contextlib.suppress(OSError):
            characters = sum(1 for e in os.scandir(view) if e.is_dir(follow_symlinks=False))
    du = shutil.disk_usage(_nearest(root))
    db_bytes = 0
    for suffix in ("", "-wal", "-shm"):
        f = db_path.with_name(db_path.name + suffix)
        if f.exists():
            db_bytes += f.stat().st_size
    library_bytes = blob_bytes + thumb_bytes + trash_bytes
    return {
        "library_root": str(root),
        "db_path": str(db_path),
        "db_bytes": db_bytes,
        "schema_version": int(store.stats()["schema_version"]),
        "disk": {
            "total": du.total,
            "free": du.free,
            "used": du.used,
            "library": library_bytes,
            "other": max(0, du.used - library_bytes),
            "mount": str(_mount_of(root)),
        },
        "blobs": {"files": blob_files, "bytes": blob_bytes},
        "thumbs": {"files": thumb_files, "bytes": thumb_bytes},
        "by_character": {"characters": characters},
    }
