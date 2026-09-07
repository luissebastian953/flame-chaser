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

    def clear(self) -> None:
        shutil.rmtree(self.view, ignore_errors=True)

    def orphans(self, live: Iterable[Path]) -> list[Path]:
        keep = {p.resolve() for p in live}
        return [p for p in self.view.rglob("*") if p.is_file() and p.resolve() not in keep]
