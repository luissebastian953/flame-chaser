"""Perceptual hashing -- the piece that makes a two-source archive work.

The same illustration on pixiv and on X is *not* the same file: X strips
metadata, re-encodes JPEG and caps dimensions, so sha256 never matches. dHash
survives re-encode and rescale, and its Hamming distance is a usable similarity
metric. It does NOT survive crops, mirroring or heavy recolouring -- those are
false negatives you accept, because the alternative (a CNN embedding) costs
three orders of magnitude more for a personal archive.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image

HASH_SIZE = 8  # -> 64-bit hash
DUPE_THRESHOLD = 6  # empirical: <=6 same image, >=12 different


def dhash(data: bytes | Image.Image, hash_size: int = HASH_SIZE) -> int:
    """Row-gradient hash. Returns a (hash_size * hash_size)-bit int."""
    img = data if isinstance(data, Image.Image) else Image.open(BytesIO(data))
    img = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    px = list(img.getdata())
    w = hash_size + 1
    bits = 0
    for row in range(hash_size):
        base = row * w
        for col in range(hash_size):
            bits = (bits << 1) | int(px[base + col] > px[base + col + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def is_duplicate(a: int, b: int, threshold: int = DUPE_THRESHOLD) -> bool:
    return hamming(a, b) <= threshold


def to_signed(h: int) -> int:
    """SQLite INTEGER is signed 64-bit; wrap so it round-trips."""
    return h - (1 << 64) if h >= (1 << 63) else h


def from_signed(h: int) -> int:
    return h + (1 << 64) if h < 0 else h
