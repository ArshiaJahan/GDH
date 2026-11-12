import { ExternalLink, Pause, Play, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CAMPAIGN_EVENTS, STATUS_LABEL, TONE_COLOR, campaignsApi, phaseChecks, phaseLabel, spendLabel, statusTone, type CampaignDetail } from "../../lib/campaigns";
import { actions, type Session } from "../../lib/store";
import { Card } from "../SidePanel";

const CHECK_COLOR: Record<string, string> = { pass: "var(--ok)", fail: "var(--bad)", pending: "var(--muted, #888)", skipped: "var(--warn, #c98a00)" };
const CHECK_MARK: Record<string, string> = { pass: "✓", fail: "✗", pending: "…", skipped: "–" };

/** Side-panel card for a campaign or chain session (settings.campaign_id): status, phase N/M, its
 *  done_when conditions with their last results, Next action, Pause / Resume and Run phase checks. */
export function CampaignCard({ s }: { s: Session }) {
  const cid: string | undefined = s.settings?.campaign_id ?? undefined;
  const [c, setC] = useState<CampaignDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const seq = useRef(0);

  const load = async () => {
    const n = ++seq.current;
    if (!cid) return setC(null);
    try {
      const d = await campaignsApi.detail(cid);
      if (n === seq.current) setC(d);
    } catch { if (n === seq.current) setC(null); }
  };
  useEffect(() => { load(); }, [cid]);
  useEffect(() => {
    if (!cid) return;
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = actions.onEvent((e) => {
      const mine = (CAMPAIGN_EVENTS.includes(e.type) && e.data?.id === cid) || (e.session_id === s.id && e.type === "agent.idle");
      if (mine) { clearTimeout(t); t = setTimeout(load, 300); }
    });
    return () => { off(); clearTimeout(t); };
  }, [cid, s.id]);

  if (!cid || !c) return null;
  const tone = statusTone(c.status);
  const p = c.phase >= 0 ? c.phases[c.phase] : undefined;
  const checks = phaseChecks(p);
  const word = c.kind === "chain" ? "Step" : "Phase";

  const run = async (key: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(key);
    try { await fn(); if (ok) actions.toast(ok); await load(); } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(null); }
  };
  const checkNow = () => run("check", async () => {
    const r = await campaignsApi.check(c.id);
    const failed = r.results.filter((x) => x.status !== "pass").length;
    actions.toast(failed ? `${failed} check${failed > 1 ? "s" : ""} not passing yet` : "All phase checks pass");
  });
  const canPause = c.status === "running";
  const canResume = ["paused", "waiting_user", "interrupted", "parked"].includes(c.status);

  return (
    <Card id="campaign" title={c.kind === "chain" ? "Workflow" : "Campaign"}
      right={<button className="btn btn-ghost px-1 py-0.5" onClick={load} title="Refresh" aria-label="Refresh campaign"><RefreshCw size={13} /></button>}>
      <div className="flex items-center gap-1.5">
        <span className="flex-1 min-w-0 truncate font-medium" title={c.title}>{c.title}</span>
        <span className="text-[11.5px] shrink-0" style={{ color: TONE_COLOR[tone] }} data-testid="campaign-status">{STATUS_LABEL[c.status] ?? c.status}</span>
      </div>
      <div className="text-[12px] text-muted mt-0.5">
        {c.template_title ?? c.template} · {word} {phaseLabel(c)}{p ? ` (${p.type})` : ""}
        {c.kind === "campaign" && <> · {spendLabel(c.spend_usd, c.budget_usd)}</>}
        {c.autopilot && <> · autopilot</>}
      </div>
      {c.reason && c.status !== "running" && <div className="text-[12px] mt-1" style={{ color: TONE_COLOR[tone] }}>{c.reason}</div>}
      {checks.length > 0 && (
        <div className="mt-1.5" role="list" aria-label="Done when">
          <div className="label">Done when</div>
          {checks.map((x, i) => (
            <div key={i} role="listitem" className="flex items-start gap-1.5 py-0.5 text-[12px]" title={x.detail || undefined}>
              <span style={{ color: CHECK_COLOR[x.status] }} className="w-3 shrink-0" aria-label={x.status}>{CHECK_MARK[x.status] ?? "…"}</span>
              <span className="flex-1 min-w-0">
                <span>{x.label}</span>
                {x.detail && x.status !== "pass" && <span className="block text-muted truncate">{x.detail}</span>}
              </span>
            </div>
          ))}
          {p?.retries != null && <div className="text-[11.5px] text-faint">Retries left: {p.retries}/{p.retries_max ?? p.retries}</div>}
        </div>
      )}
      <div className="mt-1.5 text-[12px]"><span className="label">Next action</span><div className="text-muted" data-testid="campaign-next">{c.next_action}</div></div>
      <div className="flex flex-wrap gap-1 mt-2">
        {canPause && (
          <button className="btn btn-ghost px-1.5 py-0.5 text-[12px]" disabled={busy !== null}
            onClick={() => run("pause", () => campaignsApi.act(c.id, "pause"), "Paused after the current turn")}><Pause size={12} /> Pause</button>
        )}
        {canResume && (
          <button className="btn btn-ghost px-1.5 py-0.5 text-[12px]" disabled={busy !== null}
            onClick={() => run("resume", () => campaignsApi.act(c.id, "resume"), "Resumed")}><Play size={12} /> Resume</button>
        )}
        {c.status === "awaiting_approval" && (
          <button className="btn btn-ghost px-1.5 py-0.5 text-[12px]" disabled={busy !== null}
            onClick={() => run("approve", () => campaignsApi.act(c.id, "approve_plan"), "Plan approved")}><ShieldCheck size={12} /> Approve plan</button>
        )}
        {p && !["done", "abandoned"].includes(c.status) && (
          <button className="btn btn-ghost px-1.5 py-0.5 text-[12px]" disabled={busy !== null} onClick={checkNow}
            title="Check this phase's conditions now (doesn't use a retry)"><RefreshCw size={12} /> Run phase checks</button>
        )}
        <button className="btn btn-ghost px-1.5 py-0.5 text-[12px]" onClick={() => actions.go("campaigns", { id: c.id })}>
          <ExternalLink size={12} /> Details
        </button>
      </div>
    </Card>
  );
}
