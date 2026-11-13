import { ArrowUp, Flag, Paperclip, Plug, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { get, patch, post, upload } from "../lib/api";
import { campaignsApi, parseWorkflowCommand, type ChainTemplate } from "../lib/campaigns";
import { actions, useStore, type Session } from "../lib/store";
import { parseTaskCommand, TASK_SUBCOMMANDS, taskCompletion, taskPick, taskSuggestions, type TaskHit } from "../lib/taskCodes";
import { Popover } from "./Popover";
import { UnityChip } from "./UnityChip";
import { modelLabel } from "./ui";

export type Att = { path: string; name: string; mime: string; size?: number; item_id?: string; text?: string };

import { EFFORTS, sessionCardRows } from "./ClaudeCard";

export { EFFORTS };
export const MODES: Record<string, string> = { ask: "Ask before edits", accept_edits: "Accept edits", plan: "Plan only" };

/** The new-session screen's composer: no session exists yet. The settings live on the screen
 *  (/model, /effort, /mode change them there), and sending creates the session with the first message. */
export type ComposerDraft = {
  set: (body: { model?: string; effort?: string; mode?: string }) => void;
  /** Create the session and send the first message; false when it didn't start (the text stays). */
  start: (text: string, skill: string | null, attachments: Att[]) => Promise<boolean>;
  /** The card's two control rows (location, folder, model; effort, mode). Tools and Send are added. */
  rows: [ReactNode, ReactNode];
  placeholder: string;
};
/** Commands that need a session that already exists. */
const SESSION_ONLY = ["/compact", "/clear", "/workflow"];
const WORKFLOW_UNAVAILABLE = "Workflows run on the built-in loop with an API key, so they aren't available in Claude subscription sessions.";

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

/** The composer's skills popover: type to filter (name or description), ↑ ↓ and Enter to pick.
 *  Workflows (chain templates that apply to the session folder) come first. */
function SkillPicker({ open, skills, onPick, onClose, workflows = [], onPickWorkflow }: {
  open: boolean; skills: SkillInfo[]; onPick: (name: string) => void; onClose: () => void;
  workflows?: ChainTemplate[]; onPickWorkflow?: (t: ChainTemplate) => void;
}) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const list = useRef<HTMLUListElement>(null);
  useEffect(() => { if (!open) { setQ(""); setActive(0); } }, [open]);
  const t = q.trim().toLowerCase();
  const shown = t ? skills.filter((s) => s.name.toLowerCase().includes(t) || shortDesc(s).toLowerCase().includes(t)) : skills;
  const featured = t ? [] : shown.filter((s) => FEATURED[s.name]);
  const rest = t ? shown : shown.filter((s) => !FEATURED[s.name]);
  const flows = onPickWorkflow ? (t ? workflows.filter((w) => w.title.toLowerCase().includes(t) || w.id.includes(t) || w.summary.toLowerCase().includes(t)) : workflows) : [];
  const ordered = [...featured, ...rest];
  const total = flows.length + ordered.length;
  const pickAt = (i: number) => { if (i < flows.length) onPickWorkflow?.(flows[i]); else if (ordered[i - flows.length]) onPick(ordered[i - flows.length].name); };
  useEffect(() => { list.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" }); }, [active]);
  const flowRow = (w: ChainTemplate, i: number) => (
    <li key={`wf:${w.id}`} role="option" aria-selected={i === active} data-i={i}>
      <button className={`w-full text-left px-3 py-1.5 ${i === active ? "bg-sunken" : "hover:bg-sunken"}`} onMouseEnter={() => setActive(i)} onClick={() => onPickWorkflow?.(w)}>
        <span className="flex items-center gap-1.5"><Flag size={12} className="text-action" />{w.title}</span>
        <span className="text-[12px] text-muted line-clamp-2">{w.summary || w.phases.map((p) => p.name).join(" → ")}</span>
      </button>
    </li>
  );
  const row = (s: SkillInfo) => {
    const i = flows.length + ordered.indexOf(s);
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
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, total - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
            else if (e.key === "Enter" && active < total) { e.preventDefault(); pickAt(active); }
          }} />
      </div>
      <ul ref={list} className="max-h-[min(60vh,460px)] overflow-y-auto scroll-thin py-1" role="listbox" aria-label="Skills">
        {flows.length > 0 && <li className="label px-3 pt-1 pb-0.5" role="presentation">Workflows</li>}
        {flows.map(flowRow)}
        {flows.length > 0 && ordered.length > 0 && <li className="my-1 border-t border-line" role="presentation" />}
        {ordered.length === 0 && flows.length === 0 && <li className="px-3 py-2 text-muted">{skills.length ? "No matching skills." : "No skills installed."}</li>}
        {featured.length > 0 && <li className="label px-3 pt-1 pb-0.5" role="presentation">Featured</li>}
        {featured.map(row)}
        {rest.length > 0 && !t && featured.length > 0 && <li className="my-1 border-t border-line" role="presentation" />}
        {rest.length > 0 && !t && <li className="label px-3 pt-1 pb-0.5" role="presentation">All skills</li>}
        {rest.map(row)}
      </ul>
    </Popover>
  );
}

