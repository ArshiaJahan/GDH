import { createContext, useCallback, useContext, useState } from "react";
import { fileUrl, galleryMediaUrl, type GalleryEntry } from "../lib/api";
import type { Block, Msg, ToolRun } from "../lib/store";
import { Lightbox, type LightboxEntry } from "./GalleryView";

/** An image a tool produced, ready to show: its URL (never base64), alt text and where it came from. */
export type ChatImage = { key: string; src: string; alt: string; title: string; prompt?: string; path?: string };

const clip = (s: string, n = 120) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** The images of one tool call. Where the call's result carries image blocks (comfyplug, screenshots, MCP tools),
 *  those are used (served by path); otherwise the gallery items the run saved (tool.finished `items`). */
export function callImages(b: Block, result: Block | undefined, run: ToolRun | undefined, gallery: GalleryEntry[]): ChatImage[] {
  const prompt: string | undefined = typeof b.input?.prompt === "string" && b.input.prompt.trim() ? b.input.prompt.trim() : undefined;
  const out: ChatImage[] = [];
  (result?.content ?? []).forEach((c: Block, i: number) => {
    if (c.type !== "image" || !c.path) return;
    const name = c.name ?? "image";
    out.push({ key: `${b.id}:${i}`, src: fileUrl(c.path), alt: prompt ? clip(prompt) : name, title: name, prompt, path: c.path });
  });
  if (out.length) return out;
  (run?.items ?? []).forEach((id, i) => {
    const e = gallery.find((g) => g.id === id);
    const src = e && e.kind === "image" && e.status === "done" ? galleryMediaUrl(e) : null;
    if (e && src) out.push({ key: `${b.id}:item${i}`, src, alt: e.prompt ? clip(e.prompt) : e.title ?? "image", title: e.title ?? "image", prompt: e.prompt ?? prompt, path: e.path ?? undefined });
  });
  return out;
}

export type TurnInfo = { own: Record<string, ChatImage[]>; turn: Record<string, ChatImage[]>; end: Set<string> };

/** Group the visible messages into turns (a run of assistant messages between user messages) and collect each
 *  message's images (`own`), its turn's images in order (`turn`, the same array for every message of the turn) and
 *  the id of the turn's last assistant message (`end`, where the summary strip goes). A turn with no images has
 *  no `end` entry. */
export function turnImages(messages: Msg[], results: Record<string, Block>, runs: Record<string, ToolRun>, gallery: GalleryEntry[]): TurnInfo {
  const info: TurnInfo = { own: {}, turn: {}, end: new Set() };
  let group: Msg[] = [];
  const flush = () => {
    const all: ChatImage[] = [];
    for (const m of group) {
      const own = m.content.flatMap((b) => (b.type === "tool_use" ? callImages(b, results[b.id], runs[b.id], gallery) : []));
      info.own[m.id] = own;
      all.push(...own);
    }
    if (all.length) {
      for (const m of group) info.turn[m.id] = all;
      info.end.add(group[group.length - 1].id);
    }
    group = [];
  };
  for (const m of messages) {
    if (m.role === "assistant" && !m.meta?.notice && !m.meta?.error) group.push(m);
    else flush();
  }
  flush();
  return info;
}

/** Open the viewer on image `index` of `images`. */
export const ChatImageOpenContext = createContext<(images: ChatImage[], index: number) => void>(() => {});

/** The viewer state for a chat: provide `open` through ChatImageOpenContext and render `viewer`. */
export function useChatImageViewer() {
  const [state, setState] = useState<{ images: ChatImage[]; index: number } | null>(null);
  const open = useCallback((images: ChatImage[], index: number) => setState({ images, index }), []);
  const close = useCallback(() => setState(null), []);
  let viewer = null;
  if (state && state.images[state.index]) {
    const { images, index } = state;
    const im = images[index];
    const e: LightboxEntry = { id: im.key, kind: "image", path: im.path ?? null, url: null, src: im.src, title: im.title, prompt: im.prompt, created_at: 0, source: "tool", status: "done" };
    const go = (d: number) => setState((s) => (s ? { ...s, index: (s.index + d + s.images.length) % s.images.length } : s));
    viewer = <Lightbox e={e} onClose={close} nav={{ index, count: images.length, go }} />;
  }
  return { open, viewer };
}

/** A call's images in the chat column, at the call's place: fit the width, keep the aspect ratio, lazy-loaded. */
export function InlineImages({ images, turn }: { images: ChatImage[]; turn: ChatImage[] }) {
  const open = useContext(ChatImageOpenContext);
  if (!images.length) return null;
  return (
    <div className="my-1.5 flex flex-wrap gap-2" data-testid="inline-images">
      {images.map((im) => (
        <button key={im.key} type="button" className="rounded border border-line overflow-hidden bg-sunken hover:border-action focus-visible:border-action max-w-full"
          aria-label={`Open image: ${im.alt}`} onClick={() => open(turn, Math.max(0, turn.findIndex((t) => t.key === im.key)))}>
          <img src={im.src} alt={im.alt} loading="lazy" decoding="async" className="block max-w-full max-h-[360px] w-auto h-auto object-contain" />
        </button>
      ))}
    </div>
  );
}

/** The end-of-turn summary: small thumbnails of every image in the turn, in order, scrolling sideways. */
export function TurnStrip({ images }: { images: ChatImage[] }) {
  const open = useContext(ChatImageOpenContext);
  if (!images.length) return null;
  return (
    <div role="list" aria-label={`${images.length} image${images.length === 1 ? "" : "s"} in this reply`} data-testid="turn-strip"
      className="mt-2 flex gap-1.5 overflow-x-auto scroll-thin pb-1">
      {images.map((im, i) => (
        <div role="listitem" key={im.key} className="shrink-0">
          <button type="button" className="block size-16 rounded-md border border-line bg-sunken overflow-hidden hover:border-action focus-visible:border-action"
            aria-label={`Open image ${i + 1} of ${images.length}: ${im.alt}`} onClick={() => open(images, i)}>
            <img src={im.src} alt="" loading="lazy" decoding="async" className="size-full object-cover" />
          </button>
        </div>
      ))}
    </div>
  );
}
