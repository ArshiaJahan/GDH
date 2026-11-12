import { Pin, PinOff, Plus, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { get, patch, post } from "../../lib/api";
import { actions, type Session } from "../../lib/store";
import { Popover } from "../Popover";
import { Card } from "../SidePanel";

export function ConnectorsCard({ s }: { s: Session }) {
  const [servers, setServers] = useState<any[]>([]);
  const [skills, setSkills] = useState<any[]>([]);
  useEffect(() => {
    get("/skills").then((r) => setSkills(r.skills));
  }, [s.id]);
  // On opening a session (running or not), and again when a turn ends, so a server that connected
  // (or failed to) shows it.
  const prev = useRef({ id: s.id, status: s.status });
  const [turnsEnded, setTurnsEnded] = useState(0);
  useEffect(() => {
    const p = prev.current;
    if (p.id === s.id && p.status === "running" && s.status !== "running") setTurnsEnded((n) => n + 1);
    prev.current = { id: s.id, status: s.status };
  }, [s.id, s.status]);
  useEffect(() => {
    let live = true;
    get("/mcp/servers").then((r) => { if (live) setServers(r); }).catch(() => {});
    return () => { live = false; };
  }, [s.id, turnsEnded]);
  const conn = s.settings.connectors ?? {};
  const enabledSkills: string[] = s.settings.skills ?? [];
  const progressive = s.settings.skill_mode === "progressive";
  const pinnedSkills: string[] = [...new Set<string>([...(s.settings.pinned_skills ?? []), "delegation"])];
  const loadedSkills: string[] = s.settings.loaded_skills ?? [];
  const setPinned = (name: string, on: boolean) => patch(`/sessions/${s.id}`, { settings: {
    pinned_skills: on ? [...pinnedSkills, name] : pinnedSkills.filter((x) => x !== name),
    ...(on ? { skills: [...new Set([...enabledSkills, name])], loaded_skills: loadedSkills.filter((x) => x !== name) } : {}),
  } });
  const unload = (name: string) => patch(`/sessions/${s.id}`, { settings: { loaded_skills: loadedSkills.filter((x) => x !== name) } });
  const setConn = (name: string, on: boolean) => patch(`/sessions/${s.id}`, { settings: { connectors: { ...conn, [name]: on } } });
  const setSkill = (name: string, on: boolean) =>
    patch(`/sessions/${s.id}`, { settings: { skills: on ? [...enabledSkills, name] : enabledSkills.filter((x) => x !== name) } });
  const visible = servers.filter((x) => !x.shared || s.settings.shared_tools);
  const isOn = (x: any): boolean => conn[x.name] ?? x.enabled_default;
  const dot = (x: any) => (
    <span className="size-1.5 rounded-full shrink-0" style={{ background: x.connected ? "var(--ok)" : x.error ? "var(--bad)" : x.hint ? "var(--warn)" : "var(--faint)" }} title={x.connected ? "Connected" : x.error ?? x.hint ?? "Connects on the next turn"} />
  );
  // A short server list stays as checkboxes; a long one shows what's on, plus "Add server…".
  const longServers = visible.length > SHORT_LIST;
  const onServers = visible.filter(isOn);
  const skillDesc = Object.fromEntries(skills.map((x) => [x.name, x.description ?? ""]));
  return (
    <Card id="connectors" title="Connectors" right={<button className="text-[12px] text-action hover:underline" onClick={() => actions.go("skills")}>Manage</button>}>
      <div className="label mb-0.5">MCP servers</div>
      {visible.length === 0 && <div className="text-muted mb-1">None added.</div>}
      {!longServers && visible.map((x) => (
        <label key={x.name} className="flex items-center gap-2 py-0.5">
          <input type="checkbox" checked={isOn(x)} onChange={(e) => setConn(x.name, e.target.checked)} />
          <span className="flex-1 truncate">{x.name}</span>
          {x.shared && <span className="chip">other machine</span>}
          {dot(x)}
        </label>
      ))}
      {longServers && (
        <>
          {onServers.length === 0 && <div className="text-muted text-[12.5px] py-0.5">None on for this session.</div>}
          {onServers.map((x) => (
            <EnabledRow key={x.name} name={x.name} title={x.description} onRemove={() => setConn(x.name, false)}>
              {x.shared && <span className="chip">other machine</span>}
              {dot(x)}
            </EnabledRow>
          ))}
          <AddPicker label="Add server…" empty="Every server is on."
            options={visible.filter((x) => !isOn(x)).map((x) => ({ name: x.name, description: x.description ?? (x.shared ? "On another machine" : "") }))}
            onPick={(name) => setConn(name, true)} />
        </>
      )}
      <div className="label mt-2 mb-0.5">Skills</div>
      {progressive ? (
        <>
          <div className="label mt-1 mb-0.5">Pinned</div>
          {pinnedSkills.length === 0 && <div className="text-muted text-[12.5px] py-0.5">None pinned.</div>}
          {pinnedSkills.map((name) => (
            <div key={name} className="flex items-center gap-2 py-0.5" title={skillDesc[name]}>
              <span className="flex-1 min-w-0 truncate">{name}</span>
              <button className="btn btn-ghost p-0.5 text-action" title={name === "delegation" ? "Delegation stays pinned" : `Unpin ${name}`} aria-label={`Unpin ${name}`} disabled={s.status === "running" || name === "delegation"} onClick={() => setPinned(name, false)}><PinOff size={13} /></button>
            </div>
          ))}
          <AddPicker label="Pin skill…" empty={skills.length ? "Every skill is pinned." : "No skills installed."}
            disabled={s.status === "running"}
            options={skills.filter((x) => !pinnedSkills.includes(x.name)).map((x) => ({ name: x.name, description: x.description ?? "" }))}
            onPick={(name) => setPinned(name, true)} />
          <div className="label mt-2 mb-0.5">Loaded</div>
          {loadedSkills.length === 0 && <div className="text-muted text-[12.5px] py-0.5">None loaded.</div>}
          {loadedSkills.map((name) => (
            <EnabledRow key={name} name={name} title={skillDesc[name]} onRemove={() => unload(name)} removeLabel={`Unload ${name}`}>
              <button className="btn btn-ghost p-0.5 text-faint hover:text-text" title={`Pin ${name}`} aria-label={`Pin ${name}`} disabled={s.status === "running"} onClick={() => setPinned(name, true)}><Pin size={13} /></button>
            </EnabledRow>
          ))}
          <div className="text-muted text-[12.5px] mt-1">Index: {skills.filter((x) => !pinnedSkills.includes(x.name)).length} skills</div>
        </>
      ) : (
        <>
          {enabledSkills.length === 0 && <div className="text-muted text-[12.5px] py-0.5">None added to this session.</div>}
          {enabledSkills.map((name) => (
            <EnabledRow key={name} name={name} title={skillDesc[name]} onRemove={() => setSkill(name, false)} />
          ))}
          <AddPicker label="Add skill…" empty={skills.length ? "Every skill is added." : "No skills installed."}
            options={skills.filter((x) => !enabledSkills.includes(x.name)).map((x) => ({ name: x.name, description: x.description ?? "" }))}
            onPick={(name) => setSkill(name, true)} />
        </>
      )}
    </Card>
  );
}

const SHORT_LIST = 6;

/** Something on for this session, with a remove button (also reachable by keyboard). */
function EnabledRow({ name, title, onRemove, children, removeLabel = `Remove ${name}` }: { name: string; title?: string; onRemove: () => void; children?: ReactNode; removeLabel?: string }) {
  return (
    <div className="flex items-center gap-2 py-0.5" title={title || undefined}>
      <span className="flex-1 min-w-0 truncate">{name}</span>
      {children}
      <button className="btn btn-ghost p-0.5 text-faint hover:text-text" title={removeLabel} aria-label={removeLabel} onClick={onRemove}><X size={13} /></button>
    </div>
  );
}

/** "Add …" button with a filterable list of what isn't on yet. */
function AddPicker({ label, options, onPick, empty, disabled = false }: { label: string; options: { name: string; description?: string }[]; onPick: (name: string) => void; empty: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const close = useCallback(() => { setOpen(false); setQ(""); setActive(0); }, []);
  const t = q.trim().toLowerCase();
  const shown = t ? options.filter((o) => o.name.toLowerCase().includes(t) || (o.description ?? "").toLowerCase().includes(t)) : options;
  const pick = (name: string) => { onPick(name); close(); };
  return (
    <div className="relative mt-0.5">
      <button className="flex items-center gap-1 text-[12.5px] text-action hover:underline py-0.5" disabled={disabled} aria-expanded={open} aria-haspopup="dialog" onClick={() => (open ? close() : setOpen(true))}>
        <Plus size={13} /> {label}
      </button>
      <Popover open={open && !disabled} onClose={close} label={label} className="w-full min-w-56 p-1.5">
        <input autoFocus className="input py-1 text-[13px] mb-1" placeholder="Filter" value={q} aria-label="Filter"
          onChange={(e) => { setQ(e.target.value); setActive(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, shown.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
            else if (e.key === "Enter" && shown[active]) { e.preventDefault(); pick(shown[active].name); }
          }} />
        <ul className="max-h-64 overflow-y-auto scroll-thin" role="listbox" aria-label={label}>
          {shown.length === 0 && <li className="px-2 py-1.5 text-[12.5px] text-muted">{options.length ? "No matches." : empty}</li>}
          {shown.map((o, i) => (
            <li key={o.name} role="option" aria-selected={i === active}>
              <button className={`w-full text-left px-2 py-1 rounded ${i === active ? "bg-sunken" : "hover:bg-sunken"}`} onMouseEnter={() => setActive(i)} onClick={() => pick(o.name)}>
                <span className="block truncate text-[13px]">{o.name}</span>
                {o.description && <span className="text-[11.5px] text-muted line-clamp-2">{o.description}</span>}
              </button>
            </li>
          ))}
        </ul>
      </Popover>
    </div>
  );
}

export function SharedToolsCard({ s }: { s: Session }) {
  const [busy, setBusy] = useState(false);
  const idle = s.status !== "running";
  const toggle = async (on: boolean) => {
    setBusy(true);
    try {
      await post(`/sessions/${s.id}/shared-tools`, { enabled: on });
      actions.toast(on ? "Shared tools on. Tool processes restarted." : "Shared tools off. Tool processes restarted.");
    } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Card id="shared" title="Shared tools" defaultOpen={false}>
      <label className={`flex items-start gap-2 ${idle ? "" : "opacity-60"}`}>
        <input type="checkbox" className="mt-1" checked={!!s.settings.shared_tools} disabled={!idle || busy} onChange={(e) => toggle(e.target.checked)} />
        <span>Let this session use MCP servers from my other machines</span>
      </label>
      <div className="text-[12px] text-faint mt-1 pl-5">
        Every job sent to them asks for your approval. Changing this restarts the session's tool processes, so it only applies while the session is idle.
      </div>
    </Card>
  );
}
