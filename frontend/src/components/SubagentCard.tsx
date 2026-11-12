import { GitBranch, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { post } from "../lib/api";
import { useStore, type Block } from "../lib/store";
import { toolRenderers } from "./toolRenderers";
import { GenericToolCall } from "./Chat";
import { EffortMeter, fmtDuration, fmtTokens, fmtUsd, modelName, providerOf, useModelCatalog } from "./ui";

/** A subagent as a "channel strip": provider color rail, tier, effort meter, live tokens and cost. */
export function SubagentCard({ b, result }: { b: Block; result?: Block }) {
  useModelCatalog();
  const resultText: string = result?.content?.[0]?.text ?? "";
  const subId = (resultText.match(/\b(sub_[0-9a-f]{16})\b/) ?? [])[1];
  const card = useStore((s) => (subId ? s.subagents[subId] : undefined));
  const [open, setOpen] = useState(false);
  const [, tick] = useState(0);
  const running = card ? card.status === "running" || card.status === "queued" : !result;
  useEffect(() => { if (!running) return; const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, [running]);

  const tier: string = card?.tier ?? b.input.tier;
  const model: string = card?.model ?? "";
  const prov = providerOf(model || (tier?.startsWith("codex") ? "gpt" : "claude"));
  const status = card?.status ?? (result ? (result.is_error ? "failed" : "started") : "launching");
  const elapsed = card ? (card.ended ?? Date.now() / 1000) - card.started : 0;
  const statusColor = status === "failed" ? "var(--bad)" : status === "done" ? "var(--ok)" : status === "cancelled" ? "var(--faint)" : "var(--action)";

  return (
    <div className="my-2 rounded-md border border-line surface-raised overflow-hidden flex" role="group" aria-label={`Subagent ${b.input.name}`}>
      <div className="w-1 shrink-0" style={{ background: `var(--${prov})` }} aria-hidden />
      {/* A container: below 42rem (672px) of card width the metrics move to a second line, and the
          name and status always stay readable (the status is never clipped). */}
      <div className="flex-1 min-w-0 @container">
        <div className="flex items-start">
        <button className="flex-1 min-w-0 flex flex-wrap items-center gap-x-2 gap-y-0.5 px-2.5 py-1.5 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
          <span className="font-medium min-w-[7rem] flex-1 @2xl:flex-none @2xl:max-w-[12rem] @2xl:truncate break-words [overflow-wrap:anywhere]" title={b.input.name}>{b.input.name}</span>
          <span className="order-2 @2xl:order-3 shrink-0 inline-flex items-center gap-1 text-[12px] whitespace-nowrap">
            <span className={`size-2 rounded-full ${running ? "animate-pulse" : ""}`} style={{ background: statusColor }} />{status}
          </span>
          <span className="order-3 @2xl:order-2 basis-full @2xl:basis-auto @2xl:flex-1 min-w-0 flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="text-[12px] whitespace-nowrap" title={model || undefined}>{modelName(model || tier)}</span>
            <span className="chip shrink-0 whitespace-nowrap">{tier}</span>
            <span className="inline-flex items-center gap-1 text-[12px] text-muted whitespace-nowrap"><EffortMeter effort={card?.effort ?? b.input.effort} />{card?.effort ?? b.input.effort ?? "low"}</span>
            {card?.worktree && <GitBranch size={13} className="text-muted shrink-0"><title>Own git worktree</title></GitBranch>}
            {card && (
              <span className="@2xl:ml-auto flex flex-wrap items-center gap-x-3 text-[12px] tabular-nums whitespace-nowrap">
                <span className="text-muted">{fmtTokens(card.tokens.input)} in · {fmtTokens(card.tokens.output)} out</span>
                <span>{fmtUsd(card.cost_usd)}</span>
                <span className="text-muted">{fmtDuration(elapsed)}</span>
              </span>
            )}
          </span>
        </button>
        {running && card && <button className="btn btn-ghost px-1.5 mr-1 mt-1" title="Stop this subagent" aria-label="Stop subagent" onClick={() => post(`/subagents/${card.id}/stop`)}><Square size={12} /></button>}
        </div>
        {open && (
          <div className="px-2.5 pb-2 space-y-1.5 text-[12.5px]">
            <div className="label">Brief</div>
            <pre className="whitespace-pre-wrap bg-sunken rounded p-1.5 max-h-48 overflow-auto font-sans">{b.input.instructions}</pre>
            {(card?.result_preview || card?.error) && (
              <>
                <div className="label">{card?.error ? "Error" : "Result"}</div>
                <pre className={`whitespace-pre-wrap bg-sunken rounded p-1.5 max-h-60 overflow-auto font-sans ${card?.error ? "text-bad" : ""}`}>{card?.error ?? card?.result_preview}</pre>
              </>
            )}
            {!card && resultText && <pre className="whitespace-pre-wrap bg-sunken rounded p-1.5 font-sans">{resultText}</pre>}
          </div>
        )}
      </div>
    </div>
  );
}

function SubagentResults({ b, result }: { b: Block; result?: Block }) {
  return <GenericToolCall b={{ ...b, name: "collect results" }} result={result} />;
}

toolRenderers.spawn_subagent = SubagentCard;
toolRenderers.get_subagent_result = SubagentResults;
