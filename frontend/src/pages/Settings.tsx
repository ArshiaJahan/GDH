import { ArrowUpCircle, Check, FolderOpen, Plus, RefreshCw, RotateCcw, Star, Trash2, UserMinus, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, del, get, post, type UnityInfo } from "../lib/api";
import { actions, useStore } from "../lib/store";
import { modelLabel, providerLabel, providerRank } from "../components/ui";
import { fmtBuilt, Inline, installUpdate, Notes, updateHeadline, type UpdatesStatus } from "../components/Updates";
import { revealInFinder } from "../lib/native";
import { StorageSettings } from "../components/StorageSettings";

const SECTIONS = [["accounts", "Accounts"], ["models", "Models and effort"], ["delegation", "Delegation and budgets"], ["modes", "Modes and approvals"],
  ["data", "Data policy"], ["elevenlabs", "ElevenLabs defaults"], ["unity", "Unity"], ["appearance", "Appearance"], ["storage", "Storage"], ["about", "About & updates"]];
const PROVIDER_NAME: Record<string, string> = { anthropic: providerLabel("anthropic"), openai: providerLabel("openai"), elevenlabs: providerLabel("elevenlabs") };

/** A provider's configured models by real name, each with the tiers routing to it:
 *  "GPT-6 Astra, GPT-6.1 Sol (codex.standard, codex.cli), …". Empty for providers without a catalog. */
function modelsLine(st: any, provider: string): string {
  return Object.entries(st.models as Record<string, any>).filter(([, m]) => m.provider === provider).map(([id, m]) => {
    const tiers = Object.entries(st.tiers as Record<string, string>).filter(([, x]) => x === id).map(([t]) => t);
    return `${m.display_name || id}${tiers.length ? ` (${tiers.join(", ")})` : ""}`;
  }).join(", ");
}

export function SettingsPage() {
  const args = useStore((s) => s.pageArgs);
  const [section, setSection] = useState<string>(args.section ?? "accounts");
  useEffect(() => { if (args.section) setSection(args.section); }, [args]); // e.g. "Limit settings" on the pause banner
  const [st, setSt] = useState<any>(null);
  const load = () => get("/settings").then(setSt);
  useEffect(() => { load(); }, []);
  const [saveState, mark] = useSaveState();
  // Every setting saves itself (selects and toggles at once, numbers on blur or Enter, text after a pause) and
  // shows "Saved" next to the field it belongs to; errors also get a toast.
  const save: Save = async (body, field) => {
    if (field) mark(field, "saving");
    try {
      setSt(await api("/settings", { method: "PATCH", body }));
      actions.refreshState();
      if (field) mark(field, "saved");
      return true;
    } catch (e: any) {
      if (field) mark(field, "error");
      actions.toast(e.message, "error");
      return false;
    }
  };
  if (!st) return null;
  return (
    <SaveCtx.Provider value={saveState}>
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[980px] mx-auto px-6 py-5 flex gap-8">
        <nav className="w-48 shrink-0 text-[13px]" aria-label="Settings sections">
          <h1 className="text-lg font-semibold mb-3">Settings</h1>
          {SECTIONS.map(([id, label]) => (
            <button key={id} onClick={() => setSection(id)} aria-current={section === id}
              className={`block w-full text-left px-2 py-1.5 rounded ${section === id ? "bg-sunken text-text" : "text-muted hover:text-text"}`}>{label}</button>
          ))}
          <div className="text-[11.5px] text-faint mt-4 px-2 break-words [overflow-wrap:anywhere]">Config file: {st.config_path}</div>
        </nav>
        <div className="flex-1 min-w-0 pt-10">
          {section === "accounts" && <Accounts st={st} reload={load} />}
          {section === "models" && <Models st={st} save={save} />}
          {section === "delegation" && <Delegation st={st} save={save} />}
          {section === "modes" && <Modes st={st} save={save} />}
          {section === "data" && <DataPolicy st={st} save={save} />}
          {section === "elevenlabs" && <ElevenDefaults st={st} save={save} />}
          {section === "unity" && <UnitySettings st={st} save={save} />}
          {section === "appearance" && <Appearance st={st} save={save} reload={load} />}
          {section === "storage" && <StorageSettings />}
          {section === "about" && <About />}
        </div>
      </div>
    </div>
    </SaveCtx.Provider>
  );
}

type SaveState = "saving" | "saved" | "error";
/** Saves a settings patch; `field` names the row (its label) whose "Saved" indicator to show.
 *  Resolves false when the save failed (the error is already shown). */
type Save = (body: any, field?: string) => void | Promise<boolean | void>;
const SaveCtx = createContext<Record<string, SaveState>>({});
const SAVED_MS = 2200;
const TYPE_DEBOUNCE_MS = 700;

/** Per-field save states; "saved" clears itself after a moment. */
function useSaveState(): [Record<string, SaveState>, (field: string, s: SaveState) => void] {
  const [state, setState] = useState<Record<string, SaveState>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  useEffect(() => () => Object.values(timers.current).forEach(clearTimeout), []);
  const mark = useCallback((field: string, s: SaveState) => {
    clearTimeout(timers.current[field]);
    setState((x) => ({ ...x, [field]: s }));
    if (s === "saved") timers.current[field] = setTimeout(() => setState(({ [field]: _, ...rest }) => rest), SAVED_MS);
  }, []);
  return [state, mark];
}

