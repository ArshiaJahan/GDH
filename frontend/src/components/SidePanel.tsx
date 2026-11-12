import { ChevronRight, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { get, patch, post } from "../lib/api";
import { CAMPAIGN_EVENTS, FINAL_STATUSES, campaignsApi } from "../lib/campaigns";
import { actions, sessionProfile, useStore, type Job, type Session } from "../lib/store";
import { CampaignCard } from "./cards/CampaignCard";
import { ChangesCard } from "./cards/ChangesCard";
import { GalleryCard } from "./cards/GalleryCard";
import { ConnectorsCard, SharedToolsCard } from "./cards/ConnectorsCard";
import { OutputsCard } from "./cards/OutputsCard";
import { QualityCard } from "./cards/QualityCard";
import { pickFolder } from "../lib/native";
import { EffortMeter, fmtDuration, fmtTokens, fmtUsd, isTier, modelLabel, modelName, providerLabel, providerOf, tiersOf, useModelCatalog } from "./ui";

export function Card({ id, title, right, children, defaultOpen = true }: { id: string; title: string; right?: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const key = `card:${id}`;
  const [open, setOpen] = useState(() => (localStorage.getItem(key) ?? (defaultOpen ? "1" : "0")) === "1");
  return (
    <section className="border-b border-line">
      <div className="flex items-center px-3 h-9">
        <button className="flex items-center gap-1 font-medium text-[13px] flex-1 text-left" aria-expanded={open}
          onClick={() => { setOpen(!open); localStorage.setItem(key, open ? "0" : "1"); }}>
          <ChevronRight size={14} className={`text-muted transition-transform ${open ? "rotate-90" : ""}`} />{title}
        </button>
        {open && right}
      </div>
      {open && <div className="px-3 pb-3 text-[13px]">{children}</div>}
    </section>
  );
}

export function SidePanel() {
  const sid = useStore((s) => s.currentId);
  const session = useStore((s) => s.sessions.find((x) => x.id === sid));
  if (!session) return <aside className="h-full surface border-l border-line" />;
  return (
    <aside className="h-full surface border-l border-line overflow-y-auto scroll-thin" aria-label="Session panel">
      <EnvironmentCard s={session} />
      <ContextCard s={session} />
      {/* Render nothing until their features are on for the session (gates, campaigns). */}
      <CampaignCard s={session} />
      <QualityCard s={session} />
      <ConnectorsCard s={session} />
      <SharedToolsCard s={session} />
      <OutputsCard s={session} />
      <GalleryCard s={session} />
      <ChangesCard s={session} />
      <BackgroundCard s={session} />
    </aside>
  );
}

// ------------------------------------------------------------------ environment

const MODES = [["ask", "Ask before edits"], ["accept_edits", "Accept edits"], ["plan", "Plan only"]];
const HARNESS = [["builtin", "Built-in loop"], ["agent_sdk", "Claude Agent SDK"], ["codex_cli", "Codex CLI"]];
const EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"];
const ACCOUNT_PROVIDERS = ["anthropic", "openai", "elevenlabs"].map((p) => [p, providerLabel(p)]);

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex items-center gap-2 py-1"><span className="w-[70px] shrink-0 text-muted">{label}</span><div className="flex-1 min-w-0">{children}</div></div>;
}

/** Model the Codex CLI harness runs for this session: the session's own OpenAI model, else the codex.cli tier. */
function codexCliModel(s: Session, env: any): [string, string | null] {
  const own = providerOf(isTier(s.model) ? env?.tiers?.[s.model] : s.model) === "codex";
  const cli = env?.tiers?.["codex.cli"] ?? "codex.cli";
  if (own) { const m = env?.tiers?.[s.model] ?? s.model; return [m, m === cli ? "codex.cli" : null]; }
  return [cli, "codex.cli"];
}

/** "Codex CLI · GPT-6.1 Sol": the harness and the model it runs (full label with tier in the tooltip). */
function harnessLabel(v: string, l: string, s: Session, env: any, full = false): string {
  if (v === "codex_cli") { const [m, t] = codexCliModel(s, env); return `${l} · ${full ? modelLabel(m, t) : modelName(m)}`; }
  return l;
}

/** One key profile per provider: a compact picker when the provider has several, else just its name. */
function AccountsRow({ s, upd }: { s: Session; upd: (body: Record<string, unknown>) => void }) {
  const accounts: Record<string, string[]> = useStore((x) => x.appState?.accounts) ?? {};
  return (
    <Row label="Accounts">
      <div className="flex flex-col gap-0.5">
        {ACCOUNT_PROVIDERS.map(([p, label]) => {
          const profiles = accounts[p]?.length ? accounts[p] : ["default"];
          const cur = sessionProfile(s, p, profiles);
          return (
            <div key={p} className="flex items-center gap-1.5 min-w-0">
              <span className="w-[66px] shrink-0 text-faint text-[12px]">{label}</span>
              {profiles.length > 1 ? (
                <select className="input py-0 min-w-0 flex-1 text-[12.5px]" value={cur} onChange={(e) => upd({ accounts: { [p]: e.target.value } })} aria-label={`${label} account profile`}>
                  {profiles.map((a) => <option key={a}>{a}</option>)}
                </select>
              ) : <span className="truncate" title={`${label} uses the ${cur} profile`}>{cur}</span>}
            </div>
          );
        })}
      </div>
    </Row>
  );
}

/** The title of the campaign or chain this session runs while it isn't done or abandoned (null
 *  otherwise): those need the built-in loop, so the harness picker is locked. */
function useActiveCampaign(cid: string | undefined): string | null {
  const [title, setTitle] = useState<string | null>(null);
  useEffect(() => {
    setTitle(null);
    if (!cid) return;
    let live = true;
    campaignsApi.detail(cid).then((d) => live && setTitle(FINAL_STATUSES.includes(d.status) ? null : d.title)).catch(() => {});
    const off = actions.onEvent((e) => {
      if (!CAMPAIGN_EVENTS.includes(e.type) || e.data?.id !== cid) return;
      const status = e.type === "campaign.done" ? "done" : e.data.status;
      if (status) setTitle(FINAL_STATUSES.includes(status) ? null : e.data.title ?? "a campaign");
    });
    return () => { live = false; off(); };
  }, [cid]);
  return title;
}

function EnvironmentCard({ s }: { s: Session }) {
  useModelCatalog();
  const [env, setEnv] = useState<any>(null);
  useEffect(() => { get("/environment").then(setEnv); }, []);
  const running = s.status === "running";
  const campaign = useActiveCampaign(s.settings?.campaign_id ?? undefined);
  const upd = async (body: Record<string, unknown>) => {
    try { await patch(`/sessions/${s.id}`, body); } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const choose = async () => {
    const f = await pickFolder(s.folder ?? undefined);
    if (f !== null) upd({ folder: f || null });
  };
  return (
    <Card id="env" title="Environment">
      <Row label="Where"><span>Local</span><span className="text-faint"> · this Mac</span></Row>
      <Row label="Folder">
        <button className="w-full text-left truncate hover:text-action" title={s.folder ?? "No folder: chat only"} onClick={choose}>
          {s.folder ? s.folder.replace(/^\/Users\/[^/]+/, "~") : "Chat (no folder)"}
        </button>
      </Row>
      <Row label="Model">
        <select className="input py-0.5 w-full" value={s.model} onChange={(e) => upd({ model: e.target.value })} aria-label="Model">
          {(env?.models ?? [{ id: s.model }]).map((m: any) => (
            <option key={m.id} value={m.id} title={m.id}>{modelLabel(m.id, m.tier ?? null)}</option>
          ))}
        </select>
        <select className="input py-0.5 w-[108px] mt-1" value={s.effort} onChange={(e) => upd({ effort: e.target.value })} aria-label="Effort">
          {EFFORTS.map((x) => <option key={x}>{x}</option>)}
        </select>
        <div className="mt-1 flex items-center gap-1.5 text-faint text-[12px]"><EffortMeter effort={s.effort} />{modelLabel(s.model)} · {s.effort}{["xhigh", "max"].includes(s.effort) && " (asks for approval)"}</div>
      </Row>
      <AccountsRow s={s} upd={upd} />
      <Row label="Mode">
        <select className="input py-0.5" value={s.mode} onChange={(e) => upd({ mode: e.target.value })} aria-label="Mode">
          {MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </Row>
      <Row label="Harness">
        <select className="input py-0.5" value={s.harness} disabled={running || !!campaign} onChange={(e) => upd({ harness: e.target.value })} aria-label="Harness"
          title={campaign ? `This session runs ${campaign}: campaigns and workflows use the built-in loop` : undefined}>
          {HARNESS.map(([v, l]) => (
            <option key={v} value={v} disabled={env && !env.harnesses[v]} title={harnessLabel(v, l, s, env, true)}>{harnessLabel(v, l, s, env)}{env && !env.harnesses[v] ? " (not installed)" : ""}</option>
          ))}
        </select>
      </Row>
    </Card>
  );
}

// ---------------------------------------------------------------------- context

const PARTS = [["system", "System"], ["tools", "Tools"], ["skills", "Skills"], ["messages", "Messages"], ["attachments", "Attachments"]];
const PART_COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--eleven)"];
// Progressive sessions (settings.skill_mode) split the skills part: pinned and the index sit in the
// system prompt; loaded skills live in history.
const SKILL_PARTS = [["pinned", "Pinned"], ["index", "Index"], ["loaded", "Loaded (in history)"]];

type ContextRow = { key: string; label: string; tokens: number; color: string; opacity?: number };

function contextRows(ctx: any): ContextRow[] {
  const split = ctx.skill_parts;
  return PARTS.flatMap(([k, l], i): ContextRow[] => k === "skills" && split
    ? SKILL_PARTS.map(([sk, sl], j) => ({ key: `skills.${sk}`, label: sl, tokens: split[sk] ?? 0, color: PART_COLORS[i], opacity: 1 - j * 0.3 }))
    : [{ key: k, label: l, tokens: ctx.parts[k] ?? 0, color: PART_COLORS[i] }]);
}

function ContextCard({ s }: { s: Session }) {
  useModelCatalog();
  const [ctx, setCtx] = useState<any>(null);
  const [usage, setUsage] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const msgCount = useStore((x) => x.messages[s.id]?.length ?? 0);
  // Pinning, loading or unloading a skill changes the split without adding a message.
  const skillKey = JSON.stringify([s.settings?.skill_mode ?? null, s.settings?.pinned_skills ?? null, s.settings?.loaded_skills ?? null]);
  const load = () => Promise.all([get(`/sessions/${s.id}/context`).then(setCtx), get(`/usage/session/${s.id}`).then(setUsage)]).catch(() => {});
  useEffect(() => { load(); }, [s.id, msgCount, s.model, skillKey]);
  const rows = ctx ? contextRows(ctx) : [];
  const doCompact = async () => {
    setBusy(true);
    try {
      const r = await post(`/sessions/${s.id}/compact`);
      actions.toast(r.compacted ? `Summarized ${r.compacted} older messages.` : r.message);
      await actions.reloadMessages(s.id);
    } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Card id="ctx" title="Context" right={<button className="btn py-0.5 text-[12px]" disabled={busy || s.status === "running"} onClick={doCompact} title={`Summarize older turns with ${modelLabel("claude.fast")}; originals stay in history`}>{busy ? "Compacting…" : "Compact"}</button>}>
      {ctx && (
        <>
          <div className="flex justify-between text-[12.5px]"><span>{fmtTokens(ctx.total)} of {fmtTokens(ctx.window)} tokens</span><span className="tabular-nums">{(ctx.fraction * 100).toFixed(1)}%</span></div>
          <div className="flex h-2 mt-1 rounded-sm overflow-hidden bg-sunken gap-px" role="img" aria-label="Context breakdown">
            {rows.map((r) => r.tokens > 0 && <span key={r.key} style={{ width: `${Math.max((r.tokens / ctx.window) * 100, 0.6)}%`, background: r.color, opacity: r.opacity }} />)}
          </div>
          <table className="w-full mt-2 text-[12.5px]">
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}><td className="py-0.5"><span className="inline-block size-2 rounded-sm mr-1.5 align-middle" style={{ background: r.color, opacity: r.opacity }} />{r.label}</td>
                  <td className="text-right tabular-nums">{fmtTokens(r.tokens)}</td>
                  <td className="text-right tabular-nums text-muted w-12">{((r.tokens / ctx.window) * 100).toFixed(1)}%</td></tr>
              ))}
            </tbody>
          </table>
          {!ctx.calibrated && <div className="text-[11.5px] text-faint mt-1">Estimated until the first reply; then calibrated to real token counts.</div>}
          {ctx.level !== "ok" && (
            <div role="alert" className={`mt-2 flex items-start gap-2 rounded border px-2 py-1.5 text-[12.5px] ${ctx.level === "danger" ? "border-bad text-bad" : "border-warn text-warn"}`}>
              <span className="flex-1">
                {ctx.level === "danger"
                  ? `Context is ${(ctx.fraction * 100).toFixed(0)}% full. Compact now, or start a new session; old tool output may be dropped to fit.`
                  : `Context is ${(ctx.fraction * 100).toFixed(0)}% full. Older turns are summarized automatically at ${Math.round((ctx.auto_compact_at ?? 0.8) * 100)}%; compact now to choose when.`}
              </span>
              {ctx.can_compact && <button className="btn py-0 text-[12px] shrink-0" disabled={busy || s.status === "running"} onClick={doCompact}>Compact</button>}
            </div>
          )}
        </>
      )}
      {usage && usage.models.length > 0 && (
        <div className="mt-2 pt-2 border-t border-line">
          <div className="flex justify-between font-medium text-[12.5px]"><span>This session</span><span>{fmtUsd(usage.total_cost)}</span></div>
          {usage.models.map((m: any) => (
            <div key={m.model} className="text-[12.5px] text-muted py-0.5">
              <div className="flex justify-between gap-2"><span className="truncate" title={m.model}>{modelLabel(m.model)}</span><span className="tabular-nums shrink-0">{fmtUsd(m.cost)}</span></div>
              <div className="text-[11.5px] text-faint tabular-nums">{m.characters ? `${fmtTokens(m.characters)} chars` : providerOf(m.model) === "eleven" ? `${fmtTokens(Math.round(m.credits ?? 0))} credits` : `${fmtTokens(m.input + m.cached)} in · ${fmtTokens(m.output)} out`}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------- background tasks

const KIND_LABEL: Record<string, string> = { assistant: "Skills & MCP assistant", subagent: "Subagent", command: "Command", codex_cli: "Codex CLI", elevenlabs: "ElevenLabs", scheduled: "Scheduled" };

/** Model a job ran on ("GPT-6.1 Sol · codex.cli"), unless its title already names it. */
function jobModel(j: Job): string {
  if (!j.meta?.model) return "";
  // Older Codex CLI jobs carry no tier; the CLI's model is the codex.cli tier's.
  const tier = j.meta.tier !== undefined ? j.meta.tier : j.kind === "codex_cli" && tiersOf(j.meta.model).includes("codex.cli") ? "codex.cli" : undefined;
  const label = modelLabel(j.meta.model, tier);
  return j.title.includes(label) ? "" : label;
}

/** A job's title without what the line under it already says: the kind ("Subagent …") and,
 *  for subagents, the tier (the model label names it). */
function jobTitle(j: Pick<Job, "kind" | "title" | "meta">): string {
  let t = j.title;
  const kind = KIND_LABEL[j.kind];
  if (kind && t.toLowerCase().startsWith(`${kind.toLowerCase()} `)) t = t.slice(kind.length + 1).replace(/^[:·-]\s*/, "");
  if ((j.kind === "subagent" || j.kind === "codex_cli") && j.meta?.model && j.meta?.tier) t = t.replace(` · ${j.meta.tier}`, "");
  return t.trim() || j.title;
}

function JobRow({ j }: { j: Job }) {
  useModelCatalog();
  const live = useStore((s) => s.jobLogs[j.id]);
  const [open, setOpen] = useState(false);
  const [, tick] = useState(0);
  const running = j.status === "running" || j.status === "queued";
  useEffect(() => { if (!running) return; const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, [running]);
  const elapsed = (j.ended_at ?? Date.now() / 1000) - j.started_at;
  const tail = (live ?? j.log_tail ?? "").split("\n").slice(-12).join("\n");
  const color = j.status === "failed" ? "var(--bad)" : running ? "var(--action)" : j.status === "cancelled" ? "var(--faint)" : "var(--ok)";
  return (
    <div className="py-1.5 border-b border-line last:border-0">
      <div className="flex items-center gap-1.5">
        <span className="size-2 rounded-full shrink-0" style={{ background: color }} aria-label={j.status} />
        <button className="truncate flex-1 text-left" onClick={() => setOpen(!open)} title={j.title}>{jobTitle(j)}</button>
        {running && <button className="btn btn-ghost px-1 py-0" title="Cancel" aria-label="Cancel job" onClick={() => post(`/jobs/${j.id}/cancel`)}><X size={13} /></button>}
      </div>
      <div className="text-[11.5px] text-faint pl-3.5">{KIND_LABEL[j.kind] ?? j.kind}{jobModel(j) && ` · ${jobModel(j)}`} · {j.status} · {fmtDuration(elapsed)}{j.meta?.cost_usd ? ` · ${fmtUsd(j.meta.cost_usd)}` : ""}</div>
      {open && tail && <pre className="mt-1 ml-3.5 font-mono text-[11px] bg-sunken rounded p-1.5 max-h-40 overflow-auto whitespace-pre-wrap">{tail}</pre>}
    </div>
  );
}

function BackgroundCard({ s }: { s: Session }) {
  const jobs = useStore((x) => x.jobs);
  // Skills & MCP assistant runs have no session; they show in every session's list.
  const list = Object.values(jobs).filter((j) => j.session_id === s.id || (j.session_id == null && j.kind === "assistant")).sort((a, b) => b.started_at - a.started_at);
  const running = list.filter((j) => j.status === "running" || j.status === "queued");
  const recent = list.filter((j) => !running.includes(j)).slice(0, 8);
  return (
    <Card id="bg" title={`Background tasks${running.length ? ` (${running.length})` : ""}`}>
      {running.length === 0 && <div className="text-muted pb-1">Nothing running.</div>}
      {running.map((j) => <JobRow key={j.id} j={j} />)}
      {recent.length > 0 && <div className="label mt-2 mb-0.5">Recent</div>}
      {recent.map((j) => <JobRow key={j.id} j={j} />)}
    </Card>
  );
}
