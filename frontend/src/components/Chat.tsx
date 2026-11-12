import { Archive, Brain, ChevronRight, Clock, GitBranch, PanelRight, Sparkles, Square, Trash2, TriangleAlert, Wrench } from "lucide-react";
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { fileUrl, inTauri, post } from "../lib/api";
import { MdLite } from "../lib/mdlite";
import { openLocalFile } from "../lib/native";
import { sessionActions } from "../lib/sessions";
import { actions, useStore, type AgentStatus, type Block, type Msg } from "../lib/store";
import { ApprovalCard } from "./ApprovalCard";
import { Composer } from "./Composer";
import { SafeMarkdown } from "./SafeMarkdown";
import { NoKeyNotice, SetupChecklist } from "./SetupChecklist";
import { metaRow } from "./rows";
import { SessionLimitBanner } from "./LimitsBanner";
import { SessionTasks } from "./SessionTasks";
import { toolRenderers } from "./toolRenderers";
import { EffortMeter, ProviderDot, fmtUsd, modelLabel, tiersOf, useModelCatalog } from "./ui";

const EMPTY: Msg[] = [];
const STOPPABLE_JOBS = new Set(["subagent", "codex_cli", "command"]);

/** "Rate limited, retrying in Ns" with a live countdown. */
function StatusLine({ s }: { s: AgentStatus }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);
  const left = s.until ? Math.max(0, Math.ceil(s.until - now / 1000)) : null;
  const text = s.kind === "rate_limit" && left != null ? `Rate limited, retrying in ${left}s` : s.text;
  return (
    <div role="status" className="my-2 flex items-center gap-1.5 text-[13px] text-warn">
      <Clock size={13} /> {text}
      {s.attempt != null && s.max_attempts != null && <span className="text-faint">(retry {s.attempt} of {s.max_attempts})</span>}
    </div>
  );
}

