import {
  Captions, Code2, Copy, Download, ExternalLink, FileCode, FileJson, FileSpreadsheet, FileText, FileType, FolderOpen, Globe, Image as ImageIcon,
  MessageSquareText, Music, Pause, Play, Send, ShieldAlert, Trash2, Video, Workflow,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { del, fileUrl, get, patch, post } from "../lib/api";
import { downloadPath, openLocalFile, revealInFinder } from "../lib/native";
import { actions, useStore } from "../lib/store";
import { AudioPlayer } from "./AudioPlayer";
import { SafeMarkdown } from "./SafeMarkdown";
import { TranscriptWithPlayer, fmtStamp } from "./Transcript";
import { Modal, ModalFooter, ProviderDot, fmtAgo, modelLabel, useModelCatalog } from "./ui";

export type Item = {
  id: string; session_id: string | null; session_title?: string; message_id: string | null; kind: string; subtype: string | null;
  provider: string | null; model: string | null; source: string; title: string | null; filename: string | null; path: string | null;
  url: string | null; size: number | null; mime: string | null; extracted_text?: string | null; meta: any; version: number; created_at: number;
  hl_title?: string; hl_url?: string; hl_text?: string;
};

/** Icon per kind and subtype: web links, code, data, HTML, diagrams, transcripts, media. */
export function itemIconFor(it: Pick<Item, "kind" | "subtype" | "mime">) {
  const m = it.mime ?? "";
  if (it.kind === "link") return Globe;
  if (it.subtype === "svg" || m.startsWith("image")) return ImageIcon;
  if (m.startsWith("audio")) return Music;
  if (m.startsWith("video")) return Video;
  switch (it.subtype) {
    case "code": return FileCode;
    case "html": return Code2;
    case "data": return m.includes("json") ? FileJson : FileSpreadsheet;
    case "diagram": return Workflow;
    case "transcript": return Captions;
    case "pdf": return FileType;
    default: return FileText;
  }
}

export function ItemIcon({ it, size = 15 }: { it: Item; size?: number }) {
  const I = itemIconFor(it);
  return <I size={size} className="text-muted shrink-0" />;
}

export function Thumb({ it }: { it: Item }) {
  const m = it.mime ?? "";
  if (it.path && m.startsWith("image/")) {
    return <img src={fileUrl(it.path)} alt="" loading="lazy" className="size-10 rounded object-cover border border-line shrink-0" />;
  }
  if (it.path && m.startsWith("audio/")) return <AudioThumb path={it.path} />;
  if (it.path && m.startsWith("video/")) return <VideoThumb path={it.path} />;
  return <span className="size-10 rounded bg-sunken grid place-items-center shrink-0"><ItemIcon it={it} size={17} /></span>;
}

// One row plays at a time across lists.
let playingRow: HTMLAudioElement | null = null;

/** Row mini-player: play/pause and the duration (metadata only until played). */
function AudioThumb({ path }: { path: string }) {
  const a = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [dur, setDur] = useState<number | null>(null);
  const [t, setT] = useState(0);
  const toggle = (e: React.MouseEvent | React.KeyboardEvent) => {
    e.stopPropagation();
    const el = a.current;
    if (!el) return;
    if (el.paused) {
      if (playingRow && playingRow !== el) playingRow.pause();
      playingRow = el;
      el.play().catch(() => {});
    } else el.pause();
  };
  return (
    <button className="size-10 rounded bg-sunken border border-line shrink-0 flex flex-col items-center justify-center leading-none hover:text-action"
      onClick={toggle} onKeyDown={(e) => e.key === "Enter" && e.stopPropagation()} aria-label={playing ? "Pause" : "Play"} title={playing ? "Pause" : "Play"}>
      {playing ? <Pause size={14} /> : <Play size={14} />}
      <span className="text-[9.5px] text-muted tabular-nums mt-0.5">{dur == null ? "–:––" : fmtStamp(playing || t ? t : dur)}</span>
      <audio ref={a} src={fileUrl(path)} preload="metadata" onLoadedMetadata={(e) => isFinite(e.currentTarget.duration) && setDur(e.currentTarget.duration)}
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setT(0); }}
        onTimeUpdate={(e) => setT(e.currentTarget.currentTime)} />
    </button>
  );
}

