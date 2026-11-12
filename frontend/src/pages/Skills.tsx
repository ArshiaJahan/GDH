import { Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { Suspense, lazy, useEffect, useLayoutEffect, useRef, useState } from "react";
import { del, get, patch, post } from "../lib/api";
import { actions } from "../lib/store";
import { Empty, Modal, ModalFooter } from "../components/ui";
import { AssistantBox } from "../components/AssistantBox";

type Skill = { name: string; description: string; source: string; path: string };
type Server = { name: string; transport: string; command?: string; args: string[]; url?: string; env: Record<string, string>; headers: Record<string, string>; enabled_default: boolean; shared: boolean; connected: boolean; error?: string | null; tools?: string[] | null;
  /** Built-in (a config preset): `description` says what it needs, `modified` offers Reset to default. `hint`: its command isn't installed. */
  preset?: boolean; description?: string; modified?: boolean; hint?: string | null };

/** Secret env vars and headers come back from the API masked as ••••last4 (the values live in the Keychain). */
const MASK = "••••";
const secretNames = (s: Server) => [...Object.entries(s.env ?? {}), ...Object.entries(s.headers ?? {})].filter(([, v]) => String(v).startsWith(MASK));

// The SKILL.md editor brings Monaco; it loads only when a skill is opened.
const SkillEditor = lazy(() => import("../components/SkillEditor"));

export function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [global, setGlobal] = useState<string[]>([]);
  const [servers, setServers] = useState<Server[]>([]);
  const [editing, setEditing] = useState<{ name: string | null } | null>(null); // name null: a new skill
  const [adding, setAdding] = useState<Server | true | null>(null);
  const [tests, setTests] = useState<Record<string, any>>({});
  const [q, setQ] = useState("");
  const term = q.trim().toLowerCase();
  const shownSkills = term ? skills.filter((s) => s.name.toLowerCase().includes(term) || s.description.toLowerCase().includes(term)) : skills;

  const load = async () => {
    const [sk, sv] = await Promise.all([get("/skills"), get<Server[]>("/mcp/servers")]);
    setSkills(sk.skills);
    setGlobal(sk.global);
    setServers(sv);
  };
  useEffect(() => { load(); }, []);

  const toggleGlobal = async (n: string) => {
    const next = global.includes(n) ? global.filter((x) => x !== n) : [...global, n];
    setGlobal((await post("/skills/global", { names: next })).global);
    actions.refreshState().catch(() => {}); // new sessions start with these: "+" compares against them
  };
  const openSkill = (n: string) => setEditing({ name: n });
  const test = async (n: string) => {
    setTests({ ...tests, [n]: { busy: true } });
    const r = await post(`/mcp/servers/${n}/test`);
    setTests((t) => ({ ...t, [n]: r }));
    load();
  };

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[1000px] mx-auto px-6 py-5 space-y-8">
        <section>
          <div className="flex items-center gap-3 mb-2">
            <h1 className="text-lg font-semibold">Skills</h1>
            <a href="#mcp-servers" className="text-[12.5px] text-action hover:underline" onClick={(e) => { e.preventDefault(); document.getElementById("mcp-servers")?.scrollIntoView({ behavior: "smooth" }); }}>MCP servers ↓</a>
            <label className="relative ml-auto w-56">
              <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
              <input className="input pl-7 py-1 text-[13px]" placeholder="Filter skills" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter skills"
                onKeyDown={(e) => e.key === "Escape" && setQ("")} />
            </label>
            <button className="btn" onClick={() => setEditing({ name: null })}><Plus size={14} /> New skill</button>
          </div>
          <p className="text-[13px] text-muted mb-3">Skills enabled here are on for new sessions. Turn them on or off per session in its Connectors card.</p>
          <div className="mb-3"><AssistantBox kind="skill" onFinished={load} onOpenSkill={openSkill} /></div>
          <div className="rounded-md border border-line surface divide-y divide-[var(--line)]">
            {shownSkills.map((s) => (
              <SkillRow key={s.name} s={s} on={global.includes(s.name)} onToggle={() => toggleGlobal(s.name)} onOpen={() => openSkill(s.name)} />
            ))}
            {!skills.length && <div className="p-3"><Empty>No skills yet.</Empty></div>}
            {skills.length > 0 && !shownSkills.length && <div className="p-3 text-[13px] text-muted">No skills match “{q}”.</div>}
          </div>
        </section>

        <section id="mcp-servers" className="scroll-mt-4">
          <div className="flex items-center mb-2">
            <h2 className="text-lg font-semibold">MCP servers</h2>
            <button className="btn ml-auto" onClick={() => setAdding(true)}><Plus size={14} /> Add server</button>
          </div>
          <p className="text-[13px] text-muted mb-3">Their tools are offered to the main agent and to Claude and Codex subagents you grant them to.</p>
          <div className="mb-3"><AssistantBox kind="mcp" onFinished={load} onOpenServer={(n) => document.getElementById(`mcp-server-${n}`)?.scrollIntoView({ behavior: "smooth", block: "center" })} /></div>
          <div className="space-y-2">
            {servers.map((s) => {
              const t = tests[s.name];
              return (
                <div key={s.name} id={`mcp-server-${s.name}`} className="rounded-md border border-line surface px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <span className="size-2 rounded-full" style={{ background: s.connected ? "var(--ok)" : s.error ? "var(--bad)" : "var(--faint)" }} aria-hidden />
                    <span className="font-medium">{s.name}</span>
                    <span className="chip">{s.transport}</span>
                    {s.preset && <span className="chip whitespace-nowrap shrink-0" title="Comes with GameDevWorkstation">Built-in{s.modified ? " · edited" : ""}</span>}
                    {s.shared && <span className="chip">other machine</span>}
                    <span className="text-[12px] text-muted truncate min-w-0">{s.transport === "stdio" ? [s.command, ...s.args].join(" ") : s.url}</span>
                    <div className="ml-auto flex items-center gap-2 text-[13px] whitespace-nowrap shrink-0">
                      <label className="flex items-center gap-1.5"><input type="checkbox" checked={s.enabled_default} onChange={async (e) => { await patch(`/mcp/servers/${s.name}`, { enabled_default: e.target.checked }); load(); }} /> On by default</label>
                      <button className="btn" onClick={() => test(s.name)} disabled={t?.busy}>{t?.busy ? "Testing…" : "Test connection"}</button>
                      <button className="btn" onClick={() => setAdding(s)} aria-label={`Edit ${s.name}`}>Edit</button>
                      {s.preset && s.modified && <button className="btn" onClick={() => post(`/mcp/servers/${s.name}/reset`).then(() => { actions.toast(`Reset ${s.name} to default`); load(); }, (e) => actions.toast(e.message, "error"))}>Reset to default</button>}
                      <button className="btn btn-ghost btn-danger px-1.5" aria-label={`Remove ${s.name}`} onClick={async () => { if (confirm(s.preset ? `Remove the built-in server ${s.name}? It won't be added back.` : `Remove ${s.name}?`)) { await del(`/mcp/servers/${s.name}`); load(); } }}><Trash2 size={14} /></button>
                    </div>
                  </div>
                  {s.description && <div className="mt-1 text-[12px] text-muted">{s.description}</div>}
                  {s.hint && <div className="mt-1 text-[12px] text-warn">{s.hint}</div>}
                  {secretNames(s).length > 0 && (
                    <div className="mt-1 text-[12px] text-muted">In the Keychain: {secretNames(s).map(([k, v]) => <span key={k} className="font-mono mr-2">{k} {v}</span>)}</div>
                  )}
                  {t && !t.busy && (t.ok
                    ? <div className="mt-2 text-[13px]"><span style={{ color: "var(--ok)" }}>Connected.</span> {t.tools.length} tools: <span className="text-muted">{t.tools.map((x: any) => x.name).join(", ")}</span></div>
                    : <div className="mt-2 text-[13px] text-bad">{t.error}</div>)}
                  {!t && s.error && <div className="mt-2 text-[13px] text-bad">{s.error}</div>}
                </div>
              );
            })}
            {!servers.length && <Empty>No MCP servers yet. Add one with its command (stdio) or URL (HTTP).</Empty>}
          </div>
        </section>
      </div>

      {editing && (
        <Suspense fallback={<Modal title={editing.name ?? "New skill"} onClose={() => setEditing(null)} wide><p className="text-muted">Loading the editor…</p></Modal>}>
          <SkillEditor name={editing.name} existing={skills.map((s) => s.name)} onClose={() => setEditing(null)} onSaved={load} />
        </Suspense>
      )}
      {adding && <AddServer server={adding === true ? undefined : adding} onClose={() => setAdding(null)} onAdded={() => { setAdding(null); load(); }} />}
    </div>
  );
}

