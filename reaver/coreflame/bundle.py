"""Export and import: the whole archive as one file, and back.

A bundle is a fixed list of entries - a consistent database snapshot, the
daemon settings, the webview's own state (an opaque blob the daemon never
reads), and the blobs and thumbnails - written by one of two codecs:

- `.zip`: the open container. Deflate on the small text entries, STORED on
  images (they are already compressed; gzip would only burn CPU), and a
  central directory, so `inspect` reads the manifest alone.
- `.curio`: our own framed container, one streaming pass, stdlib only.
  Every entry is cut into chunks with a crc32 each and ends in its sha256;
  the manifest sits at the head AND as an entry, the trailer carries an
  index and the hash of everything before it. A truncated file still yields
  every complete entry (the reader scans forward on the sync markers); a
  damaged file names exactly which entries are hurt.

Corruption is a property of disks and transfers, not of a format. What a
format can do is make damage detectable, locatable, and unable to reach the
live library - so `export` re-reads and verifies what it wrote before
reporting success, `verify` is a pure read, and `import_` stages everything
in a scratch folder, merges in ONE transaction and moves bytes into
`blobs/` only after that commits. A damaged image is re-fetched (its media
row keeps the url and goes back to `pending`), never lost.

Merge rules (the live schema's natural keys, so every write stays an
idempotent upsert):

- watches by slug: `keep` ours, `take` theirs, or `merge` (union of tags,
  terms and sources; the looser of each gate; the larger target)
- posts upsert, the newer `fetched_at` wins; post_watches / post_tags union
- media by (source, external_id, idx): ours wins, theirs fills gaps; new
  bytes get the artist-scoped dHash check a crawled image gets
- seen_posts: `gone` and `skipped` (the lower threshold) import freely;
  `indexed` only with its post; `failed` never
- poll_state: ours kept, theirs only for a feed we have no row for
- artists: union; a twitter handle fills a gap; followed is OR
- jobs, job_log, queue_state, trash_*: never exported, never imported
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import struct
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from . import __version__, migrations
from .blobs import BlobStore
from .config import SECRET_KEYS, Config
from .db import Store
from .models import Watch
from .phash import from_signed, hamming
from .thumbs import ThumbStore

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
MAGIC = b"CURIO\x00"
TRAILER_MAGIC = b"\x00OIRUC"
SYNC = b"\xf0\x9f\x94\xa5CE"  # per-entry sync marker: the reader resyncs on it
CHUNK = 4 * 1024 * 1024
EXTENSIONS = {"curio": ".curio", "zip": ".zip"}

# entry names, both codecs
MANIFEST = "manifest.json"
DB = "db.sqlite"
CONFIG = "config.json"
SECRETS = "secrets.json"
UI = "ui.json"
BLOB_PREFIX = "blobs/"
THUMB_PREFIX = "thumbs/"
TEXT_ENTRIES = (MANIFEST, DB, CONFIG, SECRETS, UI)

# config fields that name a machine: never carried across
MACHINE_KEYS = (
    "home",
    "db_path",
    "blob_root",
    "twitter_cookies_file",
    "twitter_cookies_from_browser",
)

# the tables a merge copies. Runtime state of one machine (jobs, job_log,
# queue_state, trash_*) and schema_version are deliberately absent.
MERGE_TABLES = (
    "artists",
    "posts",
    "post_watches",
    "post_tags",
    "media",
    "raw_payloads",
    "quarantine",
    "poll_state",
    "extraction_stats",
    "tag_stats",
    "image_kinds",
    "image_people",
    "image_identity",
    "image_characters",
    "image_origin",
    "image_label",
    "seen_posts",
)
RUNTIME_TABLES = ("job_log", "jobs", "queue_state", "trash_items", "trash_batches")

# (stage, done, total, **totals): done/total are the STAGE's own; the first
# call of an export carries every stage's total (posts, images, thumbs,
# entries) so a progress view can draw the stages still to come
Progress = Callable[..., None]
Check = Callable[[], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _noop(_stage: str, _done: int, _total: int | None, **_extra: int) -> None:
    pass


def _nocheck() -> None:
    pass


class BundleError(Exception):
    """A bundle that cannot be used: not ours, too new, or damaged where it
    matters. `code` is what the daemon and the UI switch on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- options & manifest
@dataclass
class ExportOptions:
    images: bool = True
    thumbs: bool = True
    secrets: bool = False
    fmt: str = "curio"  # curio | zip
    ui: dict[str, Any] | None = None  # the webview's state, opaque to the engine


@dataclass
class Manifest:
    app_version: str
    schema_version: int
    created_at: str
    options: dict[str, Any]
    counts: dict[str, int]
    characters: list[dict[str, Any]]
    format_version: int = FORMAT_VERSION

    def to_json(self) -> bytes:
        return json.dumps(self.__dict__, ensure_ascii=False, indent=1).encode()

    @classmethod
    def from_json(cls, data: bytes) -> Manifest:
        try:
            d = json.loads(data)
            return cls(
                app_version=str(d["app_version"]),
                schema_version=int(d["schema_version"]),
                created_at=str(d["created_at"]),
                options=dict(d.get("options") or {}),
                counts={k: int(v) for k, v in (d.get("counts") or {}).items()},
                characters=list(d.get("characters") or []),
                format_version=int(d.get("format_version", 1)),
            )
        except (ValueError, KeyError, TypeError) as e:
            raise BundleError("bad_manifest", f"manifest unreadable: {e}") from e


