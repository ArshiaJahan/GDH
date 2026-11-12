import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { post, type ApprovalButton } from "../lib/api";
import type { Approval } from "../lib/store";
import { SafeMarkdown } from "./SafeMarkdown";
import { EffortMeter, fmtUsd, modelLabel } from "./ui";

const KIND_TITLE: Record<string, string> = {
  effort: "Allow effort above high?",
  command: "Run this command?",
  edit: "Allow this edit?",
  delete: "Delete this file?",
  elevenlabs: "Run this ElevenLabs generation?",
  shared_tool: "Run a job on another machine's tools?",
  mcp_tool: "Run this MCP tool?",
  mcp_install: "Add this MCP server?",
  skill_install: "Install this skill?",
  hook_trust: "Trust this hook file?",
};

/** Kinds with their own body below; any other kind gets the generic card (payload.subject,
 *  payload.markdown, payload.buttons, payload.note; see lib/api.ts GenericApprovalPayload). */
const DEDICATED = new Set(["effort", "command", "edit", "delete", "elevenlabs", "shared_tool", "mcp_tool", "mcp_install", "skill_install"]);

/** Small estimates read better as "<$0.01" than "$0.0004". */
const fmtEstimate = (n: number) => (n > 0 && n < 0.01 ? "<$0.01" : fmtUsd(n));

