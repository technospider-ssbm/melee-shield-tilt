#!/usr/bin/env python3
"""Extract named files from a GameCube ISO (GCM) via its FST.

Usage:
    python gcm_extract.py --iso PATH --list
    python gcm_extract.py --iso PATH --out DIR PATTERN [PATTERN ...]

Patterns are matched against the FST file name (case-insensitive, simple
fnmatch-style wildcards, e.g. "Pl??.dat", "PlCo.dat").
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import struct
import sys
from pathlib import Path

EXPECTED_GAME_ID = "GALE01"
EXPECTED_REVISION = 2


class FSTEntry:
    __slots__ = ("is_dir", "name_offset", "parent_or_offset", "size_or_next", "name", "path")

    def __init__(self, is_dir, name_offset, parent_or_offset, size_or_next):
        self.is_dir = is_dir
        self.name_offset = name_offset
        self.parent_or_offset = parent_or_offset  # file: data offset; dir: parent index
        self.size_or_next = size_or_next  # file: size; dir: index of first entry after subtree
        self.name = ""
        self.path = ""


def read_header(f):
    f.seek(0)
    header = f.read(0x440)
    game_id = header[0:6].decode("ascii", errors="replace")
    revision = header[7]
    fst_offset = struct.unpack_from(">I", header, 0x424)[0]
    fst_size = struct.unpack_from(">I", header, 0x428)[0]
    return game_id, revision, fst_offset, fst_size


def read_cstring(buf: bytes, offset: int) -> str:
    end = buf.index(b"\x00", offset)
    return buf[offset:end].decode("shift_jis", errors="replace")


def parse_fst(f, fst_offset: int, fst_size: int):
    f.seek(fst_offset)
    fst_data = f.read(fst_size)

    # root entry (index 0) gives total entry count
    num_entries = struct.unpack_from(">I", fst_data, 8)[0]
    string_table_offset = num_entries * 12

    entries = []
    for i in range(num_entries):
        base = i * 12
        flag_name = struct.unpack_from(">I", fst_data, base)[0]
        is_dir = bool(flag_name >> 24)
        name_offset = flag_name & 0xFFFFFF
        parent_or_offset = struct.unpack_from(">I", fst_data, base + 4)[0]
        size_or_next = struct.unpack_from(">I", fst_data, base + 8)[0]
        entry = FSTEntry(is_dir, name_offset, parent_or_offset, size_or_next)
        if i != 0:
            entry.name = read_cstring(fst_data, string_table_offset + name_offset)
        entries.append(entry)

    # build full paths by walking the directory tree with the standard
    # "next entry after subtree" algorithm.
    def build_paths(idx: int, cur_path: str, end: int):
        i = idx
        while i < end:
            e = entries[i]
            if e.is_dir:
                next_idx = e.size_or_next
                e.path = f"{cur_path}{e.name}/"
                build_paths(i + 1, e.path, next_idx)
                i = next_idx
            else:
                e.path = f"{cur_path}{e.name}"
                i += 1

    build_paths(1, "", num_entries)
    return entries


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso", required=True, type=Path, help="Path to the GCM/ISO file")
    ap.add_argument("--out", type=Path, default=None, help="Output directory for extracted files")
    ap.add_argument("--list", action="store_true", help="List all files in the FST and exit")
    ap.add_argument("patterns", nargs="*", help="fnmatch-style filename patterns to extract, e.g. Pl??.dat")
    ap.add_argument("--skip-check", action="store_true", help="Skip game ID / revision verification (not recommended)")
    args = ap.parse_args()

    if not args.iso.exists():
        print(f"ERROR: ISO not found: {args.iso}", file=sys.stderr)
        sys.exit(1)

    with open(args.iso, "rb") as f:
        game_id, revision, fst_offset, fst_size = read_header(f)

        if not args.skip_check:
            if game_id != EXPECTED_GAME_ID:
                print(f"ERROR: game ID mismatch: got {game_id!r}, expected {EXPECTED_GAME_ID!r}", file=sys.stderr)
                sys.exit(1)
            if revision != EXPECTED_REVISION:
                print(f"ERROR: revision mismatch: got {revision}, expected {EXPECTED_REVISION} (NTSC 1.02)", file=sys.stderr)
                sys.exit(1)

        print(f"Game ID: {game_id}  Revision: {revision}  FST offset: 0x{fst_offset:X}  FST size: 0x{fst_size:X}", file=sys.stderr)

        entries = parse_fst(f, fst_offset, fst_size)
        files = [e for e in entries if not e.is_dir]

        if args.list:
            for e in files:
                print(f"{e.parent_or_offset:#010x}  {e.size_or_next:#010x}  {e.path}")
            return

        if not args.patterns:
            print("ERROR: no patterns given (use --list to see available files, or provide patterns)", file=sys.stderr)
            sys.exit(1)

        if args.out is None:
            print("ERROR: --out is required when extracting", file=sys.stderr)
            sys.exit(1)

        args.out.mkdir(parents=True, exist_ok=True)

        matched = []
        for e in files:
            base_name = e.path.rsplit("/", 1)[-1]
            for pat in args.patterns:
                if fnmatch.fnmatch(base_name.lower(), pat.lower()):
                    matched.append(e)
                    break

        if not matched:
            print("WARNING: no files matched the given patterns", file=sys.stderr)

        for e in matched:
            out_path = args.out / e.path.rsplit("/", 1)[-1]
            f.seek(e.parent_or_offset)
            data = f.read(e.size_or_next)
            out_path.write_bytes(data)
            digest = hashlib.sha1(data).hexdigest()
            print(f"extracted {e.path} -> {out_path}  size=0x{len(data):X}  sha1={digest}")


if __name__ == "__main__":
    main()
