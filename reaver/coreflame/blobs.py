"""Content-addressed blob store. sha256[:2]/sha256[2:4]/sha256.ext

Flat directories of half a million files never happen; re-downloads and
cross-source duplicates cost zero extra bytes.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


class BlobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, sha: str, ext: str = "") -> Path:
        ext = ("." + ext.lstrip(".")) if ext else ""
        return self.root / sha[:2] / sha[2:4] / f"{sha}{ext}"

    def exists(self, sha: str, ext: str = "") -> bool:
        return self.path_for(sha, ext).exists()

    def put(self, data: bytes, ext: str = "") -> tuple[str, Path, bool]:
        """Returns (sha256, path, was_new). Write is atomic via rename."""
        sha = hashlib.sha256(data).hexdigest()
        dest = self.path_for(sha, ext)
        if dest.exists():
            return sha, dest, False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + f".{os.getpid()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return sha, dest, True
