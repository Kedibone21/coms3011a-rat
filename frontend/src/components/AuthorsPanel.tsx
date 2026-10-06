import { useMemo, useState } from "react";
import { api } from "../api";
import type { Author } from "../types";
import { fmtInt } from "../format";

export default function AuthorsPanel({
  repoId,
  authors,
  onChanged,
}: {
  repoId: number;
  authors: Author[];
  onChanged: () => void;
}) {
  const [pending, setPending] = useState<number | null>(null);
  const [targetId, setTargetId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const byId = useMemo(() => new Map(authors.map((a) => [a.id, a])), [authors]);

  /** Follow merged_into chain to the final canonical author. */
  function resolve(a: Author): Author {
    let cur = a;
    const seen = new Set<number>();
    while (cur.merged_into !== null && !seen.has(cur.id)) {
      seen.add(cur.id);
      const next = byId.get(cur.merged_into);
      if (!next) break;
      cur = next;
    }
    return cur;
  }

  const groups = useMemo(() => {
    const roots = authors.filter((a) => a.merged_into === null);
    return roots.map((root) => ({
      root,
      members: authors.filter((a) => a.id !== root.id && resolve(a).id === root.id),
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authors, byId]);

  const totalUnmerged = authors.filter((a) => a.merged_into === null).length;

  async function merge() {
    if (pending === null || targetId === "") return;
    setBusy(true);
    setError(null);
    try {
      await api.addMerge(repoId, pending, Number(targetId));
      setPending(null);
      setTargetId("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function unmerge(source: number) {
    setBusy(true);
    setError(null);
    try {
      await api.removeMerge(repoId, source);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const pendingAuthor = pending === null ? null : byId.get(pending);

  return (
    <div className="authors-panel">
      <div className="panel">
        <h3>Author identities</h3>
        <p className="muted small">
          Emails are unified automatically at ingest using the repository's .mailmap.
          Manual merges below re-label the same person across different names/emails at
          query time — they are reversible and never rewrite stored commits.
        </p>
        <div className="muted small">
          {authors.length.toLocaleString()} identities · {totalUnmerged} canonical ·{" "}
          {authors.length - totalUnmerged} merged
        </div>
      </div>

      {pendingAuthor && (
        <div className="panel merge-bar">
          <span>
            Merge <b>{pendingAuthor.name}</b> ({pendingAuthor.email}) into:
          </span>
          <select
            className="input"
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
          >
            <option value="">— choose target —</option>
            {authors
              .filter((a) => a.id !== pendingAuthor.id)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.email})
                </option>
              ))}
          </select>
          <button
            className="btn btn-primary"
            disabled={busy || targetId === ""}
            onClick={merge}
          >
            Merge
          </button>
          <button className="btn" onClick={() => setPending(null)}>
            Cancel
          </button>
        </div>
      )}

      {error && <p className="error-text">{error}</p>}

      <div className="author-groups">
        {groups.map(({ root, members }) => (
          <div className="author-group" key={root.id}>
            <div className="author-row-main">
              <div className="author-id">
                <span className="author-name">{root.name}</span>
                <span className="muted small">{root.email}</span>
              </div>
              <div className="author-stats muted small">
                {fmtInt(root.commit_count)} commits · churn {fmtInt(root.churn)}
              </div>
              <button
                className="btn btn-sm"
                onClick={() => {
                  setPending(root.id);
                  setTargetId("");
                }}
              >
                Merge…
              </button>
            </div>

            {members.map((m) => {
              const via = m.merged_into !== null ? byId.get(m.merged_into) : null;
              return (
                <div className="author-row-main member" key={m.id}>
                  <div className="author-id">
                    <span className="member-mark">↳</span>
                    <span className="author-name">{m.name}</span>
                    <span className="muted small">{m.email}</span>
                    {via && via.id !== root.id && (
                      <span className="muted small">(via {via.name})</span>
                    )}
                  </div>
                  <div className="author-stats muted small">
                    {fmtInt(m.commit_count)} commits · churn {fmtInt(m.churn)}
                  </div>
                  <button
                    className="btn btn-sm"
                    disabled={busy}
                    onClick={() => unmerge(m.id)}
                  >
                    Unmerge
                  </button>
                </div>
              );
            })}
          </div>
        ))}
        {authors.length === 0 && <p className="muted pad">No authors in this repository.</p>}
      </div>
    </div>
  );
}
