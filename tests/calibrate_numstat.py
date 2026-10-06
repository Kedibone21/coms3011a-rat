#!/usr/bin/env python3
"""Byte-format calibration for the ingester's single-pass git log command.

Creates a scratch repository exercising the tricky cases (root commit, rename+edit,
pure rename, binary add/rename, deletion, empty file, paths with spaces/unicode/commas,
an empty commit, a merge commit, and a .mailmap), then prints the raw `-z` output of the
exact command the ingester uses, so the parser can be written against observed reality.

Run:  python3 tests/calibrate_numstat.py
"""
from __future__ import annotations

import pathlib
import subprocess
import tempfile

GITCFG = [
    "-c", "user.name=Cal",
    "-c", "user.email=cal@example.com",
    "-c", "commit.gpgsign=false",
]


def git(cwd: str, *args: str, check: bool = True) -> bytes:
    r = subprocess.run(["git", *GITCFG, *args], cwd=cwd, capture_output=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args} failed:\n{r.stderr.decode(errors='replace')}")
    return r.stdout


def main() -> None:
    d = tempfile.mkdtemp(prefix="nsprobe-")
    print("probe repo:", d)
    git(d, "init", "-q", "-b", "main")
    p = pathlib.Path(d)

    # commit one: root commit, two files
    (p / "f.txt").write_text("a\nb\nc\n")
    (p / "g.txt").write_text("x\ny\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "one")

    # commit two: rename+edit, binary, empty file, spaced/unicode/comma paths
    git(d, "mv", "f.txt", "h.txt")
    (p / "h.txt").write_text("a\nB\nc\nd\n")
    (p / "bin.dat").write_bytes(b"\x00\x01\x02\x03")
    (p / "empty.txt").write_text("")
    (p / "spaced dir").mkdir()
    (p / "spaced dir" / "wei rd @name.txt").write_text("hi\n")
    (p / "na\u00efve.txt").write_text("\u00fc\n")
    (p / "com,ma.txt").write_text("z\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "two")

    # empty commit
    git(d, "commit", "--allow-empty", "-qm", "empty-commit")

    # commit three: deletion, pure rename of binary, pure rename of empty file
    git(d, "rm", "-q", "g.txt")
    git(d, "mv", "bin.dat", "bin2.dat")
    git(d, "mv", "empty.txt", "empty2.txt")
    git(d, "commit", "-qm", "three")

    # merge commit (must be skipped by --no-merges)
    git(d, "checkout", "-qb", "side")
    (p / "s.txt").write_text("s\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "side1")
    git(d, "checkout", "-q", "main")
    git(d, "merge", "--no-ff", "-m", "merge side", "side")

    # commit four: mailmap that maps cal@example.com
    (p / ".mailmap").write_text("Mapped Cal <mapped@example.com> <cal@example.com>\n")
    (p / "m.txt").write_text("m\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "four")

    cmd = [
        "log", "--no-merges", "--root", "--numstat", "-z", "-M50%", "--use-mailmap",
        "--pretty=format:%x1e%H%x1f%ct%x1f%aN%x1f%aE", "HEAD", "--",
    ]
    out = git(d, *cmd).decode("utf-8", errors="replace")

    print("\nFULL RAW OUTPUT (repr):\n")
    print(repr(out))
    print("\nRECORDS (split on \\x1e):\n")
    for rec in out.split("\x1e"):
        if rec.strip():
            print(repr(rec))
            print("-" * 60)


if __name__ == "__main__":
    main()
