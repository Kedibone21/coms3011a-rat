"""Metric aggregation over ingested git history.

Semantics follow the COMS3011A spec exactly — see AGENTS.md for the summary
and reference/ for ground-truth CSVs (scripts/verify.py diffs against them).

Row model (matches the reference CSV):
    repo, ref_sha, commit_set, commit_count, object_type, path, author,
    added, removed, growth, churn, modifications, modification_frequency,
    churn_rate, ownership

- object_type: repository (root, path "/"), directory, file.
- "ALL" rows carry added/removed/growth/churn/modifications + both rates.
- per-author rows carry their own added/removed/growth/churn/modifications +
  ownership; modification_frequency/churn_rate stay empty on those rows.
- Membership: a path is a member when it appears in the file stats of a commit
  h in the set, or of a commit whose parent is in the set (H plus its direct
  children). Members appear even with no deltas inside the set (pure renames,
  files first touched just after the set). The root object always exists.
- Deltas land on the path as named at that commit; renames move nothing
  retroactively.
- |H| (commit_count) counts every commit in the set, empty commits included.

Performance model: one grouped pass per (path, effective author) for the
deltas, one grouped pass for distinct modification commits, and an in-memory
roll-up over path ancestors for directories. Per-author modification sets are
disjoint (one author per commit), so object totals need no set unions — only
per-author unions during the directory roll-up.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from decimal import Decimal

REF_COLUMNS = (
    "repo",
    "ref_sha",
    "commit_set",
    "commit_count",
    "object_type",
    "path",
    "author",
    "added",
    "removed",
    "growth",
    "churn",
    "modifications",
    "modification_frequency",
    "churn_rate",
    "ownership",
)

# CommitSet = ('all',) | ('since', ts) | ('range', start_ts, end_ts) | ('list', (sha, ...))
CommitSet = tuple


def parse_commit_set(spec: str) -> CommitSet:
    """Parse a CLI/API commit-set spec: all | since:TS | range:A-B | list:SHA,..."""
    spec = spec.strip()
    if spec == "all":
        return ("all",)
    kind, _, rest = spec.partition(":")
    if kind == "since":
        return ("since", int(rest))
    if kind == "range":
        start, _, end = rest.partition("-")
        return ("range", int(start), int(end))
    if kind == "list":
        return ("list", tuple(s for s in rest.split(",") if s))
    raise ValueError(f"bad commit set spec: {spec!r}")


def set_label(cs: CommitSet) -> str:
    if cs[0] == "all":
        return "all"
    if cs[0] == "since":
        return f"since:{cs[1]}"
    if cs[0] == "range":
        return f"range:{cs[1]}-{cs[2]}"
    if cs[0] == "list":
        return f"list:{len(cs[1])}"
    raise ValueError(f"unknown commit set: {cs!r}")


def _commit_filter(cs: CommitSet, alias: str, params: dict) -> str:
    """SQL fragment selecting the commits of the set (aliases `c` or `p`)."""
    if cs[0] == "all":
        return "1=1"
    if cs[0] == "since":
        params["since"] = cs[1]
        return f"{alias}.ts >= :since"
    if cs[0] == "range":
        params["t0"] = cs[1]
        params["t1"] = cs[2]
        return f"{alias}.ts >= :t0 AND {alias}.ts < :t1"
    if cs[0] == "list":
        keys = []
        for i, sha in enumerate(cs[1]):
            key = f"sha{i}"
            params[key] = sha
            keys.append(f":{key}")
        return f"{alias}.sha IN ({', '.join(keys)})"
    raise ValueError(f"unknown commit set: {cs!r}")


def _path_sql(path: str | None, alias: str, params: dict) -> str:
    """Restrict to a path subtree (the path itself or anything below it)."""
    if not path:
        return ""
    esc = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    params["pth"] = path
    params["pth_like"] = esc + "/%"
    return f" AND ({alias}.path = :pth OR {alias}.path LIKE :pth_like ESCAPE '\\')"


def _authors_sql(author_ids, eff_expr: str, params: dict) -> str:
    """Restrict to a set of *effective* author ids (post author-merge)."""
    if not author_ids:
        return ""
    keys = []
    for i, aid in enumerate(author_ids):
        key = f"auth{i}"
        params[key] = aid
        keys.append(f":{key}")
    return f" AND {eff_expr} IN ({', '.join(keys)})"


def set_size(conn, repo_id: int, cs: CommitSet) -> int:
    """|H| — every commit in the set, empty commits included."""
    params: dict = {"repo": repo_id}
    frag = _commit_filter(cs, "c", params)
    row = conn.execute(
        f"SELECT COUNT(*) FROM commits c WHERE c.repo_id = :repo AND ({frag})",
        params,
    ).fetchone()
    return row[0]


def ancestors(path: str) -> list[str]:
    """Directory paths containing `path` (exclusive; root is the empty string)."""
    parts = path.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts))]


def compute_rows(
    conn,
    repo_id: int,
    cs: CommitSet,
    *,
    path: str | None = None,
    authors=None,
) -> list[dict]:
    """Compute all metric rows for a repository + commit set (+ optional filters).

    `authors` holds *effective* author ids; it restricts both the commit set
    and the membership to those authors.
    """
    repo = conn.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
    if repo is None:
        raise ValueError(f"unknown repo id {repo_id}")
    n_h = set_size(conn, repo_id, cs)

    author_info = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, name, email FROM authors WHERE repo_id = ?", (repo_id,)
        )
    }
    merges = {
        r["source_author_id"]: r["target_author_id"]
        for r in conn.execute(
            "SELECT source_author_id, target_author_id FROM author_merges WHERE repo_id = ?",
            (repo_id,),
        )
    }

    def display(aid: int) -> str:
        eff = merges.get(aid, aid)
        r = author_info[eff]
        return f"{r['name']} <{r['email']}>"

    eff_expr = "COALESCE(am.target_author_id, c.author_id)"

    # ---- membership: rows of H and of commits whose parent is in H ----------
    mp: dict = {"repo": repo_id}
    cf = _commit_filter(cs, "c", mp)
    pf = _commit_filter(cs, "p", mp)
    ps = _path_sql(path, "fs", mp)
    aks = _authors_sql(authors, eff_expr, mp)
    member_paths = {
        r[0]
        for r in conn.execute(
            f"""
            SELECT DISTINCT fs.path
            FROM file_stats fs
            JOIN commits c ON c.id = fs.commit_id
            LEFT JOIN commits p ON p.id = c.parent_id
            LEFT JOIN author_merges am
                   ON am.repo_id = c.repo_id AND am.source_author_id = c.author_id
            WHERE fs.repo_id = :repo AND (({cf}) OR ({pf})) {ps} {aks}
            """,
            mp,
        )
    }

    # ---- deltas within H ----------------------------------------------------
    dp: dict = {"repo": repo_id}
    cf2 = _commit_filter(cs, "c", dp)
    ps2 = _path_sql(path, "fs", dp)
    aks2 = _authors_sql(authors, eff_expr, dp)
    base = f"""
        FROM file_stats fs
        JOIN commits c ON c.id = fs.commit_id
        LEFT JOIN author_merges am
               ON am.repo_id = c.repo_id AND am.source_author_id = c.author_id
        WHERE fs.repo_id = :repo AND ({cf2}) {ps2} {aks2}
    """

    sums: dict[tuple[str, int], tuple[int, int]] = {}
    for r in conn.execute(
        f"SELECT fs.path AS p, {eff_expr} AS aid, SUM(fs.added) AS a, SUM(fs.removed) AS rm "
        f"{base} GROUP BY p, aid",
        dp,
    ):
        sums[(r["p"], r["aid"])] = (r["a"], r["rm"])

    # Distinct modification commits per (path, effective author): churn > 0.
    mod_sets: dict[str, set[int]] = defaultdict(set)
    auth_mod_sets: dict[tuple[str, int], set[int]] = defaultdict(set)
    for r in conn.execute(
        f"SELECT fs.path AS p, {eff_expr} AS aid, fs.commit_id AS cid "
        f"{base} AND fs.added + fs.removed > 0 "
        f"GROUP BY fs.path, aid, fs.commit_id",
        dp,
    ):
        mod_sets[r["p"]].add(r["cid"])
        auth_mod_sets[(r["p"], r["aid"])].add(r["cid"])

    # ---- roll-up ------------------------------------------------------------
    file_paths = set(member_paths) | {p for p, _ in sums} | set(mod_sets)

    dir_sums: dict[tuple[str, int], list[int]] = {}
    dir_mod_sets: dict[str, set[int]] = defaultdict(set)
    dir_auth_mod_sets: dict[tuple[str, int], set[int]] = defaultdict(set)

    def acc_dir(d: str, aid: int, added: int, removed: int) -> None:
        v = dir_sums.get((d, aid))
        if v is None:
            dir_sums[(d, aid)] = [added, removed]
        else:
            v[0] += added
            v[1] += removed

    for (p, aid), (added, removed) in sums.items():
        for d in ancestors(p):
            acc_dir(d, aid, added, removed)
        acc_dir("", aid, added, removed)

    for p, s in mod_sets.items():
        for d in ancestors(p):
            dir_mod_sets[d].update(s)
        dir_mod_sets[""].update(s)

    for (p, aid), s in auth_mod_sets.items():
        for d in ancestors(p):
            dir_auth_mod_sets[(d, aid)].update(s)
        dir_auth_mod_sets[("", aid)].update(s)

    # ---- emit ---------------------------------------------------------------
    dir_auth_sums: dict[str, dict[int, list[int]]] = defaultdict(dict)
    for (d, aid), v in dir_sums.items():
        dir_auth_sums[d][aid] = v

    path_auth_sums: dict[str, dict[int, tuple[int, int]]] = defaultdict(dict)
    for (p, aid), v in sums.items():
        path_auth_sums[p][aid] = v

    dir_auth_mods: dict[str, dict[int, set[int]]] = defaultdict(dict)
    for (d, aid), s in dir_auth_mod_sets.items():
        dir_auth_mods[d][aid] = s

    path_auth_mods: dict[str, dict[int, set[int]]] = defaultdict(dict)
    for (p, aid), s in auth_mod_sets.items():
        path_auth_mods[p][aid] = s

    rows: list[dict] = []
    meta = {
        "repo": repo["name"],
        "ref_sha": repo["ref_sha"],
        "commit_set": set_label(cs),
        "commit_count": n_h,
    }
    # Rates are computed as numerator * (1/|H|) to reproduce the reference bit-for-bit.
    inv_h = (1.0 / n_h) if n_h else 0.0

    def add_rows(
        object_type: str,
        label: str,
        per_author: dict,
        per_author_mods: dict,
        all_mods: int,
    ) -> None:
        total_added = sum(v[0] for v in per_author.values())
        total_removed = sum(v[1] for v in per_author.values())
        total_churn = total_added + total_removed
        rows.append(
            {
                **meta,
                "object_type": object_type,
                "path": label,
                "author": "ALL",
                "added": total_added,
                "removed": total_removed,
                "growth": total_added - total_removed,
                "churn": total_churn,
                "modifications": all_mods,
                "modification_frequency": all_mods * inv_h,
                "churn_rate": total_churn * inv_h,
                "ownership": "",
            }
        )
        entries = []
        for aid, (a, r) in per_author.items():
            churn = a + r
            if churn <= 0:
                continue
            entries.append((display(aid), a, r, len(per_author_mods.get(aid, ()))))
        entries.sort(key=lambda t: (-(t[1] + t[2]), t[0]))
        for name, a, r, m in entries:
            rows.append(
                {
                    **meta,
                    "object_type": object_type,
                    "path": label,
                    "author": name,
                    "added": a,
                    "removed": r,
                    "growth": a - r,
                    "churn": a + r,
                    "modifications": m,
                    "modification_frequency": "",
                    "churn_rate": "",
                    "ownership": ((a + r) / total_churn) if total_churn else 0.0,
                }
            )

    # Repository root ("/") — always present (totals of the current filter).
    add_rows(
        "repository",
        "/",
        dir_auth_sums.get("", {}),
        dir_auth_mods.get("", {}),
        len(dir_mod_sets[""]),
    )

    def in_scope(pth: str) -> bool:
        return not path or pth == path or pth.startswith(path + "/")

    # Directories (subtree roll-up) — every ancestor of a member file.
    dirs = {k[0] for k in dir_sums if k[0]}
    for d in sorted(dd for dd in dirs if in_scope(dd)):
        add_rows(
            "directory",
            d,
            dir_auth_sums.get(d, {}),
            dir_auth_mods.get(d, {}),
            len(dir_mod_sets.get(d, ())),
        )

    # Files — every member path, even all-zero ones.
    for p in sorted(pth for pth in file_paths if in_scope(pth)):
        add_rows(
            "file",
            p,
            path_auth_sums.get(p, {}),
            path_auth_mods.get(p, {}),
            len(mod_sets.get(p, ())),
        )

    return rows


def _fmt_float(v: float) -> str:
    """Reference float rendering: shortest round-trip digits; below 1e-5 the
    reference switches to scientific notation with an unpadded exponent (e-6),
    elsewhere plain decimal (0.00006546537699873979 style)."""
    if v != 0.0 and abs(v) < 1e-5:
        mant, _, exp = repr(v).partition("e")
        return f"{mant}e{int(exp)}"
    return format(Decimal(repr(v)), "f")


def rows_to_csv(rows: list[dict]) -> str:
    """Render rows as reference-format CSV (same columns, \\n endings, plain decimals)."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(
        buf, fieldnames=REF_COLUMNS, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                k: (
                    ""
                    if v is None
                    else _fmt_float(v)
                    if isinstance(v, float)
                    else v
                )
                for k, v in row.items()
            }
        )
    return buf.getvalue()
