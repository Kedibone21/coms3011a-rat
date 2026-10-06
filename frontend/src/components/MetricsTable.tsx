import { useMemo, useState } from "react";
import type { MetricRow } from "../types";
import { baseName, dirOf, fmtFloat, fmtInt, fmtPercent } from "../format";

type SortKey =
  | "path"
  | "added"
  | "removed"
  | "growth"
  | "churn"
  | "modifications"
  | "modification_frequency"
  | "churn_rate";

const keyOf = (r: MetricRow) => `${r.object_type}\u001f${r.path}`;

export default function MetricsTable({
  rows,
  level,
  onNavigate,
}: {
  rows: MetricRow[];
  level: string;
  onNavigate: (path: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("churn");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [hideZero, setHideZero] = useState(false);

  const { rootRow, children } = useMemo(() => {
    const all = rows.filter((r) => r.author === "ALL");
    return {
      rootRow: all.find((r) => r.object_type === "repository"),
      children: all.filter((r) => r.object_type !== "repository" && dirOf(r.path) === level),
    };
  }, [rows, level]);

  const authorRows = useMemo(() => {
    const m = new Map<string, MetricRow[]>();
    for (const r of rows) {
      if (r.author === "ALL") continue;
      const k = keyOf(r);
      let arr = m.get(k);
      if (!arr) {
        arr = [];
        m.set(k, arr);
      }
      arr.push(r);
    }
    for (const arr of m.values())
      arr.sort((a, b) => b.churn - a.churn || a.author.localeCompare(b.author));
    return m;
  }, [rows]);

  const visible = useMemo(() => {
    let list = children;
    if (search.trim()) {
      const needle = search.trim().toLowerCase();
      list = list.filter((r) => r.path.toLowerCase().includes(needle));
    }
    if (hideZero) list = list.filter((r) => r.churn !== 0 || r.added !== 0 || r.removed !== 0);
    const dir = sortDir === "asc" ? 1 : -1;
    return [...list].sort((a, b) => {
      if (sortKey === "path") return a.path.localeCompare(b.path) * dir;
      const va = a[sortKey] === "" ? 0 : (a[sortKey] as number);
      const vb = b[sortKey] === "" ? 0 : (b[sortKey] as number);
      if (va !== vb) return (va - vb) * dir;
      return a.path.localeCompare(b.path);
    });
  }, [children, search, sortKey, sortDir, hideZero]);

  function th(k: SortKey, label: string) {
    const active = sortKey === k;
    return (
      <th
        className={`num sortable${active ? ` sorted-${sortDir}` : ""}`}
        onClick={() => {
          if (active) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
          else {
            setSortKey(k);
            setSortDir(k === "path" ? "asc" : "desc");
          }
        }}
      >
        {label}
      </th>
    );
  }

  function toggleExpand(r: MetricRow) {
    const k = keyOf(r);
    if (!authorRows.has(k)) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  function renderRow(r: MetricRow) {
    const k = keyOf(r);
    const isDir = r.object_type === "directory";
    const hasAuthors = authorRows.has(k);
    const isOpen = expanded.has(k);
    const subs = isOpen ? authorRows.get(k) : undefined;
    return (
      <>
        <tr
          key={k}
          className={`obj-row${isDir ? " dir-row" : ""}`}
          onClick={() => (isDir ? onNavigate(r.path) : toggleExpand(r))}
        >
          <td className="obj-name">
            {hasAuthors && (
              <button
                className="chevron"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleExpand(r);
                }}
              >
                {isOpen ? "▾" : "▸"}
              </button>
            )}
            <span className={`otype otype-${r.object_type}`}>{isDir ? "dir" : "file"}</span>
            <span className="obj-path" title={r.path}>
              {baseName(r.path)}
              {isDir && "/"}
            </span>
          </td>
          <td className="num">{fmtInt(r.added)}</td>
          <td className="num">{fmtInt(r.removed)}</td>
          <td className={`num ${r.growth > 0 ? "pos" : r.growth < 0 ? "neg" : ""}`}>
            {r.growth > 0 ? "+" : ""}
            {fmtInt(r.growth)}
          </td>
          <td className="num">{fmtInt(r.churn)}</td>
          <td className="num">{fmtInt(r.modifications)}</td>
          <td className="num">{fmtFloat(r.modification_frequency)}</td>
          <td className="num">{fmtFloat(r.churn_rate)}</td>
          <td className="num">{fmtPercent(r.ownership)}</td>
        </tr>
        {subs?.map((s) => (
          <tr key={k + "\u001f" + s.author} className="author-row">
            <td className="obj-name sub">
              <span className="author-chip">{s.author}</span>
            </td>
            <td className="num">{fmtInt(s.added)}</td>
            <td className="num">{fmtInt(s.removed)}</td>
            <td className={`num ${s.growth > 0 ? "pos" : s.growth < 0 ? "neg" : ""}`}>
              {s.growth > 0 ? "+" : ""}
              {fmtInt(s.growth)}
            </td>
            <td className="num">{fmtInt(s.churn)}</td>
            <td className="num">{fmtInt(s.modifications)}</td>
            <td className="num">{fmtFloat(s.modification_frequency)}</td>
            <td className="num">{fmtFloat(s.churn_rate)}</td>
            <td className="num">{fmtPercent(s.ownership)}</td>
          </tr>
        ))}
      </>
    );
  }

  const parent = dirOf(level);

  return (
    <div className="table-wrap">
      <div className="table-toolbar">
        <input
          className="input input-sm search"
          placeholder="Filter this level…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label className="check small">
          <input
            type="checkbox"
            checked={hideZero}
            onChange={(e) => setHideZero(e.target.checked)}
          />
          hide zero-churn
        </label>
        <span className="muted small grow">
          {visible.length.toLocaleString()} of {children.length.toLocaleString()} objects at
          this level
        </span>
      </div>

      <table className="metrics-table">
        <thead>
          <tr>
            <th className="sortable" onClick={() => setSortKey("path")}>
              Path
            </th>
            {th("added", "Added")}
            {th("removed", "Removed")}
            {th("growth", "Growth")}
            {th("churn", "Churn")}
            {th("modifications", "Mods")}
            {th("modification_frequency", "Mod freq")}
            {th("churn_rate", "Churn/commit")}
            <th className="num">Ownership</th>
          </tr>
        </thead>
        <tbody>
          {level !== "" && (
            <tr className="up-row" onClick={() => onNavigate(parent)}>
              <td colSpan={9}>↑ up to {parent === "" ? "/" : `/${parent}`}</td>
            </tr>
          )}
          {level === "" && rootRow && (
            <tr
              className="obj-row root-row"
              onClick={() => onNavigate("")}
              title="Repository totals"
            >
              <td className="obj-name">
                <span className="otype otype-repository">repo</span>
                <span className="obj-path">/ (repository totals)</span>
              </td>
              <td className="num">{fmtInt(rootRow.added)}</td>
              <td className="num">{fmtInt(rootRow.removed)}</td>
              <td className={`num ${rootRow.growth > 0 ? "pos" : rootRow.growth < 0 ? "neg" : ""}`}>
                {rootRow.growth > 0 ? "+" : ""}
                {fmtInt(rootRow.growth)}
              </td>
              <td className="num">{fmtInt(rootRow.churn)}</td>
              <td className="num">{fmtInt(rootRow.modifications)}</td>
              <td className="num">{fmtFloat(rootRow.modification_frequency)}</td>
              <td className="num">{fmtFloat(rootRow.churn_rate)}</td>
              <td className="num" />
            </tr>
          )}
          {visible.map(renderRow)}
          {visible.length === 0 && (
            <tr>
              <td colSpan={9} className="muted pad">
                No objects at this level{search ? " match the filter" : ""}.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