export function Composer({ session, running, draft }: { session: Session; running: boolean; draft?: ComposerDraft }) {
  const appState = useStore((s) => s.appState);
  const [text, setText] = useState("");
  const [atts, setAtts] = useState<Att[]>([]);
  const drafts = useStore((s) => s.drafts[session.id]);
  useEffect(() => {
    if (drafts?.length) {
      const files: Att[] = [];
      const texts: string[] = [];
      for (const d of drafts) {
        if ("kind" in d && d.kind === "text") texts.push(d.text);
        else if ("path" in d) files.push(d);
      }
      if (texts.length) setText(texts.join("\n\n"));
      if (files.length) setAtts((a) => [...a, ...files]);
      actions.setDrafts(session.id, []);
    }
  }, [drafts, session.id]);
  const skill = useStore((s) => s.skillChips[session.id] ?? null);
  const setSkill = (name: string | null) => actions.setSkillChip(session.id, name);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [skillMenu, setSkillMenu] = useState(false);
  // Workflows (chain templates for this folder) and the one picked for the next message.
  const [workflows, setWorkflows] = useState<ChainTemplate[]>([]);
  const [workflow, setWorkflow] = useState<ChainTemplate | null>(null);
  const subscription = !!draft || session.harness === "claude_code";
  const loadWorkflows = () => {
    if (!session.folder || subscription) return setWorkflows([]);
    campaignsApi.chains(session.folder, "chain").then((r) => setWorkflows(r.templates.filter((t) => t.kinds.includes("chain")))).catch(() => setWorkflows([]));
  };
  useEffect(() => { setWorkflow(null); loadWorkflows(); }, [session.id, session.folder, subscription]);
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
    { cmd: "/workflow", hint: "Run a workflow (phases with checks) in this session", args: workflows.map((w) => w.id) },
  ].filter((c) => (!draft || !SESSION_ONLY.includes(c.cmd)) && !(subscription && c.cmd === "/workflow")), [modelChoices, skills, workflows, !!draft, subscription]);
  /** PATCH the session, or on the new-session screen change its settings there. */
  const update = async (body: { model?: string; effort?: string; mode?: string }) => {
    if (draft) draft.set(body);
    else await patch(`/sessions/${session.id}`, body);
  };

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
    if (c === "/workflow" && /^\/workflow \S+\s/.test(text)) return []; // the workflow is chosen; the rest is the request
    const cmd = commands.find((x) => x.cmd === c);
    // /model also matches real names ("/model sol" finds gpt-6.1-sol and codex.standard); the value stays the ID or tier key.
    const match = (a: string) => a.startsWith(arg) || (c === "/model" && !!arg && modelLabel(a).toLowerCase().includes(arg.toLowerCase()));
    const hint = (a: string) => (c === "/mode" ? MODES[a] : c === "/model" ? modelLabel(a) : c === "/skill" ? shortDesc(skills.find((s) => s.name === a)!)
      : c === "/workflow" ? workflows.find((w) => w.id === a)?.title ?? "" : "");
    return (cmd?.args ?? []).filter(match).slice(0, 12).map((a) => ({ value: `${c} ${a}`, label: a, hint: hint(a) }));
  }, [text, commands, taskHits, taskCols, skills, workflows]);

  const addFiles = async (files: FileList | File[]) => {
    setBusy(true);
    try {
      // The new-session screen has no session yet: the files are filed under it when the first message is sent.
      const ups = await Promise.all(Array.from(files).map((f) => upload(f, draft ? undefined : session.id)));
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
    if (cmd === "/workflow" && subscription) return actions.toast(WORKFLOW_UNAVAILABLE, "error"), true;
    if (draft && SESSION_ONLY.includes(cmd)) return actions.toast(`${cmd} works in a session that has started. Send a message first.`, "error"), true;
    try {
      switch (cmd) {
        case "/model":
          if (!arg) return actions.toast(`Model: ${modelLabel(session.model)}`), true;
          await update({ model: arg });
          actions.toast(`Model set to ${modelLabel(arg)}`);
          return true;
        case "/effort":
          if (!EFFORTS.includes(arg)) return actions.toast(`Effort must be one of: ${EFFORTS.join(", ")}`, "error"), true;
          await update({ effort: arg });
          actions.toast(["xhigh", "max"].includes(arg) ? `Effort set to ${arg}. You'll be asked to approve it on the next turn.` : `Effort set to ${arg}`);
          return true;
        case "/mode":
          if (!MODES[arg]) return actions.toast("Mode must be ask, accept_edits or plan", "error"), true;
          await update({ mode: arg });
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
        case "/workflow": {
          const wf = parseWorkflowCommand(line.trim());
          const t = wf && workflows.find((w) => w.id === wf.id);
          if (!session.folder) return actions.toast("Workflows need a session folder; pick one first.", "error"), true;
          if (!wf?.id || !t) return actions.toast(wf?.id ? `No workflow named ${wf.id} for this folder` : `Usage: /workflow <${workflows.map((w) => w.id).join(" | ") || "id"}> [request]`, "error"), true;
          if (!wf.request) return setWorkflow(t), true; // attach the chip; the request follows
          await startWorkflow(t, wf.request);
          return true;
        }
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
    if (draft && (c.kind === "open" || c.kind === "link")) {
      actions.toast("Start the session first (send a message), then bring the task into it.", "error");
      return true;
    }
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
      if (draft) {
        if (!(await draft.start(t, sk, atts))) return;
      } else await post(`/sessions/${session.id}/messages`, { text: t, attachments: atts, ...(sk ? { skill: sk } : {}) });
      setText("");
      setAtts([]);
      setSkill(null);
    } catch (e: any) {
      actions.toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  /** Start a chain in this session (POST /api/campaigns kind chain), then send the request. */
  const startWorkflow = async (t: ChainTemplate, request: string) => {
    setBusy(true);
    try {
      await campaignsApi.create({ template: t.id, kind: "chain", session_id: session.id, request });
    } catch (e: any) {
      setBusy(false);
      actions.toast(e.message, "error");
      return;
    }
    setBusy(false);
    setWorkflow(null);
    await sendMessage(`Run the ${t.title} workflow.` + (request ? `\n\n${request}` : ""), skill);
  };

  const send = async () => {
    const t = text.trim();
    if ((!t && !atts.length && !skill && !workflow) || busy || running) return;
    if (workflow && !(t.startsWith("/") && !t.startsWith("/workflow"))) {
      const wf = t.startsWith("/workflow") ? parseWorkflowCommand(t) : null;
      await startWorkflow(workflow, wf ? wf.request : t);
      return;
    }
    if (t.startsWith("/") && !atts.length && (await runSlash(t))) {
      setText("");
      return;
    }
    await sendMessage(t, skill);
  };

  /** Take an autocomplete suggestion; a complete `/skill <name>` attaches the chip right away. */
  const choose = (value: string) => {
    const w = value.match(/^\/workflow (\S+)$/);
    const wt = w && workflows.find((x) => x.id === w[1]);
    if (wt) {
      setWorkflow(wt);
      setText("");
      setSel(0);
      return;
    }
    const m = value.match(/^\/skill (\S+)$/);
    if (m && skills.some((s) => s.name === m[1])) {
      setSkill(m[1]);
      setText("");
    } else setText(value);
    setSel(0);
  };

  const suggestionList = suggestions.length > 0 && (
    <ul className={`absolute ${draft ? "top-full mt-1" : "bottom-full mb-1"} left-0 w-[min(600px,100%)] rounded-md border border-line bg-raised shadow-lg py-1 text-[13px] z-10`} role="listbox">
      {suggestions.map((s, i) => (
        <li key={s.value} role="option" aria-selected={i === sel}>
          <button className={`w-full text-left px-3 py-1 flex items-baseline gap-3 ${i === sel ? "bg-sunken" : ""}`} title={s.hint || undefined}
            onMouseDown={(e) => { e.preventDefault(); choose(s.value); ta.current?.focus(); }}>
            <span className="font-mono shrink-0 max-w-[45%] truncate">{s.label}</span><span className="text-muted min-w-0 flex-1 truncate">{s.hint}</span>
          </button>
        </li>
      ))}
    </ul>
  );
  const chips = (atts.length > 0 || skill || workflow) && (
    <div className={`flex flex-wrap gap-1.5 ${draft ? "mb-1.5" : "mb-2"}`}>
      {workflow && (
        <span className="chip text-text" title={`Sending starts the ${workflow.title} workflow in this session: ${workflow.phases.map((p) => p.name).join(" → ")}`}>
          <Flag size={12} className="text-action" />Workflow: {workflow.title}
          <button aria-label={`Remove workflow ${workflow.title}`} onClick={() => setWorkflow(null)}><X size={12} /></button>
        </span>
      )}
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
  );
  const openSkills = () => {
    if (skillMenu) return setSkillMenu(false);
    loadSkills();
    loadWorkflows();
    setSkillMenu(true);
  };
  const skillPicker = (
    <SkillPicker open={skillMenu} skills={skills} onClose={closeSkillMenu} workflows={subscription ? [] : workflows}
      onPickWorkflow={(w) => { setWorkflow(w); setSkillMenu(false); ta.current?.focus(); }}
      onPick={(n) => { setSkill(n); setSkillMenu(false); ta.current?.focus(); }} />
  );
  const canSend = !(busy || running || (!text.trim() && !atts.length && !skill && !workflow));
  // The Claude-style card: the new-session screen, and the chat box of a Claude Code session.
  const card = draft ? { rows: draft.rows, placeholder: draft.placeholder }
    : session.harness === "claude_code" ? { rows: sessionCardRows(session), placeholder: "Reply to Claude, or type / for commands and skills…" } : null;
  const textarea = (
    <textarea
      id="composer"
      ref={ta}
      rows={draft ? 2 : 1}
      value={text}
      aria-label={draft ? "Describe a task" : undefined}
      placeholder={running ? "Agent is working… (Stop to interrupt)" : workflow ? `What should the ${workflow.title} workflow do?` : skill ? `What should ${skill} work on? (or send as is)` : card ? card.placeholder : "Message the agent, or / for commands"}
      className={card ? `w-full resize-none bg-transparent outline-none focus-visible:outline-none px-1 py-0.5 ${draft ? "min-h-[52px]" : "min-h-[28px]"} max-h-72 text-[15px] leading-[1.6] placeholder:text-faint`
        : "flex-1 resize-none bg-transparent outline-none focus-visible:outline-none py-1 max-h-60 leading-6"}
      onChange={(e) => { setText(e.target.value); setSel(0); e.target.style.height = "auto"; e.target.style.height = `${Math.min(e.target.scrollHeight, card ? 288 : 240)}px`; }}
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
          if (suggestions.length && suggestions[sel].value.trim() !== text.trim() && (pickModel || pickTask || !text.includes(" ") || /^\/(skill|workflow) \S*$/.test(text))) choose(suggestions[sel].value);
          else send();
        }
      }}
    />
  );

  if (card) {
    // The editor, then the controls (paperclip, place, model; effort, mode, Tools), then Send.
    const box = (
      <div className={`relative rounded-[20px] border border-line surface-raised px-4 pt-3.5 pb-2.5 shadow-[0_1px_2px_rgb(0_0_0/0.04),0_6px_24px_-8px_rgb(0_0_0/0.10)] focus-within:border-[color-mix(in_srgb,var(--action)_35%,var(--line))] ${drag ? "outline-2 outline-dashed outline-action -outline-offset-4" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); }}>
        {chips}
        {textarea}
        {draft && suggestionList}
        <div className="mt-2 flex items-center gap-1 min-w-0">
          <button className="btn btn-ghost px-2 shrink-0" title="Attach files (images, PDFs, text)" aria-label="Attach files" onClick={() => fileIn.current?.click()}><Paperclip size={15} /></button>
          <input ref={fileIn} type="file" multiple hidden onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
          {card.rows[0]}
        </div>
        <div className="mt-1 flex items-center gap-1 min-w-0">
          {card.rows[1]}
          <div className="relative">
            <button className={`btn btn-ghost gap-1.5 px-2 text-[14px] ${skill || workflow ? "text-action" : ""}`} title="Skills for this message" aria-label="Tools"
              aria-haspopup="dialog" aria-expanded={skillMenu} onClick={openSkills}><Plug size={15} aria-hidden />Tools</button>
            {skillPicker}
          </div>
          {!draft && <UnityChip sessionId={session.id} />}
          <button className="ml-auto shrink-0 size-9 rounded-full inline-flex items-center justify-center bg-action text-action-text transition hover:brightness-110 disabled:opacity-35 disabled:hover:brightness-100"
            disabled={!canSend} onClick={send} aria-label="Send" title={draft ? "Start the session (Enter)" : "Send (Enter)"}><ArrowUp size={18} strokeWidth={2.25} /></button>
        </div>
      </div>
    );
    if (draft) return box;
    return (
      <div className="shrink-0 surface px-4 pt-2 pb-4">
        <div className="max-w-[780px] mx-auto relative">
          {suggestionList}
          {box}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`shrink-0 border-t border-line surface px-4 py-3 ${drag ? "outline-2 outline-dashed outline-action -outline-offset-4" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); }}
    >
      <div className="max-w-[780px] mx-auto relative">
        {suggestionList}
        {chips}
        <div className="flex items-end gap-2 rounded-lg border border-line surface-raised px-2 py-1.5 focus-within:border-action">
          <button className="btn btn-ghost px-1.5 mb-0.5" title="Attach files" aria-label="Attach files" onClick={() => fileIn.current?.click()}><Paperclip size={16} /></button>
          <div className="relative mb-0.5">
            <button className={`btn btn-ghost px-1.5 ${skill ? "text-action" : ""}`} title="Use a skill" aria-label="Use a skill" aria-haspopup="dialog" aria-expanded={skillMenu}
              onClick={openSkills}><Sparkles size={16} /></button>
            {skillPicker}
          </div>
          <input ref={fileIn} type="file" multiple hidden onChange={(e) => e.target.files && addFiles(e.target.files)} />
          {textarea}
          <button className="btn btn-primary px-2 mb-0.5" disabled={!canSend} onClick={send} aria-label="Send"><ArrowUp size={16} /></button>
        </div>
        <div className="mt-1 flex items-center gap-2 text-[11.5px] text-faint">
          <span className="flex-1 min-w-0">{MODES[session.mode] ?? session.mode} · Enter to send, Shift+Enter for a new line · drop files to attach</span>
          <UnityChip sessionId={session.id} />
        </div>
      </div>
    </div>
  );
}
