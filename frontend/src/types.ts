export interface Repo {
  id: number;
  name: string;
  source_type: "url" | "zip" | string;
  source: string | null;
  ref_sha: string;
  commit_count: number;
  created_at: string;
  status: "ingesting" | "ready" | "error";
  error: string | null;
}

export interface MetricRow {
  repo: string;
  ref_sha: string;
  commit_set: string;
  commit_count: number;
  object_type: "repository" | "directory" | "file";
  path: string;
  author: string;
  added: number;
  removed: number;
  growth: number;
  churn: number;
  modifications: number;
  modification_frequency: number | "";
  churn_rate: number | "";
  ownership: number | "";
}

export interface MetricsResponse {
  repo_id: number;
  repo: string;
  ref_sha: string;
  commit_set: string;
  commit_count: number;
  rows: MetricRow[];
}

export interface Author {
  id: number;
  name: string;
  email: string;
  commit_count: number;
  churn: number;
  merged_into: number | null;
}

export interface Merge {
  source_author_id: number;
  target_author_id: number;
}

export interface CommitItem {
  sha: string;
  ts: number;
  author: string;
}

export interface CommitPage {
  total: number;
  items: CommitItem[];
}
