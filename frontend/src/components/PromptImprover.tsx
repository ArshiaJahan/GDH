import { CircleAlert, CircleCheck, CircleHelp, ClipboardList, CirclePause, SkipForward } from "lucide-react";
import { useState } from "react";
import { post } from "../lib/api";

export type PromptImproverOutcome = {
  status: "proceeded" | "asked" | "bypassed" | "unavailable" | "paused"; reason: string; questions_asked: number; calls: number;
  estimated_tokens: number; item_ids: string[]; task_code: string | null;
};
export type TaskCardView = {
  goal?: string; scope?: string[]; out_of_scope?: string[];
  acceptance_criteria?: { id: string; expected: string; verification?: string }[];
  quality_ladder_level?: string; assumptions?: string[]; risks?: string[];
  route?: { skills?: string[]; unity_route?: string; harness?: string };
};
type Saved = { task_code: string; task_link: string };

const STATUS: Record<PromptImproverOutcome["status"], { label: string; Icon: typeof CircleCheck; tone: string }> = {
  proceeded: { label: "Task card ready", Icon: CircleCheck, tone: "text-ok" },
  asked: { label: "Asked questions", Icon: CircleHelp, tone: "text-action" },
  bypassed: { label: "Skipped", Icon: SkipForward, tone: "text-muted" },
  unavailable: { label: "Prompt improver unavailable", Icon: CircleAlert, tone: "text-warn" },
  paused: { label: "Paused", Icon: CirclePause, tone: "text-warn" },
};

function List({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return <div className="mt-2"><div className="label">{title}</div><ul className="list-disc pl-5 text-[13px]">{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div>;
}

/** The prompt improver's result in the chat: what it did, the task-card preview and Save to Tasks. */
export function PromptImprover({ outcome, card, itemId, taskCode, sessionId, onSaved }: {
  outcome: PromptImproverOutcome; card?: TaskCardView | null; itemId?: string | null; taskCode?: string | null;
  sessionId: string; onSaved?: (r: Saved) => void;
}) {
  const [code, setCode] = useState<string | null>(taskCode ?? outcome.task_code ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const st = STATUS[outcome.status] ?? STATUS.unavailable;
  const unavailable = outcome.status === "unavailable";
  const canSave = (outcome.status === "proceeded" || outcome.status === "asked") && !!itemId && !code;
  const save = async () => {
    if (!itemId) return;
    setBusy(true); setError(null);
    try {
      const r = await post<Saved>(`/sessions/${sessionId}/prompt-improver/${itemId}/save`);
      setCode(r.task_code);
      onSaved?.(r);
    } catch (e: any) {
      const msg = String(e?.message ?? "");
      setError(/404|no such/i.test(msg) ? "This card can't be saved to Tasks." : (msg || "Couldn't save the task"));
    } finally { setBusy(false); }
  };
  return (
    <div role="note" aria-label="Prompt improver" data-status={outcome.status}
      className={`my-3 rounded-md border px-3 py-2 text-[13px] ${unavailable ? "border-warn/50" : "border-line surface-raised"}`}>
      <div className={`flex items-center gap-2 ${st.tone}`}>
        <st.Icon size={14} className="shrink-0" />
        <span className="font-medium">{st.label}</span>
        {outcome.reason && <span className="text-muted">{outcome.reason}</span>}
      </div>
      {outcome.status === "bypassed" && <div className="text-faint mt-1">Start a message with * to skip the prompt improver.</div>}
      {card && (
        <div className="mt-2" data-testid="pi-card">
          {card.goal && <div><span className="label">Goal</span><div>{card.goal}</div></div>}
          <List title="Scope" items={card.scope} />
          {!!card.acceptance_criteria?.length && (
            <div className="mt-2"><div className="label">Acceptance criteria</div>
              <ul className="list-disc pl-5">{card.acceptance_criteria.map((a) => <li key={a.id}>{a.expected}{a.verification && <span className="chip ml-2">{a.verification}</span>}</li>)}</ul>
            </div>
          )}
          {card.quality_ladder_level && <div className="mt-2"><span className="label">Ladder level</span> <span className="chip">{card.quality_ladder_level}</span></div>}
          <List title="Assumptions" items={card.assumptions} />
          <List title="Risks" items={card.risks} />
          {!!card.route?.skills?.length && <div className="mt-2 flex flex-wrap gap-1">{card.route.skills.map((s) => <span key={s} className="chip">{s}</span>)}</div>}
        </div>
      )}
      {(canSave || code || error) && (
        <div className="mt-2 flex items-center gap-2">
          {canSave && <button className="btn py-0.5" disabled={busy} onClick={save}>Save to Tasks</button>}
          {code && <span className="chip" data-testid="pi-task-code"><ClipboardList size={12} />{code}</span>}
          {error && <span role="alert" className="text-bad">{error}</span>}
        </div>
      )}
    </div>
  );
}
