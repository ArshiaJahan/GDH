// The "Find or create" (skills) and "Find and add" (MCP servers) boxes on the Skills & MCP page.
// A background assistant run (backend features/skill_assistant.py) streams its steps as
// assistant.updated events; MCP server and skill installs ask for approval inline.
import { AlertCircle, Check, Loader2, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { get, post } from "../lib/api";
import { actions, useStore, type AssistLink, type AssistRun } from "../lib/store";
import { ApprovalCard } from "./ApprovalCard";
import { SafeMarkdown } from "./SafeMarkdown";
import { fmtUsd, shortModel } from "./ui";

const COPY = {
  skill: {
    title: "Find or create a skill",
    hint: "Describe what the skill should help with. The assistant installs one from a trusted source, finds one on the web, or writes a new one.",
    placeholder: "Describe the skill you need…",
    button: "Find or create",
  },
  mcp: {
    title: "Find and add an MCP server",
    hint: "Describe the tools you want agents to have. The assistant finds a server (official ones first) and asks you before adding it.",
    placeholder: "Describe the MCP server you need…",
    button: "Find and add",
  },
} as const;

const TOOL_LABEL: Record<string, string> = {
  web_search: "Search", web_fetch: "Read", list_skills: "List skills", read_skill: "Read skill",
  create_skill: "Create skill", install_skill_from_url: "Install skill", list_mcp_servers: "List servers",
  add_mcp_server: "Add server", test_mcp_server: "Test server",
};

const ACTIVE = new Set(["running", "waiting"]);

export function AssistantBox({ kind, onFinished, onOpenSkill, onOpenServer }: {
  kind: "skill" | "mcp";
  onFinished: () => void;
  onOpenSkill?: (name: string) => void;
  onOpenServer?: (name: string) => void;
}) {
  const c = COPY[kind];
  const [text, setText] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const run = useStore((s) => (runId ? s.assistantRuns[runId] : undefined));
  const approval = useStore((s) => (run?.approval_id ? s.approvals[run.approval_id] : undefined));
  const active = !!run && ACTIVE.has(run.status);
  const lastStatus = useRef<string | undefined>(undefined);

  // Pick up a run that is still going (e.g. after leaving and coming back to the page).
  useEffect(() => {
    get<AssistRun[]>(`/assistant/runs?kind=${kind}&limit=1`).then((rs) => {
      const r = rs[0];
      if (r && ACTIVE.has(r.status)) {
        actions.upsertAssistantRun(r);
        setRunId(r.id);
      }
    }).catch(() => {});
  }, [kind]);

  // Refresh the list once when a run ends.
  useEffect(() => {
    const prev = lastStatus.current;
    lastStatus.current = run?.status;
    if (run && prev && ACTIVE.has(prev) && !ACTIVE.has(run.status)) onFinished();
  }, [run?.status]);

  // The approval card may have been raised before this page was listening.
  useEffect(() => {
    if (run?.approval_id && !approval) actions.loadApprovals().catch(() => {});
  }, [run?.approval_id, !!approval]);

  const start = async () => {
    const request = text.trim();
    if (!request || active) return;
    setStarting(true);
    try {
      const r = await post<{ run_id: string }>(`/assistant/${kind}`, { request });
      lastStatus.current = "running";
      setRunId(r.run_id);
      actions.upsertAssistantRun(await get<AssistRun>(`/assistant/runs/${r.run_id}`));
      setText("");
    } catch (e: any) {
      actions.toast(e.message, "error");
    } finally {
      setStarting(false);
    }
  };

  const openLink = (l: AssistLink) => (l.type === "skill" ? onOpenSkill?.(l.name) : onOpenServer?.(l.name));

  return (
    <div className="mt-3 rounded-md border border-line surface px-3 py-2.5" role="region" aria-label={c.title}>
      <div className="flex items-center gap-2 mb-1">
        <Sparkles size={14} className="text-muted" aria-hidden />
        <span className="font-medium">{c.title}</span>
        {run && !active && (
          <button className="btn btn-ghost px-1 py-0 ml-auto" title="Clear" aria-label="Clear result" onClick={() => setRunId(null)}><X size={13} /></button>
        )}
      </div>
      <p className="text-[13px] text-muted mb-2">{c.hint}</p>
      <textarea
        className="input h-16 resize-y text-[13px]"
        placeholder={c.placeholder}
        value={text}
        disabled={active}
        aria-label={c.placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); start(); } }}
      />
      <div className="flex items-center gap-2 mt-2">
        <button className="btn btn-primary" onClick={start} disabled={!text.trim() || active || starting}>
          {active || starting ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {active ? "Working…" : c.button}
        </button>
        {active && <button className="btn" onClick={() => post(`/assistant/runs/${run!.id}/cancel`)}>Cancel</button>}
        <span className="text-[12px] text-faint ml-auto">
          {run ? `${shortModel(run.model)} · ${run.effort}${run.cost_usd ? ` · ${fmtUsd(run.cost_usd)}` : ""}` : "⌘↵ to start"}
        </span>
      </div>

      {run && (
        <div className="mt-3 border-t border-line pt-2">
          <div className="text-[12px] text-muted mb-1 truncate" title={run.request}>“{run.request}”</div>
          {run.steps.length > 0 && (
            <ol className="space-y-0.5 text-[12.5px]" aria-label="Steps">
              {run.steps.map((s) => (
                <li key={s.id} className="flex items-start gap-1.5 min-w-0" title={s.output || undefined}>
                  <span className="mt-[3px] shrink-0">
                    {s.status === "running" ? <Loader2 size={12} className="animate-spin text-muted" />
                      : s.status === "error" ? <AlertCircle size={12} style={{ color: "var(--bad)" }} />
                      : <Check size={12} style={{ color: "var(--ok)" }} />}
                  </span>
                  <span className="shrink-0 font-medium">{TOOL_LABEL[s.tool] ?? s.tool}</span>
                  <span className="text-muted truncate">{s.label}</span>
                </li>
              ))}
            </ol>
          )}
          {active && !approval && !run.steps.some((s) => s.status === "running") && <div className="text-[12.5px] text-muted flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" /> Thinking…</div>}
          {approval && approval.status === "pending" && <ApprovalCard a={approval} />}
          {!active && run.result && (
            <div className="prose-ws text-[13px] mt-2">
              <SafeMarkdown text={run.result} />
            </div>
          )}
          {run.status === "failed" && run.error && <div className="text-[13px] text-bad mt-2">{run.error}</div>}
          {run.status === "cancelled" && <div className="text-[13px] text-muted mt-2">Cancelled.</div>}
          {!active && run.links.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {run.links.map((l) => (
                <button key={`${l.type}:${l.name}`} className="btn" onClick={() => openLink(l)}>
                  {l.type === "skill" ? `Open ${l.name}` : `Show ${l.name}`}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
