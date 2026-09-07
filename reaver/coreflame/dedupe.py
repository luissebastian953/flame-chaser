"""Two-level dedupe.

Level 1 -- sha256. Catches re-downloads and the same file seen twice. Free.
Level 2 -- dHash within an artist's own work. Catches the case that actually
matters here: the artist posted the picture to pixiv at 4096px PNG and to X at
2048px JPEG. Those are byte-different and visually identical, and without this
pass a two-source archive is a pile of near-duplicate pairs.

Scoping to one artist is what keeps level 2 O(hundreds) instead of O(all).
Two different artists producing dHash-identical images of the same character is
not a thing that happens; the same artist reposting their own work is the whole
phenomenon we're modelling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .db import Store
from .phash import DUPE_THRESHOLD, dhash, hamming

log = logging.getLogger(__name__)


@dataclass
class DupeVerdict:
    is_dupe: bool
    sha256: str
    phash: int | None
    dupe_of: str | None = None
    reason: str = ""


def classify(
    store: Store, data: bytes, sha: str, artist_id: str, threshold: int = DUPE_THRESHOLD
) -> DupeVerdict:
    if store.sha_exists(sha):
        return DupeVerdict(True, sha, None, sha, "exact")

    try:
        h = dhash(data)
    except Exception as e:  # truncated / unsupported image
        log.warning("phash failed (%s); keeping file, no near-dupe check", e)
        return DupeVerdict(False, sha, None, None, "unhashable")

    best, best_d = None, 65
    for other_sha, other_h in store.phashes_for_artist(artist_id):
        if other_sha == sha:
            continue
        d = hamming(h, other_h)
        if d < best_d:
            best, best_d = other_sha, d
    if best is not None and best_d <= threshold:
        return DupeVerdict(True, sha, h, best, f"phash d={best_d}")
    return DupeVerdict(False, sha, h, None, f"nearest d={best_d}")
