import { ArrowLeft, Copy, FileText, MessageSquare, Pause, Play, Plus, RefreshCw, ShieldCheck, Square, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { SafeMarkdown } from "../components/SafeMarkdown";
import { Empty, Modal, ModalFooter, fmtAgo, fmtDuration, modelLabel, useModelCatalog } from "../components/ui";
import {
  CAMPAIGN_EVENTS, MIN_CAMPAIGN_WORDS, STATUS_LABEL, TONE_COLOR, campaignsApi, describeCondition, listItems, phaseChecks, phaseLabel,
  spendLabel, statusTone, templatesFor, wordCount, type CampaignAction, type CampaignDetail, type CampaignMetrics, type CampaignRow,
  type ChainTemplate, type PhaseState,
} from "../lib/campaigns";
import { openLocalFile, pickFolder } from "../lib/native";
import { actions, useStore } from "../lib/store";

const CHECK_COLOR: Record<string, string> = { pass: "var(--ok)", fail: "var(--bad)", pending: "var(--muted, #888)", skipped: "var(--warn, #c98a00)" };

function StatusPill({ status }: { status: CampaignRow["status"] }) {
  const color = TONE_COLOR[statusTone(status)];
  return (
    <span className="chip text-[11.5px] shrink-0" style={{ color, borderColor: color }} data-testid="status-pill">
      <span className="size-1.5 rounded-full" style={{ background: color }} />{STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** Campaigns and workflow chains: the list (status, phase x/y, spend vs budget, last activity), a
 *  detail view (phases with their checks, design target, coverage, review queue, decisions,
 *  discoveries, the session chain and checkpoints, and the lifecycle buttons), the New-campaign
 *  dialog and the metrics footer. */
export function CampaignsPage() {
  const args = useStore((s) => s.pageArgs);
  const [data, setData] = useState<{ campaigns: CampaignRow[]; metrics: CampaignMetrics } | null>(null);
  const [openId, setOpenId] = useState<string | null>(args?.id ?? null);
  const [creating, setCreating] = useState(false);
  const load = () => campaignsApi.list().then(setData).catch((e) => actions.toast(e.message, "error"));
  useEffect(() => { load(); }, []);
  useEffect(() => { if (args?.id) setOpenId(args.id); }, [args?.id]);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = actions.onEvent((e) => {
      // (paused / parked / done toasts come from store.handleEvent, on every page)
      if (CAMPAIGN_EVENTS.includes(e.type)) { clearTimeout(t); t = setTimeout(load, 300); }
    });
    return () => { off(); clearTimeout(t); };
  }, []);

  if (openId) return <CampaignDetailView id={openId} onBack={() => { setOpenId(null); actions.go("campaigns"); load(); }} />;
  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[1000px] mx-auto px-6 py-5">
        <div className="flex items-center mb-1">
          <h1 className="text-lg font-semibold">Campaigns</h1>
          <button className="btn btn-primary ml-auto" onClick={() => setCreating(true)}><Plus size={14} /> New campaign</button>
        </div>
        <p className="text-[13px] text-muted mb-4">
          Multi-session work with a plan you approve, phases with checks GameDevWorkstation runs itself, and a campaign file in the project.
          For one-session work pick a workflow from the composer's skills menu (or type <span className="font-mono">/workflow</span>).
        </p>
        {data?.campaigns.length === 0 && <Empty>No campaigns or workflows yet.</Empty>}
        <div className="space-y-2">
          {data?.campaigns.map((c) => (
            <button key={c.id} className="w-full text-left rounded-md border border-line surface px-3 py-2.5 hover:border-action" onClick={() => setOpenId(c.id)}>
              <div className="flex items-center gap-2">
                <span className="font-medium truncate">{c.title}</span>
                <span className="text-[12px] text-muted shrink-0">{c.kind === "chain" ? "workflow" : "campaign"} · {c.template_title ?? c.template}</span>
                <span className="ml-auto" />
                <StatusPill status={c.status} />
              </div>
              <div className="text-[12px] text-muted mt-1 flex flex-wrap gap-x-3">
                <span>{c.kind === "chain" ? "Step" : "Phase"} {phaseLabel(c)}</span>
                <span className="tabular-nums">{spendLabel(c.spend_usd, c.budget_usd)}</span>
                <span>{c.sessions ?? 0} session{c.sessions === 1 ? "" : "s"}</span>
                {c.autopilot && <span>autopilot</span>}
                <span className="truncate" title={c.folder}>{c.folder}</span>
                <span className="ml-auto">{fmtAgo(c.last_activity ?? c.updated_at)}</span>
              </div>
              {c.reason && c.status !== "running" && <div className="text-[12px] mt-0.5" style={{ color: TONE_COLOR[statusTone(c.status)] }}>{c.reason}</div>}
            </button>
          ))}
        </div>
        {data && data.metrics.campaigns > 0 && <Metrics m={data.metrics} />}
      </div>
      {creating && <NewCampaignDialog onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); load(); setOpenId(id); }} />}
    </div>
  );
}