export function Chat() {
  useModelCatalog();
  const sid = useStore((s) => s.currentId);
  const session = useStore((s) => s.sessions.find((x) => x.id === sid));
  const messages = useStore((s) => (sid ? s.messages[sid] : undefined)) ?? EMPTY;
  const streaming = useStore((s) => (sid ? s.streaming[sid] : null));
  const approvals = useStore((s) => s.approvals);
  const sidePanelOpen = useStore((s) => s.sidePanelOpen);
  const agentStatus = useStore((s) => (sid ? s.agentStatus[sid] : null));
  // Background work this session started (subagents, Codex CLI, commands) keeps Stop available.
  const backgroundBusy = useStore((s) => Object.values(s.jobs).some((j) => j.session_id === sid && STOPPABLE_JOBS.has(j.kind) && (j.status === "running" || j.status === "queued")));
  const paging = useStore((s) => (sid ? s.paging[sid] : undefined));
  const scroller = useRef<HTMLDivElement>(null);
  const focus = useStore((s) => s.focusMessage);
  useEffect(() => {
    if (!focus || !sid) return;
    const el = document.getElementById(`msg-${focus}`);
    if (el) {
      stick.current = false;
      el.scrollIntoView({ block: "center" });
      const t = setTimeout(() => useStore.setState({ focusMessage: null }), 2500);
      return () => clearTimeout(t);
    }
    // Not loaded yet (an older page, or a compacted message): page back until it shows up, within reason.
    if (focusTries.current.id !== focus) focusTries.current = { id: focus, n: 0 };
    if (++focusTries.current.n > 40) return void useStore.setState({ focusMessage: null });
    if (paging?.hasMore) actions.loadOlder(sid);
    else if (paging && paging.compacted > 0 && !paging.showCompacted) actions.showCompacted(sid);
  }, [focus, messages.length, paging?.hasMore, paging?.showCompacted]);
  const focusTries = useRef<{ id: string | null; n: number }>({ id: null, n: 0 });
  const stick = useRef(true);
  // Older page prepended: keep what the user was looking at in place.
  const anchor = useRef<{ height: number; top: number } | null>(null);
  const older = () => {
    const el = scroller.current;
    if (!sid || !el || anchor.current || !paging?.hasMore || paging.loading) return;
    const a = { height: el.scrollHeight, top: el.scrollTop };
    anchor.current = a;
    // Cleared after the next frame too, in case the page added nothing (the effect below then doesn't run).
    actions.loadOlder(sid).finally(() => requestAnimationFrame(() => { if (anchor.current === a) anchor.current = null; }));
  };
  useLayoutEffect(() => {
    const el = scroller.current, a = anchor.current;
    if (el && a) {
      // Browsers with scroll anchoring already kept the view in place; only restore when it didn't.
      if (Math.abs(el.scrollTop - a.top) < 2) el.scrollTop = el.scrollHeight - a.height + a.top;
      anchor.current = null;
    }
  }, [messages[0]?.id]);
  const onFork = useCallback((mid: string) => { if (sid) sessionActions.fork(sid, mid); }, [sid]);

  const results = useMemo(() => {
    const m: Record<string, Block> = {};
    for (const msg of messages) for (const b of msg.content) if (b.type === "tool_result") m[b.tool_use_id] = b;
    return m;
  }, [messages]);
  const pending = Object.values(approvals).filter((a) => a.session_id === sid && a.status === "pending");

  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current && !anchor.current) el.scrollTop = el.scrollHeight;
  }, [messages, streaming, pending.length]);

  if (!session) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-muted">
        <div className="w-full max-w-[560px] px-5"><SetupChecklist /></div>
        <p>Start a session to chat with your agents.</p>
        <button className="btn btn-primary" onClick={() => sessionActions.create()}>New session</button>
      </div>
    );
  }
  const running = session.status === "running";
  const visible = messages.filter((m) => !m.meta?.tool_results);
  const firstLive = visible.findIndex((m) => !m.meta?.compacted);

  return (
    <div className="h-full flex flex-col min-w-0">
      <header className="flex items-center gap-2 px-4 h-11 border-b border-line surface shrink-0" data-tauri-drag-region>
        <h1 className="font-medium truncate">{session.title}</h1>
        <span className="chip whitespace-nowrap shrink-0"><ProviderDot model={session.model} />{modelLabel(session.model)} <EffortMeter effort={session.effort} /> {session.effort}</span>
        <SessionTasks sessionId={session.id} />
        <div className="ml-auto flex items-center gap-1">
          {(running || backgroundBusy) && <button className="btn" title={running ? "Stop the agent and everything it started" : "Stop this session's background subagents and commands"} onClick={() => post(`/sessions/${sid}/stop`)}><Square size={12} /> Stop</button>}
          <button className="btn btn-ghost px-1.5" title={sidePanelOpen ? "Hide side panel" : "Show side panel"} aria-label="Side panel" aria-pressed={sidePanelOpen} onClick={actions.toggleSidePanel}><PanelRight size={16} /></button>
        </div>
      </header>
      <SessionLimitBanner sessionId={session.id} />
      <div ref={scroller} className="flex-1 overflow-y-auto scroll-thin" onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        if (el.scrollTop < 400) older();
      }}>
        <div className="max-w-[780px] mx-auto px-5 py-5" role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation">
          {paging?.hasMore && (
            <div className="mb-3 text-center"><button className="btn btn-ghost text-[12.5px] text-muted" disabled={paging.loading} onClick={older}>{paging.loading ? "Loading…" : "Load earlier messages"}</button></div>
          )}
          {!paging?.hasMore && paging && paging.compacted > 0 && (
            <div className="mb-3 text-center text-[12px] text-faint">
              {paging.compacted} earlier message{paging.compacted === 1 ? "" : "s"} {paging.showCompacted ? "shown dimmed; the model sees their summary" : "compacted"} ·{" "}
              <button className="text-action hover:underline underline-offset-2" onClick={() => actions.showCompacted(session.id, !paging.showCompacted)}>{paging.showCompacted ? "hide" : "show"}</button>
            </div>
          )}
          {!paging?.hasMore && session.forked_from && <ForkedFrom from={session.forked_from} />}
          {visible.length === 0 && !streaming && (
            <div className="text-muted text-[13px] py-10">
              <SetupChecklist />
              Ask anything, attach files, or hand over a job to plan and delegate. Type <code className="font-mono">/</code> for commands.
            </div>
          )}
          {visible.map((m, i) => (
            <div key={m.id} id={`msg-${m.id}`} className={focus === m.id ? "rounded-md outline-2 outline-action outline-offset-4" : ""}>
              {i === firstLive && firstLive > 0 && <div className="my-4 text-center text-[12px] text-faint">Earlier messages are summarized; the model sees the summary.</div>}
              <MessageView m={m} results={results} onFork={onFork} />
            </div>
          ))}
          {streaming && <StreamingView s={streaming} />}
          {agentStatus && <StatusLine s={agentStatus} />}
          {pending.map((a) => <ApprovalCard key={a.id} a={a} />)}
        </div>
      </div>
      {(session.deleted || session.archived) && (
        <div className="mx-auto w-full max-w-[780px] px-5 pt-2">
          <div className="flex items-center gap-2 rounded-md border border-line surface-raised px-3 py-1.5 text-[13px] text-muted">
            {session.deleted ? <Trash2 size={14} /> : <Archive size={14} />}
            <span className="flex-1">{session.deleted ? "This session is in Trash." : "This session is archived. Sending a message brings it back."}</span>
            <button className="btn py-0.5" onClick={() => (session.deleted ? sessionActions.restore([session.id]) : sessionActions.archive([session.id], false))}>
              {session.deleted ? "Restore" : "Unarchive"}
            </button>
          </div>
        </div>
      )}
      <Composer session={session} running={running} />
    </div>
  );
}

