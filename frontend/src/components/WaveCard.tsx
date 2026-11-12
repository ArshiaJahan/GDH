import { GitBranch, GitMerge, Layers } from "lucide-react";
import { useEffect, useState } from "react";
import { get, type FleetUnit, type FleetWave } from "../lib/api";
import { actions, type Block } from "../lib/store";
import { GenericToolCall } from "./Chat";
import { toolRenderers } from "./toolRenderers";

/** What GET /api/waves/{id} and the `wave.updated` event carry beyond the base FleetWave type. */
export type WaveUnit = FleetUnit & {
  name?: string; branch?: string | null; worktree?: string | null; tier?: string | null; sub_status?: string | null;
  reason?: string | null; held?: string[]; conflicts?: string[];
  handoff?: { built?: string; decisions?: string; discoveries?: string; failures?: string; files?: string[] } | null;
};
export type WaveView = Omit<FleetWave, "units"> & { name?: string; units?: WaveUnit[]; merge_queue?: string[]; session_strikes?: number };

export const waveIdOf = (text: string): string | undefined => (text.match(/\bwave_[0-9a-f]{16}\b/) ?? [])[0];

const TONE: Record<string, string> = {
  running: "var(--action)", done: "var(--ok)", merged: "var(--ok)", ready: "var(--ok)", merging: "var(--action)",
  dead: "var(--bad)", conflict: "var(--bad)", stopped: "var(--bad)", held: "var(--warn)", paused: "var(--warn)",
  skipped: "var(--faint)", discarded: "var(--faint)", closed: "var(--faint)",
};
export const toneOf = (status?: string | null) => TONE[status ?? ""] ?? "var(--muted)";

/** A unit's one-line status: "dead · finished without a HANDOFF block", "held · 2 files outside scope". */
export function unitDetail(u: WaveUnit): string {
  if (u.status === "held" && u.held?.length) return `${u.held.length} file${u.held.length === 1 ? "" : "s"} outside its scope`;
  if (u.status === "conflict" && u.conflicts?.length) return `conflicts in ${u.conflicts.join(", ")}`;
  if (u.status === "dead") return u.reason ? `requeue · ${u.reason}` : "requeue";
  if (u.status === "running" && u.sub_status === "queued") return "queued";
  return "";
}

/** Before the backend answers: the units as the agent asked for them. */
function fromInput(b: Block): WaveUnit[] {
  const units: any[] = Array.isArray(b.input?.units) ? b.input.units : [];
  return units.map((u, i) => ({
    wave_id: "", sub_id: `pending-${i}`, name: String(u?.name ?? `unit ${i + 1}`), read_only: !!u?.read_only,
    scope: (Array.isArray(u?.scope) ? u.scope : []).map((s: string) => (u?.read_only && !/\(read-only\)$/i.test(s) ? `${s} (read-only)` : s)),
    status: "starting", merged: false, discoveries: null, tier: u?.tier ?? null,
  }));
}

/** A fleet wave (the run_wave tool call): units with their claimed scopes and status, the merge
 *  queue, the merge circuit breaker's strikes and each unit's HANDOFF discoveries. Live from
 *  `wave.updated`. */