/** The inline save indicator: "Saved ✓" for a moment after a save, "Not saved" after an error. */
function SavedMark({ state }: { state?: SaveState }) {
  return (
    <span role="status" aria-live="polite" className="inline-flex items-center gap-1 text-[12px] min-w-[4.5rem] whitespace-nowrap">
      {state === "saved" && <span className="inline-flex items-center gap-1 text-muted"><Check size={13} style={{ color: "var(--ok)" }} /> Saved</span>}
      {state === "error" && <span className="text-bad">Not saved</span>}
    </span>
  );
}
const useSaved = (field?: string) => useContext(SaveCtx)[field ?? ""];

function H2({ children, sub, field }: { children: ReactNode; sub?: ReactNode; field?: string }) {
  const saved = useSaved(field);
  return (
    <div className="mb-4">
      <h2 className="font-semibold text-[15px] flex items-center gap-3">{children}{field && <SavedMark state={saved} />}</h2>
      {sub && <p className="text-[13px] text-muted mt-0.5">{sub}</p>}
    </div>
  );
}
/** A settings row. Its "Saved" indicator follows saves made with `field` (the label by default). */
function Row({ label, hint, children, field, noMark }: { label: string; hint?: string; children: ReactNode; field?: string; noMark?: boolean }) {
  const saved = useSaved(field ?? label);
  return (
    <div className="grid grid-cols-[220px_1fr] gap-4 py-2 border-b border-line items-center">
      <div><div className="text-[13px]">{label}</div>{hint && <div className="text-[12px] text-faint">{hint}</div>}</div>
      <div className="flex items-center gap-3 min-w-0">{children}{!noMark && <SavedMark state={saved} />}</div>
    </div>
  );
}
/** A number that saves on blur, Enter, or when it goes away (e.g. ⌘K to another page). It never
 *  saves mid-typing: changing a $50 limit to $500 passes through $5, which must not be saved.
 *  `onSave` may return a promise of false (or reject) on failure, so the same value can be retried. */
export function Num({ value, onSave, step = 1, min = 0, label }: { value: number; onSave: (v: number) => unknown; step?: number; min?: number; label?: string }) {
  const [v, setV] = useState(String(value));
  const last = useRef(value);
  const raw = useRef(String(value));
  const latest = useRef({ onSave, min });
  latest.current = { onSave, min };
  useEffect(() => { setV(String(value)); raw.current = String(value); last.current = value; }, [value]);
  const commit = useCallback((text: string) => {
    const n = Number(text);
    if (text.trim() === "" || !Number.isFinite(n) || n < latest.current.min || n === last.current) return;
    const prev = last.current;
    last.current = n;
    const failed = () => { if (last.current === n) last.current = prev; };
    try {
      const r = latest.current.onSave(n);
      if (r && typeof (r as Promise<unknown>).then === "function") (r as Promise<unknown>).then((ok) => { if (ok === false) failed(); }, failed);
    } catch { failed(); }
  }, []);
  useEffect(() => () => commit(raw.current), [commit]);
  return <input type="number" className="input w-32" step={step} min={min} value={v} aria-label={label}
    onChange={(e) => { setV(e.target.value); raw.current = e.target.value; }}
    onBlur={() => commit(v)} onKeyDown={(e) => e.key === "Enter" && commit(v)} />;
}

