import { AlertTriangle, ChevronLeft, ChevronRight, FolderOpen, Loader2, Play, X } from "lucide-react";
import { createContext, useContext, useEffect, useState } from "react";
import { galleryApi, galleryMediaUrl, type GalleryEntry, type GalleryShotMeta } from "../lib/api";
import { revealInFinder } from "../lib/native";
import { actions, type Session } from "../lib/store";
import { Empty } from "./ui";

const GALLERY_EVENTS = ["gallery.updated", "item.updated", "item.deleted"];
const MAX_ROWS = 3;

const vec = (v?: number[]) => (v && v.length === 3 ? v.map((n) => Math.round(n * 100) / 100).join(", ") : null);

/** One line: the route a screenshot used and its framing ("MCP for Unity · camera Main Camera · fov 40"). */
function shotLine(m?: GalleryShotMeta): string | null {
  if (!m?.route) return null;
  const c = m.camera ?? {};
  const parts = [m.route_label || m.route];
  if (m.clone) parts.push("on a copy of the project");
  if (c.camera) parts.push(`camera ${c.camera}`);
  const pos = vec(c.used_pos ?? c.cam_pos);
  if (pos) parts.push(`at ${pos}`);
  const rot = vec(c.used_rot ?? c.cam_rot);
  if (rot) parts.push(`rotation ${rot}`);
  if (!rot && (c.view_target || typeof c.look_at === "string")) parts.push(`looking at ${c.view_target ?? c.look_at}`);
  const fov = c.used_fov ?? c.fov;
  if (fov) parts.push(`fov ${Math.round(fov)}`);
  const scene = c.used_scene ?? c.scene;
  if (scene) parts.push(scene);
  return parts.join(" · ");
}

function Thumb({ e, onOpen }: { e: GalleryEntry; onOpen: () => void }) {
  const box = "w-full aspect-[4/3] rounded border border-line bg-sunken overflow-hidden relative";
  if (e.status === "pending") {
    return (
      <div className={`${box} p-2 flex flex-col gap-1`} role="status" aria-label="Screenshot pending">
        <Loader2 size={16} className="animate-spin text-action" />
        <span className="text-[11.5px] text-muted line-clamp-3">{e.prompt}</span>
        {e.meta?.route_label && <span className="text-[10.5px] text-faint truncate">{e.meta.stage === "captured" ? "Captured" : "Framing"} · {e.meta.route_label}</span>}
      </div>
    );
  }
  if (e.status === "failed") {
    return (
      <div className={`${box} p-2 flex flex-col gap-1 border-bad`} role="alert" title={e.prompt ?? undefined}>
        <span className="flex items-center gap-1 text-bad text-[11.5px] font-medium"><AlertTriangle size={13} />Failed</span>
        <span className="text-[11.5px] text-muted line-clamp-4">{e.reason ?? "Screenshot failed."}</span>
      </div>
    );
  }
  const src = galleryMediaUrl(e);
  return (
    <button className={`${box} hover:border-action focus-visible:border-action`} onClick={onOpen} title={e.title ?? undefined} aria-label={`Open ${e.title ?? e.kind}`}>
      {e.kind === "image" && src && <img src={src} alt={e.title ?? ""} loading="lazy" decoding="async" className="size-full object-cover" />}
      {e.kind === "video" && src && <video src={`${src}#t=0.1`} preload="metadata" muted playsInline className="size-full object-cover" />}
      {e.kind === "audio" && <span className="size-full grid place-items-center text-[11.5px] text-muted px-2 text-center">{e.title}</span>}
      {e.kind !== "image" && (
        <span data-testid="play-badge" className="absolute inset-0 grid place-items-center pointer-events-none">
          <span className="size-7 rounded-full bg-black/60 text-white grid place-items-center"><Play size={14} fill="currentColor" /></span>
        </span>
      )}
    </button>
  );
}

/** A gallery entry, or a chat image that has only a file path: `src` (when set) is the ready-made URL. */
export type LightboxEntry = GalleryEntry & { src?: string };