/** A skill: its description clamped to two lines, with More / Less when it's longer. */
function SkillRow({ s, on, onToggle, onOpen }: { s: Skill; on: boolean; onToggle: () => void; onOpen: () => void }) {
  const [open, setOpen] = useState(false);
  const [clamped, setClamped] = useState(false);
  const desc = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = desc.current;
    if (!el) return;
    const check = () => setClamped(el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [s.description]);
  return (
    <div className="flex items-start gap-3 px-3 py-2.5">
      <input type="checkbox" className="mt-1" checked={on} onChange={onToggle} aria-label={`Enable ${s.name} for new sessions`} />
      <div className="flex-1 min-w-0">
        <div className="font-medium">{s.name} <span className="chip ml-1">{s.source === "builtin" ? "built in" : "yours"}</span></div>
        <div ref={desc} className={`text-[13px] text-muted ${open ? "" : "line-clamp-2"}`}>{s.description}</div>
        {(clamped || open) && (
          <button className="text-[12px] text-action hover:underline" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Less" : "More"}</button>
        )}
      </div>
      <button className="btn" onClick={() => actions.useSkillInChat(s.name)} title="Open the chat with this skill attached to your next message" aria-label={`Use ${s.name} in chat`}><Sparkles size={14} /> Use in chat</button>
      <button className="btn" onClick={onOpen}>View / edit</button>
    </div>
  );
}

