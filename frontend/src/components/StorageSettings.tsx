import { FolderOpen, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { get, post } from "../lib/api";
import { revealInFinder } from "../lib/native";
import { actions } from "../lib/store";
import { fmtAgo } from "./ui";

type Usage = {
  database: { path: string; bytes: number; free_bytes: number; auto_vacuum: string; schema_version: number };
  events: { count: number; bytes: number; retention_days: number };
  snapshots: { count: number; bytes: number; too_large: number };
  media: { path: string; bytes: number };
  transcripts: { path: string; bytes: number };
  logs: { path: string; bytes: number };
  last_maintenance: number | null;
};

export function fmtBytes(n?: number | null): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1);
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/** Settings → Storage: what Workspace keeps on disk, and Compact now (prune old events + VACUUM). */
export function StorageSettings() {
  const [u, setU] = useState<Usage | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => get<Usage>("/storage").then(setU).catch((e) => actions.toast(e.message, "error"));
  useEffect(() => { load(); }, []);
  const compact = async () => {
    setBusy(true);
    try {
      const r = await post<{ pruned_events: number; freed_bytes: number; usage: Usage }>("/storage/compact");
      setU(r.usage);
      actions.toast(`Compacted: ${fmtBytes(r.freed_bytes)} freed${r.pruned_events ? `, ${r.pruned_events.toLocaleString()} old events removed` : ""}.`);
    } catch (e: any) {
      actions.toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const reveal = (p: string) => revealInFinder(p).then((ok) => { if (!ok) actions.toast(p); });
  const rows: [string, number | undefined, string, string?][] = u ? [
    ["Database", u.database.bytes, `${u.database.free_bytes ? `at least ${fmtBytes(u.database.free_bytes)} reclaimable` : "Compact may reclaim fragmented space"} · version ${u.database.schema_version}`, u.database.path],
    ["  of which: event log", u.events.bytes, `${u.events.count.toLocaleString()} events, kept ${u.events.retention_days} days`],
    ["  of which: file snapshots", u.snapshots.bytes, `${u.snapshots.count.toLocaleString()} files${u.snapshots.too_large ? `, ${u.snapshots.too_large} too large to snapshot` : ""}`],
    ["Media and uploads", u.media.bytes, "", u.media.path],
    ["Subagent transcripts", u.transcripts.bytes, "", u.transcripts.path],
    ["Logs", u.logs.bytes, "", u.logs.path],
  ] : [];
  return (
    <section>
      <h2 className="font-semibold text-[15px] mb-1">Storage</h2>
      <p className="text-muted text-[13px] mb-3">
        Every day Workspace removes events older than {u?.events.retention_days ?? 7} days and gives free space back. Deleting a session
        for good removes its messages, snapshots, transcripts and the files it stored. Compact rewrites the database at its smallest.
      </p>
      {!u ? <div className="text-muted text-[13px]">Measuring…</div> : (
        <table className="w-full text-[13px] mb-3">
          <tbody>
            {rows.map(([label, bytes, detail, path]) => (
              <tr key={label} className="border-b border-line">
                <td className={`py-1.5 pr-3 whitespace-nowrap ${label.startsWith("  ") ? "pl-4 text-muted" : ""}`}>{label.trim()}</td>
                <td className="py-1.5 pr-3 tabular-nums text-right whitespace-nowrap">{fmtBytes(bytes)}</td>
                <td className="py-1.5 pr-3 text-muted">{detail}</td>
                <td className="py-1.5 text-right">{path && (
                  <button className="btn btn-ghost px-1 py-0.5" onClick={() => reveal(path)} title={path} aria-label={`Show ${label.trim()} in Finder`}><FolderOpen size={13} /></button>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="flex items-center gap-2">
        <button className="btn btn-primary" onClick={compact} disabled={busy || !u}>{busy ? "Compacting…" : "Compact database now"}</button>
        <button className="btn btn-ghost px-1.5" onClick={load} aria-label="Measure again" title="Measure again"><RefreshCw size={14} /></button>
        {u?.last_maintenance && <span className="text-faint text-[12px]">Last cleanup {fmtAgo(u.last_maintenance)}</span>}
      </div>
      {busy && <p className="text-muted text-[12px] mt-2" role="status">Agents may pause for a moment while the database is rewritten.</p>}
    </section>
  );
}
