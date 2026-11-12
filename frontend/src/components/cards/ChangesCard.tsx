import { RefreshCw, Trash2, Undo2 } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { get, post } from "../../lib/api";
import { actions, type Session } from "../../lib/store";
import { Card } from "../SidePanel";
import { Modal } from "../ui";

const DiffView = lazy(() => import("../DiffView"));

/** too_large: the file was over the snapshot size cap before the agent's first write, so there's no
 *  "before" copy to diff against or revert to. */
type Change = { path: string; root: string; where: string; added: number; removed: number; status: string; binary: boolean; too_large?: boolean; note?: string };
type Worktree = { unit: string; where: string; branch: string; dirty: boolean; ahead: number; unmerged: boolean };

export function ChangesCard({ s }: { s: Session }) {
  const [data, setData] = useState<{ mode: string; files: Change[]; worktrees?: Worktree[]; added: number; removed: number } | null>(null);
  const [diff, setDiff] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    if (!s.folder) return setData(null);
    setBusy(true);
    try { setData(await get(`/sessions/${s.id}/changes`)); } catch {} finally { setBusy(false); }
  };
  useEffect(() => { load(); }, [s.id, s.folder]);
  useEffect(() => {
    let t: any;
    const off = actions.onEvent((e) => {
      if (e.session_id === s.id && (e.type === "file.changed" || e.type === "agent.idle")) { clearTimeout(t); t = setTimeout(load, 400); }
    });
    return () => { off(); clearTimeout(t); };
  }, [s.id]);

  const open = async (f: Change) => setDiff(await get(`/sessions/${s.id}/changes/diff?${new URLSearchParams({ root: f.root, path: f.path })}`));
  const revert = async (f: Change) => {
    const what = f.status === "added" ? `Delete the new file ${f.path}?` : `Revert ${f.path} to ${data?.mode === "git" ? "the last commit" : "how it was before the agent changed it"}?`;
    if (!confirm(what)) return;
    try { await post(`/sessions/${s.id}/changes/revert`, { root: f.root, path: f.path }); load(); } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const discard = async (w: Worktree) => {
    // Clean worktrees: one confirmation. Unmerged ones: the server refuses without force and says
    // exactly what would be lost, and that is what the user confirms.
    if (!w.unmerged && !confirm(`Discard worktree ${w.unit} and its branch ${w.branch}?`)) return;
    try {
      let r = await post(`/sessions/${s.id}/worktrees/${w.unit}/discard`, {});
      if (r.needs_confirm) {
        if (!confirm(`Discard worktree ${w.unit}? ${w.branch} has ${r.detail}, which will be lost.`)) return;
        r = await post(`/sessions/${s.id}/worktrees/${w.unit}/discard`, { force: true });
      }
      if (r.discarded) actions.toast(`Discarded ${w.unit}`);
      load();
    } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const groups = (data?.files ?? []).reduce<Record<string, Change[]>>((a, f) => ((a[f.where] ??= []).push(f), a), {});
  const trees = Object.fromEntries((data?.worktrees ?? []).map((w) => [w.where, w]));
  for (const w of data?.worktrees ?? []) groups[w.where] ??= [];

  return (
    <Card id="changes" title={`Changes${data?.files.length ? ` (${data.files.length})` : ""}`}
      right={<button className="btn btn-ghost px-1 py-0.5" onClick={load} title="Refresh" aria-label="Refresh changes"><RefreshCw size={13} className={busy ? "animate-spin" : ""} /></button>}>
      {!s.folder && <div className="text-muted">Pick a folder in Environment to track file changes.</div>}
      {s.folder && data && data.files.length === 0 && !data.worktrees?.length && <div className="text-muted">No changes{data.mode === "git" ? " since the last commit" : " yet"}.</div>}
      {data && data.files.length > 0 && (
        <div className="text-[12px] text-muted mb-1 tabular-nums"><span style={{ color: "var(--ok)" }}>+{data.added}</span> <span style={{ color: "var(--bad)" }}>−{data.removed}</span> · {data.mode === "git" ? "vs last commit" : "vs before agent edits"}</div>
      )}
      {Object.entries(groups).map(([where, files]) => (
        <div key={where} className="mb-1">
          {(Object.keys(groups).length > 1 || trees[where]) && (
            <div className="label mt-1 flex items-center gap-1">
              <span className="flex-1 min-w-0 truncate">{where === "folder" ? "Session folder" : where}{trees[where] && !files.length ? (trees[where].ahead ? ` · ${trees[where].ahead} unmerged commit${trees[where].ahead === 1 ? "" : "s"}` : " · no changes") : ""}</span>
              {trees[where] && <button className="btn btn-ghost px-1 py-0 normal-case" title="Discard this worktree and its branch" aria-label={`Discard worktree ${trees[where].unit}`} onClick={() => discard(trees[where])}><Trash2 size={12} /> Discard worktree</button>}
            </div>
          )}
          {files.map((f) => (
            <div key={f.root + f.path} className="group flex items-center gap-1.5 py-0.5">
              <button className="flex-1 min-w-0 text-left truncate hover:text-action" onClick={() => open(f)} title={f.too_large ? `${f.path}: ${f.note}` : f.path} disabled={f.binary || f.too_large}>
                <span className={f.status === "deleted" ? "line-through text-muted" : ""}>{f.path}</span>
              </button>
              <span className="tabular-nums text-[11.5px] shrink-0">
                {f.too_large ? <span className="text-faint">{f.note ?? "too large to snapshot"}</span> : f.binary ? <span className="text-faint">binary</span> : <><span style={{ color: "var(--ok)" }}>+{f.added}</span> <span style={{ color: "var(--bad)" }}>−{f.removed}</span></>}
              </span>
              {!f.too_large && <button className="opacity-0 group-hover:opacity-100 focus:opacity-100 btn btn-ghost px-1 py-0" title="Revert this file" aria-label={`Revert ${f.path}`} onClick={() => revert(f)}><Undo2 size={12} /></button>}
            </div>
          ))}
        </div>
      ))}
      {diff && (
        <Modal title={diff.path} onClose={() => setDiff(null)} wide>
          <Suspense fallback={<div className="text-muted">Loading diff…</div>}>
            <DiffView original={diff.original} modified={diff.modified} language={diff.language} />
          </Suspense>
        </Modal>
      )}
    </Card>
  );
}
