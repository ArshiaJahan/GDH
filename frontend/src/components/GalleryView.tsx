import { AlertTriangle, ChevronLeft, ChevronRight, FolderOpen, Loader2, Play, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { galleryApi, galleryMediaUrl, inTauri, post, type GalleryEntry, type GalleryShotMeta } from "../lib/api";
import { pickFolder, revealInFinder } from "../lib/native";
import { actions, type Session } from "../lib/store";
import { Empty } from "./ui";

const GALLERY_EVENTS = ["gallery.updated", "item.updated", "item.deleted"];
const MAX_ROWS = 3;
const FILTERS = [
  ["all", "All"], ["generated", "Generated"], ["folders", "Screenshots & folders"], ["user", "Your uploads"],
] as const;
type Filter = (typeof FILTERS)[number][0];
const folderName = (path: string) => path.split(/[\\/]/).pop() || path;

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

/** Fixes a failed screenshot can offer (the same Unity actions as the Unity chip). */
const FIX_LABEL: Record<string, string> = {
  install_harness: "Install harness scripts",
  install_pipeline: "Install Pipeline package",
  use_clone: "Use a copy of the files",
};

function Thumb({ e, onOpen, onFix, onRetry }: {
  e: GalleryEntry; onOpen: () => void; onFix?: (action: string) => void; onRetry?: () => void;
}) {
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
      <div className={`${box} p-2 flex flex-col gap-1 border-bad`} role="alert" title={[e.prompt, e.reason].filter(Boolean).join("\n\n")}>
        <span className="flex items-center gap-1 text-bad text-[11.5px] font-medium"><AlertTriangle size={13} />Failed</span>
        <span className="text-[11.5px] text-muted line-clamp-3">{e.reason ?? "Screenshot failed."}</span>
        <span className="mt-auto flex flex-wrap gap-1">
          {(e.actions ?? []).filter((a) => a in FIX_LABEL).map((a) => (
            <button key={a} className="btn py-0.5 text-[11.5px]" onClick={() => onFix?.(a)}>{FIX_LABEL[a]}</button>
          ))}
          {e.prompt && onRetry && <button className="btn btn-ghost py-0.5 text-[11.5px]" onClick={onRetry}>Retry</button>}
        </span>
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
  useEffect(() => {
    let version = 0;
    const load = () => {
      const request = ++version;
      galleryApi.list(sessionId).then((result) => { if (request === version) setEntries(result); }).catch(() => {});
    };
    setEntries([]);
    load();
    const unsubscribe = actions.onEvent((e) => {
      if (GALLERY_EVENTS.includes(e.type) && (e.session_id === sessionId || e.type === "item.deleted")) load();
    });
    return () => { version++; unsubscribe(); };
  }, [sessionId]);
  return { entries, setEntries };
}

/** The Gallery tab: the screenshot prompt and every entry as a grid of larger thumbnails. */
export function GalleryTab({ s, entries, setEntries }: { s: Session; entries: GalleryEntry[]; setEntries: React.Dispatch<React.SetStateAction<GalleryEntry[]>> }) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [source, setSource] = useState<Filter>("all");
  const [filtered, setFiltered] = useState<{ sessionId: string; source: Filter; entries: GalleryEntry[] }>();
  const [folders, setFolders] = useState<Awaited<ReturnType<typeof galleryApi.folders>>>();
  const [updating, setUpdating] = useState(false);
  const refresh = useCallback(async (force = false) => {
    setEntries(await galleryApi.list(s.id, undefined, force));
    setFolders(await galleryApi.folders(s.id));
  }, [s.id, setEntries]);
  useEffect(() => {
    const loadFolders = () => galleryApi.folders(s.id).then(setFolders).catch(() => {});
    const onFocus = () => { refresh(true).catch(() => {}); };
    refresh().catch(() => {});
    window.addEventListener("focus", onFocus);
    const unsubscribe = actions.onEvent((e) => {
      if (e.type === "gallery.updated" && e.session_id === s.id && ["added", "removed"].includes(e.data?.status)) loadFolders();
    });
    return () => { window.removeEventListener("focus", onFocus); unsubscribe(); };
  }, [refresh, s.id]);
  useEffect(() => {
    if (source === "all") return;
    let active = true;
    galleryApi.list(s.id, source).then((result) => {
      if (active) setFiltered({ sessionId: s.id, source, entries: result });
    }).catch(() => {});
    return () => { active = false; };
  }, [s.id, source, entries]);
  const updateFolders = async (update: () => Promise<void>) => {
    setUpdating(true);
    try { await update(); } catch (err: any) { actions.toast(err.message, "error"); } finally { setUpdating(false); }
  };
  const importFolder = () => updateFolders(async () => {
    const picked = await pickFolder();
    const path = (picked ?? (!inTauri() ? window.prompt("Folder path") : null))?.trim();
    if (!path) return;
    await galleryApi.addFolder(s.id, path);
    await refresh();
  });
  const removeFolder = (path: string) => updateFolders(async () => {
    await galleryApi.removeFolder(s.id, path);
    await refresh();
  });
  const fix = async (action: string) => {
    try {
      const r = await post<{ status: string; message?: string }>(`/unity/actions/${action}`, { session_id: s.id });
      actions.toast(r?.message || (r?.status === "pending" ? "Approve it in the Chat tab, then retry the screenshot" : `Unity: ${r?.status ?? "done"}`),
        r?.status === "error" ? "error" : undefined);
    } catch (err: any) { actions.toast(err.message, "error"); }
  };
  const retry = async (p: string) => {
    try {
      const e = await galleryApi.screenshot(s.id, p);
      setEntries((cur) => (cur.some((x) => x.id === e.id) ? cur : [e, ...cur]));
    } catch (err: any) { actions.toast(err.message, "error"); }
  };
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
  let visible = entries;
  if (source !== "all") {
    visible = filtered?.sessionId === s.id && filtered.source === source ? filtered.entries : entries.filter((e) => (
      source === "generated" ? e.source !== "user" && e.source !== "folder" : e.source === (source === "folders" ? "folder" : "user")
    ));
    if (source === "folders") {
      visible = [...visible, ...entries.filter((e) => e.source === "screenshot")].sort((a, b) => b.created_at - a.created_at);
    }
  }
  const viewing = visible.find((e) => e.id === open);
  const root = s.folder?.replace(/[\\/]+$/, "");
  const defaultLabel = (path: string) => root && (path.startsWith(`${root}/`) || path.startsWith(`${root}\\`))
    ? path.slice(root.length + 1) : path;
  return (
    <div className="h-full overflow-y-auto scroll-thin p-4 text-[13px]">
      <form className="flex flex-col gap-1.5 mb-3 max-w-xl" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <textarea className="input w-full resize-none leading-snug" rows={rows} value={prompt} placeholder="What should the screenshot show?"
          aria-label="Screenshot prompt" onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }} />
        <button type="submit" className="btn btn-primary self-end" disabled={!prompt.trim() || busy}>Take screenshot</button>
      </form>
      <div className="flex flex-wrap items-center gap-1.5 mb-2">
        <div role="group" aria-label="Gallery source" className="flex flex-wrap gap-1">
          {FILTERS.map(([value, label]) => (
            <button key={value} className={`btn ${source === value ? "btn-primary" : "btn-ghost"} px-2 py-1`}
              aria-pressed={source === value} onClick={() => { setSource(value); setOpen(null); }}>{label}</button>
          ))}
        </div>
        <button className="btn btn-ghost ml-auto" disabled={updating} onClick={importFolder}><FolderOpen size={14} />Import folder…</button>
        <button className="btn btn-ghost" disabled={updating} onClick={() => updateFolders(() => refresh(true))}>Refresh</button>
      </div>
      {!!folders?.imported.length && <div className="flex flex-wrap gap-1.5 mb-2">
        {folders.imported.map(({ path, exists, count }) => (
          <div key={path} title={path} className="inline-flex items-center gap-1 rounded border border-line bg-sunken pl-2 text-[12px] text-muted">
            <span>{folderName(path)} ({exists ? count : "unavailable"})</span>
            <button className="btn btn-ghost p-1" aria-label={`Remove folder ${folderName(path)}`} disabled={updating}
              onClick={() => removeFolder(path)}><X size={13} /></button>
          </div>
        ))}
      </div>}
      {!!folders?.default.length && <div className="mb-3 text-[12px] text-muted">
        Also showing: {folders.default.map(({ path, count }) => `${defaultLabel(path)} (${count})`).join(", ")}
      </div>}
      {visible.length === 0 ? <Empty>No media yet.</Empty> : (
        <div data-testid="gallery-grid" aria-label="Gallery" role="list" className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
          {visible.map((e) => <div key={e.id} role="listitem">
            <Thumb e={e} onOpen={() => setOpen(e.id)} onFix={fix} onRetry={e.prompt ? () => retry(e.prompt!) : undefined} />
            {e.folder && <div className="truncate text-[11.5px] text-muted" title={e.folder}>{folderName(e.folder)}</div>}
          </div>)}
        </div>
      )}
      {viewing && <Lightbox e={viewing} onClose={() => setOpen(null)} />}
    </div>
  );
}
