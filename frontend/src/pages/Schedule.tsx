import { Pencil, Play, Plus, Trash2, X } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { api, del, get, patch, post } from "../lib/api";
import { actions } from "../lib/store";
import { pickFolder } from "../lib/native";
import { Empty, Modal, fmtAgo, fmtDuration, modelLabel, modelName, useModelCatalog } from "../components/ui";
import { PRESETS, TIME_FORMAT, describeSchedule as describe } from "../lib/schedule";
import { ModalFooter } from "../components/ui";

type Task = { id: string; name: string; prompt: string; schedule: string; model: string; effort: string; folder: string | null; mode: string; enabled: boolean; next_run: number | null; runs: any[] };

/** Schedule: scheduled and recurring prompts (backend features/tasks_feature.py, REST /api/tasks).
 *  Not the task board, which is the Tasks page (pages/Board.tsx). */
export function SchedulePage() {
  useModelCatalog();
  const [data, setData] = useState<{ tasks: Task[]; running: any[] } | null>(null);
  const [editing, setEditing] = useState<Partial<Task> | null>(null);
  const load = () => get("/tasks").then(setData);
  useEffect(() => { load(); const t = setInterval(load, 10_000); return () => clearInterval(t); }, []);
  useEffect(() => actions.onEvent((e) => { if (e.type === "tasks.updated" || e.type === "job.updated") load(); }), []);

  const runNow = async (t: Task) => {
    const r = await post(`/tasks/${t.id}/run`);
    actions.toast(`Started "${t.name}" in a new session.`);
    load();
    return r;
  };

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[1000px] mx-auto px-6 py-5">
        <div className="flex items-center mb-1">
          <h1 className="text-lg font-semibold">Schedule</h1>
          <button className="btn btn-primary ml-auto" onClick={() => setEditing({ schedule: PRESETS[0][1], effort: "low", mode: "ask", enabled: true, model: "claude.standard" })}><Plus size={14} /> New schedule</button>
        </div>
        <p className="text-[13px] text-muted mb-4">Each run starts a new session with the task's model, effort, folder and mode. Schedules only fire while GameDevWorkstation is running; a run missed while it was closed is skipped.</p>

        {data?.tasks.length === 0 && <Empty>No scheduled prompts yet.</Empty>}
        <div className="space-y-2">
          {data?.tasks.map((t) => (
            <div key={t.id} className={`rounded-md border border-line surface px-3 py-2.5 ${t.enabled ? "" : "opacity-70"}`}>
              <div className="flex items-center gap-2">
                <span className="font-medium">{t.name}</span>
                <span className="text-[13px] text-muted">{describe(t.schedule)}</span>
                <div className="ml-auto flex items-center gap-1">
                  <span className="text-[12px] text-muted mr-2 tabular-nums">{t.next_run ? `Next: ${new Date(t.next_run * 1000).toLocaleString([], TIME_FORMAT)}` : t.enabled ? "No upcoming run" : ""}</span>
                  <label className="flex items-center gap-1.5 text-[12px] text-muted mr-2 cursor-pointer select-none" title={t.enabled ? "Runs on schedule" : "Won't run on schedule; Run now still works"}>
                    <input type="checkbox" checked={t.enabled} onChange={async (e) => { await patch(`/tasks/${t.id}`, { enabled: e.target.checked }); load(); }} />
                    Enabled
                  </label>
                  <button className="btn" onClick={() => runNow(t)}><Play size={13} /> Run now</button>
                  <button className="btn btn-ghost px-1.5" aria-label="Edit" onClick={() => setEditing(t)}><Pencil size={14} /></button>
                  <button className="btn btn-ghost btn-danger px-1.5" aria-label="Delete" onClick={async () => { if (confirm(`Delete "${t.name}"?`)) { await del(`/tasks/${t.id}`); load(); } }}><Trash2 size={14} /></button>
                </div>
              </div>
              <div className="text-[12px] text-muted mt-1">{modelLabel(t.model)} · {t.effort} · {t.mode === "accept_edits" ? "accept edits" : t.mode === "plan" ? "plan only" : "ask before edits"} · {t.folder ?? "chat (no folder)"}</div>
              <div className="text-[13px] mt-1 line-clamp-2">{t.prompt}</div>
              {t.runs.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {t.runs.slice(0, 8).map((r) => (
                    <button key={r.id} className="chip hover:text-text" onClick={() => r.session_id && actions.openSession(r.session_id)} title={r.session_title}>
                      <span className="size-1.5 rounded-full" style={{ background: r.status === "done" ? "var(--ok)" : r.status === "failed" ? "var(--bad)" : "var(--action)" }} />
                      {fmtAgo(r.started_at)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        <h2 className="font-semibold mt-8 mb-2">Running now, all sessions</h2>
        {!data?.running.length && <Empty>Nothing running.</Empty>}
        {data?.running.map((j) => (
          <div key={j.id} className="flex items-center gap-2 py-1.5 border-b border-line text-[13px]">
            <span className="size-2 rounded-full bg-action animate-pulse" />
            <span className="truncate">{j.title}</span>
            <button className="text-muted hover:text-action truncate" onClick={() => j.session_id && actions.openSession(j.session_id)}>{j.session_title}</button>
            <span className="ml-auto text-muted tabular-nums">{fmtDuration(j.elapsed_s)}</span>
            <button className="btn btn-ghost px-1" aria-label="Cancel" onClick={async () => { await post(`/jobs/${j.id}/cancel`); load(); }}><X size={13} /></button>
          </div>
        ))}
      </div>
      {editing && <TaskEditor t={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
    </div>
  );
}

function TaskEditor({ t, onClose, onSaved }: { t: Partial<Task>; onClose: () => void; onSaved: () => void }) {
  useModelCatalog();
  const [f, setF] = useState<Partial<Task>>(t);
  const [env, setEnv] = useState<any>(null);
  const [custom, setCustom] = useState(!PRESETS.some(([, v]) => v === t.schedule) && !!t.schedule);
  useEffect(() => { get("/environment").then(setEnv); }, []);
  const save = async () => {
    try {
      if (t.id) await patch(`/tasks/${t.id}`, f);
      else await api("/tasks", { method: "POST", body: f });
      onSaved();
    } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const L = "block mb-3";
  return (
    <Modal title={t.id ? "Edit schedule" : "New schedule"} onClose={onClose}>
      <label className={L}><span className="label">Name</span><input className="input" value={f.name ?? ""} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Morning inbox digest" /></label>
      <label className={L}><span className="label">Prompt</span><textarea className="input h-28" value={f.prompt ?? ""} onChange={(e) => setF({ ...f, prompt: e.target.value })} /></label>
      <div className={L}>
        <span className="label">Schedule</span>
        <div className="flex gap-2">
          <select className="input" value={custom ? "custom" : f.schedule} onChange={(e) => { if (e.target.value === "custom") setCustom(true); else { setCustom(false); setF({ ...f, schedule: e.target.value }); } }}>
            {PRESETS.map(([l, v]) => <option key={v} value={v}>{l}</option>)}
            <option value="custom">Custom (cron, once:…, every:…)</option>
          </select>
          {custom && <input className="input font-mono" value={f.schedule ?? ""} onChange={(e) => setF({ ...f, schedule: e.target.value })} placeholder="15 7 * * 1-5 or once:2026-12-01T09:00" />}
        </div>
        {custom && <span className="block text-[12px] text-faint mt-1">{f.schedule ? describe(f.schedule) : ""}</span>}
      </div>
      <div className="grid grid-cols-[1.6fr_0.8fr_1.1fr] gap-3">
        <label className={L}><span className="label">Model</span>
          <select className="input" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })}>
            {/* Runs use the built-in loop, which drives Claude and OpenAI (Responses API) models alike. */}
            {([["claude", "anthropic", "Claude"], ["codex", "openai", "OpenAI"]] as const).map(([prefix, provider, name]) => (
              <Fragment key={provider}>
                <optgroup label={`${name} tiers`}>
                  {env && Object.keys(env.tiers).filter((x) => x.startsWith(`${prefix}.`)).map((x) => <option key={x} value={x}>{modelLabel(x)}</option>)}
                </optgroup>
                <optgroup label={`${name} models`}>
                  {env?.models.filter((m: any) => m.provider === provider).map((m: any) => <option key={m.id} value={m.id}>{m.display_name || modelName(m.id)}</option>)}
                </optgroup>
              </Fragment>
            ))}
          </select>
        </label>
        <label className={L}><span className="label">Effort</span>
          <select className="input" value={f.effort} onChange={(e) => setF({ ...f, effort: e.target.value })}>{["none", "low", "medium", "high"].map((x) => <option key={x}>{x}</option>)}</select>
        </label>
        <label className={L}><span className="label">Mode</span>
          <select className="input" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}>
            <option value="ask">Ask before edits</option><option value="accept_edits">Accept edits</option><option value="plan">Plan only</option>
          </select>
        </label>
      </div>
      <div className={L}><span className="label">Folder</span>
        <div className="flex gap-2"><input className="input" value={f.folder ?? ""} onChange={(e) => setF({ ...f, folder: e.target.value || null })} placeholder="Chat (no folder)" />
          <button className="btn" onClick={async () => { const p = await pickFolder(f.folder ?? undefined); if (p !== null) setF({ ...f, folder: p || null }); }}>Choose…</button></div>
      </div>
      <p className="text-[12px] text-faint mb-3">In "Ask before edits" mode a scheduled run waits for you at each edit or command. Effort above high isn't available for scheduled runs.</p>
      <ModalFooter><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.name || !f.prompt || !f.schedule} onClick={save}>{t.id ? "Save" : "Create schedule"}</button></ModalFooter>
    </Modal>
  );
}
