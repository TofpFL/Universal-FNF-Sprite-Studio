"""Native .RCHR archive support.

Authoritative format spec: gh::rchr in the R-Slice engine (src/rchr.cpp).
This module is a byte-compatible Python implementation - archives written
here mount in the engine and vice versa.

Layout (all integers little-endian):

    [0..95]    header, 96 bytes
    [96..]     name blob: every entry's '/'-separated UTF-8 path, concatenated
    index      entryCount records of 40 bytes
    data       payloads, each stored raw or zlib/DEFLATE (method byte)

Header fields:
    magic[4] "RCHR", u16 version (=1), u16 flags (=0),
    u32 entryCount, u32 nameBytes,
    u64 indexOffset, u64 indexSize, u64 dataOffset, u64 dataSize,
    u32 headerCrc (crc32 of bytes [0,48)), then zero padding to 96.

Index record (40 bytes):
    u32 nameOff, u32 nameLen   (into the name blob)
    u64 dataOff                (absolute file offset of the stored payload)
    u64 storedSize, u64 rawSize
    u32 crc                    (crc32 of the raw/uncompressed bytes)
    u8  method                 (0 = stored, 1 = zlib/deflate)
    u8  reserved[3]
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Union

MAGIC = b"RCHR"
VERSION = 1
HEADER_SIZE = 96
INDEX_ENTRY_SIZE = 40
MAX_NAME = 4096
MAX_FILE = 512 << 20  # same sanity bound the C++ reader uses

PathLike = Union[str, os.PathLike]


class RchrError(Exception):
    pass


@dataclass
class Entry:
    path: str                 # install-relative, '/'-separated
    offset: int = 0           # absolute file offset of stored payload
    stored_size: int = 0
    raw_size: int = 0
    crc: int = 0              # of the raw/uncompressed bytes
    method: int = 0           # 0 store, 1 zlib/deflate


def is_rchr_file(path: PathLike) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == MAGIC
    except OSError:
        return False


def _norm_name(name: str) -> str:
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name.lstrip("/")


def _safe_rel(rel: str) -> bool:
    """Refuse paths that could escape the destination when extracted."""
    if not rel or "\\" in rel or rel.startswith("/") or ":" in rel:
        return False
    for part in rel.split("/"):
        if part in ("", ".", ".."):
            return False
    return True


def _read_all(path: PathLike) -> bytes:
    with open(path, "rb") as f:
        return f.read()


class Archive:
    """A parsed .rchr file. Cheap to construct - only header+index are read."""

    def __init__(self, path: PathLike):
        self.path = str(path)
        self.entries: list[Entry] = []
        self._name_blob = b""
        self._parse()

    def _parse(self) -> None:
        size = os.path.getsize(self.path)
        with open(self.path, "rb") as f:
            header = f.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE:
            raise RchrError("short header")
        if header[:4] != MAGIC:
            raise RchrError("not an .rchr file")
        (version, _flags, entry_count, name_bytes,
         index_off, index_size, data_off, data_size, header_crc) = struct.unpack_from(
            "<HHIIQQQQI", header, 4)
        if version != VERSION:
            raise RchrError(f"unsupported .rchr version {version}")
        if zlib.crc32(header[:48]) & 0xFFFFFFFF != header_crc:
            raise RchrError("header crc mismatch")
        if index_size != entry_count * INDEX_ENTRY_SIZE:
            raise RchrError("bad index size")
        if index_off != HEADER_SIZE + name_bytes:
            raise RchrError("bad index offset")
        if data_off != index_off + index_size:
            raise RchrError("bad data offset")
        if index_off > (1 << 40) or data_off > (1 << 40) or data_size > (1 << 40):
            raise RchrError("archive too large")
        if data_off + data_size > size:
            raise RchrError("data region outside file")
        with open(self.path, "rb") as f:
            f.seek(HEADER_SIZE)
            self._name_blob = f.read(name_bytes)
            if len(self._name_blob) != name_bytes:
                raise RchrError("short name blob")
            index = f.read(index_size)
            if len(index) != index_size:
                raise RchrError("short index")
        self.data_offset = data_off
        self.data_size = data_size
        for i in range(entry_count):
            rec = index[i * INDEX_ENTRY_SIZE:(i + 1) * INDEX_ENTRY_SIZE]
            name_off, name_len, data_off_e, stored, raw, crc, method = struct.unpack_from(
                "<IIQQQIB", rec, 0)
            if name_off + name_len > len(self._name_blob):
                raise RchrError("entry name out of range")
            name = self._name_blob[name_off:name_off + name_len].decode("utf-8")
            if method > 1 or data_off_e < data_off or \
               data_off_e + stored > data_off + data_size or \
               stored > (1 << 32) or raw > (1 << 32):
                raise RchrError(f"bad entry {name}")
            self.entries.append(Entry(name, int(data_off_e), int(stored),
                                      int(raw), crc, method))

    def read_entry(self, entry: Entry) -> bytes:
        """Returns the entry's raw (uncompressed) bytes, CRC-verified."""
        if entry.offset < self.data_offset or \
           entry.offset + entry.stored_size > self.data_offset + self.data_size:
            raise RchrError("entry outside data region")
        with open(self.path, "rb") as f:
            f.seek(entry.offset)
            stored = f.read(entry.stored_size)
        if len(stored) != entry.stored_size:
            raise RchrError(f"cannot read entry data for {entry.path}")
        if entry.method == 1:
            try:
                raw = zlib.decompress(stored)
            except zlib.error as e:
                raise RchrError(f"cannot decompress {entry.path}: {e}") from e
        else:
            raw = stored
        if len(raw) != entry.raw_size:
            raise RchrError(f"size mismatch in {entry.path}")
        if zlib.crc32(raw) & 0xFFFFFFFF != entry.crc:
            raise RchrError(f"crc mismatch in {entry.path}")
        return raw

    def read(self, arcname: str) -> bytes:
        for e in self.entries:
            if e.path == arcname:
                return self.read_entry(e)
        raise RchrError(f"no such entry: {arcname}")

    def extract(self, dest_dir: PathLike) -> list[str]:
        """Extracts every entry under dest_dir. Returns written paths."""
        dest = Path(dest_dir)
        written = []
        for e in self.entries:
            if not _safe_rel(e.path):
                raise RchrError(f"unsafe path in archive: {e.path}")
            out = dest / e.path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(self.read_entry(e))
            written.append(str(out))
        return written