export function ApprovalCard({ a }: { a: Approval }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const p = a.payload ?? {};
  const generic = !DEDICATED.has(a.kind);
  const decide = async (decision: "approve" | "downgrade" | "deny", choice?: string) => {
    setBusy(true);
    try {
      await post(`/approvals/${a.id}`, generic ? { decision, choice, note: p.note ? note : undefined } : { decision });
    } finally {
      setBusy(false);
    }
  };
  const done = a.status !== "pending";
  const buttons: ApprovalButton[] | null = generic && Array.isArray(p.buttons) && p.buttons.length ? p.buttons : null;
  return (
    <div className={`my-3 rounded-md border ${done ? "border-line opacity-70" : "border-warn"} surface-raised`} role="group"
      aria-labelledby={`approval-${a.id}`}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-line">
        <ShieldAlert size={15} className="text-warn" aria-hidden />
        {/* role=alert: announced as soon as the card appears, wherever it is shown */}
        <span id={`approval-${a.id}`} className="font-medium" role={done ? undefined : "alert"}>
          {done ? "" : <span className="sr-only">Approval needed: </span>}{KIND_TITLE[a.kind] ?? (generic && p.subject ? p.subject : "Approve?")}
        </span>
        {p.role === "subagent" && <span className="chip">from subagent</span>}
        {done && <span className="ml-auto chip">{a.status}</span>}
      </div>
      <div className="px-3 py-2 text-[13px] space-y-1.5">
        {a.kind === "effort" && (
          <>
            <div className="flex items-center gap-2">
              <span className="text-muted w-24">For</span>
              <span>{p.subagent ?? p.subject}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted w-24">Effort</span>
              <EffortMeter effort={p.effort} /> <span>{p.effort}</span>
              {p.model && <span className="text-muted" title={p.model}>on {modelLabel(p.model, p.tier)}</span>}
            </div>
            {p.reason && <div className="flex gap-2"><span className="text-muted w-24 shrink-0">Why</span><span>{p.reason}</span></div>}
            <div className="flex items-center gap-2" title={p.est_basis}>
              <span className="text-muted w-24 shrink-0">Extra cost</span>
              {p.est_extra_time_s != null ? (
                // Main session: estimated per turn by the backend (agent/loop.py estimate_above_high).
                <span>≈ {fmtEstimate(p.est_extra_cost_usd)}, ≈ +{Math.round(p.est_extra_time_s)}s <span className="text-muted">(estimate{p.est_per ? `, per ${p.est_per}` : ""})</span></span>
              ) : (
                <>
                  <span>{p.est_extra_cost_usd != null ? `≈ ${fmtEstimate(p.est_extra_cost_usd)} (estimate)` : "unknown"}</span>
                  {p.est_extra_time && <span className="text-muted">· {p.est_extra_time}</span>}
                </>
              )}
            </div>
          </>
        )}
        {a.kind === "command" && (
          <>
            <pre className="font-mono text-[12.5px] bg-sunken rounded px-2 py-1.5 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{p.command}</pre>
            <div className="text-muted">in {p.cwd}</div>
          </>
        )}
        {(a.kind === "edit" || a.kind === "delete") && (
          <>
            <div className="font-mono text-[12.5px] break-words [overflow-wrap:anywhere]">{p.path ?? p.subject}</div>
            {p.old != null && (
              <div className="grid grid-cols-2 gap-2 font-mono text-[12px]">
                <pre className="bg-sunken rounded p-1.5 whitespace-pre-wrap max-h-40 overflow-auto" style={{ color: "var(--bad)" }}>{p.old}</pre>
                <pre className="bg-sunken rounded p-1.5 whitespace-pre-wrap max-h-40 overflow-auto" style={{ color: "var(--ok)" }}>{p.new}</pre>
              </div>
            )}
            {p.bytes != null && <div className="text-muted">{p.bytes.toLocaleString()} characters</div>}
          </>
        )}
        {a.kind === "elevenlabs" && (
          <>
            <div>{p.feature}: {p.characters?.toLocaleString()} characters{p.est_credits ? ` · about ${p.est_credits.toLocaleString()} credits` : ""}</div>
            {p.preview && <div className="text-muted line-clamp-3">{p.preview}</div>}
          </>
        )}
        {a.kind === "mcp_install" && (
          <>
            <div><span className="font-medium">{p.name}</span>{p.description && <span className="text-muted"> · {p.description}</span>}</div>
            <pre className="font-mono text-[12.5px] bg-sunken rounded px-2 py-1.5 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{p.command ?? p.url}</pre>
            <div className="text-muted">{p.transport === "http" ? "Connects to this URL" : "Runs this command on your Mac"} whenever a session uses its tools.</div>
            {p.source_url && <div className="text-muted break-words [overflow-wrap:anywhere]">Source: <a href={p.source_url} target="_blank" rel="noreferrer" className="underline">{p.source_url}</a></div>}
            {p.env && Object.keys(p.env).length > 0 && (
              <div>
                <div className="text-muted">With these environment variables:</div>
                <pre className="font-mono text-[12.5px] bg-sunken rounded px-2 py-1.5 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                  {Object.entries(p.env as Record<string, string>).map(([k, v]) => `${k}=${v}`).join("\n")}
                </pre>
              </div>
            )}
            {p.required_env?.length > 0 && <div>Needs from you: <span className="font-mono">{p.required_env.join(", ")}</span> (not stored by the assistant)</div>}
          </>
        )}
        {a.kind === "skill_install" && (
          <>
            <div><span className="font-medium">{p.name}</span>{p.description && <span className="text-muted"> · {p.description}</span>}</div>
            {p.source_url ? (
              <div className="text-muted break-all">Source: <a href={p.source_url} target="_blank" rel="noreferrer" className="underline">{p.source_url}</a>
                {p.fetched_url && p.fetched_url !== p.source_url && <> (fetched {p.fetched_url})</>}</div>
            ) : (
              <div className="text-muted">Written by the Skills assistant (it may have read web pages while writing it).</div>
            )}
            <div className="text-muted">Its instructions become part of the agent's system prompt in every session that turns it on.{p.replaces ? " It replaces the skill with the same name." : ""}</div>
            <pre className="font-mono text-[12px] bg-sunken rounded px-2 py-1.5 whitespace-pre-wrap break-words max-h-72 overflow-auto" aria-label="SKILL.md">{p.skill_md}</pre>
            {p.skill_md_lines > 200 && <div className="text-muted">First 200 of {p.skill_md_lines} lines of SKILL.md.</div>}
            {p.files?.length > 0 && (
              <div>
                <div className="text-muted">Also saves these files from the same folder:</div>
                <ul className="font-mono text-[12px]">{(p.files as { path: string; bytes: number }[]).map((f) => <li key={f.path}>{f.path} <span className="text-muted">({f.bytes.toLocaleString()} bytes)</span></li>)}</ul>
              </div>
            )}
            {p.skipped?.length > 0 && <div className="text-muted">Skipped: {(p.skipped as string[]).join("; ")}</div>}
          </>
        )}
        {a.kind === "shared_tool" && <div>{p.tool} on {p.machine}: {p.summary}</div>}
        {generic && (
          <>
            {KIND_TITLE[a.kind] && p.subject && <div className="font-medium">{p.subject}</div>}
            {p.markdown && <div className="prose-ws max-h-96 overflow-auto"><SafeMarkdown text={String(p.markdown)} /></div>}
            {p.note && !done && (
              <label className="block">
                <span className="text-muted">{p.note.label ?? "Note"}</span>
                <textarea className="input w-full mt-1 min-h-16" value={note} placeholder={p.note.placeholder ?? ""}
                  onChange={(e) => setNote(e.target.value)} />
              </label>
            )}
            {p.answer?.choice && <div className="text-muted">Answered: {(buttons ?? []).find((b) => b.id === p.answer.choice)?.label ?? p.answer.choice}</div>}
          </>
        )}
        {a.kind === "mcp_tool" && (
          <>
            <div><span className="font-medium">{p.tool}</span> <span className="text-muted">from {p.server}</span></div>
            <pre className="font-mono text-[12.5px] bg-sunken rounded px-2 py-1.5 whitespace-pre-wrap break-all">{p.summary}</pre>
            {p.hints?.length > 0 && <div className="text-muted">The server says this tool {(p.hints as string[]).join("; ")}.</div>}
          </>
        )}
      </div>
      {!done && buttons && (
        <div className="flex flex-wrap gap-2 px-3 py-2 border-t border-line">
          {buttons.map((b) => (
            <button key={b.id} className={`btn ${b.style === "primary" ? "btn-primary" : b.style === "ghost" ? "btn-ghost" : ""}`} disabled={busy}
              onClick={() => decide(b.decision === "deny" ? "deny" : "approve", b.id)}>{b.label}</button>
          ))}
        </div>
      )}
      {!done && !buttons && (
        <div className="flex gap-2 px-3 py-2 border-t border-line">
          <button className="btn btn-primary" disabled={busy} onClick={() => decide("approve")}>Approve</button>
          {a.kind === "effort" && <button className="btn" disabled={busy} onClick={() => decide("downgrade")}>Run at high instead</button>}
          <button className="btn btn-ghost" disabled={busy} onClick={() => decide("deny")}>{a.kind === "effort" ? "Cancel" : "Decline"}</button>
        </div>
      )}
    </div>
  );
}
