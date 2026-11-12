import { AlertTriangle, FolderOpen, Loader2, Play, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { galleryApi, galleryMediaUrl, type GalleryEntry, type GalleryShotMeta } from "../../lib/api";
import { revealInFinder } from "../../lib/native";
import { actions, type Session } from "../../lib/store";
import { Card } from "../SidePanel";

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
  const box = "snap-start shrink-0 w-[132px] h-[96px] rounded border border-line bg-sunken overflow-hidden relative";
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

function Lightbox({ e, onClose }: { e: GalleryEntry; onClose: () => void }) {
  const src = galleryMediaUrl(e);
  useEffect(() => {
    const k = (ev: KeyboardEvent) => ev.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const reveal = async () => {
    if (e.path && !(await revealInFinder(e.path))) actions.toast(e.path);
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/70 grid place-items-center p-6" role="dialog" aria-modal="true" aria-label="Gallery preview" onClick={onClose}>
      <div className="surface-raised border border-line rounded-lg max-w-[90vw] max-h-[90vh] flex flex-col overflow-hidden" onClick={(ev) => ev.stopPropagation()}>
        <div className="flex items-center gap-2 px-3 h-10 border-b border-line">
          <span className="font-medium truncate flex-1" title={e.title ?? undefined}>{e.title}</span>
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

export function GalleryCard({ s }: { s: Session }) {
  const [entries, setEntries] = useState<GalleryEntry[]>([]);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const strip = useRef<HTMLDivElement>(null);
  const load = () => galleryApi.list(s.id).then(setEntries).catch(() => {});
  useEffect(() => { setEntries([]); load(); }, [s.id]);
  useEffect(() => actions.onEvent((e) => { if (GALLERY_EVENTS.includes(e.type) && (e.session_id === s.id || e.type === "item.deleted")) load(); }), [s.id]);

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
  const rows = Math.min(MAX_ROWS, Math.max(1, prompt.split("\n").length, Math.ceil(prompt.length / 38)));
  // The mouse wheel scrolls the strip sideways (a trackpad's own horizontal scroll is left alone).
  const wheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && strip.current) strip.current.scrollLeft += e.deltaY;
  };
  const viewing = entries.find((x) => x.id === open);
  return (
    <Card id="gallery" title={`Gallery${entries.length ? ` (${entries.length})` : ""}`}>
      <form className="flex flex-col gap-1.5 mb-2" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <textarea className="input w-full resize-none leading-snug" rows={rows} value={prompt} placeholder="What should the screenshot show?"
          aria-label="Screenshot prompt" onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }} />
        <button type="submit" className="btn btn-primary self-end" disabled={!prompt.trim() || busy}>Take screenshot</button>
      </form>
      {entries.length === 0 ? <div className="text-muted">No media yet.</div> : (
        <div ref={strip} onWheel={wheel} data-testid="gallery-strip" tabIndex={0} aria-label="Gallery"
          className="flex gap-2 overflow-x-auto snap-x snap-mandatory scroll-thin pb-1">
          {entries.map((e) => <Thumb key={e.id} e={e} onOpen={() => setOpen(e.id)} />)}
        </div>
      )}
      {viewing && <Lightbox e={viewing} onClose={() => setOpen(null)} />}
    </Card>
  );
}
