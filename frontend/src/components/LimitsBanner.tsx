import { Info, PauseCircle, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import { actions, useStore, type LimitPause } from "../lib/store";
import { Popover } from "./Popover";
import { fmtUsd } from "./ui";

/** A spend-limit pause on one line: what's paused, spend vs limit (truncated; the full text is in
 *  Details), Resume today / Resume this session, and a link to the limit settings. */
function PauseBar({ p, onResume, compact }: { p: LimitPause; onResume: () => Promise<void>; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [details, setDetails] = useState(false);
  const global = p.scope === "global";
  const what = global ? "today" : "this session";
  const summary = `${fmtUsd(p.spent_usd)} of ${fmtUsd(p.limit_usd)} ${what}`;
  const full = `${global ? "Daily spend limit reached" : "Session spend limit reached"}: ${summary}.${global ? " It resets at midnight." : ""}`;
  return (
    <div role="alert" className={`flex items-center gap-2 px-4 h-9 text-[13px] border-b border-warn whitespace-nowrap ${compact ? "" : "surface-raised"}`}
      style={{ background: "color-mix(in srgb, var(--warn) 14%, transparent)" }}>
      <PauseCircle size={15} className="text-warn shrink-0" />
      <span className="font-medium shrink-0">{global ? "All agents paused" : "Session paused"}</span>
      <span className="text-muted min-w-0 truncate" title={full}>{global ? "Daily" : "Session"} limit: {summary}{global ? " · resets at midnight" : ""}</span>
      <div className="relative shrink-0">
        <button className="btn btn-ghost p-1" title="Details" aria-label="Spend limit details" aria-expanded={details} onClick={() => setDetails(!details)}><Info size={14} /></button>
        <Popover open={details} onClose={() => setDetails(false)} label="Spend limit details" className="w-72 p-3 text-[12.5px] whitespace-normal">
          <p>{full}</p>
          <p className="text-muted mt-1.5">
            Resuming allows up to another {fmtUsd(p.limit_usd)} {what} before {global ? "everything pauses" : "this session pauses"} again.
            {global && " Raising the daily limit lifts the pause too."}
          </p>
        </Popover>
      </div>
      <div className="ml-auto flex items-center gap-1 shrink-0">
        <button className="btn btn-primary py-0.5" disabled={busy} title={`Allows up to another ${fmtUsd(p.limit_usd)} ${what} before pausing again`}
          onClick={async () => { setBusy(true); try { await onResume(); } finally { setBusy(false); } }}>{global ? "Resume today" : "Resume this session"}</button>
        <button className="btn btn-ghost p-1" title="Limit settings" aria-label="Limit settings" onClick={() => actions.go("settings", { section: "delegation" })}><Settings size={14} /></button>
      </div>
    </div>
  );
}

/** Top of the main area while the daily limit pauses everything. Re-checks every minute so it
 *  disappears after midnight even when nothing else runs. */
export function GlobalLimitBanner() {
  const p = useStore((s) => s.limits.global);
  useEffect(() => {
    if (!p) return;
    const t = setInterval(() => actions.loadLimits().catch(() => {}), 60_000);
    return () => clearInterval(t);
  }, [!!p]);
  if (!p) return null;
  return <PauseBar p={p} onResume={() => actions.resumeLimits()} />;
}

/** On a session's chat while its own spend limit pauses it. */
export function SessionLimitBanner({ sessionId }: { sessionId: string }) {
  const p = useStore((s) => s.limits.sessions[sessionId]);
  if (!p) return null;
  return <PauseBar p={p} compact onResume={() => actions.resumeLimits(sessionId)} />;
}
