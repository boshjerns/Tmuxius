#!/usr/bin/env python3
"""Reject unreviewed files and common private artifacts in this public tree."""

from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATH = re.compile(r"/(?:home/(?!example/|user/|runner/)[^/\s]+|root|Users/(?!example/)[^/\s]+)/")
SENSITIVE_SUFFIXES = (".jsonl", ".sqlite", ".sqlite3", ".db", ".pem", ".key", ".log", ".cast")


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
            if not name.startswith("docs/assets/") or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                problems.append(f"Unexpected image: {name}")
                continue
            cursor = 8
            while cursor + 12 <= len(data):
                length = struct.unpack(">I", data[cursor:cursor + 4])[0]
                kind = data[cursor + 4:cursor + 8]
                if kind not in {b"IHDR", b"IDAT", b"IEND"}:
                    problems.append(f"Unexpected image metadata: {name}")
                    break
                cursor += length + 12
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
    print(f"Publication manifest: {len(actual)} reviewed files; no private artifact types or image metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
