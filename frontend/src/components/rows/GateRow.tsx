import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import type { GateMeta } from "../../lib/api";
import type { Msg } from "../../lib/store";
import { RowShell, msgText } from "./RowShell";

/** Split a gate message ("[Workspace gate <id>] <reason>\n\n<untrusted-…>evidence</untrusted-…>")
 *  into the reason and the quoted evidence (the untrusted markers are for the model, not people). */
export function splitGateText(text: string, id: string): { reason: string; evidence: string } {
  let t = text.trim();
  const head = `[Workspace gate ${id}]`;
  if (t.startsWith(head)) t = t.slice(head.length).trim();
  const m = t.match(/<untrusted-[0-9a-f]+ source="[^"]*">\n?([\s\S]*?)\n?<\/untrusted-[0-9a-f]+>/);
  if (!m || m.index == null) return { reason: t, evidence: "" };
  return { reason: t.slice(0, m.index).trim(), evidence: m[1].trim() };
}

/** The short "· 3 compile errors" part: the reason up to its first sentence or "after …". */
export function gateSummary(reason: string): string {
  const first = reason.split("\n")[0].split(/ after this turn|\. /)[0].replace(/\.$/, "").trim();
  return first.length > 70 ? first.slice(0, 69) + "…" : first;
}

const STATUS_WORD: Record<string, string> = { fail: "failed", pass: "passed", skipped: "skipped", error: "errored" };

/** meta.gate: a gate result the agent was asked to act on (a failing pre_complete gate):
 *  "Gate unity.compile failed (attempt 1/2) · 3 compile errors", expandable to the reason and the
 *  evidence it quoted (Unity console errors, failing tests, command output). */
export function GateRow({ m }: { m: Msg }) {
  const g = m.meta.gate as GateMeta;
  const status = g.status ?? "fail";
  const word = STATUS_WORD[status] ?? status;
  const { reason, evidence } = splitGateText(msgText(m.content), g.id);
  const summary = gateSummary(reason);
  const last = status === "fail" && g.max != null && g.attempt >= g.max;
  const Icon = status === "pass" ? ShieldCheck : status === "fail" ? ShieldAlert : ShieldQuestion;
  const details = reason || evidence ? (
    <div className="space-y-1.5">
      {reason && <p className="whitespace-pre-wrap">{reason}</p>}
      {evidence && (
        <pre className="font-mono text-[11.5px] whitespace-pre-wrap max-h-72 overflow-auto bg-sunken rounded px-2 py-1">{evidence}</pre>
      )}
      <p className="text-[11px]">
        {g.level ? `Level ${g.level} · ` : ""}{g.hook && g.hook !== g.id ? `hook ${g.hook} · ` : ""}
        {status !== "fail" ? "" : last ? "Last automatic attempt: if it still fails, it's handed to you."
          : "The agent was asked to fix it before finishing."}
      </p>
    </div>
  ) : undefined;
  return (
    <RowShell icon={<Icon size={13} />} tone={status === "fail" ? (last ? "bad" : "warn") : "muted"}
      label={`Gate ${g.id} ${word}`} details={details}>
      <span>Gate {g.id} {word}{g.max != null ? ` (attempt ${g.attempt}/${g.max})` : ""}</span>
      {summary && <span className="opacity-80"> · {summary}</span>}
    </RowShell>
  );
}
