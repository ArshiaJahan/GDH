import { ArrowUp, Paperclip, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { get, patch, post, upload } from "../lib/api";
import { actions, useStore, type Session } from "../lib/store";
import { parseTaskCommand, TASK_SUBCOMMANDS, taskCompletion, taskPick, taskSuggestions, type TaskHit } from "../lib/taskCodes";
import { Popover } from "./Popover";
import { modelLabel } from "./ui";

type Att = { path: string; name: string; mime: string; size?: number; item_id?: string; text?: string };

const EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"];
const MODES: Record<string, string> = { ask: "Ask before edits", accept_edits: "Accept edits", plan: "Plan only" };

type SkillInfo = { name: string; description: string; featured?: boolean };
/** Short menu blurbs for the built-in skills pinned at the top of the skills menu. */
const FEATURED: Record<string, string> = {
  graphify: "Turn a folder, repo or docs into a queryable knowledge graph",
  "grill-me": "A relentless interview to sharpen a plan or design",
  "claude-handoff": "Hand this conversation to a fresh background agent",
  "game-designer": "Design, critique and balance games and game features",
  "cost-effective-claude-delegation": "Do a task at the lowest total cost",
  "high-performance-claude-delegation": "Parallel Opus subagents for speed and quality",
  "unity-router": "Unity game: pick the right Unity skills for the task",
};
const shortDesc = (s: SkillInfo) => FEATURED[s.name] ?? s.description;

/** The composer's skills popover: type to filter (name or description), ↑ ↓ and Enter to pick. */
function SkillPicker({ open, skills, onPick, onClose }: { open: boolean; skills: SkillInfo[]; onPick: (name: string) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const list = useRef<HTMLUListElement>(null);
  useEffect(() => { if (!open) { setQ(""); setActive(0); } }, [open]);
  const t = q.trim().toLowerCase();
  const shown = t ? skills.filter((s) => s.name.toLowerCase().includes(t) || shortDesc(s).toLowerCase().includes(t)) : skills;
  const featured = t ? [] : shown.filter((s) => FEATURED[s.name]);
  const rest = t ? shown : shown.filter((s) => !FEATURED[s.name]);
  const ordered = [...featured, ...rest];
  useEffect(() => { list.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" }); }, [active]);
  const row = (s: SkillInfo) => {
    const i = ordered.indexOf(s);
    return (
      <li key={s.name} role="option" aria-selected={i === active} data-i={i}>
        <button className={`w-full text-left px-3 py-1.5 ${i === active ? "bg-sunken" : "hover:bg-sunken"}`} onMouseEnter={() => setActive(i)} onClick={() => onPick(s.name)}>
          <span className="block">{s.name}</span>
          <span className="text-[12px] text-muted line-clamp-2">{shortDesc(s)}</span>
        </button>
      </li>
    );
  };
  return (
    <Popover open={open} onClose={onClose} above label="Use a skill" className="w-[360px] max-w-[calc(100vw-32px)] text-[13px] flex flex-col">
      <div className="p-1.5 border-b border-line">
        <input autoFocus className="input py-1 text-[13px]" placeholder="Filter skills" value={q} aria-label="Filter skills"
          onChange={(e) => { setQ(e.target.value); setActive(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, ordered.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
            else if (e.key === "Enter" && ordered[active]) { e.preventDefault(); onPick(ordered[active].name); }
          }} />
      </div>
      <ul ref={list} className="max-h-[min(60vh,460px)] overflow-y-auto scroll-thin py-1" role="listbox" aria-label="Skills">
        {ordered.length === 0 && <li className="px-3 py-2 text-muted">{skills.length ? "No matching skills." : "No skills installed."}</li>}
        {featured.length > 0 && <li className="label px-3 pt-1 pb-0.5" role="presentation">Featured</li>}
        {featured.map(row)}
        {rest.length > 0 && !t && featured.length > 0 && <li className="my-1 border-t border-line" role="presentation" />}
        {rest.length > 0 && !t && <li className="label px-3 pt-1 pb-0.5" role="presentation">All skills</li>}
        {rest.map(row)}
      </ul>
    </Popover>
  );
}

export function Composer({ session, running }: { session: Session; running: boolean }) {
  const appState = useStore((s) => s.appState);
  const [text, setText] = useState("");
  const [atts, setAtts] = useState<Att[]>([]);
  const drafts = useStore((s) => s.drafts[session.id]);
  useEffect(() => {
    if (drafts?.length) {
      setAtts((a) => [...a, ...(drafts as Att[])]);
      useStore.setState((x) => ({ drafts: { ...x.drafts, [session.id]: [] } }));
    }
  }, [drafts, session.id]);
  const skill = useStore((s) => s.skillChips[session.id] ?? null);
  const setSkill = (name: string | null) => actions.setSkillChip(session.id, name);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [skillMenu, setSkillMenu] = useState(false);
  const closeSkillMenu = useCallback(() => setSkillMenu(false), []);
  const loadSkills = () => get("/skills").then((r) => {
    const all: SkillInfo[] = r.skills;
    const pinned = Object.keys(FEATURED).map((n) => all.find((s) => s.name === n)).filter(Boolean) as SkillInfo[];
    setSkills([...pinned, ...all.filter((s) => !FEATURED[s.name]).sort((a, b) => a.name.localeCompare(b.name))]);
  }).catch(() => {});
  useEffect(() => { loadSkills(); }, []);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [sel, setSel] = useState(0);
  const ta = useRef<HTMLTextAreaElement>(null);
  const fileIn = useRef<HTMLInputElement>(null);

  const modelChoices = useMemo(() => [...Object.keys(appState?.tiers ?? {}), ...Object.keys(appState?.models ?? {})], [appState]);

  const commands = useMemo(() => [
    { cmd: "/model", hint: "Switch model or tier", args: modelChoices },
    { cmd: "/effort", hint: "Set thinking effort", args: EFFORTS },
    { cmd: "/mode", hint: "Ask before edits, accept edits, or plan only", args: Object.keys(MODES) },
    { cmd: "/compact", hint: "Summarize older turns to free context", args: [] },
    { cmd: "/clear", hint: "Start fresh; history stays visible", args: [] },
    { cmd: "/skill", hint: "Use a skill in this message", args: skills.map((s) => s.name) },
    { cmd: "/task", hint: "Task board: new, <code>, move, done, list, link", args: TASK_SUBCOMMANDS.map(([s]) => s) },
  ], [modelChoices, skills]);

  // /task autocomplete: task codes from the board (matched by the backend) and its column names.
  const [taskHits, setTaskHits] = useState<TaskHit[]>([]);
  const [taskCols, setTaskCols] = useState<string[]>([]);
  const completion = taskCompletion(text);
  const codeQuery = completion && completion.field !== "column" ? completion.partial : null;
  useEffect(() => {
    if (codeQuery === null) return;
    const t = setTimeout(() => get<TaskHit[]>(`/tasks/suggest?q=${encodeURIComponent(codeQuery)}&limit=8`).then(setTaskHits).catch(() => setTaskHits([])), 100);
    return () => clearTimeout(t);
  }, [codeQuery]);
  const wantsColumns = completion?.field === "column";
  useEffect(() => {
    if (wantsColumns && !taskCols.length) get("/tasks/boards").then((r) => setTaskCols(r.boards.flatMap((b: any) => b.columns.map((c: any) => c.name)))).catch(() => {});
  }, [wantsColumns]); // eslint-disable-line react-hooks/exhaustive-deps

  const suggestions = useMemo(() => {
    if (!text.startsWith("/") || text.includes("\n")) return [];
    const [c, arg = ""] = text.split(/\s+/, 2);
    const hasSpace = /\s/.test(text);
    if (!hasSpace) return commands.filter((x) => x.cmd.startsWith(c)).map((x) => ({ value: x.cmd + (x.args.length ? " " : ""), label: x.cmd, hint: x.hint }));
    if (c === "/skill" && /^\/skill \S+\s/.test(text)) return []; // the skill is chosen; the rest is the message
    if (c === "/task") return taskSuggestions(text, taskHits, taskCols);
    const cmd = commands.find((x) => x.cmd === c);
    // /model also matches real names ("/model sol" finds gpt-6.1-sol and codex.standard); the value stays the ID or tier key.
    const match = (a: string) => a.startsWith(arg) || (c === "/model" && !!arg && modelLabel(a).toLowerCase().includes(arg.toLowerCase()));
    const hint = (a: string) => (c === "/mode" ? MODES[a] : c === "/model" ? modelLabel(a) : c === "/skill" ? shortDesc(skills.find((s) => s.name === a)!) : "");
    return (cmd?.args ?? []).filter(match).slice(0, 12).map((a) => ({ value: `${c} ${a}`, label: a, hint: hint(a) }));
  }, [text, commands, taskHits, taskCols]);

  const addFiles = async (files: FileList | File[]) => {
    setBusy(true);
    try {
      const ups = await Promise.all(Array.from(files).map((f) => upload(f, session.id)));
      setAtts((a) => [...a, ...ups]);
      const notes = ups.map((u) => u.note).filter(Boolean); // e.g. a HEIC photo converted to JPEG for the model
      if (notes.length) actions.toast(notes.join(" "));
    } catch (e: any) {
      actions.toast(`Upload failed: ${e.message}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const runSlash = async (line: string): Promise<boolean> => {
    const [cmd, ...rest] = line.trim().split(/\s+/);
    const arg = rest.join(" ");
    try {
      switch (cmd) {
        case "/model":
          if (!arg) return actions.toast(`Model: ${modelLabel(session.model)}`), true;
          await patch(`/sessions/${session.id}`, { model: arg });
          actions.toast(`Model set to ${modelLabel(arg)}`);
          return true;
        case "/effort":
          if (!EFFORTS.includes(arg)) return actions.toast(`Effort must be one of: ${EFFORTS.join(", ")}`, "error"), true;
          await patch(`/sessions/${session.id}`, { effort: arg });
          actions.toast(["xhigh", "max"].includes(arg) ? `Effort set to ${arg}. You'll be asked to approve it on the next turn.` : `Effort set to ${arg}`);
          return true;
        case "/mode":
          if (!MODES[arg]) return actions.toast("Mode must be ask, accept_edits or plan", "error"), true;
          await patch(`/sessions/${session.id}`, { mode: arg });
          actions.toast(`Mode: ${MODES[arg]}`);
          return true;
        case "/compact": {
          actions.toast("Compacting older turns…");
          const r = await post(`/sessions/${session.id}/compact`);
          actions.toast(r.compacted ? `Summarized ${r.compacted} older messages.` : r.message);
          await actions.reloadMessages(session.id);
          return true;
        }
        case "/clear":
          await post(`/sessions/${session.id}/clear`);
          return true;
        case "/task":
          return await runTask(line);
        case "/skill": {
          const [name, ...more] = rest;
          if (!name || !skills.some((s) => s.name === name)) return actions.toast(name ? `No skill named ${name}` : "Usage: /skill <name> [message]", "error"), true;
          if (!more.length) return setSkill(name), true; // attach the chip; the message follows
          await sendMessage(more.join(" "), name);
          return true;
        }
      }
    } catch (e: any) {
      actions.toast(e.message, "error");
      return true;
    }
    return false;
  };

  /** /task …: the board's commands (see lib/taskCodes.ts parseTaskCommand). */
  const runTask = async (line: string): Promise<boolean> => {
    const c = parseTaskCommand(line);
    const open = (code: string) => ({ label: "Open", run: () => actions.go("board", { task: code }) });
    switch (c.kind) {
      case "board":
        actions.go("board");
        break;
      case "list":
        actions.go("board", { q: c.query });
        break;
      case "error":
        actions.toast(c.message, "error");
        break;
      case "new": {
        const t = await post("/tasks/items", { title: c.title, labels: c.labels, priority: c.priority, column: c.column });
        actions.toast(`Created ${t.code} in ${t.column}`, "info", open(t.code));
        break;
      }
      case "open": {
        const t = await post(`/tasks/items/${c.code}/attach`, { session_id: session.id });
        actions.toast(`${t.code} is now in this conversation and linked to this session`, "info", open(t.code));
        break;
      }
      case "move": {
        const t = await patch(`/tasks/items/${c.code}`, { column: c.column });
        actions.toast(`${t.code} moved to ${t.column}`, "info", open(t.code));
        break;
      }
      case "done": {
        const t = await post(`/tasks/items/${c.code}/done`);
        actions.toast(`${t.code} moved to ${t.column}`, "info", open(t.code));
        break;
      }
      case "link": {
        const t = await post(`/tasks/items/${c.code}/sessions`, { session_id: session.id });
        actions.toast(`This session is linked to ${t.code}`, "info", open(t.code));
        break;
      }
    }
    return true;
  };

  const sendMessage = async (t: string, sk: string | null) => {
    setBusy(true);
    try {
      await post(`/sessions/${session.id}/messages`, { text: t, attachments: atts, ...(sk ? { skill: sk } : {}) });
      setText("");
      setAtts([]);
      setSkill(null);
    } catch (e: any) {
      actions.toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    const t = text.trim();
    if ((!t && !atts.length && !skill) || busy || running) return;
    if (t.startsWith("/") && !atts.length && (await runSlash(t))) {
      setText("");
      return;
    }
    await sendMessage(t, skill);
  };

  /** Take an autocomplete suggestion; a complete `/skill <name>` attaches the chip right away. */
  const choose = (value: string) => {
    const m = value.match(/^\/skill (\S+)$/);
    if (m && skills.some((s) => s.name === m[1])) {
      setSkill(m[1]);
      setText("");
    } else setText(value);
    setSel(0);
  };

  return (
    <div
      className={`shrink-0 border-t border-line surface px-4 py-3 ${drag ? "outline-2 outline-dashed outline-action -outline-offset-4" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); }}
    >
      <div className="max-w-[780px] mx-auto relative">
        {suggestions.length > 0 && (
          <ul className="absolute bottom-full mb-1 left-0 w-[min(600px,100%)] rounded-md border border-line bg-raised shadow-lg py-1 text-[13px] z-10" role="listbox">
            {suggestions.map((s, i) => (
              <li key={s.value} role="option" aria-selected={i === sel}>
                <button className={`w-full text-left px-3 py-1 flex items-baseline gap-3 ${i === sel ? "bg-sunken" : ""}`} title={s.hint || undefined}
                  onMouseDown={(e) => { e.preventDefault(); choose(s.value); ta.current?.focus(); }}>
                  <span className="font-mono shrink-0 max-w-[45%] truncate">{s.label}</span><span className="text-muted min-w-0 flex-1 truncate">{s.hint}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {(atts.length > 0 || skill) && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {skill && (
              <span className="chip text-text" title="This message invokes the skill; it stays on for the session">
                <Sparkles size={12} className="text-action" />{skill}
                <button aria-label={`Remove skill ${skill}`} onClick={() => setSkill(null)}><X size={12} /></button>
              </span>
            )}
            {atts.map((a, i) => (
              <span key={i} className="chip">{a.name}<button aria-label={`Remove ${a.name}`} onClick={() => setAtts(atts.filter((_, j) => j !== i))}><X size={12} /></button></span>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2 rounded-lg border border-line surface-raised px-2 py-1.5 focus-within:border-action">
          <button className="btn btn-ghost px-1.5 mb-0.5" title="Attach files" aria-label="Attach files" onClick={() => fileIn.current?.click()}><Paperclip size={16} /></button>
          <div className="relative mb-0.5">
            <button className={`btn btn-ghost px-1.5 ${skill ? "text-action" : ""}`} title="Use a skill" aria-label="Use a skill" aria-haspopup="dialog" aria-expanded={skillMenu}
              onClick={() => {
                if (skillMenu) return setSkillMenu(false);
                loadSkills();
                setSkillMenu(true);
              }}><Sparkles size={16} /></button>
            <SkillPicker open={skillMenu} skills={skills} onClose={closeSkillMenu}
              onPick={(n) => { setSkill(n); setSkillMenu(false); ta.current?.focus(); }} />
          </div>
          <input ref={fileIn} type="file" multiple hidden onChange={(e) => e.target.files && addFiles(e.target.files)} />
          <textarea
            id="composer"
            ref={ta}
            rows={1}
            value={text}
            placeholder={running ? "Agent is working… (Stop to interrupt)" : skill ? `What should ${skill} work on? (or send as is)` : "Message the agent, or / for commands"}
            className="flex-1 resize-none bg-transparent outline-none focus-visible:outline-none py-1 max-h-60 leading-6"
            onChange={(e) => { setText(e.target.value); setSel(0); e.target.style.height = "auto"; e.target.style.height = `${Math.min(e.target.scrollHeight, 240)}px`; }}
            onPaste={(e) => { if (e.clipboardData.files.length) { e.preventDefault(); addFiles(e.clipboardData.files); } }}
            onKeyDown={(e) => {
              if (suggestions.length && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
                e.preventDefault();
                setSel((sel + (e.key === "ArrowDown" ? 1 : suggestions.length - 1)) % suggestions.length);
              } else if (suggestions.length && e.key === "Tab") {
                e.preventDefault();
                choose(suggestions[sel].value);
              } else if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                // `/model sol`: a partial name or label picks the highlighted model instead of setting "sol".
                const modelArg = text.trim().match(/^\/model\s+(.+)$/)?.[1];
                const pickModel = modelArg !== undefined && !modelChoices.includes(modelArg);
                const pickTask = /^\/task\s/.test(text) && taskPick(text, taskCols); // a half-typed task code or column
                if (suggestions.length && suggestions[sel].value.trim() !== text.trim() && (pickModel || pickTask || !text.includes(" ") || /^\/skill \S*$/.test(text))) choose(suggestions[sel].value);
                else send();
              }
            }}
          />
          <button className="btn btn-primary px-2 mb-0.5" disabled={busy || running || (!text.trim() && !atts.length && !skill)} onClick={send} aria-label="Send"><ArrowUp size={16} /></button>
        </div>
        <div className="mt-1 text-[11.5px] text-faint">{MODES[session.mode] ?? session.mode} · Enter to send, Shift+Enter for a new line · drop files to attach</div>
      </div>
    </div>
  );
}
