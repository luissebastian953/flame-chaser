"""Thumbnails at ingest. A grid of 500 cards pointing at 8 MB PNGs moves ~4 GB
through the webview and stalls it; a 400px WebP is ~15 KB and costs ~30 ms once.
Stored beside the blobs, addressed by the ORIGINAL's sha, so the gallery never
needs a second lookup: thumbs/69/9a/<sha>.webp"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

THUMB_PX = 400
QUALITY = 82


def dims(data: bytes) -> tuple[int, int] | None:
    """Pixel size of the decoded file -- what the viewer shows at 1:1. Reads
    the header only; None when Pillow cannot open it."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            upright = ImageOps.exif_transpose(img) or img
            return upright.width, upright.height
    except Exception:
        return None


class ThumbStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, sha: str) -> Path:
        return self.root / sha[:2] / sha[2:4] / f"{sha}.webp"

    def exists(self, sha: str) -> bool:
        return self.path_for(sha).exists()

    def make(self, sha: str, data: bytes, px: int = THUMB_PX) -> Path | None:
        """Idempotent. Returns the path, or None if the bytes aren't an image
        Pillow can read (the blob is still kept; only the preview is missing)."""
        dest = self.path_for(sha)
        if dest.exists():
            return dest
        try:
            img: Image.Image = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            img.thumbnail((px, px * 2), Image.Resampling.LANCZOS)  # tall art keeps height
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=QUALITY, method=4)
        except Exception as e:
            log.warning("thumbnail failed for %s: %s", sha[:12], e)
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".webp.tmp")
        tmp.write_bytes(buf.getvalue())
        tmp.replace(dest)
        return dest