/** "Forked from <title>": opens the original session at the message the fork started from. */
function ForkedFrom({ from }: { from: { session_id: string; message_id: string; title: string } }) {
  const source = useStore((s) => s.sessions.find((x) => x.id === from.session_id));
  const open = async () => {
    await actions.openSession(from.session_id);
    useStore.setState({ focusMessage: from.message_id });
  };
  return (
    <div className="mb-3 flex items-center gap-1.5 text-[12.5px] text-muted">
      <GitBranch size={13} className="shrink-0" />
      Forked from
      {source ? <button className="text-action hover:underline underline-offset-2 truncate" onClick={open}>{source.title}</button>
        : <span className="truncate">{from.title} (deleted)</span>}
    </div>
  );
}

function ForkButton({ onClick }: { onClick: () => void }) {
  return (
    <button className="opacity-0 group-hover/msg:opacity-100 focus:opacity-100 inline-flex items-center gap-1 rounded px-1 text-[11.5px] text-faint hover:text-text hover:bg-sunken"
      title="Fork from here: a new session with the conversation up to this message" aria-label="Fork from here" onClick={onClick}>
      <GitBranch size={12} /> Fork
    </button>
  );
}

const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-ws">
      <SafeMarkdown text={text} />
    </div>
  );
});

function Thinking({ text, live }: { text: string; live?: boolean }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="my-1.5 text-[13px]">
      <button className="flex items-center gap-1 text-muted hover:text-text" onClick={() => setOpen(!open)} aria-expanded={open}>
        <ChevronRight size={13} className={open ? "rotate-90" : ""} /><Brain size={13} /> {live ? "Thinking…" : "Thought process"}
      </button>
      {open && <div className="mt-1 pl-4 border-l-2 border-line text-muted whitespace-pre-wrap">{text}</div>}
    </div>
  );
}

