"""Streaming parser for the single-pass `git log --numstat -z` output.

The ingest command emits one record per commit:

    \\x1e<sha>\\x1f<committer-ts>\\x1f<name>\\x1f<email>\\x1f<parents>\\n
        <added>\\t<removed>\\t<path>\\0
        <added>\\t<removed>\\t\\0<oldpath>\\0<newpath>\\0   (renames)
        ...

Binary entries carry '-' for both counts. Pure renames report 0\\t0. Empty
commits carry no entries. See tests/calibrate_numstat.py for the byte-level
ground truth this parser was built against.
"""
from __future__ import annotations

from dataclasses import dataclass

REC_SEP = b"\x1e"
FIELD_SEP = "\x1f"
BINARY = -1


@dataclass(slots=True)
class Entry:
    added: int              # BINARY (-1) for binary files
    removed: int
    path: str               # attributed path (new path for renames)
    old_path: str | None = None

    @property
    def is_binary(self) -> bool:
        return self.added == BINARY


@dataclass(slots=True)
class CommitRecord:
    sha: str
    ts: int
    name: str
    email: str
    parent_sha: str | None
    entries: list[Entry]


class LogParser:
    """Incremental parser: feed() raw byte chunks, get CommitRecords back."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, chunk: bytes) -> list[CommitRecord]:
        self._buf += chunk
        recs = self._buf.split(REC_SEP)
        self._buf = recs.pop()
        out = []
        for rec in recs:
            parsed = parse_record(rec.decode("utf-8", errors="replace"))
            if parsed is not None:
                out.append(parsed)
        return out

    def finish(self) -> list[CommitRecord]:
        rec, self._buf = self._buf, b""
        parsed = parse_record(rec.decode("utf-8", errors="replace")) if rec else None
        return [parsed] if parsed is not None else []


def _count(field: str) -> int:
    return BINARY if field == "-" else int(field)


def parse_record(rec: str) -> CommitRecord | None:
    """Parse one record (the text between two \\x1e separators)."""
    if not rec:
        return None
    parts = rec.split(FIELD_SEP, 4)
    if len(parts) < 5:
        return None
    sha, ts, name, email, tail = parts

    # The parents field is terminated by '\n' (entries follow) or '\0' (empty commit).
    cut = -1
    for idx in (tail.find("\n"), tail.find("\x00")):
        if idx != -1 and (cut == -1 or idx < cut):
            cut = idx
    if cut == -1:
        parents, rest = tail, ""
    else:
        parents, rest = tail[:cut], tail[cut + 1:]
    parent_sha = parents.split(" ", 1)[0] or None

    entries: list[Entry] = []
    segments = rest.split("\x00")
    i, n = 0, len(segments)
    while i < n:
        seg = segments[i]
        if seg.startswith("\n"):
            seg = seg[1:]
        if seg == "":
            i += 1
            continue
        fields = seg.split("\t", 2)
        if len(fields) != 3:
            i += 1  # malformed segment; be defensive
            continue
        added, removed, path = fields
        if path == "":
            # Rename entry: the next two NUL-terminated segments are old and new path.
            old = segments[i + 1] if i + 1 < n else ""
            new = segments[i + 2] if i + 2 < n else ""
            i += 3
            if new:
                entries.append(Entry(_count(added), _count(removed), new, old))
        else:
            entries.append(Entry(_count(added), _count(removed), path))
            i += 1

    try:
        ts_int = int(ts)
    except ValueError:
        return None
    return CommitRecord(
        sha=sha, ts=ts_int, name=name, email=email, parent_sha=parent_sha, entries=entries
    )