/** Poster: the first frame, from metadata only (muted, never plays in the row). */
function VideoThumb({ path }: { path: string }) {
  const [dur, setDur] = useState<number | null>(null);
  return (
    <span className="relative size-10 rounded overflow-hidden border border-line bg-sunken shrink-0">
      {/* #t= asks for a frame just past 0 so WebKit paints a poster instead of black. */}
      <video src={`${fileUrl(path)}#t=0.1`} preload="metadata" muted playsInline className="size-full object-cover"
        onLoadedMetadata={(e) => isFinite(e.currentTarget.duration) && setDur(e.currentTarget.duration)} />
      <span className="absolute inset-x-0 bottom-0 flex items-center justify-between px-0.5 bg-black/55 text-white text-[9px] leading-[12px] tabular-nums">
        <Video size={9} />{dur != null && fmtStamp(dur)}
      </span>
    </span>
  );
}

export function fmtSize(n?: number | null) {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

/** Only <mark> survives from search highlights; everything else is escaped. */
export function safeHighlight(s?: string | null): string {
  if (!s) return "";
  const esc = s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/&lt;mark&gt;/g, "<mark>").replace(/&lt;\/mark&gt;/g, "</mark>");
}

export async function jumpToMessage(it: Item) {
  if (!it.session_id) return;
  await actions.openSession(it.session_id);
  if (it.message_id) useStore.setState({ focusMessage: it.message_id });
}

export async function sendItem(it: Item) {
  const sid = useStore.getState().currentId;
  if (!sid) return actions.toast("Open a session first.", "error");
  const r = await post(`/items/${it.id}/send`, { target: "chat", session_id: sid });
  actions.attachToChat(sid, r.attachment, r.warning);
}

/** What /items/{id}/send says when the subagent can't take the item (it finished, or it's a Codex CLI run). */
type SendRefusal = { status: "not_running" | "no_inbox"; message: string; subagent: { id: string; name: string; status: string; session_id: string | null } };

/** An item's actions. `labeled` (the viewer) spells out the less common ones next to their icons. */
export function ItemActions({ it, onOpen, onDeleted, labeled }: { it: Item; onOpen: () => void; onDeleted?: () => void; labeled?: boolean }) {
  const subagents = useStore((s) => s.subagents);
  const all = Object.values(subagents) as any[];
  const running = all.filter((x) => x.status === "running" || x.status === "queued");
  // Finished ones are offered too: picking one explains it can't read messages and offers the alternatives.
  const finished = all.filter((x) => ["done", "failed", "cancelled"].includes(x.status)).sort((a, b) => (b.ended ?? 0) - (a.ended ?? 0)).slice(0, 8);
  const [refused, setRefused] = useState<SendRefusal | null>(null);
  const copy = async (text: string) => { await navigator.clipboard.writeText(text); actions.toast("Copied"); };
  const sendToSub = async (subId: string) => {
    try {
      const r = await post(`/items/${it.id}/send`, { target: "subagent", subagent_id: subId });
      if (r.ok === false) setRefused(r);
      else actions.toast(r.warning ?? "Sent to the subagent.");
    } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const remove = async () => {
    if (!confirm(`Remove "${it.title}" from the index?${it.path?.includes("/media/") ? " The stored file is deleted too." : " Your file on disk is kept."}`)) return;
    await del(`/items/${it.id}?delete_file=true`);
    onDeleted?.();
  };
  const reveal = async () => {
    if (it.path && !(await revealInFinder(it.path))) copy(it.path);
  };
  const b = "btn btn-ghost px-1.5 py-1";
  const lbl = (text: string) => (labeled ? <span className="text-[12px]">{text}</span> : null);
  return (
    <div className="flex items-center gap-0.5 shrink-0" onClick={(e) => e.stopPropagation()}>
      <button className={b} title="Open" aria-label="Open" onClick={onOpen}><ExternalLink size={14} /></button>
      {it.message_id && <button className={b} title="Jump to the message it came from" aria-label="Jump to source message" onClick={() => jumpToMessage(it)}><MessageSquareText size={14} />{lbl("Source")}</button>}
      {it.path && <button className={b} title="Download" aria-label="Download" onClick={() => downloadPath(it.path!, it.filename ?? undefined)}><Download size={14} /></button>}
      {it.path && <button className={b} title="Reveal in Finder (copies the path in the browser)" aria-label="Reveal in Finder" onClick={reveal}><FolderOpen size={14} />{lbl("Finder")}</button>}
      <button className={b} title={it.url ? "Copy link" : "Copy path"} aria-label="Copy path or link" onClick={() => copy(it.url ?? it.path ?? "")}><Copy size={14} /></button>
      <button className={b} title="Send to chat" aria-label="Send to chat" onClick={() => sendItem(it)}><Send size={14} />{lbl("To chat")}</button>
      {running.length + finished.length > 0 && (
        <select className="input py-0.5 w-28 text-[12px]" value="" aria-label="Send to subagent" onChange={(e) => e.target.value && sendToSub(e.target.value)}>
          <option value="">To subagent…</option>
          {running.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          {finished.length > 0 && <optgroup label="Finished">{finished.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.status})</option>)}</optgroup>}
        </select>
      )}
      {refused && createPortal(<SubagentRefusal it={it} r={refused} onClose={() => setRefused(null)} />, document.body)}
      {it.kind !== "link" && (
        <button className={b} aria-pressed={!!it.meta?.sensitive} title={it.meta?.sensitive ? "Marked sensitive (click to unmark)" : "Mark sensitive (data policy decides which providers may get it)"}
          aria-label="Toggle sensitive" onClick={async () => { await patch(`/items/${it.id}`, { sensitive: !it.meta?.sensitive }); actions.toast(it.meta?.sensitive ? "Unmarked" : "Marked sensitive"); onDeleted?.(); }}>
          <ShieldAlert size={14} style={{ color: it.meta?.sensitive ? "var(--warn)" : undefined }} />{lbl(it.meta?.sensitive ? "Sensitive" : "Mark sensitive")}
        </button>
      )}
      <span className="w-px h-4 bg-line mx-1 shrink-0" aria-hidden />
      <button className={`${b} btn-danger`} title="Delete" aria-label="Delete" onClick={remove}><Trash2 size={14} /></button>
    </div>
  );
}

