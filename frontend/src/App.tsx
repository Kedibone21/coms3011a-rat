import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Author, MetricsResponse, Repo } from "./types";
import RepoSidebar from "./components/RepoSidebar";
import CommitSetBuilder from "./components/CommitSetBuilder";
import MetricsTable from "./components/MetricsTable";
import Overview from "./components/Overview";
import AuthorsPanel from "./components/AuthorsPanel";
import { shortSha } from "./format";

type View = "overview" | "table" | "authors";

interface HashState {
  repo?: number;
  set?: string;
  path?: string;
  authors?: number[];
}

function readHash(): HashState {
  try {
    const raw = decodeURIComponent(location.hash.replace(/^#/, ""));
    if (!raw) return {};
    const h = JSON.parse(raw);
    return h && typeof h === "object" ? (h as HashState) : {};
  } catch {
    return {};
  }
}

export default function App() {
  const initial = useMemo(readHash, []);
  const [repos, setRepos] = useState<Repo[]>([]);
  const [reposLoaded, setReposLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(initial.repo ?? null);
  const [setSpec, setSetSpec] = useState(initial.set ?? "all");
  const [path, setPath] = useState(initial.path ?? "");
  const [authorIds, setAuthorIds] = useState<number[]>(
    Array.isArray(initial.authors) ? initial.authors : [],
  );
  const [view, setView] = useState<View>("overview");
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [authors, setAuthors] = useState<Author[]>([]);
  const [authorsVersion, setAuthorsVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshRepos = useCallback(async () => {
    try {
      setRepos(await api.repos());
      setReposLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refreshRepos();
  }, [refreshRepos]);

  // Poll while any ingest is running.
  const anyIngesting = repos.some((r) => r.status === "ingesting");
  useEffect(() => {
    if (!anyIngesting) return;
    const t = setTimeout(refreshRepos, 1500);
    return () => clearTimeout(t);
  }, [anyIngesting, repos, refreshRepos]);

  // Drop a selection that no longer exists (e.g. restored from hash after delete).
  useEffect(() => {
    if (reposLoaded && selectedId !== null && !repos.some((r) => r.id === selectedId)) {
      setSelectedId(null);
    }
  }, [reposLoaded, repos, selectedId]);

  const selectedRepo = useMemo(
    () => repos.find((r) => r.id === selectedId) ?? null,
    [repos, selectedId],
  );
  const ready = selectedRepo?.status === "ready";

  useEffect(() => {
    if (selectedId === null || !ready) {
      setAuthors([]);
      return;
    }
    let alive = true;
    api
      .authors(selectedId)
      .then((a) => alive && setAuthors(a))
      .catch(() => alive && setAuthors([]));
    return () => {
      alive = false;
    };
  }, [selectedId, ready, authorsVersion]);

  const authorsParam = authorIds.length ? authorIds.join(",") : undefined;

  useEffect(() => {
    if (selectedId === null || !ready) {
      setMetrics(null);
      return;
    }
    let alive = true;
    setLoading(true);
    api
      .metrics(selectedId, { set: setSpec, authors: authorsParam })
      .then((m) => {
        if (!alive) return;
        setMetrics(m);
        setError(null);
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [selectedId, ready, setSpec, authorsParam]);

  // Keep shareable state in the URL hash.
  useEffect(() => {
    const h = JSON.stringify({ repo: selectedId, set: setSpec, path, authors: authorIds });
    history.replaceState(null, "", `#${encodeURIComponent(h)}`);
  }, [selectedId, setSpec, path, authorIds]);

  function selectRepo(id: number) {
    setSelectedId(id);
    setPath("");
    setAuthorIds([]);
    setError(null);
  }

  async function deleteRepo(id: number) {
    try {
      await api.deleteRepo(id);
      if (id === selectedId) setSelectedId(null);
      await refreshRepos();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function onAdded(id: number) {
    await refreshRepos();
    selectRepo(id);
  }

  function toggleAuthor(id: number) {
    setAuthorIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  const crumbs = useMemo(() => {
    const parts = path === "" ? [] : path.split("/");
    const out = [{ label: "/", value: "" }];
    let acc = "";
    for (const p of parts) {
      acc = acc === "" ? p : `${acc}/${p}`;
      out.push({ label: p, value: acc });
    }
    return out;
  }, [path]);

  const exportHref =
    selectedId !== null
      ? api.exportUrl(selectedId, {
          set: setSpec,
          path: path || undefined,
          authors: authorsParam,
        })
      : undefined;

  return (
    <div className="app">
      <RepoSidebar
        repos={repos}
        selectedId={selectedId}
        onSelect={selectRepo}
        onDelete={deleteRepo}
        onAdded={onAdded}
      />

      <main className="main">
        {error && (
          <div className="error-banner">
            {error}
            <button className="btn btn-sm" onClick={() => setError(null)}>
              dismiss
            </button>
          </div>
        )}

        {selectedRepo === null ? (
          <div className="welcome panel">
            <h2>Analyse git repositories</h2>
            <p className="muted">
              Ingest a repository from a <b>public clone URL</b> or a <b>zip containing
              .git</b>, then explore file, directory and repository metrics for any
              commit set, filtered by author or path.
            </p>
            <ul className="muted">
              <li>Metrics: added / removed / growth / churn / modifications / rates / ownership</li>
              <li>Commit sets: all, since a time, time ranges, or a manual SHA list</li>
              <li>Author identity merging (.mailmap automatic + manual, reversible)</li>
              <li>CSV export matching the reference format byte-for-byte</li>
            </ul>
            <p className="muted">
              Use <b>+ Add repository</b> in the sidebar to get started.
            </p>
          </div>
        ) : selectedRepo.status !== "ready" ? (
          <div className="welcome panel">
            {selectedRepo.status === "ingesting" ? (
              <>
                <h2>
                  <span className="spinner" /> Ingesting {selectedRepo.name}…
                </h2>
                <p className="muted">
                  Cloning / extracting and analysing history. Large repositories can take
                  a minute or two; this page updates automatically.
                </p>
              </>
            ) : (
              <>
                <h2>Ingest failed — {selectedRepo.name}</h2>
                <pre className="error-pre">{selectedRepo.error}</pre>
                <p className="muted">Delete this repository and try again.</p>
              </>
            )}
          </div>
        ) : (
          <>
            <header className="repo-header">
              <div>
                <h2>
                  {selectedRepo.name}{" "}
                  {loading && <span className="muted small">loading…</span>}
                </h2>
                <div className="muted small">
                  <code title={selectedRepo.ref_sha}>{shortSha(selectedRepo.ref_sha)}</code>
                  {" · "}
                  {selectedRepo.commit_count.toLocaleString()} commits at ingest
                  {" · "}
                  {selectedRepo.source_type === "url" && selectedRepo.source ? (
                    <a href={selectedRepo.source} target="_blank" rel="noreferrer">
                      source
                    </a>
                  ) : (
                    "zip upload"
                  )}
                </div>
              </div>
              <div className="header-actions">
                <div className="tabs">
                  {(["overview", "table", "authors"] as View[]).map((v) => (
                    <button
                      key={v}
                      className={view === v ? "tab active" : "tab"}
                      onClick={() => setView(v)}
                    >
                      {v === "overview" ? "Overview" : v === "table" ? "Metrics" : "Authors"}
                    </button>
                  ))}
                </div>
                <a className="btn btn-primary" href={exportHref} download>
                  ⭳ Export CSV
                </a>
              </div>
            </header>

            <div className="toolbar">
              <CommitSetBuilder
                repoId={selectedRepo.id}
                spec={setSpec}
                onSpec={setSetSpec}
              />

              <details className="dropdown">
                <summary className="btn">
                  Authors{authorIds.length > 0 ? ` (${authorIds.length})` : " (all)"} ▾
                </summary>
                <div className="menu">
                  {authors.map((a) => (
                    <label key={a.id} className="check">
                      <input
                        type="checkbox"
                        checked={authorIds.includes(a.id)}
                        onChange={() => toggleAuthor(a.id)}
                      />
                      <span>
                        {a.name} <span className="muted small">{a.email}</span>
                      </span>
                    </label>
                  ))}
                  {authorIds.length > 0 && (
                    <button className="btn btn-sm" onClick={() => setAuthorIds([])}>
                      Clear selection
                    </button>
                  )}
                </div>
              </details>

              {path !== "" && (
                <span className="chip chip-active">
                  path: /{path}
                  <button className="chip-x" onClick={() => setPath("")} title="Clear scope">
                    ×
                  </button>
                </span>
              )}

              {authorIds.length > 0 && (
                <span className="muted small">
                  (author filter active — most metrics are author-scoped)
                </span>
              )}
            </div>

            {metrics === null ? (
              <p className="muted pad">No metrics yet.</p>
            ) : view === "overview" ? (
              <Overview rows={metrics.rows} commitCount={metrics.commit_count} />
            ) : view === "table" ? (
              <>
                <nav className="breadcrumbs">
                  {crumbs.map((c, i) => (
                    <span key={c.value}>
                      {i > 0 && <span className="crumb-sep">/</span>}
                      <button
                        className={`crumb${c.value === path ? " current" : ""}`}
                        onClick={() => setPath(c.value)}
                      >
                        {c.label}
                      </button>
                    </span>
                  ))}
                </nav>
                <MetricsTable rows={metrics.rows} level={path} onNavigate={setPath} />
              </>
            ) : (
              <AuthorsPanel
                repoId={selectedRepo.id}
                authors={authors}
                onChanged={() => setAuthorsVersion((v) => v + 1)}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