def list_entries(path: PathLike) -> list[Entry]:
    return Archive(path).entries


def read_entry_file(path: PathLike, arcname: str) -> bytes:
    return Archive(path).read(arcname)


def extract_archive(rchr_path: PathLike, dest_dir: PathLike) -> list[str]:
    return Archive(rchr_path).extract(dest_dir)


def pack(out_path: PathLike, files: Iterable[tuple[str, PathLike]]) -> dict:
    """Packs (arcname, disk-path-or-bytes) pairs into a new .rchr archive.

    `files` items are (install-relative arcname, source). Source may be a
    filesystem path or raw bytes. Entries are stored raw when deflate would
    not shrink them (same rule as the C++ packer).
    Returns stats: {entries, raw_bytes, stored_bytes}.
    """
    items: list[tuple[str, bytes]] = []
    name_bytes = 0
    for arc, src in files:
        name = _norm_name(arc)
        if not _safe_rel(name):
            raise RchrError(f"bad archive path: {arc}")
        if isinstance(src, (bytes, bytearray, memoryview)):
            raw = bytes(src)
        else:
            raw = _read_all(src)
        if len(raw) > MAX_FILE:
            raise RchrError(f"file too large: {name}")
        items.append((name, raw))
        name_bytes += len(name.encode("utf-8"))
    if not items:
        raise RchrError("nothing to pack")

    # Per-entry payloads: deflate only when it actually shrinks.
    stored_blobs: list[bytes] = []
    methods: list[int] = []
    for _name, raw in items:
        if raw:
            comp = zlib.compress(raw, 6)
            if len(comp) < len(raw):
                stored_blobs.append(comp)
                methods.append(1)
                continue
        stored_blobs.append(raw)
        methods.append(0)

    name_blob = bytearray()
    name_offs = []
    for name, _raw in items:
        name_offs.append(len(name_blob))
        name_blob += name.encode("utf-8")

    entry_count = len(items)
    index_off = HEADER_SIZE + len(name_blob)
    index_size = entry_count * INDEX_ENTRY_SIZE
    data_off = index_off + index_size

    index = bytearray(index_size)
    data_pos = data_off
    data_chunks = []
    for i, ((name, raw), blob, method) in enumerate(zip(items, stored_blobs, methods)):
        struct.pack_into("<II", index, i * INDEX_ENTRY_SIZE, name_offs[i], len(name.encode("utf-8")))
        struct.pack_into("<QQQ", index, i * INDEX_ENTRY_SIZE + 8, data_pos, len(blob), len(raw))
        struct.pack_into("<I", index, i * INDEX_ENTRY_SIZE + 32, zlib.crc32(raw) & 0xFFFFFFFF)
        index[i * INDEX_ENTRY_SIZE + 36] = method
        data_pos += len(blob)
        data_chunks.append(blob)
    data_size = data_pos - data_off

    header = bytearray(HEADER_SIZE)
    header[0:4] = MAGIC
    struct.pack_into("<HH", header, 4, VERSION, 0)
    struct.pack_into("<II", header, 8, entry_count, len(name_blob))
    struct.pack_into("<QQQQ", header, 16, index_off, index_size, data_off, data_size)
    struct.pack_into("<I", header, 48, zlib.crc32(bytes(header[:48])) & 0xFFFFFFFF)

    with open(out_path, "wb") as f:
        f.write(header)
        f.write(name_blob)
        f.write(index)
        for blob in data_chunks:
            f.write(blob)

    raw_total = sum(len(r) for _n, r in items)
    stored_total = sum(len(b) for b in stored_blobs)
    return {"entries": entry_count, "raw_bytes": raw_total, "stored_bytes": stored_total}


def mount_dir(rchr_path: PathLike, cache_root: PathLike) -> Path:
    """Extracts `rchr_path` into <cache_root>/<crc32-hex>/ once (sentinel-
    guarded), mirroring gh::rchr::mountDir. Returns the mounted directory."""
    crc = 0
    with open(rchr_path, "rb") as f:
        while True:
            chunk = f.read(1 << 16)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    crc &= 0xFFFFFFFF
    cache = Path(cache_root)
    out_dir = cache / f"{crc:08x}"
    sentinel = out_dir / ".rchr-ok"
    if sentinel.exists():
        return out_dir
    extract_archive(rchr_path, out_dir)
    sentinel.write_text("ok")
    return out_dir