function Metrics({ m }: { m: CampaignMetrics }) {
  const pct = (x: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);
  const parks = Object.entries(m.parks_by_reason);
  return (
    <div className="mt-8 border-t border-line pt-3 text-[12px] text-muted" aria-label="Campaign metrics">
      <div className="label mb-1">Metrics</div>
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        <span>Spend ${m.spend_usd.toFixed(2)}</span>
        <span>Cost per story {m.cost_per_story_usd == null ? "—" : `$${m.cost_per_story_usd.toFixed(2)}`}</span>
        <span>Time per story {m.wall_s_per_story == null ? "—" : fmtDuration(m.wall_s_per_story)}</span>
        <span>First-pass gate rate {pct(m.first_pass_gate_rate)}</span>
        <span>Gate retries per phase {m.gate_retries_per_phase ?? "—"}</span>
        <span>Escalations {m.escalations}</span>
        {parks.length > 0 && <span>Parks: {parks.map(([k, v]) => `${k} ×${v}`).join(", ")}</span>}
      </div>
    </div>
  );
}

function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="mt-5">
      <div className="flex items-center mb-1.5"><h2 className="font-semibold text-[14px]">{title}</h2><span className="ml-auto">{right}</span></div>
      {children}
    </section>
  );
}

function PhaseRow({ p, i, current, kind }: { p: PhaseState; i: number; current: boolean; kind: string }) {
  const checks = phaseChecks(p);
  return (
    <tr className={`border-b border-line align-top ${current ? "bg-sunken" : ""}`}>
      <td className="py-1.5 pr-2 tabular-nums text-muted">{i + 1}</td>
      <td className="py-1.5 pr-2"><span className="font-medium">{p.name}</span><div className="text-[11.5px] text-muted">{p.type}{p.skills.length ? ` · ${p.skills.join(", ")}` : ""}{p.fleet ? " · fleet-eligible" : ""}</div></td>
      <td className="py-1.5 pr-2">
        <div className="flex flex-wrap gap-1">
          {checks.map((x, j) => (
            <span key={j} className="chip text-[11.5px]" style={{ color: CHECK_COLOR[x.status] }} title={x.detail || x.status}>{x.label}</span>
          ))}
        </div>
      </td>
      <td className="py-1.5 pr-2 text-[12px]">{p.status ?? "pending"}{current && kind !== "chain" ? " ◀" : ""}</td>
      <td className="py-1.5 text-[12px] tabular-nums text-muted">{p.retries ?? "—"}/{p.retries_max ?? p.retries ?? "—"}</td>
    </tr>
  );
}

