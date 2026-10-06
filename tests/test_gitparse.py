"""Unit tests for the streaming `git log --numstat -z` parser."""
from __future__ import annotations

from rat.gitparse import BINARY, LogParser, parse_record

FIELD = "\x1f"
REC = "\x1e"


def header(sha: str, ts: int, name: str, email: str, parents: str, term: str = "\n") -> str:
    return f"{sha}{FIELD}{ts}{FIELD}{name}{FIELD}{email}{FIELD}{parents}{term}"


def test_plain_entry():
    rec = header("abc", 100, "Ann", "a@x", "p1") + "5\t2\tsrc/f.py\x00"
    r = parse_record(rec)
    assert r is not None
    assert (r.sha, r.ts, r.name, r.email, r.parent_sha) == ("abc", 100, "Ann", "a@x", "p1")
    (e,) = r.entries
    assert (e.added, e.removed, e.path, e.old_path) == (5, 2, "src/f.py", None)


def test_root_commit_has_no_parent():
    rec = header("r1", 100, "Ann", "a@x", "") + "3\t0\tf.txt\x00"
    r = parse_record(rec)
    assert r is not None
    assert r.parent_sha is None
    assert r.entries[0].added == 3


def test_merge_first_parent_only():
    rec = header("m", 100, "Ann", "a@x", "p1 p2") + "1\t0\tf\x00"
    r = parse_record(rec)
    assert r is not None
    assert r.parent_sha == "p1"


def test_empty_commit_no_entries():
    rec = header("e1", 100, "Ann", "a@x", "p1", term="\x00")
    r = parse_record(rec)
    assert r is not None
    assert r.entries == []


def test_empty_commit_nul_then_nothing():
    rec = header("e2", 100, "Ann", "a@x", "", term="\n")
    r = parse_record(rec)
    assert r is not None
    assert r.parent_sha is None
    assert r.entries == []


def test_rename_entry_keeps_both_paths():
    rec = header("r", 100, "Ann", "a@x", "p") + "0\t0\t\x00old.txt\x00new.txt\x00"
    r = parse_record(rec)
    assert r is not None
    (e,) = r.entries
    assert (e.added, e.removed, e.path, e.old_path) == (0, 0, "new.txt", "old.txt")


def test_binary_entry():
    rec = header("b", 100, "Ann", "a@x", "p") + "-\t-\timg.png\x00"
    r = parse_record(rec)
    assert r is not None
    (e,) = r.entries
    assert e.is_binary
    assert e.added == BINARY


def test_mixed_entries_in_one_commit():
    rec = (
        header("mix", 100, "Ann", "a@x", "p")
        + "1\t0\tsrc/a.py\x00"
        + "-\t-\timg.png\x00"
        + "0\t0\t\x00old.py\x00new.py\x00"
        + "2\t3\tsrc/b.py\x00"
    )
    r = parse_record(rec)
    assert r is not None
    assert len(r.entries) == 4
    assert [e.path for e in r.entries] == ["src/a.py", "img.png", "new.py", "src/b.py"]
    assert r.entries[2].old_path == "old.py"


def test_malformed_records_return_none():
    assert parse_record("") is None
    assert parse_record("only\x1ftwo") is None
    bad_ts = f"x{FIELD}nope{FIELD}A{FIELD}a@x{FIELD}p\n1\t0\tf\x00"
    assert parse_record(bad_ts) is None


def test_truncated_rename_is_ignored():
    rec = header("t", 100, "Ann", "a@x", "p") + "0\t0\t\x00oldonly\x00"
    r = parse_record(rec)
    assert r is not None
    assert r.entries == []


def test_incremental_feed_across_chunk_boundaries():
    rec1 = header("s1", 1, "A", "a@x", "") + "1\t0\tf1\x00"
    rec2 = header("s2", 2, "B", "b@x", "s1") + "2\t0\tf2\x00"
    stream = (REC + rec1 + REC + rec2 + REC).encode()
    parser = LogParser()
    out = []
    for i in range(0, len(stream), 7):  # tiny chunks split records mid-way
        out.extend(parser.feed(stream[i : i + 7]))
    out.extend(parser.finish())
    assert [r.sha for r in out] == ["s1", "s2"]
    assert out[1].entries[0].added == 2


def test_finish_without_leading_separator():
    """The first record has no leading \\x1e; finish() must still return it."""
    rec1 = header("q1", 1, "A", "a@x", "") + "1\t0\tf\x00"
    parser = LogParser()
    assert parser.feed((REC + rec1).encode()) == []  # rec1 still buffered
    rec2 = header("q2", 2, "B", "b@x", "q1") + "1\t0\tg\x00"
    out = parser.feed((REC + rec2).encode())
    assert [r.sha for r in out] == ["q1"]
    out = parser.finish()
    assert [r.sha for r in out] == ["q2"]
