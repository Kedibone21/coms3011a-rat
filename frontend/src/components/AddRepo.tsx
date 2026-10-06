import { useRef, useState } from "react";
import { api } from "../api";

export default function AddRepo({ onAdded }: { onAdded: (id: number) => void }) {
  const [tab, setTab] = useState<"url" | "zip">("url");
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function submitUrl() {
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.addUrl(url.trim(), name.trim() || undefined);
      setUrl("");
      setName("");
      onAdded(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submitZip() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.addZip(file, name.trim() || undefined);
      setFile(null);
      setName("");
      onAdded(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="addrepo">
      <div className="tabs tabs-sm">
        <button
          className={tab === "url" ? "tab active" : "tab"}
          onClick={() => setTab("url")}
        >
          Clone URL
        </button>
        <button
          className={tab === "zip" ? "tab active" : "tab"}
          onClick={() => setTab("zip")}
        >
          Zip upload
        </button>
      </div>

      {tab === "url" ? (
        <>
          <input
            className="input"
            placeholder="https://github.com/owner/repo.git"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitUrl()}
          />
          <input
            className="input"
            placeholder="Display name (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button
            className="btn btn-primary btn-block"
            disabled={busy || !url.trim()}
            onClick={submitUrl}
          >
            {busy ? "Adding…" : "Clone & ingest"}
          </button>
          <p className="muted small">
            Public repositories only (http/https). Ingest runs in the background.
          </p>
        </>
      ) : (
        <>
          <div
            className={`dropzone${drag ? " dragging" : ""}`}
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              const f = e.dataTransfer.files?.[0];
              if (f) setFile(f);
            }}
          >
            {file ? (
              <span>{file.name}</span>
            ) : (
              <span>
                Drop a .zip here
                <br />
                <span className="muted small">
                  must contain a .git directory — zip the full repository folder
                  (including .git)
                </span>
              </span>
            )}
            <input
              ref={fileInput}
              type="file"
              accept=".zip,application/zip"
              hidden
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <input
            className="input"
            placeholder="Display name (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button
            className="btn btn-primary btn-block"
            disabled={busy || !file}
            onClick={submitZip}
          >
            {busy ? "Uploading…" : "Upload & ingest"}
          </button>
        </>
      )}

      {error && <p className="error-text small">{error}</p>}
    </div>
  );
}
