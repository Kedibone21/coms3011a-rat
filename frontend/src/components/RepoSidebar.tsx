import { useState } from "react";
import type { Repo } from "../types";
import { shortSha } from "../format";
import AddRepo from "./AddRepo";

function StatusBadge({ repo }: { repo: Repo }) {
  if (repo.status === "ingesting")
    return <span className="badge badge-ingesting">ingesting…</span>;
  if (repo.status === "error")
    return (
      <span className="badge badge-error" title={repo.error ?? "ingest failed"}>
        error
      </span>
    );
  return <span className="badge badge-ready">ready</span>;
}

export default function RepoSidebar({
  repos,
  selectedId,
  onSelect,
  onDelete,
  onAdded,
}: {
  repos: Repo[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
  onAdded: (id: number) => void;
}) {
  const [showAdd, setShowAdd] = useState(false);

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <h1>Repo Analysis Tool</h1>
        <button
          className="btn btn-primary btn-block"
          onClick={() => setShowAdd((v) => !v)}
        >
          {showAdd ? "Close" : "+ Add repository"}
        </button>
        {showAdd && <AddRepo onAdded={onAdded} />}
      </div>

      <nav className="repo-list">
        {repos.length === 0 && (
          <p className="muted pad">No repositories yet. Add one above.</p>
        )}
        {repos.map((r) => (
          <div
            key={r.id}
            className={`repo-item${r.id === selectedId ? " active" : ""}`}
            onClick={() => onSelect(r.id)}
          >
            <div className="repo-item-top">
              <span className="repo-name" title={r.source ?? r.name}>
                {r.name}
              </span>
              <StatusBadge repo={r} />
            </div>
            <div className="repo-item-meta">
              <span>{r.source_type === "zip" ? "zip upload" : "clone"}</span>
              {r.status === "ready" && (
                <>
                  <span>·</span>
                  <span>{r.commit_count.toLocaleString()} commits</span>
                  <span>·</span>
                  <code>{shortSha(r.ref_sha)}</code>
                </>
              )}
            </div>
            {r.status === "error" && (
              <div className="repo-error" title={r.error ?? ""}>
                {r.error}
              </div>
            )}
            <button
              className="repo-delete"
              title="Delete repository"
              onClick={(e) => {
                e.stopPropagation();
                if (confirm(`Delete "${r.name}"? This removes the repo and all metrics.`))
                  onDelete(r.id);
              }}
            >
              ×
            </button>
          </div>
        ))}
      </nav>
    </aside>
  );
}