function Accounts({ st, reload }: { st: any; reload: () => void }) {
  const [draft, setDraft] = useState<Record<string, { profile: string; key: string }>>({});
  // Keys keep an explicit Save (they're secrets); the result shows inline like every other setting.
  const [keyState, markKey] = useSaveState();
  const saveKey = async (provider: string, profile: string, key: string) => {
    const k = provider + profile;
    markKey(k, "saving");
    try {
      await post("/settings/keys", { provider, profile, key });
      setDraft((d) => ({ ...d, [k]: { profile, key: "" } }));
      markKey(k, "saved");
      reload();
    } catch (e: any) { markKey(k, "error"); actions.toast(e.message, "error"); }
  };
  /** Add or reorder profiles (first = default); this never removes one (deleteProfile does). */
  const setProfiles = async (provider: string, profiles: string[], msg: string) => {
    try {
      await post(`/settings/accounts/${provider}`, { profiles });
      actions.toast(msg);
      reload();
      actions.refreshState();
    } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const deleteProfile = async (provider: string, profile: string) => {
    if (!confirm(`Delete the ${profile} profile? Its key is removed from the Keychain, and sessions using it switch to the default profile.`)) return;
    try {
      await del(`/settings/accounts/${provider}/${profile}`);
      actions.toast(`Deleted the ${profile} profile.`);
      reload();
      actions.refreshState();
    } catch (e: any) { actions.toast(e.message, "error"); }
  };
  return (
    <div>
      <H2 sub="Keys are stored in the macOS Keychain, never in the config file or logs. Add more profiles to keep several keys per provider; each session picks one per provider in its Environment card. New sessions start on the default (first) profile.">Accounts</H2>
      {Object.entries(st.accounts as Record<string, any[]>).sort(([a], [b]) => providerRank(a) - providerRank(b)).map(([provider, profiles]) => (
        <section key={provider} className="mb-6">
          <h3 className="font-medium mb-1">{PROVIDER_NAME[provider]}</h3>
          {modelsLine(st, provider) && <div className="text-[12px] text-muted mb-1">Models: {modelsLine(st, provider)}</div>}
          {profiles.map((p, i) => {
            const k = provider + p.profile;
            const names = profiles.map((x) => x.profile);
            return (
              <div key={p.profile} className="flex items-center gap-2 py-1.5 border-b border-line text-[13px]">
                <span className="w-32 flex items-center gap-1.5 min-w-0">
                  <span className="font-medium truncate" title={p.profile}>{p.profile}</span>
                  {profiles.length > 1 && (i === 0
                    ? <span className="chip text-[11px] py-0" title="New sessions use this profile">default</span>
                    : <button className="btn btn-ghost px-1 py-0" title="Make default" aria-label={`Make ${p.profile} the default ${provider} profile`}
                        onClick={() => setProfiles(provider, [p.profile, ...names.filter((x) => x !== p.profile)], `${p.profile} is now the default.`)}><Star size={13} /></button>)}
                </span>
                <span className="w-40 text-muted">{p.has_key ? `Key ${p.hint} · ${p.source}` : "No key"}</span>
                <input type="password" autoComplete="off" className="input flex-1" placeholder={p.has_key ? "Replace key" : "Paste API key"}
                  value={draft[k]?.key ?? ""} onChange={(e) => setDraft({ ...draft, [k]: { profile: p.profile, key: e.target.value } })} aria-label={`${provider} ${p.profile} key`} />
                <button className="btn btn-primary" disabled={!draft[k]?.key || keyState[k] === "saving"} onClick={() => saveKey(provider, p.profile, draft[k].key)}>Save</button>
                <SavedMark state={keyState[k]} />
                {p.has_key && p.source === "keychain" && (
                  <button className="btn btn-ghost btn-danger px-1.5" aria-label="Remove key" title="Remove key" onClick={async () => { if (confirm(`Remove the ${p.profile} key?`)) { await del(`/settings/keys/${provider}/${p.profile}`); actions.toast("Key removed. Checking the account again…"); reload(); } }}><Trash2 size={14} /></button>
                )}
                {profiles.length > 1 && (
                  <button className="btn btn-ghost btn-danger px-1.5" aria-label={`Delete profile ${p.profile}`} title="Delete profile" onClick={() => deleteProfile(provider, p.profile)}><UserMinus size={14} /></button>
                )}
              </div>
            );
          })}
          <AddProfile onAdd={(profile, key) => key ? saveKey(provider, profile, key)
            : setProfiles(provider, [...profiles.map((x) => x.profile), profile], `Added the ${profile} profile. Paste its key to use it.`)} />
        </section>
      ))}
      <p className="text-[12px] text-faint">Status for each key shows on My usage. The Codex CLI uses your OpenAI key, or its own login if you've run <code className="font-mono">codex login</code>.</p>
    </div>
  );
}

function AddProfile({ onAdd }: { onAdd: (profile: string, key: string) => void }) {
  const [open, setOpen] = useState(false);
  const [p, setP] = useState("");
  const [k, setK] = useState("");
  if (!open) return <button className="btn btn-ghost mt-1 text-[12.5px]" onClick={() => setOpen(true)}><Plus size={13} /> Add profile</button>;
  return (
    <div className="flex gap-2 mt-2">
      <input autoFocus className="input w-36" placeholder="Profile name" value={p} onChange={(e) => setP(e.target.value)} aria-label="Profile name" />
      <input type="password" autoComplete="off" className="input flex-1" placeholder="API key (optional, add it later)" value={k} onChange={(e) => setK(e.target.value)} aria-label="API key" />
      <button className="btn btn-primary" disabled={!/^[a-zA-Z0-9_-]{1,32}$/.test(p)} onClick={() => { onAdd(p, k); setOpen(false); setP(""); setK(""); }}>Add</button>
      <button className="btn btn-ghost" onClick={() => { setOpen(false); setP(""); setK(""); }}>Cancel</button>
    </div>
  );
}

// Tier keys are unchanged ("codex.*" stays); the groups only name the models behind them.
const TIER_GROUPS: [string, string, string][] = [
  ["claude", "Claude tiers", "The claude.* tiers run Anthropic models."],
  ["codex", "OpenAI tiers", "OpenAI retired its *-codex API models, so the codex.* tiers run GPT-6 models."],
  ["", "Other tiers", ""],
];
const tierGroup = (tier: string) => (tier.startsWith("claude.") ? "claude" : tier.startsWith("codex.") ? "codex" : "");

function Models({ st, save }: { st: any; save: Save }) {
  const ids = Object.keys(st.models);
  const byProv = (p: string) => ids.filter((i) => st.models[i].provider === p);
  return (
    <div>
      <H2 sub="Tiers are what the delegation skill routes to. Prices and context windows live in the config file.">Models and effort</H2>
      <Row label="Default orchestrator model">
        <select className="input w-64" value={st.orchestrator.model} onChange={(e) => save({ orchestrator: { model: e.target.value } }, "Default orchestrator model")}>
          {byProv("anthropic").map((m) => <option key={m} value={m}>{modelLabel(m)}</option>)}
        </select>
      </Row>
      <Row label="Default orchestrator effort" hint="Above high is set per session and asks each time.">
        <select className="input w-40" value={st.orchestrator.effort} onChange={(e) => save({ orchestrator: { effort: e.target.value } }, "Default orchestrator effort")}>
          {["none", "low", "medium", "high"].map((x) => <option key={x}>{x}</option>)}
        </select>
      </Row>
      <Row label="Show thinking"><input type="checkbox" checked={!!st.orchestrator.show_thinking} onChange={(e) => save({ orchestrator: { show_thinking: e.target.checked } }, "Show thinking")} /></Row>
      {TIER_GROUPS.map(([prefix, title, note]) => Object.keys(st.tiers).some((t) => tierGroup(t) === prefix) && (
        <div key={prefix || "other"}>
          <div className="mt-6 font-medium text-[13px]">{title}</div>
          {note && <div className="text-[12px] text-faint mb-2">{note} Models: {modelsLine(st, prefix === "claude" ? "anthropic" : "openai")}.</div>}
          {Object.entries(st.tiers as Record<string, string>).filter(([tier]) => tierGroup(tier) === prefix).map(([tier, model]) => (
            <Row key={tier} label={tier} hint={tier === "codex.cli" ? "Model passed to codex exec" : undefined}>
              <select className="input w-80" value={model} onChange={(e) => save({ tiers: { [tier]: e.target.value } }, tier)} aria-label={`${tier} model`}>
                {byProv(tier.startsWith("claude") ? "anthropic" : "openai").map((m) => (
                  <option key={m} value={m}>{st.models[m].display_name || m} · {m} (${st.models[m].input}/${st.models[m].output})</option>
                ))}
              </select>
            </Row>
          ))}
        </div>
      ))}
      <Row label="Default subagent effort">
        <select className="input w-40" value={st.delegation.default_subagent_effort} onChange={(e) => save({ delegation: { default_subagent_effort: e.target.value } }, "Default subagent effort")}>
          {["none", "low", "medium", "high"].map((x) => <option key={x}>{x}</option>)}
        </select>
      </Row>
    </div>
  );
}

function Delegation({ st, save }: { st: any; save: Save }) {
  const d = st.delegation;
  const mp = d.max_parallel ?? {};
  return (
    <div>
      <H2 sub="The M4 Air is fanless: these defaults keep it cool. Codex CLI builds and tests run locally.">Delegation and budgets</H2>
      <Row label="Parallel API subagents" hint="Claude and Codex combined"><Num value={mp.claude_codex ?? 4} min={1} onSave={(v) => save({ delegation: { max_parallel: { ...mp, claude_codex: v } } }, "Parallel API subagents")} /></Row>
      <Row label="Parallel Codex CLI runs" hint={`Runs ${modelLabel("codex.cli")}`}><Num value={mp.codex_cli ?? 2} min={1} onSave={(v) => save({ delegation: { max_parallel: { ...mp, codex_cli: v } } }, "Parallel Codex CLI runs")} /></Row>
      <Row label="Show the plan first above" hint="USD; confirm_over_usd"><Num value={d.confirm_over_usd} step={0.25} onSave={(v) => save({ delegation: { confirm_over_usd: v } }, "Show the plan first above")} /></Row>
      <Row label="Job budget" hint="USD; job_budget_usd"><Num value={d.job_budget_usd} step={0.5} onSave={(v) => save({ delegation: { job_budget_usd: v } }, "Job budget")} /></Row>
      <Row label="Per-subagent spend cap" hint="USD"><Num value={d.subagent_spend_cap_usd} step={0.25} onSave={(v) => save({ delegation: { subagent_spend_cap_usd: v } }, "Per-subagent spend cap")} /></Row>
      <Row label="Subagent max turns"><Num value={d.subagent_max_turns} min={1} onSave={(v) => save({ delegation: { subagent_max_turns: v } }, "Subagent max turns")} /></Row>
      <Row label="Daily spend limit" hint="USD; all agents pause when hit, until midnight or Resume anyway"><Num value={st.limits.global_daily_usd} step={1} onSave={(v) => save({ limits: { global_daily_usd: v } }, "Daily spend limit")} /></Row>
      <Row label="Per-session spend limit" hint="USD; pauses that session until you raise it or Resume anyway"><Num value={st.limits.session_usd} step={1} onSave={(v) => save({ limits: { session_usd: v } }, "Per-session spend limit")} /></Row>
      <p className="text-[12px] text-faint mt-2">Parallel limits apply after a restart.</p>
    </div>
  );
}

const ALLOW_KINDS = ["run_command", "edit", "delete", "elevenlabs", "codex_cli", "mcp", "shared_tool", "skill_install", "mcp_install"];

/** True for a complete rule: a known kind, a colon and a non-empty pattern. Anything else (say a
 *  half-typed `run_command:`) is never saved, since an empty pattern could be read as `*`. */
export const validAllowRule = (r: string) => {
  const i = r.indexOf(":");
  return i > 0 && ALLOW_KINDS.includes(r.slice(0, i).trim()) && r.slice(i + 1).trim() !== "";
};
/** The rules on screen that get saved: trimmed, complete ones only. */
export const savableAllowRules = (list: string[]) => list.map((r) => r.trim()).filter(validAllowRule);

/** The approval allowlist as an editable list: edits save after a pause, add and remove at once.
 *  Incomplete rows stay on screen (marked) but are left out of what's saved until they're complete. */
export function Allowlist({ rules, save }: { rules: string[]; save: (rules: string[]) => void }) {
  const [rows, setRows] = useState<string[]>(rules);
  const [draft, setDraft] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pending = useRef<string[] | null>(null);
  const saved = useRef(rules.join("\n"));
  saved.current = rules.join("\n");
  // The saved list wins unless the complete rules on screen already match it: that keeps a trailing
  // space mid-typing. Incomplete rows are never in the saved list, so they're kept either way.
  useEffect(() => {
    if (pending.current) return;
    setRows((cur) => (savableAllowRules(cur).join("\n") === rules.join("\n") ? cur
      : [...rules, ...cur.filter((r) => r.trim() && !validAllowRule(r.trim()) && !rules.includes(r))]));
  }, [rules.join("\n")]); // eslint-disable-line react-hooks/exhaustive-deps
  const flush = () => {
    clearTimeout(timer.current);
    if (!pending.current) return;
    const next = savableAllowRules(pending.current);
    pending.current = null;
    if (next.join("\n") !== saved.current) save(next);
  };
  useEffect(() => flush, []); // eslint-disable-line react-hooks/exhaustive-deps
  const commit = (next: string[], now: boolean) => {
    setRows(next);
    pending.current = next;
    clearTimeout(timer.current);
    if (now) flush();
    else timer.current = setTimeout(flush, TYPE_DEBOUNCE_MS);
  };
  const valid = validAllowRule;
  const add = () => {
    const r = draft.trim();
    if (!r) return;
    commit([...rows, r], true);
    setDraft("");
  };
  return (
    <div>
      <ul className="space-y-1">
        {rows.map((r, i) => (
          <li key={i} className="flex items-center gap-1.5">
            <input className={`input font-mono text-[12.5px] py-1 ${r.trim() && !valid(r.trim()) ? "border-warn" : ""}`} value={r} spellCheck={false} aria-label={`Allowlist rule ${i + 1}`}
              title={r.trim() && !valid(r.trim()) ? `Starts with one of: ${ALLOW_KINDS.join(", ")}, then :pattern` : undefined}
              onChange={(e) => commit(rows.map((x, j) => (j === i ? e.target.value : x)), false)} onBlur={flush} />
            <button className="btn btn-ghost px-1.5 text-faint hover:text-text" title="Remove rule" aria-label={`Remove rule ${r}`} onClick={() => commit(rows.filter((_, j) => j !== i), true)}><X size={14} /></button>
            {r.trim() && !valid(r.trim()) && <span className="text-[12px] text-warn whitespace-nowrap">Not saved until complete</span>}
          </li>
        ))}
        {rows.length === 0 && <li className="text-[12.5px] text-muted py-1">No rules: everything listed above asks first.</li>}
      </ul>
      <div className="flex items-center gap-1.5 mt-2">
        <input className="input font-mono text-[12.5px] py-1" placeholder="run_command:git status*" value={draft} spellCheck={false} aria-label="New allowlist rule"
          onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn shrink-0" disabled={!draft.trim()} onClick={add}><Plus size={13} /> Add rule</button>
      </div>
    </div>
  );
}

function Modes({ st, save }: { st: any; save: Save }) {
  const saved = useSaved("Approval allowlist");
  return (
    <div>
      <H2 sub="Shell commands, deletes, above-high effort, large ElevenLabs generations, shared-tool jobs and MCP tools that aren't read-only always ask unless allowlisted.">Modes and approvals</H2>
      <Row label="Default mode for new sessions">
        <select className="input w-56" value={st.modes.default} onChange={(e) => save({ modes: { default: e.target.value } }, "Default mode for new sessions")}>
          <option value="ask">Ask before edits</option><option value="accept_edits">Accept edits</option><option value="plan">Plan only</option>
        </select>
      </Row>
      <div className="mt-4">
        <div className="text-[13px] mb-1 flex items-center gap-3">Approval allowlist <SavedMark state={saved} /></div>
        <div className="text-[12px] text-faint mb-2">One rule each, as <code className="font-mono">kind:pattern</code> with * wildcards. Kinds: run_command, edit, delete, elevenlabs, codex_cli, mcp and shared_tool (pattern <code className="font-mono">server__tool</code>), skill_install, mcp_install. Examples: <code className="font-mono">run_command:git status*</code>, <code className="font-mono">mcp:github__get_*</code>, <code className="font-mono">shared_tool:laptop__*</code>. A run_command rule covers one simple command only: anything with <code className="font-mono">; &amp; | ` $ ( ) &lt; &gt;</code> or a line break still asks, unless the rule is exactly <code className="font-mono">run_command:*</code>.</div>
        <Allowlist rules={st.modes.allowlist ?? []} save={(rules) => save({ modes: { allowlist: rules } }, "Approval allowlist")} />
      </div>
    </div>
  );
}

const UNITY_BACKENDS: [string, string, string][] = [
  ["auto", "Auto", "MCP when the Editor is open and MCP for Unity is connected, else the Unity CLI live Editor, else batch"],
  ["mcp", "MCP", "MCP for Unity while the Editor is open, unity.sh batchmode when it's closed (the previous behaviour)"],
  ["cli", "CLI", "Never use MCP for Unity: the official unity CLI drives a live Editor (Pipeline package) or runs batch jobs when it's closed"],
];

/** A text setting that saves on blur or Enter (paths: never mid-typing). */
function TextSetting({ value, onSave, label, placeholder }: { value: string; onSave: (v: string) => unknown; label: string; placeholder?: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => { if (v !== value) onSave(v); };
  return <input className="input flex-1 font-mono text-[12.5px]" value={v} aria-label={label} placeholder={placeholder} spellCheck={false}
    onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />;
}

export function UnitySettings({ st, save }: { st: any; save: Save }) {
  const u = st.unity ?? {};
  const [info, setInfo] = useState<UnityInfo | null>(null);
  useEffect(() => { get<UnityInfo>("/unity/info").then((i) => setInfo(i ?? null)).catch(() => setInfo(null)); }, []);
  const set = (k: string, label: string) => (v: unknown) => save({ unity: { [k]: v } }, label);
  const backend = u.backend ?? "auto";
  const cli = info?.cli;
  return (
    <div>
      <H2 sub="Which route compile, test, build and eval take for Unity projects: MCP for Unity or the official Unity CLI.">Unity</H2>
      <Row label="Default backend" field="Default backend">
        <div role="radiogroup" aria-label="Default Unity backend" className="inline-flex rounded-md border border-line overflow-hidden">
          {UNITY_BACKENDS.map(([v, label]) => (
            <button key={v} role="radio" aria-checked={backend === v} title={UNITY_BACKENDS.find((b) => b[0] === v)?.[2]}
              className={`px-3 py-1 text-[13px] ${backend === v ? "bg-sunken text-text font-medium" : "text-muted hover:text-text"}`}
              onClick={() => backend !== v && save({ unity: { backend: v } }, "Default backend")}>{label}</button>
          ))}
        </div>
      </Row>
      <ul className="text-[12px] text-faint py-2 space-y-0.5">
        {UNITY_BACKENDS.map(([v, label, text]) => <li key={v}><span className="text-muted">{label}:</span> {text}</li>)}
      </ul>
      <Row label="Unity CLI" noMark>
        <div className="text-[13px] min-w-0" data-testid="unity-cli">
          {!cli ? <span className="text-muted">Checking…</span>
            : !cli.path && !cli.version ? <span className="text-muted">Not found — install with Unity Hub or <code className="font-mono">curl -fsSL https://unity.com/install.sh | bash</code></span>
            : <>
                <span className="font-mono break-all">{cli.path}</span>{cli.version && <span className="chip ml-2">{cli.version}</span>}
                {cli.update_available && <span className="chip ml-2 text-action">update available: {cli.update_available}</span>}
                {cli.ok === false && <div className="text-[12px] text-bad">{cli.reason || "The CLI did not respond."}</div>}
              </>}
        </div>
      </Row>
      <Row label="Installed editors" noMark>
        <div className="text-[13px] min-w-0">
          {!info?.editors?.length ? <span className="text-muted">None found</span>
            : <ul>{info.editors.map((e) => (
                <li key={e.location} title={e.location}><span className="font-mono">{e.version}</span>{e.architecture && <span className="text-faint"> · {e.architecture}</span>}
                  <span className="text-faint font-mono text-[12px]"> · {e.location}</span></li>
              ))}</ul>}
        </div>
      </Row>
      <Row label="Unity CLI path" hint="Empty: look it up automatically"><TextSetting value={u.cli_path ?? ""} label="Unity CLI path" onSave={set("cli_path", "Unity CLI path")} /></Row>
      <Row label="Editor path" hint="Empty: pick the project's version"><TextSetting value={u.editor_path ?? ""} label="Editor path" onSave={set("editor_path", "Editor path")} /></Row>
      <Row label="Live call timeout" hint="Seconds"><Num value={u.live_timeout_s ?? 120} min={1} label="Live call timeout" onSave={set("live_timeout_s", "Live call timeout")} /></Row>
      <Row label="Batch timeout" hint="Seconds"><Num value={u.batch_timeout_s ?? 900} min={1} label="Batch timeout" onSave={set("batch_timeout_s", "Batch timeout")} /></Row>
      <Row label="Test timeout" hint="Seconds"><Num value={u.test_timeout_s ?? 1800} min={1} label="Test timeout" onSave={set("test_timeout_s", "Test timeout")} /></Row>
      <Row label="Build timeout" hint="Seconds"><Num value={u.build_timeout_s ?? 3600} min={1} label="Build timeout" onSave={set("build_timeout_s", "Build timeout")} /></Row>
      <Row label="Eval policy" hint="Running C# in the Editor through the CLI">
        <select className="input w-40" value={u.eval ?? "ask"} aria-label="Eval policy" onChange={(e) => save({ unity: { eval: e.target.value } }, "Eval policy")}>
          <option value="ask">ask</option><option value="off">off</option>
        </select>
      </Row>
      <Row label="No graphics" hint="Batch jobs run with -nographics">
        <input type="checkbox" checked={!!u.nographics} aria-label="No graphics" onChange={(e) => save({ unity: { nographics: e.target.checked } }, "No graphics")} />
      </Row>
    </div>
  );
}

function DataPolicy({ st, save }: { st: any; save: Save }) {
  const allowed: string[] = st.data_policy.sensitive_allowed ?? [];
  const toggle = (p: string, on: boolean) => save({ data_policy: { sensitive_allowed: on ? [...allowed, p] : allowed.filter((x) => x !== p) } }, PROVIDER_NAME[p]);
  return (
    <div>
      <H2 sub="Mark a file sensitive from its menu on the Artifacts page. These providers may receive sensitive files.">Data policy</H2>
      {["anthropic", "openai", "elevenlabs"].map((p) => (
        <Row key={p} label={PROVIDER_NAME[p]} hint={modelsLine(st, p) || undefined}><input type="checkbox" checked={allowed.includes(p)} onChange={(e) => toggle(p, e.target.checked)} aria-label={`Allow ${p}`} /></Row>
      ))}
    </div>
  );
}

function ElevenDefaults({ st, save }: { st: any; save: Save }) {
  const e = st.elevenlabs;
  const [voices, setVoices] = useState<any[]>([]);
  // Only list voices when the default profile has a key; without one the route answers 400 no_key.
  useEffect(() => {
    get<any>("/elevenlabs/status").then((s) => (s?.has_key ? get<any[]>("/elevenlabs/voices").then(setVoices) : undefined)).catch(() => {});
  }, []);
  return (
    <div>
      <H2>ElevenLabs defaults</H2>
      <Row label="Voice">
        <select className="input w-64" value={e.voice_id} onChange={(x) => save({ elevenlabs: { voice_id: x.target.value } }, "Voice")}>
          <option value="">First voice in my account</option>
          {voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{v.name}</option>)}
        </select>
      </Row>
      <Row label="Text to speech model">
        <select className="input w-64" value={e.model_id} onChange={(x) => save({ elevenlabs: { model_id: x.target.value } }, "Text to speech model")}>
          {["eleven_v4", "eleven_v4_turbo", "eleven_flash_v2_5", "eleven_v3", "eleven_multilingual_v2"].map((m) => <option key={m}>{m}</option>)}
        </select>
      </Row>
      <Row label="Output format">
        <select className="input w-64" value={e.output_format} onChange={(x) => save({ elevenlabs: { output_format: x.target.value } }, "Output format")}>
          {["mp3_44100_128", "mp3_44100_192", "mp3_22050_32", "wav_44100", "opus_48000_128"].map((m) => <option key={m}>{m}</option>)}
        </select>
      </Row>
      <Row label="Ask before agent generations over" hint="Characters for speech; estimated credits for sound effects and music"><Num value={e.confirm_over_characters} step={100} onSave={(v) => save({ elevenlabs: { confirm_over_characters: v } }, "Ask before agent generations over")} /></Row>
    </div>
  );
}

const isObj = (x: any) => x && typeof x === "object" && !Array.isArray(x);
const deepMerge = (a: any, b: any): any => {
  const out = { ...(a ?? {}) };
  for (const [k, v] of Object.entries(b ?? {})) out[k] = isObj(v) && isObj(out[k]) ? deepMerge(out[k], v) : v;
  return out;
};
const PERSIST_MS = 400;
type Update = (patch: any, now?: boolean) => void;

/** Sliders apply live (local state and the app background) and write config.toml only when
 *  released or after PERSIST_MS without movement, not on every input tick. */
function Appearance({ st, save, reload }: { st: any; save: Save; reload: () => void }) {
  const [a, setA] = useState<any>(st.appearance ?? {});
  const live = useRef<any>(a);
  const pending = useRef<any>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const saveRef = useRef(save);
  saveRef.current = save;
  const inflight = useRef(0);
  // Server state wins unless the user has unsaved movement or a save in flight (an older save's
  // response would otherwise snap the sliders back).
  useEffect(() => { if (!pending.current && !inflight.current) { live.current = st.appearance ?? {}; setA(live.current); } }, [st.appearance]);
  const flush = () => {
    clearTimeout(timer.current);
    const body = pending.current;
    pending.current = null;
    if (!body) return;
    inflight.current++;
    // save() refreshes app state; until this save and any newer edits are done, refreshState keeps
    // the live values (actions.setLiveAppearance) instead of the server's older copy.
    Promise.resolve(saveRef.current({ appearance: body }, "appearance")).finally(() => {
      if (--inflight.current === 0 && !pending.current) actions.setLiveAppearance(null);
    });
  };
  useEffect(() => flush, []); // leaving the page persists what's pending
  const update: Update = (patch, now = false) => {
    live.current = deepMerge(live.current, patch);
    setA(live.current);
    useStore.setState((x) => (x.appState ? { appState: { ...x.appState, appearance: live.current } } : {}));
    actions.setLiveAppearance(live.current);
    pending.current = deepMerge(pending.current, patch);
    clearTimeout(timer.current);
    if (now) flush();
    else timer.current = setTimeout(flush, PERSIST_MS);
  };
  const release = { onPointerUp: flush, onKeyUp: flush, onBlur: flush };
  return (
    <div>
      <H2 sub="Image, animated GIF or video (MP4 with H.264/HEVC, or WebM). Video is muted and loops, pauses when the window is hidden or on battery under 20%, and shows a still frame when Reduce motion is on." field="appearance">Appearance</H2>
      <Row label="Panel opacity" hint="Lower shows more background">
        <input type="range" min={0.55} max={1} step={0.01} className="w-64" value={a.panel_opacity ?? 1} {...release} aria-label="Panel opacity"
          onChange={(e) => update({ panel_opacity: Number(e.target.value) })} />
      </Row>
      {(["light", "dark"] as const).map((theme) => <BgEditor key={theme} theme={theme} bg={a[theme] ?? {}} update={update} release={release} reload={reload} />)}
    </div>
  );
}

function BgEditor({ theme, bg, update, release, reload }: { theme: "light" | "dark"; bg: any; update: Update; release: Record<string, () => void>; reload: () => void }) {
  const inp = useRef<HTMLInputElement>(null);
  const uploadBg = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    try { await api(`/settings/background?theme=${theme}`, { method: "POST", body: fd }); reload(); actions.refreshState(); } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const set = (k: string, v: any, now = false) => update({ [theme]: { [k]: v } }, now);
  const video = bg.kind === "video";
  return (
    <div className="mt-6">
      <div className="font-medium text-[13px] mb-1">{theme === "light" ? "Light theme background" : "Dark theme background"}</div>
      <Row label="File">
        <div className="flex gap-2 items-center">
          <button className="btn" onClick={() => inp.current?.click()}>{bg.path ? "Replace…" : "Choose…"}</button>
          <input ref={inp} type="file" hidden accept="image/png,image/jpeg,image/webp,image/gif,video/mp4,video/quicktime,video/webm" onChange={(e) => e.target.files?.[0] && uploadBg(e.target.files[0])} />
          {bg.path && <span className="text-[12.5px] text-muted truncate">{bg.path.split("/").pop()} · {bg.kind}</span>}
          {bg.path && <button className="btn btn-ghost btn-danger" onClick={async () => { await del(`/settings/background/${theme}`); reload(); actions.refreshState(); }}>Remove</button>}
        </div>
      </Row>
      {bg.path && (
        <>
          <Row label="Fit" hint={video ? "Tile works for images and GIFs; videos cover or fit the window" : undefined}>
            <select className="input w-40" value={video && bg.fit === "tile" ? "cover" : bg.fit ?? "cover"} onChange={(e) => set("fit", e.target.value, true)}>
              <option value="cover">Cover</option><option value="contain">Contain</option><option value="tile" disabled={video}>Tile{video ? " (images only)" : ""}</option>
            </select>
          </Row>
          <Row label="Dim"><input type="range" min={0} max={0.9} step={0.05} className="w-64" value={bg.dim ?? 0.35} aria-label={`${theme === "light" ? "Light" : "Dark"} background dim`} {...release} onChange={(e) => set("dim", Number(e.target.value))} /></Row>
          <Row label="Blur"><input type="range" min={0} max={24} step={1} className="w-64" value={bg.blur ?? 0} aria-label={`${theme === "light" ? "Light" : "Dark"} background blur`} {...release} onChange={(e) => set("blur", Number(e.target.value))} /></Row>
        </>
      )}
    </div>
  );
}

function About() {
  const [u, setU] = useState<UpdatesStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const load = () => get<UpdatesStatus>("/updates").then(setU).catch((e) => actions.toast(e.message, "error"));
  useEffect(() => { load(); }, []);
  useEffect(() => actions.onEvent((e) => { if (e.type.startsWith("update.")) load(); }), []);
  if (!u) return null;
  const cur = u.current;
  const check = async () => {
    setChecking(true);
    try {
      const r = await post<UpdatesStatus>("/updates/check");
      setU(r);
      actions.refreshState();
      actions.toast(r.update ? `${updateHeadline(r.update.latest, r.install_supported)}.` : r.latest ? "You're on the latest version." : "Nothing published in the updates folder yet.");
    } catch (e: any) { actions.toast(e.message, "error"); } finally { setChecking(false); }
  };
  const reveal = async () => {
    if (!(await revealInFinder(u.dir))) {
      navigator.clipboard?.writeText(u.dir).catch(() => {});
      actions.toast(`Updates folder: ${u.dir} (path copied)`);
    }
  };
  const rollback = () => u.previous && confirm(`Roll back to GameDevWorkstation ${u.previous.version}? The app restarts, and ${cur.version} is kept so you can go forward again.`)
    && installUpdate({ rollback: true });
  return (
    <div>
      <H2 sub={<Inline text="New versions are built on this Mac with `make release` into the updates folder. The app checks the folder and offers to install them." />}>About & updates</H2>
      <Row label="Running version">
        <span className="font-mono">v{cur.version}</span>
        <span className="chip ml-2">{cur.frozen ? "app" : "from source"}</span>
      </Row>
      <Row label="Commit">
        <span className="font-mono text-[13px]">{cur.git_commit ?? "unknown"}</span>
        {cur.git_dirty && <span className="text-[12px] text-warn ml-2">with uncommitted changes</span>}
      </Row>
      <Row label="Built">{cur.built_at ? fmtBuilt(cur.built_at) : <span className="text-muted">{cur.frozen ? "unknown" : "not built: running from the source tree"}</span>}</Row>
      <Row label="Updates folder" hint={`Checked every ${u.check_interval_s}s; [updates] dir in config.toml`}>
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-[12.5px] truncate" title={u.dir}>{u.dir}</span>
          {!u.dir_exists && <span className="chip">not created yet</span>}
          <button className="btn btn-ghost px-1.5 shrink-0" onClick={reveal} title="Show in Finder" aria-label="Show in Finder"><FolderOpen size={14} /></button>
        </div>
      </Row>
      <Row label="Latest available">
        {u.update ? <span><span className="font-mono text-action">v{u.update.latest}</span> <span className="text-muted text-[13px]">{u.install_supported ? "ready to install" : "available"}</span></span>
          : u.latest ? <span className="text-muted">v{u.latest.version} · you're up to date</span>
          : <span className="text-muted">Nothing published yet</span>}
      </Row>
      <div className="flex flex-wrap gap-2 mt-4">
        <button className="btn" onClick={check} disabled={checking}><RefreshCw size={14} className={checking ? "animate-spin" : ""} /> Check now</button>
        <button className="btn btn-primary" disabled={!u.update || !u.install_supported} onClick={() => installUpdate({ version: u.update!.latest })}>
          <ArrowUpCircle size={14} /> Install & restart
        </button>
        <button className="btn" disabled={!u.previous || !u.install_supported} onClick={rollback}
          title={u.previous ? `Kept from the last install: ${u.previous.app_path}` : "No previous version kept yet"}>
          <RotateCcw size={14} /> Roll back{u.previous ? ` to v${u.previous.version}` : " to previous"}
        </button>
      </div>
      {!u.install_supported && u.reason && <p className="text-[12.5px] text-muted mt-2"><Inline text={u.reason} /></p>}
      <div className="mt-8 mb-2 font-medium text-[13px]">Release history</div>
      {!u.history.length && <p className="text-[13px] text-muted">No releases in the folder yet. Run <code className="font-mono">make release</code> in the repo.</p>}
      {u.history.map((r) => (
        <section key={r.version} className="border-b border-line py-3">
          <div className="flex items-center gap-2 mb-1.5 text-[13px]">
            <span className="font-mono font-medium">v{r.version}</span>
            {r.version === cur.version && <span className="chip">running</span>}
            {r.version === u.latest?.version && r.version !== cur.version && <span className="chip text-action">latest</span>}
            <span className="text-faint">{[fmtBuilt(r.built_at), r.git_commit].filter(Boolean).join(" · ")}</span>
          </div>
          <Notes text={r.notes} />
        </section>
      ))}
    </div>
  );
}
