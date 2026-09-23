#!/usr/bin/env python3
"""Reject unreviewed files and common private artifacts in this public tree."""

from pathlib import Path
import re
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATH = re.compile(r"/(?:home/(?!example/|user/|runner/)[^/\s]+|root|Users/(?!example/)[^/\s]+)/")
SENSITIVE_SUFFIXES = (".jsonl", ".sqlite", ".sqlite3", ".db", ".pem", ".key", ".log", ".cast")


def png_problem(data):
    """Accept bounded RGB/RGBA PNGs without metadata or trailing payloads."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "Invalid PNG signature"
    cursor = 8
    seen_header = False
    compressed = []
    row_size = raw_size = 0
    while cursor < len(data):
        if cursor + 12 > len(data):
            return "Truncated PNG chunk"
        length = struct.unpack(">I", data[cursor:cursor + 4])[0]
        kind = data[cursor + 4:cursor + 8]
        end = cursor + length + 12
        if end > len(data):
            return "Truncated PNG payload"
        payload = data[cursor + 8:end - 4]
        checksum = struct.unpack(">I", data[end - 4:end])[0]
        if zlib.crc32(kind + payload) != checksum:
            return "Invalid PNG checksum"
        if not seen_header and kind != b"IHDR":
            return "PNG header must come first"
        if kind == b"IHDR":
            if seen_header or length != 13:
                return "Invalid PNG header"
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload)
            if not width or not height or depth != 8 or color not in {2, 6} or any(
                    (compression, filtering, interlace)):
                return "Unsupported PNG format"
            row_size = 1 + width * (3 if color == 2 else 4)
            raw_size = row_size * height
            if raw_size > 64_000_000:
                return "PNG decoded image is too large"
            seen_header = True
        elif kind == b"IDAT":
            compressed.append(payload)
        elif kind == b"IEND":
            if length or not compressed:
                return "Invalid PNG ending"
            if end != len(data):
                return "Trailing data after PNG ending"
            try:
                decoder = zlib.decompressobj()
                pixels = decoder.decompress(b"".join(compressed), raw_size + 1)
            except zlib.error:
                return "Invalid PNG image data"
            if (len(pixels) != raw_size or not decoder.eof
                    or decoder.unused_data or decoder.unconsumed_tail):
                return "Invalid or trailing compressed PNG data"
            if any(pixels[offset] > 4 for offset in range(0, raw_size, row_size)):
                return "Invalid PNG row filter"
            return None
        else:
            return "Unexpected PNG metadata or chunk"
        cursor = end
    return "Missing PNG ending"


def main():
    expected = {line.strip() for line in (ROOT / "public-files.txt").read_text().splitlines()
                if line.strip() and not line.startswith("#")}
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, capture_output=True, check=True)
    actual = {item.decode() for item in result.stdout.split(b"\0") if item}
    problems = [f"Unreviewed file: {name}" for name in sorted(actual - expected)]
    problems += [f"Missing public file: {name}" for name in sorted(expected - actual)]
    for name in sorted(actual):
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            problems.append(f"Not a regular source file: {name}")
            continue
        if path.name.startswith(".env") or name.endswith(SENSITIVE_SUFFIXES):
            problems.append(f"Private artifact type: {name}")
        data = path.read_bytes()
        if len(data) > 2_000_000:
            problems.append(f"Unexpected large artifact: {name}")
        if name.endswith(".png"):
            if not name.startswith("docs/assets/"):
                problems.append(f"Unexpected image: {name}")
                continue
            problem = png_problem(data)
            if problem:
                problems.append(f"{problem}: {name}")
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"Unexpected binary: {name}")
            continue
        if PRIVATE_PATH.search(text):
            problems.append(f"Personal absolute path: {name}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"Publication manifest: {len(actual)} reviewed files; no private artifact types, image metadata, or trailing PNG data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