# ---------------------------------------------------------------- codecs
@dataclass
class Entry:
    name: str
    size: int
    sha256: str
    offset: int = 0  # curio only


class Sink(Protocol):
    def write(self, b: bytes, /) -> int: ...


class _Devnull:
    def write(self, b: bytes, /) -> int:
        return len(b)


class Writer(Protocol):
    def add(self, name: str, src: BinaryIO | bytes, size: int) -> str: ...

    def close(self) -> None: ...


class Reader:
    """`entries()` is the index; `copy(name, out)` streams one entry's
    bytes and tells whether they verified against the recorded hash."""

    def entries(self) -> list[Entry]:
        raise NotImplementedError

    def copy(self, name: str, out: Sink) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def names(self) -> set[str]:
        return {e.name for e in self.entries()}

    def read(self, name: str) -> bytes:
        buf = io.BytesIO()
        if not self.copy(name, buf):
            raise BundleError("damaged", f"{name} does not verify")
        return buf.getvalue()

    def extract(self, name: str, dest: Path) -> bool:
        """Stream one entry to `dest`; False (and no file) when it does not verify."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        with tmp.open("wb") as f:
            ok = self.copy(name, f)
        if ok:
            tmp.replace(dest)
        else:
            tmp.unlink(missing_ok=True)
        return ok


def _is_text(name: str) -> bool:
    return name in TEXT_ENTRIES


def _iter_src(src: BinaryIO | bytes) -> Iterator[bytes]:
    if isinstance(src, bytes):
        for i in range(0, len(src), CHUNK):
            yield src[i : i + CHUNK]
        return
    while True:
        b = src.read(CHUNK)
        if not b:
            return
        yield b


# -- zip -------------------------------------------------------------------
class ZipWriter:
    """Deflate on text, STORED on images; the per-entry hashes ride in a
    final `index.json` so a reader verifies bytes, not just names."""

    def __init__(self, path: Path) -> None:
        self.zf = zipfile.ZipFile(path, "w", allowZip64=True)
        self.hashes: dict[str, str] = {}

    def add(self, name: str, src: BinaryIO | bytes, size: int) -> str:
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED if _is_text(name) else zipfile.ZIP_STORED
        info.file_size = size
        h = hashlib.sha256()
        with self.zf.open(info, "w", force_zip64=True) as out:
            for part in _iter_src(src):
                h.update(part)
                out.write(part)
        self.hashes[name] = h.hexdigest()
        return self.hashes[name]

    def close(self) -> None:
        self.zf.writestr(
            zipfile.ZipInfo("index.json", date_time=(1980, 1, 1, 0, 0, 0)),
            json.dumps(self.hashes).encode(),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        self.zf.close()


class ZipReader(Reader):
    def __init__(self, path: Path) -> None:
        try:
            self.zf = zipfile.ZipFile(path)
            self.index: dict[str, str] = json.loads(self.zf.read("index.json"))
        except (KeyError, ValueError, zipfile.BadZipFile, EOFError) as e:
            raise BundleError("not_a_bundle", f"not a zip bundle: {e}") from e

    def entries(self) -> list[Entry]:
        return [
            Entry(i.filename, i.file_size, self.index[i.filename])
            for i in self.zf.infolist()
            if i.filename in self.index
        ]

    def copy(self, name: str, out: Sink) -> bool:
        want = self.index.get(name)
        if want is None:
            return False
        h = hashlib.sha256()
        try:
            with self.zf.open(name) as f:
                while True:
                    b = f.read(CHUNK)
                    if not b:
                        break
                    h.update(b)
                    out.write(b)
        except (zipfile.BadZipFile, zlib.error, EOFError, KeyError, OSError):
            return False
        return h.hexdigest() == want

    def close(self) -> None:
        self.zf.close()


# -- curio -----------------------------------------------------------------
# header:  MAGIC | u16 format | u16 flags | u32 len | zlib(manifest)
# entry:   SYNC | u8 kind(0 raw, 1 zlib per chunk) | u16 name_len | name | u64 size
#          | (u32 len | u32 crc32 | bytes)* | u32 0 | sha256[32] of the plain bytes
# trailer: TRAILER_MAGIC | u32 len | zlib(index json) | u64 index_offset
#          | sha256[32] of everything before it | MAGIC
_HDR = struct.Struct("<6sHHI")
_ENT = struct.Struct("<6sBH")
_CHK = struct.Struct("<II")
_TAIL = 8 + 32 + 6


class _Hashing:
    """A file that hashes what passes through it."""

    def __init__(self, f: BinaryIO) -> None:
        self.f, self.h, self.pos = f, hashlib.sha256(), 0

    def write(self, b: bytes) -> int:
        self.h.update(b)
        self.pos += len(b)
        return self.f.write(b)


class CurioWriter:
    def __init__(self, path: Path, manifest: bytes) -> None:
        self._f = path.open("wb")
        self.out = _Hashing(self._f)
        self.index: list[dict[str, Any]] = []
        m = zlib.compress(manifest, 6)
        self.out.write(_HDR.pack(MAGIC, FORMAT_VERSION, 0, len(m)))
        self.out.write(m)

    def add(self, name: str, src: BinaryIO | bytes, size: int) -> str:
        offset = self.out.pos
        kind = 1 if _is_text(name) else 0
        nb = name.encode()
        self.out.write(_ENT.pack(SYNC, kind, len(nb)))
        self.out.write(nb)
        self.out.write(struct.pack("<Q", size))
        h = hashlib.sha256()
        for part in _iter_src(src):
            h.update(part)
            c = zlib.compress(part, 6) if kind else part
            self.out.write(_CHK.pack(len(c), zlib.crc32(c)))
            self.out.write(c)
        self.out.write(struct.pack("<I", 0))
        sha = h.hexdigest()
        self.out.write(bytes.fromhex(sha))
        self.index.append({"name": name, "size": size, "sha256": sha, "offset": offset})
        return sha

    def close(self) -> None:
        index_offset = self.out.pos
        idx = zlib.compress(json.dumps(self.index).encode(), 6)
        self.out.write(TRAILER_MAGIC)
        self.out.write(struct.pack("<I", len(idx)))
        self.out.write(idx)
        self.out.write(struct.pack("<Q", index_offset))
        self._f.write(self.out.h.digest())
        self._f.write(MAGIC)
        self._f.flush()
        os.fsync(self._f.fileno())
        self._f.close()


class CurioReader(Reader):
    """Reads through the trailer index when it is intact, else scans forward
    on the sync markers and recovers every complete entry."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.f = path.open("rb")
        self.size = path.stat().st_size
        head = self.f.read(_HDR.size)
        if len(head) < _HDR.size or head[:6] != MAGIC:
            self.f.close()
            raise BundleError("not_a_bundle", "not a .curio bundle")
        _, self.format_version, self.flags, mlen = _HDR.unpack(head)
        if self.format_version > FORMAT_VERSION:
            self.f.close()
            raise BundleError(
                "bundle_too_new",
                f"bundle format v{self.format_version}; this app reads up to v{FORMAT_VERSION}",
            )
        try:
            self.head_manifest = zlib.decompress(self.f.read(mlen))
        except zlib.error as e:
            self.f.close()
            raise BundleError("damaged", f"head manifest damaged: {e}") from e
        self.first_entry = _HDR.size + mlen
        self.trailer_ok = False
        self.file_hash_ok = False
        found = self._read_trailer()
        self._entries: list[Entry] = found if found is not None else self._scan()
        self._by_name = {e.name: e for e in self._entries}

    # -- index ----------------------------------------------------------------
    def _read_trailer(self) -> list[Entry] | None:
        if self.size < self.first_entry + 6 + 4 + _TAIL:
            return None
        self.f.seek(self.size - _TAIL)
        end = self.f.read(_TAIL)
        if end[-6:] != MAGIC:
            return None
        (index_offset,) = struct.unpack("<Q", end[:8])
        digest = end[8:40]
        self.f.seek(index_offset)
        if (
            not (self.first_entry <= index_offset < self.size - _TAIL)
            or self.f.read(6) != TRAILER_MAGIC
        ):
            return None
        (ilen,) = struct.unpack("<I", self.f.read(4))
        try:
            idx = json.loads(zlib.decompress(self.f.read(ilen)))
        except (zlib.error, ValueError):
            return None
        if self.f.tell() != self.size - _TAIL:
            return None
        self.trailer_ok = True
        h = hashlib.sha256()
        self.f.seek(0)
        left = self.size - 32 - 6
        while left > 0:
            b = self.f.read(min(CHUNK, left))
            if not b:
                break
            h.update(b)
            left -= len(b)
        self.file_hash_ok = h.digest() == digest
        return [Entry(e["name"], int(e["size"]), e["sha256"], int(e["offset"])) for e in idx]

    def _scan(self) -> list[Entry]:
        """No usable trailer: walk the entries from the head, resyncing past
        any that does not parse. A damaged entry is listed with an empty
        hash, so verify() fails it by name instead of losing its neighbours."""
        out: list[Entry] = []
        pos = self.first_entry
        while True:
            hdr = self._entry_header(pos)
            if hdr is None:
                break
            name, size, body = hdr
            end = self._skip_chunks(body)
            sha = self._read_sha(end) if end is not None else None
            out.append(Entry(name, size, sha or "", pos))
            if sha is None:
                nxt = self._find_sync(body)
                if nxt is None:
                    break
                pos = nxt
                continue
            pos = end + 32  # type: ignore[operator]
        return out

    def _entry_header(self, pos: int) -> tuple[str, int, int] | None:
        """(name, size, offset of the first chunk), or None if no entry starts here."""
        self.f.seek(pos)
        raw = self.f.read(_ENT.size)
        if len(raw) < _ENT.size or raw[:6] != SYNC:
            return None
        _, _kind, nlen = _ENT.unpack(raw)
        name = self.f.read(nlen)
        rest = self.f.read(8)
        if len(name) < nlen or len(rest) < 8:
            return None
        (size,) = struct.unpack("<Q", rest)
        try:
            return name.decode(), size, self.f.tell()
        except UnicodeDecodeError:
            return None

    def _skip_chunks(self, pos: int) -> int | None:
        """Offset just past the terminating u32 0, or None if the chunk list
        runs off the file or looks wrong."""
        self.f.seek(pos)
        while True:
            raw = self.f.read(4)
            if len(raw) < 4:
                return None
            (n,) = struct.unpack("<I", raw)
            if n == 0:
                return self.f.tell()
            if n > CHUNK * 2 or self.f.tell() + 4 + n > self.size:
                return None
            self.f.seek(n + 4, 1)

    def _read_sha(self, pos: int) -> str | None:
        self.f.seek(pos)
        b = self.f.read(32)
        return b.hex() if len(b) == 32 else None

    def _find_sync(self, pos: int) -> int | None:
        self.f.seek(pos)
        carry = b""
        while True:
            b = self.f.read(CHUNK)
            if not b:
                return None
            buf = carry + b
            i = buf.find(SYNC)
            if i >= 0:
                return pos - len(carry) + i
            pos += len(b)
            carry = buf[-(len(SYNC) - 1) :]

    # -- reading ----------------------------------------------------------------
    def entries(self) -> list[Entry]:
        return list(self._entries)

    def _stream(self, e: Entry) -> Iterator[bytes]:
        hdr = self._entry_header(e.offset)
        if hdr is None or hdr[0] != e.name:
            raise BundleError("damaged", f"{e.name}: entry header unreadable")
        self.f.seek(e.offset + 6)
        kind = self.f.read(1)[0]
        self.f.seek(hdr[2])
        while True:
            raw = self.f.read(4)
            if len(raw) < 4:
                raise BundleError("damaged", f"{e.name}: truncated")
            (n,) = struct.unpack("<I", raw)
            if n == 0:
                return
            crc_raw = self.f.read(4)
            c = self.f.read(n)
            if len(crc_raw) < 4 or len(c) < n or zlib.crc32(c) != struct.unpack("<I", crc_raw)[0]:
                raise BundleError("damaged", f"{e.name}: chunk crc mismatch")
            try:
                yield zlib.decompress(c) if kind else c
            except zlib.error as err:
                raise BundleError("damaged", f"{e.name}: {err}") from err

    def copy(self, name: str, out: Sink) -> bool:
        e = self._by_name.get(name)
        if e is None or not e.sha256:
            return False
        h = hashlib.sha256()
        total = 0
        try:
            for part in self._stream(e):
                h.update(part)
                total += len(part)
                out.write(part)
        except BundleError:
            return False
        return total == e.size and h.hexdigest() == e.sha256

    def close(self) -> None:
        self.f.close()