export function WaveCard({ b, result }: { b: Block; result?: Block }) {
  const text: string = result?.content?.[0]?.text ?? "";
  const id = waveIdOf(text);
  const [wave, setWave] = useState<WaveView | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!id) return;
    let alive = true;
    get<WaveView>(`/waves/${id}`).then((w) => { if (alive) setWave(w); }).catch(() => {});
    const off = actions.onEvent((e) => { if (e.type === "wave.updated" && e.data?.id === id) setWave(e.data as WaveView); });
    return () => { alive = false; off(); };
  }, [id]);

  if (result?.is_error || (result && !id)) return <GenericToolCall b={b} result={result} />;

  const units: WaveUnit[] = wave?.units ?? fromInput(b);
  const status = wave?.status ?? (result ? "running" : "starting");
  const strikes = wave?.session_strikes ?? wave?.strikes ?? 0;
  const queue = (wave?.merge_queue ?? []).map((sid) => units.find((u) => u.sub_id === sid)?.name ?? sid);
  const merged = units.filter((u) => u.merged).length;
  const writers = units.filter((u) => !u.read_only).length;
  const title = wave?.name ?? b.input?.name ?? "wave";

  return (
    <div className="my-2 rounded-md border border-line surface-raised overflow-hidden" role="group" aria-label={`Fleet wave ${title}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 px-2.5 py-1.5">
        <Layers size={14} className="text-muted shrink-0" aria-hidden />
        <span className="font-medium break-words [overflow-wrap:anywhere]">{wave ? `Wave ${wave.n} · ${title}` : title}</span>
        <span className="inline-flex items-center gap-1 text-[12px] whitespace-nowrap">
          <span className={`size-2 rounded-full ${status === "running" || status === "merging" ? "animate-pulse" : ""}`} style={{ background: toneOf(status) }} />{status}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-x-3 text-[12px] text-muted tabular-nums whitespace-nowrap">
          {writers > 0 && <span className="inline-flex items-center gap-1"><GitMerge size={12} aria-hidden />{merged}/{writers} merged</span>}
          <span title="Merge circuit breaker: the first conflict pauses the wave, a second stops Fleet for the session"
            style={strikes ? { color: strikes >= 2 ? "var(--bad)" : "var(--warn)" } : undefined}>breaker {strikes}/2</span>
        </span>
      </div>
      <ul className="border-t border-line divide-y divide-[var(--line)] text-[12.5px]">
        {units.map((u) => {
          const detail = unitDetail(u);
          const h = u.handoff;
          const hasReport = !!(h && (h.built || h.decisions || h.discoveries || h.failures)) || !!u.held?.length;
          const isOpen = !!open[u.sub_id];
          return (
            <li key={u.sub_id} className="px-2.5 py-1">
              <button className="w-full flex flex-wrap items-center gap-x-2 gap-y-0.5 text-left disabled:cursor-default" disabled={!hasReport}
                onClick={() => setOpen({ ...open, [u.sub_id]: !isOpen })} aria-expanded={hasReport ? isOpen : undefined}>
                <span className="size-2 rounded-full shrink-0" style={{ background: toneOf(u.status) }} aria-hidden />
                <span className="font-medium">{u.name ?? u.sub_id}</span>
                <span className="text-[12px]">{u.status}{u.read_only ? " · read-only" : ""}</span>
                {u.tier && <span className="chip shrink-0">{u.tier}</span>}
                <span className="flex flex-wrap gap-1 min-w-0">
                  {u.scope.map((s) => <code key={s} className="text-[11.5px] bg-sunken rounded px-1 break-all">{s}</code>)}
                </span>
                {u.branch && !u.merged && u.status !== "discarded" && (
                  <GitBranch size={12} className="text-muted shrink-0"><title>{u.branch}</title></GitBranch>
                )}
                {detail && <span className={`basis-full text-[12px] ${u.status === "dead" || u.status === "conflict" ? "text-bad" : "text-muted"}`}>{detail}</span>}
              </button>
              {isOpen && (
                <div className="mt-1 mb-1 ml-4 pl-2 border-l-2 border-line space-y-1 text-muted">
                  {h?.built && <p><span className="label">Built</span> {h.built}</p>}
                  {h?.decisions && <p><span className="label">Decisions</span> {h.decisions}</p>}
                  {h?.discoveries && <p><span className="label">Discoveries</span> {h.discoveries}</p>}
                  {h?.failures && <p><span className="label">Unresolved</span> {h.failures}</p>}
                  {!!u.held?.length && <p><span className="label">Outside scope</span> {u.held.join(", ")}</p>}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {queue.length > 0 && (
        <div className="border-t border-line px-2.5 py-1 text-[12px] text-muted">Merge queue: {queue.join(" → ")}</div>
      )}
    </div>
  );
}

toolRenderers.run_wave = WaveCard;
