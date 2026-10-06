export function fmtInt(n: number | ""): string {
  if (n === "") return "";
  return n.toLocaleString("en-US");
}

export function fmtFloat(v: number | ""): string {
  if (v === "") return "";
  if (v === 0) return "0";
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
  if (abs >= 1) return v.toLocaleString("en-US", { maximumFractionDigits: 3 });
  return v.toPrecision(4).replace(/0+$/, "").replace(/\.$/, "");
}

export function fmtPercent(v: number | ""): string {
  if (v === "") return "";
  return `${(v * 100).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
}

export function shortSha(sha: string): string {
  return sha ? sha.slice(0, 8) : "";
}

export function tsToInput(ts: number): string {
  const d = new Date(ts * 1000);
  const pad = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

export function inputToTs(value: string): number | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  if (Number.isNaN(ms)) return null;
  return Math.floor(ms / 1000);
}

export function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Direct parent directory of a repo-relative path ("" for repo root). */
export function dirOf(path: string): string {
  const i = path.lastIndexOf("/");
  return i === -1 ? "" : path.slice(0, i);
}

export function baseName(path: string): string {
  const i = path.lastIndexOf("/");
  return i === -1 ? path : path.slice(i + 1);
}