/** The subagent can't read the item: send it to its session's chat, or ask the main agent to follow up. */
function SubagentRefusal({ it, r, onClose }: { it: Item; r: SendRefusal; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const sid = r.subagent.session_id;
  const toChat = async () => {
    if (!sid) return;
    try {
      const a = await post(`/items/${it.id}/send`, { target: "chat", session_id: sid });
      onClose();
      actions.attachToChat(sid, a.attachment, a.warning);
    } catch (e: any) { actions.toast(e.message, "error"); }
  };
  const followUp = async () => {
    if (!sid) return;
    setBusy(true);
    try {
      await post(`/items/${it.id}/send`, { target: "followup", subagent_id: r.subagent.id });
      onClose();
      await actions.openSession(sid);
      actions.toast(`Asked the main agent to follow up on ${r.subagent.name}.`);
    } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <div onClick={(e) => e.stopPropagation()}>
      <Modal title={r.status === "no_inbox" ? `${r.subagent.name} can't take messages` : `${r.subagent.name} has finished`} onClose={onClose}>
        <p className="text-[13.5px]">{r.message}</p>
        <p className="text-[13px] text-muted mt-1">What should happen with “{it.title}”?</p>
        {!sid && <p className="text-[13px] text-bad mt-2">Its session is gone, so there's nowhere to send it.</p>}
        <ul className="mt-3 space-y-1 text-[12.5px] text-muted list-disc pl-5">
          <li><span className="text-text">Run a follow-up</span> posts “Follow up on subagent {r.subagent.name} with item {it.id}: …” to the session and starts the main agent.</li>
          <li><span className="text-text">Send to chat</span> attaches it to that session's composer so you can add a note first.</li>
        </ul>
        <ModalFooter>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={!sid || busy} onClick={toChat}>Send to chat</button>
          <button className="btn btn-primary" disabled={!sid || busy} onClick={followUp} title="Ask the orchestrator to run a follow-up">Run a follow-up</button>
        </ModalFooter>
      </Modal>
    </div>
  );
}

export function ItemRow({ it, onOpen, onDeleted }: { it: Item; onOpen: () => void; onDeleted?: () => void }) {
  useModelCatalog();
  return (
    <div className="group flex items-center gap-3 px-2 py-1.5 rounded hover:bg-sunken cursor-pointer" onClick={onOpen} role="button" tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      <Thumb it={it} />
      <div className="min-w-0 flex-1">
        {it.hl_title ? <div className="truncate" dangerouslySetInnerHTML={{ __html: safeHighlight(it.hl_title) }} /> : <div className="truncate">{it.title}</div>}
        <div className="text-[12px] text-muted flex items-center gap-1.5 truncate">
          <ProviderDot provider={it.provider ?? undefined} model={it.model ?? undefined} />
          <span title={it.model ?? undefined}>{it.model ? modelLabel(it.model) : it.provider ?? ""}</span>
          <span>· {it.kind === "link" ? (it.subtype === "mentioned" ? "mentioned" : "cited") : it.source === "user" ? "attached" : it.source === "tool" ? "generated" : "made"} {fmtAgo(it.created_at)}</span>
          {it.subtype && it.kind !== "link" && <span>· {it.subtype}</span>}
          {it.size ? <span>· {fmtSize(it.size)}</span> : null}
          {it.version > 1 && <span>· v{it.version}</span>}
          {it.url && <span className="truncate">· {it.url}</span>}
        </div>
        {it.hl_text && <div className="text-[12px] text-muted line-clamp-2 mt-0.5" dangerouslySetInnerHTML={{ __html: safeHighlight(it.hl_text) }} />}
      </div>
      <div className="opacity-0 group-hover:opacity-100 focus-within:opacity-100"><ItemActions it={it} onOpen={onOpen} onDeleted={onDeleted} /></div>
    </div>
  );
}

/** Viewer: sandboxed iframe for HTML (no same-origin, no network to the app), media players, text. */
export function ItemViewer({ id, onClose }: { id: string; onClose: () => void }) {
  useModelCatalog();
  const [it, setIt] = useState<any>(null);
  const [text, setText] = useState<string | null>(null);
  const [ver, setVer] = useState<string>(id);
  useEffect(() => { get(`/items/${ver}`).then(setIt); }, [ver]);
  useEffect(() => {
    setText(null);
    if (!it?.path) return;
    const m = it.mime ?? "";
    if (it.subtype === "html") { fetch(fileUrl(it.path)).then((r) => r.text()).then(setText); return; }
    const isText = it.subtype === "markdown" || it.subtype === "code" || it.subtype === "data" || it.subtype === "transcript" || m.startsWith("text/") || m.includes("json");
    if (isText) fetch(fileUrl(it.path)).then((r) => r.text()).then((t) => setText(t.slice(0, 500_000)));
  }, [it]);
  if (!it) return null;
  const m = it.mime ?? "";
  const src = it.path ? fileUrl(it.path) : "";
  let body;
  if (it.kind === "link") {
    body = <div className="space-y-2"><a className="text-action underline break-all" href={it.url} target="_blank" rel="noreferrer">{it.url}</a>{it.extracted_text && it.extracted_text !== it.url && <p className="text-muted">{it.extracted_text}</p>}</div>;
  } else if (it.subtype === "html") {
    // srcdoc + sandbox without allow-same-origin: the page runs scripts in an opaque origin and never sees the app's token.
    body = text == null ? <p className="text-muted">Loading…</p> : <iframe title={it.title} srcDoc={text} sandbox="allow-scripts allow-popups" className="w-full h-[70vh] rounded border border-line bg-white" />;
  } else if (m.startsWith("image/") || it.subtype === "svg") {
    body = <img src={src} alt={it.title} className="max-w-full max-h-[70vh] mx-auto" />;
  } else if (m.startsWith("audio/")) {
    body = <AudioPlayer path={it.path} />;
  } else if (m.startsWith("video/")) {
    body = <video src={src} controls className="max-w-full max-h-[70vh] mx-auto" />;
  } else if (m === "application/pdf") {
    body = <iframe title={it.title} src={src} className="w-full h-[70vh] rounded border border-line" />;
  } else if (it.subtype === "markdown" && text != null) {
    body = <div className="prose-ws"><SafeMarkdown text={text} /></div>;
  } else if (it.subtype === "transcript" && transcriptWords(text)) {
    body = <TranscriptWithPlayer words={transcriptWords(text)!} audioPath={it.meta?.audio} />;
  } else if (it.subtype === "transcript" && it.extracted_text) {
    body = <div className="whitespace-pre-wrap text-[13.5px] leading-6">{it.extracted_text}</div>;
  } else if (text != null) {
    body = <pre className="font-mono text-[12.5px] bg-sunken rounded p-3 overflow-auto max-h-[70vh] whitespace-pre">{text}</pre>;
  } else {
    body = <p className="text-muted">No preview for this file type. Download it or reveal it in Finder.</p>;
  }
  return (
    <Modal title={it.title ?? "Item"} onClose={onClose} wide>
      <div className="flex items-center gap-2 mb-3 text-[12px] text-muted">
        <ProviderDot provider={it.provider} model={it.model} />{it.model ? modelLabel(it.model) : it.provider} · {it.session_title ?? "no session"} · {fmtAgo(it.created_at)}
        {it.versions?.length > 1 && (
          <select className="input py-0.5 w-auto ml-2" value={ver} onChange={(e) => setVer(e.target.value)} aria-label="Version">
            {it.versions.map((v: any) => <option key={v.id} value={v.id}>v{v.version} · {modelLabel(v.model)} · {fmtAgo(v.created_at)}</option>)}
          </select>
        )}
        <div className="ml-auto"><ItemActions it={it} labeled onOpen={() => it.path && openLocalFile(it.path)} onDeleted={onClose} /></div>
      </div>
      {body}
    </Modal>
  );
}

/** Word timings from a saved ElevenLabs transcript (JSON), or null for anything else. */
function transcriptWords(text: string | null): any[] | null {
  if (!text) return null;
  try {
    const w = JSON.parse(text)?.words;
    return Array.isArray(w) && w.length ? w : null;
  } catch { return null; }
}