/** "KEY=value" / "Name: value" lines → object, split at the first separator so values may contain = or :. */
function parseKv(text: string, seps: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const i = seps.map((c) => line.indexOf(c)).filter((n) => n > 0).sort((a, b) => a - b)[0];
    if (i === undefined) continue;
    const k = line.slice(0, i).trim();
    if (k) out[k] = line.slice(i + 1).trim();
  }
  return out;
}

function AddServer({ server, onClose, onAdded }: { server?: Server; onClose: () => void; onAdded: () => void }) {
  const lines = (m: Record<string, string> | undefined, sep: string) => Object.entries(m ?? {}).map(([k, v]) => `${k}${sep}${v}`).join("\n");
  const [f, setF] = useState(server
    ? { name: server.name, transport: server.transport, command: server.command ?? "", url: server.url ?? "", shared: server.shared,
        args: server.args.map((a) => (/\s/.test(a) ? `"${a}"` : a)).join(" "), headers: lines(server.headers, ": "), env: lines(server.env, "=") }
    : { name: "", transport: "stdio", command: "", args: "", url: "", headers: "", env: "", shared: false });
  const save = async () => {
    try {
      await post("/mcp/servers", {
        name: f.name, transport: f.transport, command: f.command || null, url: f.url || null, shared: f.shared,
        args: f.args.trim() ? f.args.match(/(?:[^\s"]+|"[^"]*")+/g)!.map((a) => a.replace(/^"|"$/g, "")) : [],
        headers: parseKv(f.headers, [":"]), env: parseKv(f.env, ["=", ":"]),
        ...(server ? { enabled_default: server.enabled_default } : {}),
      });
      onAdded();
    } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const row = "block mb-3";
  return (
    <Modal title={server ? `Edit ${server.name}` : "Add MCP server"} onClose={onClose}>
      <label className={row}><span className="label">Name</span><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="github" disabled={!!server} /></label>
      <div className="inline-flex rounded border border-line overflow-hidden text-[13px] mb-3">
        {["stdio", "http"].map((t) => <button key={t} className={`px-3 py-1 ${f.transport === t ? "bg-sunken font-medium" : ""}`} aria-pressed={f.transport === t} onClick={() => setF({ ...f, transport: t })}>{t === "stdio" ? "Command (stdio)" : "URL (HTTP)"}</button>)}
      </div>
      {f.transport === "stdio" ? (
        <>
          <label className={row}><span className="label">Command</span><input className="input font-mono" value={f.command} onChange={(e) => setF({ ...f, command: e.target.value })} placeholder="npx" /></label>
          <label className={row}><span className="label">Arguments</span><input className="input font-mono" value={f.args} onChange={(e) => setF({ ...f, args: e.target.value })} placeholder="-y @modelcontextprotocol/server-filesystem ~/Documents" /></label>
          <label className={row}><span className="label">Environment (KEY=value per line; keys, tokens and passwords go to the Keychain. Leave a ••••1234 value as is to keep it, or replace it)</span><textarea className="input font-mono h-16" value={f.env} onChange={(e) => setF({ ...f, env: e.target.value })} /></label>
        </>
      ) : (
        <>
          <label className={row}><span className="label">URL</span><input className="input font-mono" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://example.com/mcp" /></label>
          <label className={row}><span className="label">Headers (Name: value per line; Authorization and other secret headers go to the Keychain. Leave a ••••1234 value as is to keep it)</span><textarea className="input font-mono h-16" value={f.headers} onChange={(e) => setF({ ...f, headers: e.target.value })} /></label>
        </>
      )}
      <label className="flex items-center gap-2 text-[13px] mb-3"><input type="checkbox" checked={f.shared} onChange={(e) => setF({ ...f, shared: e.target.checked })} /> This server runs on another machine (only used in sessions with Shared tools on; every job asks first)</label>
      <ModalFooter>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!f.name}>{server ? "Save" : "Add server"}</button>
      </ModalFooter>
    </Modal>
  );
}