def open_reader(path: Path) -> Reader:
    path = Path(path)
    if not path.is_file():
        raise BundleError("no_file", str(path))
    with path.open("rb") as f:
        head = f.read(6)
    if head == MAGIC:
        return CurioReader(path)
    if head[:2] == b"PK":
        return ZipReader(path)
    raise BundleError("not_a_bundle", f"{path.name} is neither a .curio nor a .zip bundle")


def format_of(reader: Reader) -> str:
    return "curio" if isinstance(reader, CurioReader) else "zip"


# ---------------------------------------------------------------- export
def _db_snapshot(store: Store, dest: Path) -> None:
    """A consistent copy while a crawl may be writing: the backup API, never
    a file copy (WAL). This machine's runtime state is dropped from the copy."""
    dst = sqlite3.connect(dest)
    try:
        store.conn.backup(dst)
        for t in RUNTIME_TABLES:
            dst.execute(f"DELETE FROM {t}")
        dst.commit()
        dst.execute("VACUUM")
    finally:
        dst.close()


def portable_config(cfg: Config) -> dict[str, Any]:
    d = {k: (str(v) if isinstance(v, Path) else v) for k, v in cfg.__dict__.items()}
    for k in (*MACHINE_KEYS, *SECRET_KEYS):
        d.pop(k, None)
    return d