export function GenericToolCall({ b, result }: { b: Block; result?: Block }) {
  const run = useStore((s) => s.toolRuns[b.id]);
  const [open, setOpen] = useState(false);
  const status = result ? (result.is_error ? "error" : "done") : run?.status === "done" ? (run.is_error ? "error" : "done") : "running";
  const output = result ? (result.content ?? []).map((c: Block) => c.text ?? `[${c.type}]`).join("\n") : run?.output;
  const summary = b.input?.path ?? b.input?.command ?? b.input?.pattern ?? b.input?.text?.slice?.(0, 60) ?? "";
  return (
    <div className="my-1.5 text-[13px] rounded border border-line surface-raised">
      <button className="w-full flex items-center gap-1.5 px-2 py-1 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <ChevronRight size={13} className={`text-muted ${open ? "rotate-90" : ""}`} />
        <Wrench size={13} className="text-muted" />
        <span className="font-medium">{b.name}</span>
        <span className="text-muted truncate font-mono text-[12px]">{String(summary)}</span>
        <span className={`ml-auto text-[12px] ${status === "error" ? "text-bad" : status === "running" ? "text-action" : "text-faint"}`}>
          {status === "running" ? "running…" : status === "error" ? "failed" : "done"}
        </span>
      </button>
      {open && (
        <div className="px-2 pb-2 space-y-1.5">
          <pre className="font-mono text-[12px] bg-sunken rounded p-1.5 overflow-auto max-h-48 whitespace-pre-wrap">{JSON.stringify(b.input, null, 2)}</pre>
          {output != null && <pre className={`font-mono text-[12px] bg-sunken rounded p-1.5 overflow-auto max-h-72 whitespace-pre-wrap ${status === "error" ? "text-bad" : ""}`}>{output}</pre>}
        </div>
      )}
    </div>
  );
}

function Attachment({ b }: { b: Block }) {
  if (b.type === "image" && b.path) return <img src={fileUrl(b.path)} alt={b.name ?? "image"} className="max-h-48 rounded border border-line" />;
  if (b.type === "audio" && b.path) return <audio controls src={fileUrl(b.path)} className="h-8" />;
  const path = b.path;
  if (path && inTauri()) {
    // In the app the file opens in its default app via the shell; a backend URL (with its token) never leaves.
    return <button type="button" className="chip hover:text-text" onClick={() => void openLocalFile(path)}>{b.name ?? b.type}</button>;
  }
  return <a className="chip hover:text-text" href={path ? fileUrl(path) : undefined} target="_blank" rel="noreferrer">{b.name ?? b.type}</a>;
}

/** Re-render a message only when it, or the result of one of its own tool calls, changed (not on
 *  every streamed token or new message elsewhere in a long session). */
const sameMessage = (a: MsgProps, b: MsgProps) => a.m === b.m && a.onFork === b.onFork
  && a.m.content.every((c) => c.type !== "tool_use" || a.results[c.id] === b.results[c.id]);
type MsgProps = { m: Msg; results: Record<string, Block>; onFork: (id: string) => void };

const MessageView = memo(function MessageView({ m, results, onFork }: MsgProps) {
  const compacted = m.meta?.compacted;
  if (m.meta?.notice) return <Notice m={m} />;
  // Harness-written messages (skill loads, gate results, campaign briefs) get their own rows.
  const Row = metaRow(m);
  if (Row) return <div className={compacted ? "opacity-60" : ""}><Row m={m} /></div>;
  if (m.role === "user") {
    const skill: string | undefined = m.meta?.invoked_skill;
    let text = m.content.filter((b) => b.type === "text").map((b) => b.text).join("\n");
    if (skill && text.startsWith(`Use the ${skill} skill.`)) text = text.slice(`Use the ${skill} skill.`.length).trim(); // shown as the chip
    const atts = m.content.filter((b) => ["image", "audio", "file"].includes(b.type));
    return (
      <div className={`group/msg my-4 flex items-start justify-end gap-1.5 ${compacted ? "opacity-60" : ""}`}>
        <span className="pt-1.5"><ForkButton onClick={() => onFork(m.id)} /></span>
        <div className="max-w-[85%] rounded-lg px-3.5 py-2 bg-sunken">
          {(atts.length > 0 || skill) && <div className="flex flex-wrap gap-2 mb-1.5">
            {skill && <span className="chip text-text" title={`Use the ${skill} skill.`}><Sparkles size={12} className="text-action" />{skill}</span>}
            {atts.map((b, i) => <Attachment key={i} b={b} />)}
          </div>}
          {m.meta?.summary ? <><div className="label mb-1">Summary of earlier turns</div><Markdown text={text} /></> : <MdLite text={text} />}
        </div>
      </div>
    );
  }
  if (m.meta?.error_kind === "no_key" || m.meta?.error === "no_key") return <NoKeyNotice m={m} />;
  if (m.meta?.error) return <ErrorMessage m={m} />;
  const usage = m.meta?.usage;
  return (
    <div className={`group/msg my-4 ${compacted ? "opacity-60" : ""}`}>
      {m.content.map((b, i) => {
        if (b.type === "text") return <Markdown key={i} text={b.text} />;
        if (b.type === "thinking") return <Thinking key={i} text={b.thinking} />;
        if (b.type === "tool_use") {
          const R = toolRenderers[b.name] ?? GenericToolCall;
          return <R key={i} b={b} result={results[b.id]} />;
        }
        return null;
      })}
      <div className="mt-1 min-h-5 text-[11.5px] text-faint flex items-center gap-1.5">
        {usage && <><ProviderDot model={m.meta.model} />{modelLabel(m.meta.model, m.meta.harness === "codex_cli" && tiersOf(m.meta.model).includes("codex.cli") ? "codex.cli" : undefined)} · {m.meta.effort} · {fmtUsd(usage.cost_usd)}</>}
        <ForkButton onClick={() => onFork(m.id)} />
      </div>
    </div>
  );
}, sameMessage);