function CampaignDetailView({ id, onBack }: { id: string; onBack: () => void }) {
  const [c, setC] = useState<CampaignDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [budget, setBudget] = useState("");
  const seq = useRef(0);
  const load = async () => {
    const n = ++seq.current;
    try {
      const d = await campaignsApi.detail(id);
      if (n === seq.current) { setC(d); setBudget(d.budget_usd == null ? "" : String(d.budget_usd)); }
    } catch (e: any) { actions.toast(e.message, "error"); }
  };
  useEffect(() => { load(); }, [id]);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = actions.onEvent((e) => { if (CAMPAIGN_EVENTS.includes(e.type) && e.data?.id === id) { clearTimeout(t); t = setTimeout(load, 300); } });
    return () => { off(); clearTimeout(t); };
  }, [id]);
  if (!c) return <div className="p-6 text-muted">Loading…</div>;

  const act = async (a: CampaignAction, body: Record<string, unknown> = {}, ok?: string) => {
    setBusy(a);
    try { await campaignsApi.act(c.id, a, body); if (ok) actions.toast(ok); await load(); } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(null); }
  };
  const save = async (body: Parameters<typeof campaignsApi.update>[1]) => {
    try { await campaignsApi.update(c.id, body); await load(); } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const st = c.status;
  const resumable = ["paused", "waiting_user", "interrupted", "parked"].includes(st);
  const live = !["done", "abandoned"].includes(st);
  const cur = c.phase >= 0 ? c.phases[c.phase] : undefined;
  const manual = cur ? cur.done_when.map((d, j) => ({ d, j })).filter((x) => x.d.type === "manual") : [];
  const answerManual = async (j: number, decision: "pass" | "fail") => {
    const note = prompt(decision === "pass" ? "Note (optional):" : "What's wrong? (the agent reads this)") ?? "";
    try { await campaignsApi.review(c.id, c.phase, j, decision, note); await load(); } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const btn = "btn px-2 py-1 text-[12.5px]";
  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[1000px] mx-auto px-6 py-5">
        <button className="btn btn-ghost px-1.5 -ml-1.5 mb-2 text-[13px]" onClick={onBack}><ArrowLeft size={14} /> All campaigns</button>
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold truncate">{c.title}</h1>
          <StatusPill status={st} />
          <button className="btn btn-ghost px-1 ml-auto" onClick={load} aria-label="Refresh"><RefreshCw size={14} /></button>
        </div>
        <div className="text-[12.5px] text-muted mt-0.5">
          {c.kind === "chain" ? "Workflow" : "Campaign"} · {c.template_title ?? c.template} · {c.kind === "chain" ? "step" : "phase"} {phaseLabel(c)} · {spendLabel(c.spend_usd, c.budget_usd)} · {c.sessions ?? 0}/{c.max_sessions ?? "—"} sessions
          {c.model ? ` · ${modelLabel(c.model)}` : ""}{c.effort ? ` · ${c.effort}` : ""}
        </div>
        {c.reason && st !== "running" && <div className="mt-1 text-[13px]" style={{ color: TONE_COLOR[statusTone(st)] }}>{c.reason}</div>}
        <div className="mt-2 text-[13px]"><span className="label">Next action </span>{c.next_action}</div>

        <div className="flex flex-wrap gap-1.5 mt-3" role="toolbar" aria-label="Campaign actions">
          {st === "draft" && <button className={`${btn} btn-primary`} disabled={!!busy} onClick={() => act("start", {}, "Planning started in a new session")}><Play size={13} /> Start</button>}
          {st === "awaiting_approval" && <button className={`${btn} btn-primary`} disabled={!!busy} onClick={() => act("approve_plan", {}, "Plan approved")}><ShieldCheck size={13} /> Approve plan</button>}
          {st === "awaiting_approval" && <button className={btn} disabled={!!busy} onClick={() => { const note = prompt("What should change in the plan?"); if (note !== null) act("revise_plan", { note }); }}>Revise plan…</button>}
          {st === "running" && <button className={btn} disabled={!!busy} onClick={() => act("pause", {}, "Pauses after the current turn")}><Pause size={13} /> Pause</button>}
          {resumable && <button className={`${btn} btn-primary`} disabled={!!busy} onClick={() => act("resume", {}, "Resumed")}><Play size={13} /> Resume</button>}
          {live && st !== "parked" && st !== "draft" && <button className={btn} disabled={!!busy} onClick={() => act("park", {}, "Parked")}><Square size={13} /> Park</button>}
          {c.kind === "campaign" && ["running", "paused", "waiting_user", "interrupted"].includes(st) && (
            <button className={btn} disabled={!!busy} title="Continue the current phase in a fresh session" onClick={() => act("rollover", {}, "New session started")}>New session</button>
          )}
          {live && <button className={`${btn} btn-danger`} disabled={!!busy} onClick={() => { if (confirm(`Abandon "${c.title}"? Its file and history stay.`)) act("abandon"); }}><Trash2 size={13} /> Abandon</button>}
          {c.path && <button className={btn} onClick={() => openLocalFile(c.path!)}><FileText size={13} /> Open file</button>}
          {c.current_session && <button className={btn} onClick={() => actions.openSession(c.current_session!)}><MessageSquare size={13} /> Open current session</button>}
          {st === "done" && c.current_session && (
            <button className={btn} onClick={() => { actions.setSkillChip(c.current_session!, "postmortem"); actions.openSession(c.current_session!); }}>Write a postmortem…</button>
          )}
        </div>

        {live && (
          <div className="flex flex-wrap items-center gap-4 mt-3 text-[12.5px]">
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" checked={c.autopilot} onChange={(e) => save({ autopilot: e.target.checked })} aria-label="Autopilot" /> Autopilot
            </label>
            <label className="flex items-center gap-1.5">Budget $
              <input className="input w-20 py-0.5" inputMode="decimal" value={budget} aria-label="Budget"
                onChange={(e) => setBudget(e.target.value)} onBlur={() => { if (budget !== String(c.budget_usd ?? "")) save({ budget_usd: budget === "" ? null : Number(budget) }); }} />
            </label>
          </div>
        )}

        <Section title={c.kind === "chain" ? "Steps" : "Phases"}>
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-[11.5px] text-muted border-b border-line"><th className="py-1 pr-2">#</th><th className="pr-2">Phase</th><th className="pr-2">Done when</th><th className="pr-2">Status</th><th>Retries</th></tr></thead>
            <tbody>{c.phases.map((p, i) => <PhaseRow key={i} p={p} i={i} current={i === c.phase && live} kind={c.kind} />)}</tbody>
          </table>
        </Section>

        {manual.length > 0 && (
          <Section title="Your checks for this phase">
            {manual.map(({ d, j }) => (
              <div key={j} className="flex items-center gap-2 py-1 text-[13px]">
                <span className="flex-1">{describeCondition(d)}</span>
                <button className="btn px-2 py-0.5 text-[12px]" onClick={() => answerManual(j, "pass")}>Pass</button>
                <button className="btn px-2 py-0.5 text-[12px]" onClick={() => answerManual(j, "fail")}>Fail</button>
              </div>
            ))}
          </Section>
        )}

        {c.doc && (
          <>
            <Section title="Design target">
              {c.doc.design_target.length === 0 ? <Empty>Not written yet (the plan session fills it).</Empty> : (
                <ul className="text-[13px] space-y-0.5">
                  {c.doc.design_target.map((t, i) => <li key={i} className="flex gap-2"><input type="checkbox" checked={t.done} readOnly aria-label={t.text} />{t.text}</li>)}
                </ul>
              )}
              {c.doc.scope.stories.length > 0 && <div className="text-[12px] text-muted mt-1">Stories: {c.doc.scope.stories.join(", ")}</div>}
            </Section>
            {c.doc.coverage && <Section title="Coverage"><div className="text-[13px] md"><SafeMarkdown text={c.doc.coverage} /></div></Section>}
            <Section title="Review queue">
              {listItems(c.doc.review).length === 0 ? <Empty>Nothing waiting for you.</Empty> : (
                <ul className="text-[13px] space-y-0.5">{listItems(c.doc.review).map((l, i) => <li key={i}>{l.replace(/^\[( |x)\]\s*/, (_m, x) => (x === "x" ? "✓ " : "• "))}</li>)}</ul>
              )}
            </Section>
            <Section title="Decision log">
              {listItems(c.doc.decisions).length === 0 ? <Empty>No decisions logged.</Empty> : <ul className="text-[13px] space-y-0.5">{listItems(c.doc.decisions).map((l, i) => <li key={i}>{l}</li>)}</ul>}
            </Section>
            <Section title="Discoveries">
              {listItems(c.doc.discoveries).length === 0 ? <Empty>No discoveries yet.</Empty> : <ul className="text-[13px] space-y-0.5">{listItems(c.doc.discoveries).slice(-30).map((l, i) => <li key={i}>{l}</li>)}</ul>}
            </Section>
            {c.doc.completion && <Section title="Completion record"><pre className="text-[12.5px] whitespace-pre-wrap">{c.doc.completion}</pre></Section>}
          </>
        )}

        <Section title="Sessions">
          {c.session_chain.length === 0 ? <Empty>No session yet.</Empty> : (
            <div className="space-y-0.5">
              {c.session_chain.map((s) => (
                <div key={s.session_id} className="flex items-center gap-2 text-[13px]">
                  {s.exists ? <button className="text-action hover:underline truncate" onClick={() => actions.openSession(s.session_id)}>{s.title ?? s.session_id}</button>
                    : <span className="text-muted truncate">{s.title ?? s.session_id} (deleted)</span>}
                  <span className="text-[12px] text-muted shrink-0">{s.phase != null && s.phase >= 0 ? `phase ${s.phase + 1}` : "plan"}</span>
                  <span className="text-[12px] text-faint ml-auto shrink-0">{fmtAgo(s.started_at)}{s.end_reason ? ` · ended (${s.end_reason})` : " · current"}</span>
                </div>
              ))}
            </div>
          )}
        </Section>

        {c.checkpoints.length > 0 && (
          <Section title="Checkpoints">
            <p className="text-[12px] text-muted mb-1">GameDevWorkstation never resets your project. To go back to the start of a phase, run its command yourself in the project folder.</p>
            {c.checkpoints.map((k) => (
              <div key={k.ref} className="flex items-center gap-2 py-0.5 text-[12.5px]">
                <span className="shrink-0">Phase {k.phase} {k.name}</span>
                <code className="font-mono text-[11.5px] truncate flex-1" title={k.ref}>{k.restore}</code>
                <button className="btn btn-ghost px-1" aria-label={`Copy restore command for phase ${k.phase}`}
                  onClick={() => navigator.clipboard?.writeText(k.restore).then(() => actions.toast("Command copied"))}><Copy size={13} /></button>
              </div>
            ))}
          </Section>
        )}
      </div>
    </div>
  );
}

function NewCampaignDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  useModelCatalog();
  const appState = useStore((s) => s.appState);
  const [folder, setFolder] = useState("");
  const [templates, setTemplates] = useState<ChainTemplate[]>([]);
  const [f, setF] = useState({ template: "", request: "", title: "", budget: "10", autopilot: false, model: "", effort: "medium", mode: "accept_edits", start: true });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    campaignsApi.chains(folder || null, "campaign").then((r) => {
      const ts = templatesFor(r.templates, "campaign");
      setTemplates(ts);
      setF((x) => (ts.some((t) => t.id === x.template) ? x : { ...x, template: ts[0]?.id ?? "" }));
    }).catch(() => setTemplates([]));
  }, [folder]);
  const words = wordCount(f.request);
  const short = words > 0 && words < MIN_CAMPAIGN_WORDS;
  const tpl = useMemo(() => templates.find((t) => t.id === f.template), [templates, f.template]);
  const tiers = Object.keys(appState?.tiers ?? {});
  const create = async (force = false) => {
    setBusy(true);
    try {
      const c = await campaignsApi.create({
        template: f.template, kind: "campaign", folder, request: f.request, title: f.title || undefined,
        budget_usd: f.budget === "" ? undefined : Number(f.budget), autopilot: f.autopilot, model: f.model || undefined,
        effort: f.effort, mode: f.mode, start: f.start, force,
      });
      actions.toast(f.start ? "Campaign created: planning runs in a new session" : "Campaign created");
      onCreated(c.id);
    } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(false); }
  };
  const L = "block mb-3";
  return (
    <Modal title="New campaign" onClose={onClose} wide>
      <div className={L}><span className="label">Project folder</span>
        <div className="flex gap-2"><input className="input" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="/Users/you/Games/MyGame" aria-label="Project folder" />
          <button className="btn" onClick={async () => { const p = await pickFolder(folder || undefined); if (p) setFolder(p); }}>Choose…</button></div>
      </div>
      <label className={L}><span className="label">Workflow</span>
        <select className="input" value={f.template} onChange={(e) => setF({ ...f, template: e.target.value })} aria-label="Workflow">
          {templates.length === 0 && <option value="">No workflow applies to this folder</option>}
          {templates.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
        </select>
        {tpl && <span className="block text-[12px] text-muted mt-1">{tpl.summary || tpl.phases.map((p) => p.name).join(" → ")}</span>}
      </label>
      <label className={L}><span className="label">Request: the end state you want</span>
        <textarea className="input h-28" value={f.request} onChange={(e) => setF({ ...f, request: e.target.value })} aria-label="Request"
          placeholder="From Title, Boss Rush starts a run of 5 bosses in a row; death returns to Title in under 3 s; the best time is saved and shown." />
        <span className="block text-[12px] mt-1" style={{ color: short ? "var(--warn, #c98a00)" : undefined }}>
          {short ? `${words} words: for something this small a workflow in one session (composer → Workflows) fits better.` : `${words} words`}
        </span>
      </label>
      <div className="grid grid-cols-[1.4fr_0.7fr_0.8fr_1fr] gap-3">
        <label className={L}><span className="label">Title (optional)</span><input className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
        <label className={L}><span className="label">Budget ($)</span><input className="input" inputMode="decimal" value={f.budget} onChange={(e) => setF({ ...f, budget: e.target.value })} /></label>
        <label className={L}><span className="label">Effort</span>
          <select className="input" value={f.effort} onChange={(e) => setF({ ...f, effort: e.target.value })}>{["none", "low", "medium", "high"].map((x) => <option key={x}>{x}</option>)}</select>
        </label>
        <label className={L}><span className="label">Model</span>
          <select className="input" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })}>
            <option value="">Default</option>{tiers.map((t) => <option key={t} value={t}>{modelLabel(t)}</option>)}
          </select>
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-4 mb-3 text-[13px]">
        <label className="flex items-center gap-1.5"><span className="label mb-0">Mode</span>
          <select className="input py-0.5" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}>
            <option value="accept_edits">Accept edits</option><option value="ask">Ask before edits</option><option value="plan">Plan only</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" checked={f.autopilot} onChange={(e) => setF({ ...f, autopilot: e.target.checked })} /> Autopilot</label>
        <label className="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" checked={f.start} onChange={(e) => setF({ ...f, start: e.target.checked })} /> Start planning now</label>
      </div>
      <p className="text-[12px] text-faint mb-3">You always approve the plan before any phase runs, autopilot or not. Campaigns run at high effort or below.</p>
      <ModalFooter start={short ? <button className="btn btn-ghost text-[12.5px]" disabled={busy || !folder || !f.template} onClick={() => create(true)}>Create anyway</button> : undefined}>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !folder || !f.template || !f.request.trim() || short} onClick={() => create()}>Create campaign</button>
      </ModalFooter>
    </Modal>
  );
}