def _stored_media(store: Store) -> list[sqlite3.Row]:
    return store.conn.execute(
        "SELECT DISTINCT sha256, ext FROM media WHERE state='stored' AND sha256 IS NOT NULL"
    ).fetchall()


def _watch_summary(store: Store) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        "SELECT w.slug, w.label, w.pixiv_tags, "
        "(SELECT count(*) FROM post_watches pw WHERE pw.slug=w.slug) AS posts "
        "FROM watches w ORDER BY w.slug"
    ).fetchall()
    return [
        {
            "slug": r["slug"],
            "label": r["label"],
            "pixiv_tags": json.loads(r["pixiv_tags"]),
            "posts": r["posts"],
        }
        for r in rows
    ]


def export(
    store: Store,
    blobs: BlobStore,
    thumbs: ThumbStore,
    cfg: Config,
    dest: Path,
    opts: ExportOptions | None = None,
    progress: Progress = _noop,
    check: Check = _nocheck,
) -> dict[str, Any]:
    """Write the bundle to `dest`: a `.part` first, renamed only after the
    read-back verification passes. Returns the counts plus bytes written."""
    opts = opts or ExportOptions()
    if opts.fmt not in EXTENSIONS:
        raise BundleError("bad_format", opts.fmt)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    media = _stored_media(store) if opts.images else []
    thumb_shas = [r["sha256"] for r in media if thumbs.exists(r["sha256"])] if opts.thumbs else []
    st = store.stats()
    manifest = Manifest(
        app_version=__version__,
        schema_version=int(st["schema_version"]),
        created_at=_now(),
        options={"images": opts.images, "thumbs": opts.thumbs, "secrets": opts.secrets},
        counts={
            "characters": int(st["watches"]),
            "posts": int(st["posts"]),
            "images": len(media),
            "thumbs": len(thumb_shas),
        },
        characters=_watch_summary(store),
    )
    mbytes = manifest.to_json()
    entries = 4 + len(media) + len(thumb_shas) + (1 if opts.secrets else 0)
    with tempfile.TemporaryDirectory(prefix="curio-export-") as td:
        snap = Path(td) / "db.sqlite"
        progress(
            "snapshot",
            0,
            1,
            posts=manifest.counts["posts"],
            images=len(media),
            thumbs=len(thumb_shas),
            entries=entries,
        )
        _db_snapshot(store, snap)
        progress("snapshot", 1, 1)
        w: Writer = CurioWriter(part, mbytes) if opts.fmt == "curio" else ZipWriter(part)
        try:
            w.add(MANIFEST, mbytes, len(mbytes))
            with snap.open("rb") as f:
                w.add(DB, f, snap.stat().st_size)
            c = json.dumps(portable_config(cfg), indent=1).encode()
            w.add(CONFIG, c, len(c))
            if opts.secrets:
                s = json.dumps(
                    {k: getattr(cfg, k) for k in SECRET_KEYS if getattr(cfg, k)}
                ).encode()
                w.add(SECRETS, s, len(s))
            u = json.dumps(opts.ui or {}, ensure_ascii=False).encode()
            w.add(UI, u, len(u))
            progress("images", 0, len(media))
            for i, r in enumerate(media):
                check()
                p = blobs.path_for(r["sha256"], r["ext"])
                if not p.exists():
                    continue  # the row says stored, the disk disagrees: gc territory
                with p.open("rb") as f:
                    w.add(f"{BLOB_PREFIX}{r['sha256']}.{r['ext']}", f, p.stat().st_size)
                if i % 50 == 49:
                    progress("images", i + 1, len(media))
            progress("images", len(media), len(media))
            progress("thumbs", 0, len(thumb_shas))
            for i, sha in enumerate(thumb_shas):
                check()
                p = thumbs.path_for(sha)
                with p.open("rb") as f:
                    w.add(f"{THUMB_PREFIX}{sha}.webp", f, p.stat().st_size)
                if i % 200 == 199:
                    progress("thumbs", i + 1, len(thumb_shas))
            progress("thumbs", len(thumb_shas), len(thumb_shas))
        except BaseException:
            w.close()
            part.unlink(missing_ok=True)
            raise
        w.close()
    # the double guard: read back what was written before calling it done
    progress("verify", 0, entries)
    report = verify(part, check=check, progress=progress)
    if not report["ok"]:
        part.unlink(missing_ok=True)
        raise BundleError("write_failed", f"read-back failed: {report['damaged'][:3]}")
    part.replace(dest)
    return {
        "path": str(dest),
        "bytes": dest.stat().st_size,
        "format": opts.fmt,
        **manifest.counts,
    }


