// App updates: the sidebar banner, the "what's new" modal and the restarting overlay.
// The backend watches the updates folder and sends `update.available`; see features/updates.py.
import { ArrowRight, ArrowUpCircle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { get, post } from "../lib/api";
import { actions, useStore } from "../lib/store";
import { Modal, ModalFooter } from "./ui";

export type UpdatesStatus = {
  current: { version: string; git_commit: string | null; git_dirty: boolean; built_at: string | null; frozen: boolean };
  dir: string; dir_exists: boolean; check_interval_s: number;
  latest: Release | null; update: { latest: string } | null; history: Release[];
  previous: { version: string; app_path: string } | null;
  install_supported: boolean; reason: string | null; bundle_path: string | null;
  installing: { version: string } | null; busy_sessions: number; log_path: string;
};
export type Release = { version: string; built_at: string | null; git_commit: string | null; notes: string; app_path: string };

export function fmtBuilt(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Ask the backend to install (or roll back) and restart. It answers before the app quits. */
export async function installUpdate(opts: { version?: string; rollback?: boolean } = {}) {
  try {
    const r = await post(opts.rollback ? "/updates/rollback" : "/updates/install", opts.rollback ? {} : { version: opts.version });
    useStore.setState({ restarting: { version: r.version, from: r.from, rollback: opts.rollback, at: Date.now(), log: r.log }, updateOpen: false });
  } catch (e: any) {
    actions.toast(e.message, "error");
  }
}

/** Plain text with `code` spans (the backend's messages mention commands). */
export function Inline({ text }: { text: string }) {
  return <>{text.split("`").map((part, i) => (i % 2 ? <code key={i} className="font-mono text-[0.92em]">{part}</code> : part))}</>;
}

export function Notes({ text }: { text: string }) {
  if (!text.trim()) return <p className="text-[13px] text-muted">No notes for this version.</p>;
  return <div className="prose-ws text-[13px]"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown></div>;
}

/** "Update vX ready" where Install & restart works (the macOS app), "Update vX available" otherwise. */
export function updateHeadline(version: string, supported: boolean | undefined): string {
  return `Update v${version} ${supported === false ? "available" : "ready"}`;
}

/** Compact one-line notice above the sidebar footer. */
export function UpdateBanner() {
  const u = useStore((s) => s.update);
  if (!u) return null;
  const supported = u.install_supported !== false;
  return (
    // "Update" shows once the sidebar is wide enough; the version, state and action always fit.
    <div className="mb-1 @container">
      <button onClick={() => useStore.setState({ updateOpen: true })}
        title={supported ? `Update v${u.latest} is ready to install` : `Update v${u.latest} is available; see what's new`}
        className="w-full flex items-center gap-2 px-2 py-1 rounded border text-left text-[12.5px] leading-tight hover:bg-sunken"
        style={{ borderColor: "color-mix(in srgb, var(--action) 45%, var(--line))", background: "color-mix(in srgb, var(--action) 8%, transparent)" }}>
        <ArrowUpCircle size={15} className="text-action shrink-0" />
        <span className="min-w-0 truncate text-text"><span className="hidden @[17rem]:inline">Update </span>v{u.latest} {supported ? "ready" : "available"}</span>
        <span className="ml-auto shrink-0 text-action font-medium">{supported ? "Install" : "What's new"}</span>
      </button>
    </div>
  );
}

export function UpdateModal() {
  const open = useStore((s) => s.updateOpen);
  const u = useStore((s) => s.update);
  const [status, setStatus] = useState<UpdatesStatus | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) get<UpdatesStatus>("/updates").then(setStatus).catch(() => {});
  }, [open]);
  if (!open || !u) return null;
  const close = () => useStore.setState({ updateOpen: false });
  const rel = status?.latest?.version === u.latest ? status.latest : null;
  const supported = status?.install_supported ?? false;
  return (
    <Modal title={updateHeadline(u.latest, status?.install_supported ?? u.install_supported)} onClose={close}>
      <div className="flex items-center gap-2 mb-3 text-[13px]">
        <span className="chip font-mono">v{u.current}</span>
        <ArrowRight size={14} className="text-faint" />
        <span className="chip font-mono text-action">v{u.latest}</span>
        <span className="text-faint ml-1">{[fmtBuilt(u.built_at), u.git_commit].filter(Boolean).join(" · ")}</span>
      </div>
      <div className="mb-4 max-h-[40vh] overflow-auto scroll-thin"><Notes text={rel?.notes ?? u.notes} /></div>
      {status && !supported && (
        <p className="text-[12.5px] text-muted border border-line rounded px-3 py-2 mb-3"><Inline text={status.reason ?? ""} /></p>
      )}
      {status && supported && status.busy_sessions > 0 && (
        <p className="text-[12.5px] text-warn mb-3">
          {status.busy_sessions === 1 ? "One session is" : `${status.busy_sessions} sessions are`} still working; restarting stops {status.busy_sessions === 1 ? "it" : "them"}.
        </p>
      )}
      {supported && (
        <p className="text-[12px] text-faint mb-3">GameDevWorkstation quits, swaps in the new version and reopens. The current version is kept, so you can roll back from Settings → About & updates.</p>
      )}
      <ModalFooter>
        {supported || !status ? (
          <>
            <button className="btn" onClick={close}>Later</button>
            <button className="btn btn-primary" disabled={!supported || busy}
              onClick={async () => { setBusy(true); await installUpdate({ version: u.latest }); setBusy(false); }}>
              {busy ? <Loader2 size={14} className="animate-spin" /> : <ArrowUpCircle size={14} />} Install & restart
            </button>
          </>
        ) : (
          <button className="btn btn-primary" onClick={close}>Got it</button>
        )}
      </ModalFooter>
    </Modal>
  );
}

/** Covers the window once an install is accepted; the app quits a moment later. */
export function RestartingOverlay() {
  const r = useStore((s) => s.restarting);
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    setSlow(false);
    if (!r) return;
    const t = setTimeout(() => setSlow(true), 60_000);
    return () => clearTimeout(t);
  }, [r]);
  if (!r) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" role="alertdialog" aria-label="Restarting">
      <div className="surface-raised border border-line rounded-lg shadow-xl px-6 py-5 w-[420px] max-w-[92vw] text-center">
        <Loader2 size={22} className="animate-spin text-action mx-auto mb-3" />
        <div className="font-medium">{r.rollback ? `Rolling back to GameDevWorkstation ${r.version}…` : `Restarting into GameDevWorkstation ${r.version}…`}</div>
        <p className="text-[13px] text-muted mt-1">The app quits, swaps versions and reopens in a few seconds.</p>
        {slow && (
          <div className="mt-4 text-[12.5px] text-muted">
            <p>This is taking longer than expected; the old version is still running.{r.log && <> The log is at <code className="font-mono break-all">{r.log}</code>.</>}</p>
            <button className="btn mt-3" onClick={() => useStore.setState({ restarting: null })}>Dismiss</button>
          </div>
        )}
      </div>
    </div>
  );
}
