import { Play, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { get, post, type GateStatus, type LadderLevel, type LadderPill } from "../../lib/api";
import { actions, type Session } from "../../lib/store";
import { ItemViewer } from "../items";
import { Card } from "../SidePanel";
import { fmtAgo } from "../ui";

// Wire shapes of GET /api/ladder (features/ladder.py Ladder.report).
type EvidenceBrief = {
  id: string; level: string; status: GateStatus; source: string; observed: string; ts: number; path: string | null;
  item_id: string | null; subjects: string[]; summary: string; fresh: boolean | null;
};
type LevelState = { level: LadderLevel; state: LadderPill; missing: string[]; evidence: EvidenceBrief[]; shots: { path: string; item_id: string | null }[] };
type StoryState = {
  id: string; title: string; status: string; milestone: string; ok: boolean; missing: string[];
  override: EvidenceBrief | null; levels: Record<LadderLevel, LevelState>;
};
type GateRun = { gate: string; status: GateStatus; summary: string | null; attempt: number; level: string | null; started_at: number };
export type LadderReport = {
  enabled: boolean; project: string | null; unity: boolean; backlog: boolean; current: string | null;
  stories: StoryState[]; gates: GateRun[];
};
/** GET /api/hooks (WP2): only the parts this card uses; absent when the hooks engine isn't there. */
type HooksInfo = { sources?: { kind: string; name: string; state: string; active: boolean }[] };

export const LEVELS: [LadderLevel, string][] = [["L1", "L1"], ["L2", "L2"], ["L3", "L3"], ["L4", "L4"], ["manual", "Manual"]];
const UNITY_PRESET = "unity-router";

const PILL_STYLE: Record<LadderPill, { color: string; mark: string }> = {
  pass: { color: "var(--ok)", mark: "✓" },
  fail: { color: "var(--bad)", mark: "✗" },
  stale: { color: "var(--warn, #c98a00)", mark: "↻" },
  pending: { color: "var(--muted, #888)", mark: "…" },
  "n/a": { color: "var(--faint, #aaa)", mark: "–" },
};

function Pill({ level, label, state, active, onClick }: { level: string; label: string; state: LadderPill; active: boolean; onClick: () => void }) {
  const st = PILL_STYLE[state] ?? PILL_STYLE.pending;
  return (
    <button
      className={`px-1.5 py-0 rounded border text-[11.5px] tabular-nums ${active ? "border-action" : "border-line"}`}
      style={{ color: st.color, opacity: state === "n/a" ? 0.6 : 1 }}
      title={`${label}: ${state}`} aria-label={`${level} ${state}`} aria-pressed={active} onClick={onClick}>
      {label} {st.mark}
    </button>
  );
}

/** Side-panel card for the quality ladder and Unity gates: the gate toggle and consent, the last
 *  result of each gate, L1–L4 + Manual pills for the stories in progress (click one for its
 *  evidence), and Run compile gate / Run critique / Refresh project context. Renders nothing for
 *  sessions whose folder has neither a BACKLOG.md nor a Unity project. */
export function QualityCard({ s }: { s: Session }) {
  const [rep, setRep] = useState<LadderReport | null>(null);
  const [hooks, setHooks] = useState<HooksInfo | null>(null);
  const [open, setOpen] = useState<{ story: string; level: LadderLevel } | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const seq = useRef(0);

  const load = async () => {
    const n = ++seq.current;
    if (!s.folder) return setRep(null);
    try {
      const r = await get<LadderReport>(`/ladder?session_id=${encodeURIComponent(s.id)}`);
      if (n === seq.current) setRep(r);
    } catch { if (n === seq.current) setRep(null); }
    try { setHooks(await get<HooksInfo>(`/hooks?session_id=${encodeURIComponent(s.id)}`)); } catch { setHooks(null); }
  };
  useEffect(() => { setOpen(null); load(); }, [s.id, s.folder]);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = actions.onEvent((e) => {
      const mine = e.session_id === s.id || (e.type === "ladder.updated" && !!rep?.project && e.data?.project === rep.project);
      if (mine && ["ladder.updated", "gate.result", "gate.exhausted", "agent.idle", "file.changed"].includes(e.type)) {
        clearTimeout(t);
        t = setTimeout(load, 400);
      }
    });
    return () => { off(); clearTimeout(t); };
  }, [s.id, rep?.project]);

  if (!rep || !rep.enabled) return null;

  const run = async (key: string, path: string, body: unknown, ok: string) => {
    setBusy(key);
    try { await post(path, body); actions.toast(ok); } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(null); }
  };
  const preset = hooks?.sources?.find((p) => p.kind === "preset" && p.name === UNITY_PRESET);
  const toggleGates = () => run("preset", "/hooks/preset", { project: rep.project, preset: UNITY_PRESET, enabled: !preset?.active },
    preset?.active ? "Unity gates off" : "Unity gates: confirm on the card in the chat").then(load);
  const accept = async (st: StoryState) => {
    const note = prompt(`Accept ${st.id} without the missing evidence?\n\n${st.missing.slice(0, 8).join("\n")}\n\nNote (optional):`);
    if (note === null) return;
    await run(`accept:${st.id}`, "/ladder/override", { session_id: s.id, story: st.id, note }, `${st.id} accepted`);
    load();
  };

  const sel = open && rep.stories.find((x) => x.id === open.story)?.levels[open.level];
  return (
    <Card id="quality" title="Quality"
      right={<button className="btn btn-ghost px-1 py-0.5" onClick={load} title="Refresh" aria-label="Refresh quality"><RefreshCw size={13} /></button>}>
      {rep.unity && (
        <label className="flex items-center gap-2 py-1">
          <input type="checkbox" checked={!!preset?.active} disabled={!hooks || busy === "preset"} onChange={toggleGates} aria-label="Unity gates" />
          <span className="flex-1">Unity gates</span>
          <span className="text-[11.5px] text-muted">{!hooks ? "unavailable" : preset?.active ? "on" : preset?.state === "needs_consent" || preset?.state === "changed" ? "needs consent" : "off"}</span>
        </label>
      )}
      {rep.gates.length > 0 && (
        <div className="mb-1">
          <div className="label mt-1">Gates</div>
          {rep.gates.slice(0, 8).map((g) => (
            <div key={g.gate} className="flex items-center gap-1.5 py-0.5 text-[12px]" title={g.summary ?? ""}>
              <span style={{ color: g.status === "pass" ? "var(--ok)" : g.status === "fail" ? "var(--bad)" : undefined }} className="w-12 shrink-0">{g.status}</span>
              <span className="flex-1 min-w-0 truncate">{g.gate}</span>
              <span className="text-faint shrink-0">{fmtAgo(g.started_at)}</span>
            </div>
          ))}
        </div>
      )}
      <div className="label mt-1">{rep.current ? `Stories in progress · ${rep.current}` : "Stories in progress"}</div>
      {!rep.backlog && <div className="text-muted">No BACKLOG.md in this folder.</div>}
      {rep.backlog && rep.stories.length === 0 && <div className="text-muted">No story is in progress (status doing).</div>}
      {rep.stories.map((st) => (
        <div key={st.id} className="py-1">
          <div className="flex items-center gap-1.5">
            <span className="flex-1 min-w-0 truncate" title={st.title}><span className="tabular-nums">{st.id}</span> {st.title}</span>
            {st.override ? <span className="text-[11.5px] text-muted">accepted by you</span>
              : st.ok ? <span className="text-[11.5px]" style={{ color: "var(--ok)" }}>ready</span>
              : <button className="text-[11.5px] text-action hover:underline" onClick={() => accept(st)} disabled={busy === `accept:${st.id}`}
                  title="Accept this story without the missing evidence">Accept…</button>}
          </div>
          <div className="flex flex-wrap gap-1 mt-0.5" role="group" aria-label={`${st.id} ladder`}>
            {LEVELS.map(([lv, label]) => (
              <Pill key={lv} level={lv} label={label} state={st.levels[lv]?.state ?? "n/a"} active={open?.story === st.id && open.level === lv}
                onClick={() => setOpen(open?.story === st.id && open.level === lv ? null : { story: st.id, level: lv })} />
            ))}
          </div>
          {open?.story === st.id && sel && (
            <div className="mt-1 pl-2 border-l border-line text-[12px]" data-testid="ladder-detail">
              {sel.state === "n/a" && <div className="text-muted">Not needed for this story.</div>}
              {sel.missing.map((m, i) => <div key={i} className="text-muted">• {m}</div>)}
              {sel.evidence.map((e) => (
                <div key={e.id} className="flex items-center gap-1.5 py-0.5" title={e.path ?? e.source}>
                  <span style={{ color: e.status === "pass" ? "var(--ok)" : "var(--bad)" }}>{e.status}</span>
                  <span className="flex-1 min-w-0 truncate">{e.summary || e.source}</span>
                  {e.fresh === false && <span className="text-faint">stale</span>}
                  {e.item_id && <button className="text-action hover:underline" onClick={() => setViewing(e.item_id)}>open</button>}
                  <span className="text-faint shrink-0">{fmtAgo(e.ts)}</span>
                </div>
              ))}
              {sel.shots.map((sh) => (
                <div key={sh.path} className="flex items-center gap-1.5 py-0.5">
                  <span className="flex-1 min-w-0 truncate" title={sh.path}>{sh.path}</span>
                  {sh.item_id && <button className="text-action hover:underline" onClick={() => setViewing(sh.item_id)}>view</button>}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
      <div className="flex flex-wrap gap-1 mt-2">
        {rep.unity && (
          <button className="btn btn-ghost px-1.5 py-0.5 text-[12px]" disabled={busy !== null}
            onClick={() => run("compile", "/hooks/run", { session_id: s.id, gate: "unity.compile" }, "Compile gate started")}>
            <Play size={12} /> Run compile gate
          </button>
        )}
        {rep.backlog && (
          <button className="btn btn-ghost px-1.5 py-0.5 text-[12px]" disabled={busy !== null || rep.stories.length === 0}
            title="Three reviewers look at the stories in progress (about $0.15 per round)"
            onClick={() => run("critique", "/ladder/critique", { session_id: s.id, stories: rep.stories.map((x) => x.id) }, "Critique started")}>
            <Sparkles size={12} /> Run critique
          </button>
        )}
        <button className="btn btn-ghost px-1.5 py-0.5 text-[12px]" disabled={busy !== null}
          onClick={() => run("context", "/hooks/run", { session_id: s.id, gate: "context.pack" }, "Project context refreshed")}>
          <RefreshCw size={12} /> Refresh project context
        </button>
      </div>
      {viewing && <ItemViewer id={viewing} onClose={() => setViewing(null)} />}
    </Card>
  );
}