# ---------------------------------------------------------------- verify / inspect
def verify(path: Path, check: Check = _nocheck, progress: Progress = _noop) -> dict[str, Any]:
    """A pure read: every entry re-hashed. Never raises on damage - it
    names the damaged entries; raises BundleError only when the file is not
    a bundle at all."""
    r = open_reader(Path(path))
    try:
        damaged = []
        sink = _Devnull()
        n = 0
        entries = r.entries()
        for e in entries:
            check()
            n += 1
            if not r.copy(e.name, sink):
                damaged.append(e.name)
            if n % 50 == 0:
                progress("verify", n, len(entries))
        progress("verify", n, len(entries))
        out: dict[str, Any] = {"ok": not damaged, "entries": n, "damaged": damaged}
        if isinstance(r, CurioReader):
            out["trailer_ok"] = r.trailer_ok
            out["file_hash_ok"] = r.file_hash_ok
            out["ok"] = out["ok"] and r.trailer_ok and r.file_hash_ok
        return out
    finally:
        r.close()


def read_manifest(r: Reader) -> Manifest:
    """The manifest entry; for a .curio whose entry is hurt, the head copy."""
    try:
        return Manifest.from_json(r.read(MANIFEST))
    except BundleError:
        if isinstance(r, CurioReader):
            return Manifest.from_json(r.head_manifest)
        raise


@dataclass
class Conflict:
    slug: str
    label: str
    mine: dict[str, Any]
    theirs: dict[str, Any]
    kind: str = "same_slug"  # same_slug | same_tags (another slug, overlapping pixiv tags)
    suggest: str | None = None  # same_tags: our slug they probably mean