/** An app note in the chat (reply cut off at the output limit, per-turn call limit, context full).
 *  The model never sees these. The last one offers Continue. */
function Notice({ m }: { m: Msg }) {
  const sid = useStore((s) => s.currentId);
  const last = useStore((s) => (sid ? s.messages[sid]?.[s.messages[sid].length - 1]?.id === m.id : false));
  const running = useStore((s) => s.sessions.find((x) => x.id === sid)?.status === "running");
  const text = m.content.map((b) => b.text ?? "").join("");
  const canContinue = last && !running && (m.meta.notice === "max_tokens" || m.meta.notice === "turn_limit");
  const go = () => sid && post(`/sessions/${sid}/messages`, { text: "continue" }).catch((e) => actions.toast(e.message, "error"));
  return (
    <div role="note" className="my-3 flex items-center gap-2 rounded-md border border-line surface-raised px-3 py-1.5 text-[13px] text-warn">
      <Clock size={13} className="shrink-0" /><span className="flex-1">{text}</span>
      {canContinue && <button className="btn py-0.5 shrink-0" onClick={go}>Continue</button>}
    </div>
  );
}

/** A failed turn (meta.error): an alert icon and the message in normal weight. Older messages
 *  carried a "⚠️ " prefix in their text; it's dropped here. */
function ErrorMessage({ m }: { m: Msg }) {
  const text = m.content.filter((b) => b.type === "text").map((b) => b.text).join("\n").replace(/^\s*⚠️?\s*/u, "");
  return (
    <div role="alert" className={`my-4 flex items-start gap-2 rounded-md border px-3 py-2 text-[13.5px] ${m.meta?.compacted ? "opacity-60" : ""}`}
      style={{ borderColor: "color-mix(in srgb, var(--bad) 40%, var(--line))", background: "color-mix(in srgb, var(--bad) 6%, transparent)" }}>
      <TriangleAlert size={15} className="text-bad shrink-0 mt-[3px]" aria-label="Error" />
      <div className="min-w-0 flex-1"><Markdown text={text} /></div>
    </div>
  );
}

function StreamingView({ s }: { s: { text: string; thinking: string; tools: { id: string; name: string }[] } }) {
  // The chat's log region announces "Agent is replying…" once; aria-busy keeps screen readers from
  // reading every delta. The finished reply replaces this view and is announced as a new message.
  return (
    <div className="my-4">
      <span className="sr-only">Agent is replying…</span>
      <div aria-busy="true">
        <Thinking text={s.thinking} live />
        {s.text ? <div className="caret"><Markdown text={s.text} /></div> : !s.tools.length && <div className="text-muted text-[13px] caret">Working</div>}
        {s.tools.map((t) => <div key={t.id} className="text-[13px] text-muted flex items-center gap-1.5 my-1"><Wrench size={13} />{t.name}…</div>)}
      </div>
    </div>
  );
}