/** The preview. With `nav`, Left / Right (and the arrow buttons) step through a set of images, e.g. one chat turn's. */
export function Lightbox({ e, onClose, nav }: { e: LightboxEntry; onClose: () => void; nav?: { index: number; count: number; go: (delta: number) => void } }) {
  const src = e.src ?? galleryMediaUrl(e);
  useEffect(() => {
    const k = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") onClose();
      else if (nav && nav.count > 1 && ev.key === "ArrowLeft") nav.go(-1);
      else if (nav && nav.count > 1 && ev.key === "ArrowRight") nav.go(1);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, nav]);
  const reveal = async () => {
    if (e.path && !(await revealInFinder(e.path))) actions.toast(e.path);
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/70 grid place-items-center p-6" role="dialog" aria-modal="true" aria-label="Gallery preview" onClick={onClose}>
      <div className="surface-raised border border-line rounded-lg max-w-[90vw] max-h-[90vh] flex flex-col overflow-hidden" onClick={(ev) => ev.stopPropagation()}>
        <div className="flex items-center gap-2 px-3 h-10 border-b border-line">
          <span className="font-medium truncate flex-1" title={e.title ?? undefined}>{e.title}</span>
          {nav && nav.count > 1 && (
            <span className="flex items-center gap-0.5 text-[12px] text-muted tabular-nums">
              <button className="btn btn-ghost px-1 py-1" onClick={() => nav.go(-1)} aria-label="Previous image"><ChevronLeft size={15} /></button>
              {nav.index + 1} / {nav.count}
              <button className="btn btn-ghost px-1 py-1" onClick={() => nav.go(1)} aria-label="Next image"><ChevronRight size={15} /></button>
            </span>
          )}
          {e.path && <button className="btn btn-ghost px-1.5 py-1" onClick={reveal} title="Reveal in Finder (shows the path in the browser)"><FolderOpen size={14} /><span className="text-[12px]">Open in Finder</span></button>}
          <button className="btn btn-ghost px-1.5 py-1" onClick={onClose} aria-label="Close"><X size={15} /></button>
        </div>
        <div className="overflow-auto bg-sunken grid place-items-center min-h-0">
          {e.kind === "image" && src && <img src={src} alt={e.title ?? ""} className="max-w-full max-h-[70vh] object-contain" />}
          {e.kind === "video" && src && <video src={src} controls autoPlay className="max-w-full max-h-[70vh]" />}
          {e.kind === "audio" && src && <audio src={src} controls autoPlay className="m-6" />}
        </div>
        <div className="px-3 py-2 text-[12.5px] border-t border-line space-y-0.5">
          {e.prompt && <div><span className="text-muted">Prompt: </span>{e.prompt}</div>}
          {shotLine(e.meta) && <div data-testid="shot-route"><span className="text-muted">Captured via: </span>{shotLine(e.meta)}</div>}
          {e.meta?.notes && <div className="text-muted">{e.meta.notes}</div>}
          {e.path && <div className="text-faint font-mono text-[11.5px] break-all select-text">{e.path}</div>}
        </div>
      </div>
    </div>
  );
}

/** The session's gallery entries, for views (the chat) that map a saved item id to its file. */
export const GalleryEntriesContext = createContext<GalleryEntry[]>([]);
export const useGalleryEntries = () => useContext(GalleryEntriesContext);

/** A session's gallery entries, kept fresh from the live events (the tab strip shows the count). */
export function useGallery(sessionId: string) {
  const [entries, setEntries] = useState<GalleryEntry[]>([]);
  const load = () => galleryApi.list(sessionId).then(setEntries).catch(() => {});
  useEffect(() => { setEntries([]); load(); }, [sessionId]);
  useEffect(() => actions.onEvent((e) => { if (GALLERY_EVENTS.includes(e.type) && (e.session_id === sessionId || e.type === "item.deleted")) load(); }), [sessionId]);
  return { entries, setEntries };
}

/** The Gallery tab: the screenshot prompt and every entry as a grid of larger thumbnails. */
export function GalleryTab({ s, entries, setEntries }: { s: Session; entries: GalleryEntry[]; setEntries: React.Dispatch<React.SetStateAction<GalleryEntry[]>> }) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const submit = async () => {
    const p = prompt.trim();
    if (!p || busy) return;
    setBusy(true);
    try {
      const e = await galleryApi.screenshot(s.id, p);
      setPrompt("");
      setEntries((cur) => (cur.some((x) => x.id === e.id) ? cur : [e, ...cur]));
    } catch (err: any) { actions.toast(err.message, "error"); } finally { setBusy(false); }
  };
  const rows = Math.min(MAX_ROWS, Math.max(1, prompt.split("\n").length, Math.ceil(prompt.length / 80)));
  const viewing = entries.find((x) => x.id === open);
  return (
    <div className="h-full overflow-y-auto scroll-thin p-4 text-[13px]">
      <form className="flex flex-col gap-1.5 mb-3 max-w-xl" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <textarea className="input w-full resize-none leading-snug" rows={rows} value={prompt} placeholder="What should the screenshot show?"
          aria-label="Screenshot prompt" onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }} />
        <button type="submit" className="btn btn-primary self-end" disabled={!prompt.trim() || busy}>Take screenshot</button>
      </form>
      {entries.length === 0 ? <Empty>No media yet.</Empty> : (
        <div data-testid="gallery-grid" aria-label="Gallery" role="list" className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
          {entries.map((e) => <div key={e.id} role="listitem"><Thumb e={e} onOpen={() => setOpen(e.id)} /></div>)}
        </div>
      )}
      {viewing && <Lightbox e={viewing} onClose={() => setOpen(null)} />}
    </div>
  );
}
