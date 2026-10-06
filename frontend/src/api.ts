import type {
  Author,
  CommitPage,
  Merge,
  MetricsResponse,
  Repo,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

type QueryValue = string | number | null | undefined;

function qs(params: object): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params) as [string, QueryValue][]) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface MetricsParams {
  set?: string;
  path?: string;
  authors?: string;
  object_type?: string;
}

export const api = {
  repos: () => fetch("/api/repos").then(json<Repo[]>),

  repo: (id: number) => fetch(`/api/repos/${id}`).then(json<Repo>),

  addUrl: (url: string, name?: string, ref?: string) =>
    fetch("/api/repos/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, name: name || null, ref: ref || "HEAD" }),
    }).then(json<{ id: number }>),

  addZip: (file: File, name?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (name) fd.append("name", name);
    fd.append("ref", "HEAD");
    return fetch("/api/repos/zip", { method: "POST", body: fd }).then(
      json<{ id: number }>,
    );
  },

  deleteRepo: (id: number) =>
    fetch(`/api/repos/${id}`, { method: "DELETE" }).then(json<void>),

  metrics: (id: number, params: MetricsParams) =>
    fetch(`/api/repos/${id}/metrics${qs(params)}`).then(
      json<MetricsResponse>,
    ),

  authors: (id: number) => fetch(`/api/repos/${id}/authors`).then(json<Author[]>),

  merges: (id: number) => fetch(`/api/repos/${id}/merges`).then(json<Merge[]>),

  addMerge: (id: number, source: number, target: number) =>
    fetch(`/api/repos/${id}/merges`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_author_id: source, target_author_id: target }),
    }).then(json<Merge>),

  removeMerge: (id: number, source: number) =>
    fetch(`/api/repos/${id}/merges/${source}`, { method: "DELETE" }).then(
      json<void>,
    ),

  commits: (id: number, params: { q?: string; limit?: number; offset?: number }) =>
    fetch(`/api/repos/${id}/commits${qs(params)}`).then(json<CommitPage>),

  exportUrl: (id: number, params: MetricsParams) =>
    `/api/repos/${id}/export.csv${qs(params)}`,
};
