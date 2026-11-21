import { ChevronRight, GitBranch, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { get, post } from "../lib/api";
import { actions, useStore, type SessionSubagent } from "../lib/store";
import { subagentStatusColor } from "./SubagentCard";
import { EffortMeter, Empty, fmtDuration, fmtTokens, fmtUsd, modelName, providerOf, useModelCatalog } from "./ui";

type Detail = SessionSubagent & { result?: string | null; instructions?: string | null; brief?: string | null };

export const isLive = (st: string) => st === "running" || st === "queued";

/** This session's subagents, newest first (also the source of the tab's running badge). */
export function useSessionSubagents(sessionId: string): SessionSubagent[] {
  const all = useStore((s) => s.subagents);
  return useMemo(() => Object.values(all).filter((x) => x.session_id === sessionId).sort((a, b) => b.started - a.started), [all, sessionId]);
}

function Row({ sub }: { sub: SessionSubagent }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [failed, setFailed] = useState(false);
  const [, tick] = useState(0);
  const live = isLive(sub.status);
  useEffect(() => { if (!live) return; const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, [live]);
  // Fetched on first expand, and again when the run finishes so the result shows up.
  useEffect(() => {
    if (!open) return;
    let on = true;
    get<Detail>(`/subagents/${sub.id}`).then((d) => { if (on) { setDetail(d); setFailed(false); } }).catch(() => on && setFailed(true));
    return () => { on = false; };
  }, [open, sub.id, sub.status]);

  const prov = providerOf(sub.model || (sub.tier?.startsWith("codex") ? "gpt" : "claude"));
  const elapsed = (sub.ended ?? Date.now() / 1000) - sub.started;
  const brief = detail?.instructions ?? detail?.brief;
  const result = detail?.result ?? sub.result_preview;
  const worktree = detail?.worktree ?? sub.worktree;
  const error = detail?.error ?? sub.error;
  return (
    <li className="rounded-md border border-line surface-raised overflow-hidden flex" aria-label={`Subagent ${sub.name}`}>
      <div className="w-1 shrink-0" style={{ background: `var(--${prov})` }} aria-hidden />
      <div className="flex-1 min-w-0">
        <div className="flex items-start">
          <button className="flex-1 min-w-0 flex flex-wrap items-center gap-x-3 gap-y-0.5 px-2.5 py-1.5 text-left" aria-expanded={open} onClick={() => setOpen(!open)}>
            <ChevronRight size={14} className={`text-muted shrink-0 transition-transform ${open ? "rotate-90" : ""}`} aria-hidden />
            <span className="font-medium min-w-[7rem] flex-1 truncate" title={sub.name}>{sub.name}</span>
            <span className="inline-flex items-center gap-1 text-[12px] whitespace-nowrap">
              <span className={`size-2 rounded-full ${live ? "animate-pulse" : ""}`} style={{ background: subagentStatusColor(sub.status) }} />{sub.status}
            </span>
            <span className="inline-flex items-center gap-2 text-[12px] whitespace-nowrap">
              <span title={sub.model || undefined}>{modelName(sub.model || sub.tier)}</span>
              <span className="chip">{sub.tier}</span>
              <span className="inline-flex items-center gap-1 text-muted"><EffortMeter effort={sub.effort} />{sub.effort || "low"}</span>
              {sub.worktree && <GitBranch size={13} className="text-muted"><title>Own git worktree</title></GitBranch>}
            </span>
            <span className="flex items-center gap-x-3 text-[12px] tabular-nums whitespace-nowrap">
              <span className="text-muted">{fmtTokens(sub.tokens.input)} in · {fmtTokens(sub.tokens.output)} out</span>
              <span>{fmtUsd(sub.cost_usd)}</span>
              <span className="text-muted">{fmtDuration(elapsed)}</span>
            </span>
          </button>
          {live && <button className="btn btn-ghost px-1.5 mr-1 mt-1" title="Stop this subagent" aria-label={`Stop ${sub.name}`}
            onClick={() => post(`/subagents/${sub.id}/stop`).catch((e: any) => actions.toast(e.message, "error"))}><Square size={12} /></button>}
        </div>
        {open && (
          <div className="px-2.5 pb-2 space-y-1.5 text-[12.5px]">
            {failed && !detail && <div className="text-muted">Couldn't load the details.</div>}
            {!detail && !failed && <div className="text-muted">Loading…</div>}
            {brief && <><div className="label">Brief</div><pre className="whitespace-pre-wrap bg-sunken rounded p-1.5 max-h-48 overflow-auto font-sans select-text">{brief}</pre></>}
            {(result || error) && (
              <>
                <div className="label">{error ? "Error" : "Result"}</div>
                <pre className={`whitespace-pre-wrap bg-sunken rounded p-1.5 max-h-60 overflow-auto font-sans select-text ${error ? "text-bad" : ""}`}>{error ?? result}</pre>
              </>
            )}
            {worktree && <div><span className="text-muted">Worktree: </span><span className="font-mono text-[11.5px] break-all select-text">{worktree}</span></div>}
          </div>
        )}
      </div>
    </li>
  );
}

/** The Subagents tab: every subagent this session started, live. */
export function SubagentsTab({ sessionId }: { sessionId: string }) {
  useModelCatalog();
  const subs = useSessionSubagents(sessionId);
  return (
    <div className="h-full overflow-y-auto scroll-thin p-4 text-[13px]">
      {subs.length === 0 ? <Empty>No subagents in this session yet.</Empty> : <ul className="space-y-2" aria-label="Subagents">{subs.map((x) => <Row key={x.id} sub={x} />)}</ul>}
    </div>
  );
}
