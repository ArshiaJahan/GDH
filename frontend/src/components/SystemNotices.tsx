import { AlertTriangle, Copy, RotateCcw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { inTauri } from "../lib/api";
import { useStore } from "../lib/store";

/** What the desktop shell reports when the backend isn't there (lib.rs BackendExit). */
export type BackendExit = { kind: "exited" | "timeout" | "error"; message: string; code?: number | null; log_path: string; last_lines: string };

export const isBackendExit = (e: unknown): e is BackendExit =>
  !!e && typeof e === "object" && "log_path" in e && "message" in e;

/** Calls `onExit` when the desktop shell reports that the backend process stopped. */
export function useBackendExit(onExit: (e: BackendExit) => void) {
  const cb = useRef(onExit);
  cb.current = onExit;
  useEffect(() => {
    if (!inTauri()) return;
    let unlisten: (() => void) | undefined;
    let gone = false;
    import("@tauri-apps/api/event").then(({ listen }) =>
      listen<BackendExit>("backend-exited", (e) => cb.current(e.payload)).then((u) => (gone ? u() : (unlisten = u))));
    return () => {
      gone = true;
      unlisten?.();
    };
  }, []);
}

/** Full-window screen when GameDevWorkstation's engine (the backend) stopped: why, its log and Restart. */
export function EngineStopped({ exit }: { exit: BackendExit }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const restart = async () => {
    setBusy(true);
    setErr(null);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("restart_backend");
      sessionStorage.removeItem("ws-seq");
      window.location.reload(); // reconnects through backend_info, which waits for the new engine
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      setBusy(false);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(exit.log_path);
      setCopied(true);
    } catch {}
  };
  const stopped = exit.kind === "exited";
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-8 bg-bg" role="alertdialog" aria-modal="true"
      aria-labelledby="engine-stopped-title" aria-describedby="engine-stopped-desc">
      <div className="max-w-2xl w-full">
        <h1 id="engine-stopped-title" ref={heading} tabIndex={-1} className="text-lg font-semibold mb-1 flex items-center gap-2 outline-none">
          <AlertTriangle size={18} className="text-bad" /> {stopped ? "GameDevWorkstation's engine stopped" : "GameDevWorkstation's engine didn't start"}
        </h1>
        <p id="engine-stopped-desc" className="text-muted mb-3">
          {exit.message} Your sessions are saved. Restart the engine to continue; if it keeps stopping, the log below says why.
        </p>
        <div className="flex items-center gap-2 mb-2 text-[12.5px]">
          <span className="text-muted">Log:</span>
          <code className="font-mono truncate flex-1 min-w-0" title={exit.log_path}>{exit.log_path}</code>
          <button className="btn py-0.5" onClick={copy} aria-label="Copy the log file's path"><Copy size={13} /> {copied ? "Copied" : "Copy path"}</button>
        </div>
        {exit.last_lines && (
          <pre className="font-mono text-[11.5px] bg-sunken rounded p-2 max-h-72 overflow-auto whitespace-pre-wrap mb-3" aria-label="Last lines of the log">{exit.last_lines}</pre>
        )}
        {err && <p className="text-bad text-[13px] mb-2" role="alert">{err}</p>}
        {inTauri() && (
          <button className="btn btn-primary" onClick={restart} disabled={busy}><RotateCcw size={14} /> {busy ? "Restarting…" : "Restart"}</button>
        )}
      </div>
    </div>
  );
}

/** Banner when config.toml couldn't be read at startup and the app runs on the defaults. */
export function ConfigErrorBanner() {
  const err = useStore((s) => s.appState?.config_error) as { message: string; error: string; broken_path: string; at: number } | null | undefined;
  const key = err ? `config-error-dismissed:${err.at}` : "";
  const [hidden, setHidden] = useState(() => !!key && sessionStorage.getItem(key) === "1");
  if (!err || hidden) return null;
  return (
    <div role="alert" className="flex items-start gap-2 border-b border-line px-4 py-2 text-[13px] surface-raised">
      <AlertTriangle size={15} className="text-warn mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <div>{err.message}</div>
        <div className="text-muted text-[12px] break-all">{err.error}</div>
      </div>
      <button className="btn btn-ghost px-1 py-0.5" aria-label="Dismiss" title="Dismiss"
        onClick={() => { sessionStorage.setItem(key, "1"); setHidden(true); }}><X size={14} /></button>
    </div>
  );
}