def _bundle_watches(conn: sqlite3.Connection, schema: str = "main") -> list[Watch]:
    """The bundle's watches from an opened or attached copy. Tolerates an
    older schema: a missing column takes the model's default."""
    cols = [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info(watches)").fetchall()]
    out = []
    for r in conn.execute(f"SELECT * FROM {schema}.watches ORDER BY slug").fetchall():
        d = dict(zip(cols, tuple(r), strict=True))
        kw: dict[str, Any] = {
            "slug": d["slug"],
            "label": d.get("label") or "",
            "pixiv_tags": json.loads(d.get("pixiv_tags") or "[]"),
            "match_terms": json.loads(d.get("match_terms") or "[]"),
            "min_bookmarks": d.get("min_bookmarks") or 0,
            "include_r18": bool(d.get("include_r18") or 0),
        }
        if d.get("sources"):
            kw["sources"] = json.loads(d["sources"])
        for k in ("target", "gender", "gender_mode"):
            if d.get(k) is not None:
                kw[k] = d[k]
        if d.get("kind_filter") is not None:
            kw["kind_filter"] = bool(d["kind_filter"])
        out.append(Watch(**kw))
    return out


def conflicts(mine: list[Watch], theirs: list[Watch]) -> list[Conflict]:
    by_slug = {w.slug: w for w in mine}
    by_tag: dict[str, Watch] = {}
    for w in mine:
        for tag in w.pixiv_tags:
            by_tag.setdefault(tag, w)
    out: list[Conflict] = []
    for t in theirs:
        if t.slug in by_slug:
            m = by_slug[t.slug]
            if m.model_dump() != t.model_dump():
                out.append(Conflict(t.slug, m.label or t.label, m.model_dump(), t.model_dump()))
            continue
        hit = next((by_tag[tag] for tag in t.pixiv_tags if tag in by_tag), None)
        if hit is not None:
            out.append(
                Conflict(t.slug, t.label, hit.model_dump(), t.model_dump(), "same_tags", hit.slug)
            )
    return out


def merge_watch(mine: Watch, theirs: Watch) -> Watch:
    """Union of what they name, the looser of each gate, the larger target."""

    def union(a: list[str], b: list[str]) -> list[str]:
        return list(dict.fromkeys([*a, *b]))

    genders = {mine.gender, theirs.gender}
    gender = mine.gender if len(genders) == 1 else "any"
    mode = "partial" if "partial" in (mine.gender_mode, theirs.gender_mode) else "full"
    return Watch.model_validate(
        {
            "slug": mine.slug,
            "label": mine.label or theirs.label,
            "pixiv_tags": union(mine.pixiv_tags, theirs.pixiv_tags),
            "match_terms": union(mine.match_terms, theirs.match_terms),
            "min_bookmarks": min(mine.min_bookmarks, theirs.min_bookmarks),
            "include_r18": mine.include_r18 or theirs.include_r18,
            "sources": union(list(mine.sources), list(theirs.sources)),
            "target": max(mine.target, theirs.target),
            "kind_filter": mine.kind_filter and theirs.kind_filter,
            "gender": gender,
            "gender_mode": mode if gender != "any" else mine.gender_mode,
        }
    )


def _staged_db(r: Reader, td: Path) -> Path:
    """The bundle's database, extracted, integrity-checked and migrated to
    this app's schema - on the copy, never in place."""
    snap = td / DB
    if not r.extract(DB, snap):
        raise BundleError("damaged", "the bundle's database does not verify")
    conn = sqlite3.connect(snap)
    try:
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise BundleError("damaged", f"database integrity: {ok}")
        have = migrations.current_version(conn)
        newest = max(m[0] for m in migrations.MIGRATIONS)
        if have > newest:
            raise BundleError(
                "bundle_too_new", f"bundle schema v{have}; this app knows up to v{newest}"
            )
        if have == 0:
            raise BundleError("damaged", "the bundle's database has no schema")
        migrations.apply(conn, snap, __version__)
        conn.commit()
    finally:
        conn.close()
    return snap


def inspect(path: Path, store: Store) -> dict[str, Any]:
    """What the bundle holds and where it collides with this archive. Reads
    the manifest and the watches only; the full verify is the import's job."""
    r = open_reader(Path(path))
    try:
        m = read_manifest(r)
        names = r.names()
        with tempfile.TemporaryDirectory(prefix="curio-inspect-") as td:
            conn = sqlite3.connect(_staged_db(r, Path(td)))
            try:
                theirs = _bundle_watches(conn)
            finally:
                conn.close()
        mine = store.watches()
        mine_slugs = {w.slug for w in mine}
        posts = {c["slug"]: int(c.get("posts") or 0) for c in m.characters}
        return {
            "path": str(path),
            "format": format_of(r),
            "app_version": m.app_version,
            "schema_version": m.schema_version,
            "created_at": m.created_at,
            "counts": m.counts,
            "has": {
                "images": any(n.startswith(BLOB_PREFIX) for n in names),
                "thumbs": any(n.startswith(THUMB_PREFIX) for n in names),
                "secrets": SECRETS in names,
                "ui": UI in names,
            },
            "characters": [
                {**w.model_dump(), "posts": posts.get(w.slug, 0), "new": w.slug not in mine_slugs}
                for w in theirs
            ],
            "conflicts": [c.__dict__ for c in conflicts(mine, theirs)],
        }
    finally:
        r.close()


# ---------------------------------------------------------------- import
@dataclass
class ImportOptions:
    mode: str = "merge"  # merge | restore
    settings: str = "keep"  # keep | take
    secrets: bool = False
    characters: dict[str, str] = field(default_factory=dict)  # slug -> keep | take | merge
    default_policy: str = "merge"
    salvage: bool = False  # go on with the intact entries when some are damaged


def _upsert_watch_row(conn: sqlite3.Connection, w: Watch) -> None:
    conn.execute(
        """INSERT INTO watches(slug,label,pixiv_tags,match_terms,min_bookmarks,include_r18,
                              sources,target,kind_filter,gender,gender_mode)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(slug) DO UPDATE SET
             label=excluded.label, pixiv_tags=excluded.pixiv_tags, match_terms=excluded.match_terms,
             min_bookmarks=excluded.min_bookmarks, include_r18=excluded.include_r18,
             sources=excluded.sources, target=excluded.target, kind_filter=excluded.kind_filter,
             gender=excluded.gender, gender_mode=excluded.gender_mode""",
        (
            w.slug,
            w.label,
            json.dumps(w.pixiv_tags, ensure_ascii=False),
            json.dumps(w.match_terms, ensure_ascii=False),
            w.min_bookmarks,
            int(w.include_r18),
            json.dumps(w.sources),
            w.target,
            int(w.kind_filter),
            w.gender,
            w.gender_mode,
        ),
    )


def _merge(conn: sqlite3.Connection, snap: Path, opts: ImportOptions) -> dict[str, int]:
    """One transaction: ATTACH the staged copy and upsert table by table."""
    counts: dict[str, int] = {}
    mine = {w.slug: w for w in _bundle_watches(conn)}
    conn.execute("ATTACH DATABASE ? AS b", (str(snap),))
    try:
        conn.execute("BEGIN")
        n = 0
        for theirs in _bundle_watches(conn, "b"):
            policy = opts.characters.get(theirs.slug, opts.default_policy)
            if theirs.slug not in mine or policy == "take":
                w = theirs
            elif policy == "keep":
                continue
            else:
                w = merge_watch(mine[theirs.slug], theirs)
            _upsert_watch_row(conn, w)
            n += 1
        counts["characters"] = n

        def run(key: str, sql: str) -> None:
            counts[key] = counts.get(key, 0) + conn.execute(sql).rowcount

        # `WHERE true` disambiguates the upsert's ON CONFLICT from a join (sqlite docs)
        run(
            "artists",
            """INSERT INTO artists SELECT * FROM b.artists WHERE true
               ON CONFLICT(source,artist_id) DO UPDATE SET
                 name=CASE WHEN artists.name='' THEN excluded.name ELSE artists.name END,
                 handle=CASE WHEN artists.handle='' THEN excluded.handle ELSE artists.handle END,
                 twitter_handle=COALESCE(artists.twitter_handle, excluded.twitter_handle),
                 followed=max(artists.followed, excluded.followed),
                 checked_at=max(COALESCE(artists.checked_at,''), COALESCE(excluded.checked_at,''))""",
        )
        run(
            "posts",
            """INSERT INTO posts SELECT * FROM b.posts WHERE true
               ON CONFLICT(source,external_id) DO UPDATE SET
                 artist_id=excluded.artist_id, artist_name=excluded.artist_name,
                 artist_handle=excluded.artist_handle, title=excluded.title,
                 caption=excluded.caption, page_count=excluded.page_count,
                 illust_type=excluded.illust_type, is_r18=excluded.is_r18,
                 posted_at=excluded.posted_at, fetched_at=excluded.fetched_at,
                 permalink=excluded.permalink, bookmark_count=excluded.bookmark_count,
                 source_meta=excluded.source_meta, raw_sha=excluded.raw_sha, state=excluded.state
               WHERE excluded.fetched_at > posts.fetched_at""",
        )
        for t in (
            "post_watches",
            "post_tags",
            "media",
            "raw_payloads",
            "quarantine",
            "poll_state",
            "extraction_stats",
            "image_kinds",
            "image_people",
            "image_identity",
            "image_characters",
            "image_origin",
            "image_label",
        ):
            run(t, f"INSERT OR IGNORE INTO {t} SELECT * FROM b.{t}")
        run(
            "tag_stats",
            """INSERT INTO tag_stats SELECT * FROM b.tag_stats WHERE true
               ON CONFLICT(slug,tag_norm) DO UPDATE SET
                 state=CASE WHEN tag_stats.state='suggested' THEN excluded.state
                            ELSE tag_stats.state END""",
        )
        # the visited gate: gone and skipped freely, indexed only with its post, failed never
        run(
            "seen_posts",
            """INSERT OR IGNORE INTO seen_posts
               SELECT * FROM b.seen_posts s WHERE s.state IN ('gone','skipped')
                  OR (s.state='indexed' AND EXISTS (SELECT 1 FROM b.posts p
                        WHERE p.source=s.source AND p.external_id=s.external_id))""",
        )
        conn.execute(
            """UPDATE seen_posts SET threshold=(SELECT min(s.threshold) FROM b.seen_posts s
                 WHERE s.source=seen_posts.source AND s.external_id=seen_posts.external_id)
               WHERE state='skipped' AND threshold IS NOT NULL AND EXISTS (
                 SELECT 1 FROM b.seen_posts s
                 WHERE s.source=seen_posts.source AND s.external_id=seen_posts.external_id
                   AND s.state='skipped' AND s.threshold < seen_posts.threshold)"""
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("DETACH DATABASE b")
    return counts


def _restore(conn: sqlite3.Connection, snap: Path) -> dict[str, int]:
    """Replace every merge table with the bundle's, keeping this machine's
    runtime state (jobs, queue, trash). One transaction."""
    conn.execute("ATTACH DATABASE ? AS b", (str(snap),))
    counts: dict[str, int] = {}
    try:
        conn.execute("BEGIN")
        for t in ("watches", *MERGE_TABLES):
            conn.execute(f"DELETE FROM {t}")
            counts[t] = conn.execute(f"INSERT INTO {t} SELECT * FROM b.{t}").rowcount
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("DETACH DATABASE b")
    counts["characters"] = counts.pop("watches", 0)
    return counts


def _on_disk_hashes(store: Store, blobs: BlobStore, artist_id: str) -> list[tuple[str, int]]:
    """The artist's images whose bytes are already in blobs/: what a new one
    is compared against - the same scope as dedupe.classify, minus rows the
    merge just added whose bytes are still staged."""
    rows = store.conn.execute(
        """SELECT m.sha256, m.phash, m.ext FROM media m
           JOIN posts p ON p.source=m.source AND p.external_id=m.external_id
           WHERE m.phash IS NOT NULL AND m.sha256 IS NOT NULL AND m.state='stored'
             AND (p.artist_id=? OR p.artist_handle=?)""",
        (artist_id, artist_id),
    ).fetchall()
    return [
        (r["sha256"], from_signed(r["phash"])) for r in rows if blobs.exists(r["sha256"], r["ext"])
    ]


def _place_blobs(
    store: Store,
    blobs: BlobStore,
    thumbs: ThumbStore,
    staged: Path,
    threshold: int,
    progress: Progress,
    check: Check,
) -> dict[str, int]:
    """After the transaction committed: move staged bytes into blobs/ and
    thumbs/. A new image gets the artist-scoped near-dupe check a crawled
    one gets; a `stored` row whose bytes never arrived goes back to
    `pending`, so the next crawl re-downloads it from the url it kept."""
    placed = dupes = refetch = 0
    rows = store.conn.execute(
        """SELECT m.source, m.external_id, m.idx, m.sha256, m.ext, m.phash, p.artist_id
           FROM media m JOIN posts p ON p.source=m.source AND p.external_id=m.external_id
           WHERE m.state='stored' AND m.sha256 IS NOT NULL"""
    ).fetchall()
    total = len(rows)
    for i, r in enumerate(rows):
        check()
        sha, ext = r["sha256"], r["ext"]
        key = (r["source"], r["external_id"], r["idx"])
        dest = blobs.path_for(sha, ext)
        if dest.exists():
            continue
        src = staged / f"{sha}.{ext}"
        if not src.exists():
            store.conn.execute(
                "UPDATE media SET state='pending', sha256=NULL, phash=NULL, dupe_of=NULL, "
                "error=NULL WHERE source=? AND external_id=? AND idx=?",
                key,
            )
            refetch += 1
            continue
        near = None
        if r["phash"] is not None:
            h = from_signed(int(r["phash"]))
            for other_sha, other_h in _on_disk_hashes(store, blobs, r["artist_id"]):
                if other_sha != sha and hamming(h, other_h) <= threshold:
                    near = other_sha
                    break
        if near is not None:
            store.conn.execute(
                "UPDATE media SET state='dupe', dupe_of=? WHERE source=? AND external_id=? AND idx=?",
                (near, *key),
            )
            dupes += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dest)
        except OSError:
            shutil.copy2(src, dest)
        placed += 1
        if not thumbs.exists(sha):
            t = staged / f"{sha}.webp"
            if t.exists():
                td = thumbs.path_for(sha)
                td.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(t, td)
            else:
                thumbs.make(sha, dest.read_bytes())
        if i % 50 == 0:
            progress("place", i, total)
    return {"placed": placed, "dupes": dupes, "refetch": refetch}


def _apply_config(cfg: Config, incoming: dict[str, Any]) -> None:
    for k, v in incoming.items():
        if k in MACHINE_KEYS or k in SECRET_KEYS or not hasattr(cfg, k):
            continue
        setattr(cfg, k, v)
    cfg.save()


def import_(
    store: Store,
    blobs: BlobStore,
    thumbs: ThumbStore,
    cfg: Config,
    path: Path,
    opts: ImportOptions | None = None,
    progress: Progress = _noop,
    check: Check = _nocheck,
) -> dict[str, Any]:
    """Verify, stage, merge (or restore), place. Raises BundleError before
    anything is written when the bundle is unusable; once the transaction
    commits the library is fully merged. Returns the counts, the damaged
    entry names, and the bundle's ui state when settings were taken."""
    opts = opts or ImportOptions()
    path = Path(path)
    progress("verify", 0, None)
    report = verify(path, check=check)
    damaged = set(report["damaged"])
    if DB in damaged:
        raise BundleError("damaged", "the bundle's database does not verify")
    if damaged and not opts.salvage:
        raise BundleError(
            "damaged", f"{len(damaged)} damaged entries; import with salvage to go on"
        )
    staging = Path(cfg.home) / "import" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    staging.mkdir(parents=True, exist_ok=True)
    r = open_reader(path)
    try:
        snap = _staged_db(r, staging)
        names = r.names() - damaged
        imgs = [n for n in names if n.startswith((BLOB_PREFIX, THUMB_PREFIX))]
        progress("stage", 0, len(imgs))
        for i, n in enumerate(sorted(imgs)):
            check()
            if not r.extract(n, staging / n.split("/", 1)[1]):
                damaged.add(n)
            if i % 50 == 0:
                progress("stage", i, len(imgs))
        config_in = json.loads(r.read(CONFIG)) if CONFIG in names else {}
        secrets_in = json.loads(r.read(SECRETS)) if opts.secrets and SECRETS in names else {}
        ui = json.loads(r.read(UI)) if UI in names else {}
        r.close()
        progress("merge", 0, None)
        take = opts.mode == "restore" or opts.settings == "take"
        counts = (
            _restore(store.conn, snap) if opts.mode == "restore" else _merge(store.conn, snap, opts)
        )
        placed = _place_blobs(store, blobs, thumbs, staging, cfg.dupe_threshold, progress, check)
        if take:
            _apply_config(cfg, config_in)
        if secrets_in:
            for k, v in secrets_in.items():
                if k in SECRET_KEYS and v:
                    setattr(cfg, k, v)
            cfg.save_secrets()
        return {
            "mode": opts.mode,
            "damaged": sorted(damaged),
            "ui": ui if take else None,
            **counts,
            **placed,
        }
    finally:
        r.close()
        shutil.rmtree(staging, ignore_errors=True)
