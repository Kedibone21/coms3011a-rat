import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { CommitItem } from "../types";
import { fmtDate, inputToTs, shortSha, tsToInput } from "../format";

type Mode = "all" | "since" | "range" | "list";

function modeOf(spec: string): Mode {
  if (spec.startsWith("since:")) return "since";
  if (spec.startsWith("range:")) return "range";
  if (spec.startsWith("list:")) return "list";
  return "all";
}

export default function CommitSetBuilder({
  repoId,
  spec,
  onSpec,
}: {
  repoId: number;
  spec: string;
  onSpec: (spec: string) => void;
}) {
  const [mode, setMode] = useState<Mode>(modeOf(spec));
  const [since, setSince] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<CommitItem[]>([]);
  const [total, setTotal] = useState(0);
  const [picked, setPicked] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  // Reflect externally-set specs (e.g. hash restore).
  useEffect(() => {
    const m = modeOf(spec);
    setMode(m);
    if (m === "since" && spec.startsWith("since:")) {
      const ts = Number(spec.slice(6));
      if (!Number.isNaN(ts)) setSince(tsToInput(ts));
    }
    if (m === "range") {
      const [a, b] = spec.slice(6).split("-").map(Number);
      if (!Number.isNaN(a)) setFrom(tsToInput(a));
      if (!Number.isNaN(b)) setTo(tsToInput(b));
    }
    if (m === "list") setPicked(spec.slice(5).split(",").filter(Boolean));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec, repoId]);

  // Debounced commit search for the manual-list mode.
  useEffect(() => {
    if (!open || mode !== "list") return;
    const t = setTimeout(async () => {
      try {
        const page = await api.commits(repoId, { q: q.trim() || undefined, limit: 50 });
        setResults(page.items);
        setTotal(page.total);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }, 250);
    return () => clearTimeout(t);
  }, [q, open, mode, repoId]);

  const label = useMemo(() => {
    if (mode === "all") return "all commits";
    if (mode === "since") return spec;
    if (mode === "range") return spec;
    return `list: ${picked.length} commit${picked.length === 1 ? "" : "s"}`;
  }, [mode, spec, picked.length]);

  function applySince() {
    const ts = inputToTs(since);
    if (ts === null) return;
    onSpec(`since:${ts}`);
  }
  function applyRange() {
    const a = inputToTs(from);
    const b = inputToTs(to);
    if (a === null || b === null || a >= b) {
      setError("Range needs from < to");
      return;
    }
    onSpec(`range:${a}-${b}`);
  }
  function applyList() {
    if (picked.length === 0) return;
    onSpec(`list:${picked.join(",")}`);
  }
  function toggle(sha: string) {
    setPicked((p) => (p.includes(sha) ? p.filter((s) => s !== sha) : [...p, sha]));
  }

  return (
    <div className="csb">
      <button className="btn csb-toggle" onClick={() => setOpen((v) => !v)}>
        <span className="csb-label">Commit set:</span> {label} {open ? "▴" : "▾"}
      </button>

      {open && (
        <div className="csb-menu">
          <div className="tabs tabs-sm">
            {(["all", "since", "range", "list"] as Mode[]).map((m) => (
              <button
                key={m}
                className={mode === m ? "tab active" : "tab"}
                onClick={() => {
                  setMode(m);
                  setError(null);
                  if (m === "all") onSpec("all");
                }}
              >
                {m === "all" ? "All" : m === "since" ? "Since" : m === "range" ? "Range" : "Manual list"}
              </button>
            ))}
          </div>

          {mode === "all" && (
            <p className="muted small">All commits reachable from the ingested ref.</p>
          )}

          {mode === "since" && (
            <div className="row">
              <input
                type="datetime-local"
                className="input"
                value={since}
                onChange={(e) => setSince(e.target.value)}
              />
              <button className="btn btn-primary" onClick={applySince} disabled={!since}>
                Apply
              </button>
            </div>
          )}

          {mode === "range" && (
            <>
              <div className="row">
                <input
                  type="datetime-local"
                  className="input"
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                />
                <span className="muted">to</span>
                <input
                  type="datetime-local"
                  className="input"
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                />
                <button className="btn btn-primary" onClick={applyRange} disabled={!from || !to}>
                  Apply
                </button>
              </div>
              <p className="muted small">Start inclusive, end exclusive.</p>
            </>
          )}

          {mode === "list" && (
            <>
              <input
                className="input"
                placeholder="Search commits by SHA prefix or author…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <p className="muted small">
                {total.toLocaleString()} commit{total === 1 ? "" : "s"} match
              </p>
              <div className="commit-list">
                {results.map((c) => (
                  <label key={c.sha} className="commit-item">
                    <input
                      type="checkbox"
                      checked={picked.includes(c.sha)}
                      onChange={() => toggle(c.sha)}
                    />
                    <code>{shortSha(c.sha)}</code>
                    <span className="commit-author">{c.author}</span>
                    <span className="muted small">{fmtDate(c.ts)}</span>
                  </label>
                ))}
                {results.length === 0 && <p className="muted small">No commits found.</p>}
              </div>
              {picked.length > 0 && (
                <div className="picked-chips">
                  {picked.map((s) => (
                    <button key={s} className="chip" onClick={() => toggle(s)} title="Remove">
                      {shortSha(s)} ×
                    </button>
                  ))}
                </div>
              )}
              <button
                className="btn btn-primary btn-block"
                onClick={applyList}
                disabled={picked.length === 0}
              >
                Apply list ({picked.length})
              </button>
            </>
          )}

          {error && <p className="error-text small">{error}</p>}
        </div>
      )}
    </div>
  );
}
