"""End-to-end engine tests on the deterministic tiny repository.

The golden file (`tests/golden/tiny_all.csv`) freezes the byte-exact export for
the full commit set; regenerate it only with `scripts/make_golden.py` after
deliberately re-verifying the semantics against `scripts/verify.py`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rat import metrics

GOLDEN = Path(__file__).parent / "golden" / "tiny_all.csv"


def find(rows, object_type, path, author="ALL"):
    for r in rows:
        if (
            r["object_type"] == object_type
            and r["path"] == path
            and r["author"] == author
        ):
            return r
    raise AssertionError(f"no row {object_type} {path} {author}")


def author_rows(rows, object_type, path):
    return [
        r
        for r in rows
        if r["object_type"] == object_type and r["path"] == path and r["author"] != "ALL"
    ]


def _aid(conn, repo_id, email):
    return conn.execute(
        "SELECT id FROM authors WHERE repo_id = ? AND email = ?", (repo_id, email)
    ).fetchone()[0]


# ---- full set -----------------------------------------------------------------

def test_ingest_counts(tiny):
    assert tiny.n == 5  # the empty commit c5 is part of |H|
    assert tiny.ref_sha == tiny.shas[4]


def test_all_set_matches_golden(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",))
    assert metrics.rows_to_csv(rows).encode() == GOLDEN.read_bytes()


def test_row_structure_and_order(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",))
    assert [(r["object_type"], r["path"], r["author"]) for r in rows] == [
        ("repository", "/", "ALL"),
        ("repository", "/", "Alice <alice@example.com>"),
        ("repository", "/", "Bob <bob@example.com>"),
        ("directory", "dir", "ALL"),
        ("directory", "dir", "Alice <alice@example.com>"),
        ("directory", "dir", "Bob <bob@example.com>"),
        ("file", "a.txt", "ALL"),
        ("file", "a.txt", "Alice <alice@example.com>"),
        ("file", "dir/b.txt", "ALL"),
        ("file", "dir/b.txt", "Alice <alice@example.com>"),
        ("file", "dir/b.txt", "Bob <bob@example.com>"),
        ("file", "dir/c.txt", "ALL"),
        ("file", "dir/c.txt", "Alice <alice@example.com>"),
        ("file", "dir/c2.txt", "ALL"),
    ]


def test_repository_totals(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",))
    root = find(rows, "repository", "/")
    assert root["commit_count"] == 5
    assert root["commit_set"] == "all"
    assert (root["added"], root["removed"], root["growth"], root["churn"]) == (7, 0, 7, 7)
    assert root["modifications"] == 3
    assert root["modification_frequency"] == pytest.approx(3 * (1 / 5))
    assert root["churn_rate"] == pytest.approx(7 * (1 / 5))
    assert root["ownership"] == ""


def test_author_split_and_ownership(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",))
    alice = find(rows, "repository", "/", "Alice <alice@example.com>")
    bob = find(rows, "repository", "/", "Bob <bob@example.com>")
    assert (alice["added"], alice["churn"], alice["modifications"]) == (6, 6, 2)
    assert alice["ownership"] == pytest.approx(6 / 7)
    assert alice["modification_frequency"] == "" and alice["churn_rate"] == ""
    assert (bob["added"], bob["churn"], bob["modifications"]) == (1, 1, 1)
    assert bob["ownership"] == pytest.approx(1 / 7)


def test_rename_old_path_stays_member(tiny):
    """dir/c.txt (old path) keeps its delta; dir/c2.txt (new path) is all-zero."""
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",))
    old = find(rows, "file", "dir/c.txt")
    new = find(rows, "file", "dir/c2.txt")
    assert (old["added"], old["churn"], old["modifications"]) == (1, 1, 1)
    assert (new["added"], new["removed"], new["churn"], new["modifications"]) == (0, 0, 0, 0)
    assert new["modification_frequency"] == 0.0
    assert new["churn_rate"] == 0.0


def test_directory_rollup(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",))
    d = find(rows, "directory", "dir")
    assert (d["added"], d["churn"], d["modifications"]) == (3, 3, 3)
    alice = find(rows, "directory", "dir", "Alice <alice@example.com>")
    bob = find(rows, "directory", "dir", "Bob <bob@example.com>")
    assert (alice["added"], alice["ownership"]) == (2, pytest.approx(2 / 3))
    assert (bob["added"], bob["ownership"]) == (1, pytest.approx(1 / 3))


def test_ownership_tie_sorted_by_name(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",))
    b_authors = author_rows(rows, "file", "dir/b.txt")
    assert [r["author"] for r in b_authors] == [
        "Alice <alice@example.com>",
        "Bob <bob@example.com>",
    ]
    assert [r["ownership"] for r in b_authors] == [0.5, 0.5]


# ---- commit-set filters -------------------------------------------------------

def test_since_commit_set(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("since", 200))
    root = find(rows, "repository", "/")
    assert root["commit_count"] == 4  # c2..c5
    assert (root["added"], root["churn"], root["modifications"]) == (3, 3, 2)
    assert root["modification_frequency"] == 2 * (1 / 4)
    assert root["churn_rate"] == 3 * (1 / 4)
    assert find(rows, "file", "a.txt")["churn"] == 1  # only c2's delta
    assert find(rows, "file", "dir/c2.txt")["churn"] == 0  # rename commit c4 is in H


def test_range_commit_set(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("range", 200, 400))
    root = find(rows, "repository", "/")
    assert root["commit_count"] == 2  # c2, c3
    assert (root["added"], root["modifications"]) == (3, 2)
    assert root["modification_frequency"] == 1.0  # 2 * (1/2)
    assert root["churn_rate"] == 1.5  # 3 * (1/2)
    paths = {r["path"] for r in rows if r["object_type"] == "file"}
    # membership = rows of H plus rows of commits whose parent is in H:
    # the rename commit c4 (parent c3 in H) makes both rename paths members.
    assert paths == {"a.txt", "dir/b.txt", "dir/c.txt", "dir/c2.txt"}
    assert find(rows, "file", "dir/c.txt")["churn"] == 1  # delta from c2
    assert find(rows, "file", "dir/c2.txt")["churn"] == 0  # c4 is outside H


def test_list_commit_set(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("list", (tiny.shas[0],)))
    root = find(rows, "repository", "/")
    assert root["commit_set"] == "list:1"
    assert root["commit_count"] == 1
    assert (root["added"], root["churn"], root["modifications"]) == (4, 4, 1)
    assert root["modification_frequency"] == 1.0
    assert root["churn_rate"] == 4.0
    paths = {r["path"] for r in rows if r["object_type"] == "file"}
    # c2's rows enter via parent(c2) = c1 ∈ H, so dir/c.txt is a member...
    assert paths == {"a.txt", "dir/b.txt", "dir/c.txt"}
    # ...but with zero deltas: dir/c.txt was only touched by c2, outside H.
    zero = find(rows, "file", "dir/c.txt")
    assert (zero["added"], zero["churn"], zero["modifications"]) == (0, 0, 0)
    assert find(rows, "file", "a.txt")["added"] == 3


# ---- path / author filters ----------------------------------------------------

def test_path_filter_scopes_rows(tiny):
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",), path="dir")
    root = find(rows, "repository", "/")
    assert root["added"] == 3  # only the dir subtree
    paths = {(r["object_type"], r["path"]) for r in rows}
    assert ("file", "a.txt") not in paths
    assert ("file", "dir/b.txt") in paths
    assert ("directory", "dir") in paths


def test_author_filter(tiny):
    alice = _aid(tiny.conn, tiny.repo_id, "alice@example.com")
    rows = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",), authors=[alice])
    root = find(rows, "repository", "/")
    assert root["commit_count"] == 5  # |H| stays the unfiltered set size
    assert (root["added"], root["churn"], root["modifications"]) == (6, 6, 2)
    assert all(r["author"] in ("ALL", "Alice <alice@example.com>") for r in rows)
    paths = {r["path"] for r in rows if r["object_type"] == "file"}
    assert "dir/c2.txt" not in paths  # only Bob touched it
    b_rows = author_rows(rows, "file", "dir/b.txt")
    assert [r["added"] for r in b_rows] == [1]  # Bob's delta hidden


def test_author_merge_folds_identity(tiny):
    alice = _aid(tiny.conn, tiny.repo_id, "alice@example.com")
    bob = _aid(tiny.conn, tiny.repo_id, "bob@example.com")
    before = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",))
    tiny.conn.execute(
        "INSERT INTO author_merges(repo_id, source_author_id, target_author_id) VALUES(?,?,?)",
        (tiny.repo_id, bob, alice),
    )
    tiny.conn.commit()
    after = metrics.compute_rows(tiny.conn, tiny.repo_id, ("all",))

    all_before = [r for r in before if r["author"] == "ALL"]
    all_after = [r for r in after if r["author"] == "ALL"]
    assert all_before == all_after  # totals unchanged by a merge

    b_authors = author_rows(after, "file", "dir/b.txt")
    assert len(b_authors) == 1
    assert b_authors[0]["author"] == "Alice <alice@example.com>"
    assert (b_authors[0]["added"], b_authors[0]["modifications"]) == (2, 2)
    assert b_authors[0]["ownership"] == 1.0
    assert all("Bob" not in r["author"] for r in after)


# ---- CLI wiring ----------------------------------------------------------------

def test_cli_export_matches_golden(tiny, tmp_path):
    from rat.cli import main

    out = tmp_path / "export.csv"
    rc = main(
        ["export", "--db", str(tiny.db_path), "--repo-id", str(tiny.repo_id), "--out", str(out)]
    )
    assert rc == 0
    assert out.read_bytes() == GOLDEN.read_bytes()


def test_cli_export_unknown_name_returns_2(tiny):
    from rat.cli import main

    assert main(["export", "--db", str(tiny.db_path), "--name", "nope"]) == 2
