// Campaigns and workflow chains (backend features/campaigns.py, chains.py): wire types beyond the
// shared ones in lib/api.ts, REST helpers and small pure helpers the page, the side-panel card and
// the composer share.
import { get, patch, post, type Campaign, type CampaignPhase, type CampaignStatus, type DoneWhen } from "./api";

/** One workflow template (GET /api/chains). */
export type ChainTemplate = {
  id: string; title: string; summary: string; kinds: ("chain" | "campaign")[]; applies_to: "any" | "unity" | "backlog";
  critique: boolean; blocking_gates: string[]; phases: CampaignPhase[]; source: string; skill?: string;
};
export type ChainsResponse = { templates: ChainTemplate[]; errors: { file: string; skill: string; errors: string[] }[] };

/** A done_when result of the last evaluation (phase.results). */
export type CheckResult = { index: number; type: DoneWhen["type"]; label: string; status: "pass" | "fail" | "pending" | "skipped"; detail: string };
export type Checkpoint = { phase: number; name: string; ref: string; sha: string; kind: "stash" | "head"; restore: string; ts: number };
export type PhaseState = CampaignPhase & {
  retries_max?: number; started_at?: number | null; ended_at?: number | null; results?: CheckResult[];
  handoff?: string; checkpoint?: Checkpoint | null; stories?: string[]; instructions?: string; fleet?: boolean;
};
/** GET /api/campaigns list rows and campaign.updated events. */
export type CampaignRow = Omit<Campaign, "phases"> & {
  phases: PhaseState[]; reason?: string | null; pending?: string | null; template_title?: string | null; request?: string;
  spend_usd?: number; sessions?: number; last_activity?: number;
};
export type CampaignSessionRow = {
  campaign_id: string; session_id: string; phase: number | null; started_at: number; ended_at: number | null;
  end_reason: string | null; title: string | null; exists: boolean;
};
export type CampaignDoc = {
  design_target: { done: boolean; text: string }[]; scope: { stories: string[]; paths: string[]; out_of_scope: string[] };
  constraints: string; coverage: string; review: string; decisions: string; discoveries: string; active: string;
  continuation: string; completion: string;
};
/** GET /api/campaigns/{id}. */
export type CampaignDetail = CampaignRow & {
  next_action: string; current_session: string | null; session_chain: CampaignSessionRow[]; checkpoints: Checkpoint[];
  path: string | null; doc: CampaignDoc | null;
  state: { plan_rounds?: number; drift_failures?: number; escalations?: number; parks?: Record<string, number>; completion?: string; plan_card?: string };
};
export type CampaignMetrics = {
  campaigns: number; spend_usd: number; stories: number; cost_per_story_usd: number | null; wall_s_per_story: number | null;
  first_pass_gate_rate: number | null; gate_retries_per_phase: number | null; escalations: number; parks_by_reason: Record<string, number>;
};
export type NewCampaign = {
  template: string; kind: "chain" | "campaign"; request?: string; folder?: string; session_id?: string; title?: string;
  budget_usd?: number; autopilot?: boolean; model?: string; effort?: string; mode?: string; start?: boolean; force?: boolean;
};
export type CampaignAction = "start" | "pause" | "resume" | "park" | "abandon" | "approve_plan" | "revise_plan" | "rollover";

export const campaignsApi = {
  chains: (folder?: string | null, kind?: string) => {
    const q = new URLSearchParams({ ...(folder ? { folder } : {}), ...(kind ? { kind } : {}) }).toString();
    return get<ChainsResponse>(`/chains${q ? `?${q}` : ""}`);
  },
  list: (folder?: string) => get<{ campaigns: CampaignRow[]; metrics: CampaignMetrics }>(`/campaigns${folder ? `?folder=${encodeURIComponent(folder)}` : ""}`),
  detail: (id: string) => get<CampaignDetail>(`/campaigns/${encodeURIComponent(id)}`),
  create: (body: NewCampaign) => post<CampaignRow>("/campaigns", body),
  update: (id: string, body: Partial<Pick<CampaignRow, "budget_usd" | "autopilot" | "max_sessions" | "title" | "effort" | "mode">>) =>
    patch<CampaignRow>(`/campaigns/${encodeURIComponent(id)}`, body),
  act: (id: string, action: CampaignAction, body: Record<string, unknown> = {}) => post<CampaignRow>(`/campaigns/${encodeURIComponent(id)}/${action}`, body),
  check: (id: string) => post<{ results: CheckResult[] }>(`/campaigns/${encodeURIComponent(id)}/check`),
  review: (id: string, phase: number, index: number, decision: "pass" | "fail", note = "") =>
    post(`/campaigns/${encodeURIComponent(id)}/review`, { phase, index, decision, note }),
};

/** Events that change a campaign (the page and the card reload on them). */
export const CAMPAIGN_EVENTS = ["campaign.updated", "campaign.paused", "campaign.done"];

export const STATUS_LABEL: Record<CampaignStatus, string> = {
  draft: "Draft", planning: "Planning", validating: "Validating plan", awaiting_approval: "Needs your approval", running: "Running",
  paused: "Paused", waiting_user: "Waiting for you", interrupted: "Interrupted", done: "Done", parked: "Parked", abandoned: "Abandoned",
};

/** Statuses a campaign or chain never leaves. */
export const FINAL_STATUSES: string[] = ["done", "abandoned"];

/** Reasons the user caused themselves (no toast for those: they just did it). */
const USER_REASONS = ["paused by you", "stopped by you", "parked by you", "abandoned by you"];

/** The app-wide notice for a campaign event (store.handleEvent shows it as a toast on any page):
 *  done, parked, waiting for you, or paused by the harness. Null for anything else (interrupted at
 *  startup, the user's own pause). */
export function campaignNotice(type: string, d: any): { text: string; kind: "info" | "error"; id: string } | null {
  if (!d?.id) return null;
  const title = d.title ?? "A campaign";
  const why = d.reason && !USER_REASONS.includes(d.reason) ? `: ${d.reason}` : "";
  if (type === "campaign.done") return { text: `${title} is done.`, kind: "info", id: d.id };
  if (type !== "campaign.paused" || USER_REASONS.includes(d.reason)) return null;
  if (d.status === "parked") return { text: `${title} is parked and needs you${why}`, kind: "error", id: d.id };
  if (d.status === "waiting_user") return { text: `${title} is waiting for you${why}`, kind: "info", id: d.id };
  if (d.status === "paused") return { text: `${title} paused${why}`, kind: "info", id: d.id };
  return null;
}

/** Colour of a status pill: ok (done), action (moving), warn (needs you), bad (parked), muted. */
export function statusTone(s: CampaignStatus | string): "ok" | "action" | "warn" | "bad" | "muted" {
  if (s === "done") return "ok";
  if (s === "running" || s === "planning" || s === "validating") return "action";
  if (s === "awaiting_approval" || s === "waiting_user" || s === "paused" || s === "interrupted") return "warn";
  if (s === "parked") return "bad";
  return "muted";
}
export const TONE_COLOR = { ok: "var(--ok)", action: "var(--action)", warn: "var(--warn, #c98a00)", bad: "var(--bad)", muted: "var(--muted, #888)" };

/** "2/5 Build" (or "plan" before the plan is approved). */
export function phaseLabel(c: Pick<CampaignRow, "phase" | "phases" | "status">): string {
  if (c.phase < 0 || c.phase >= c.phases.length) return c.status === "done" ? `${c.phases.length}/${c.phases.length}` : "plan";
  return `${c.phase + 1}/${c.phases.length} ${c.phases[c.phase].name}`;
}

/** A done_when condition in words (mirrors chains.describe on the backend). */
export function describeCondition(d: DoneWhen): string {
  const s = (k: string) => (d[k] == null ? "" : String(d[k]));
  switch (d.type) {
    case "file_exists": return `file ${s("path")}${d.newer_than ? " (new this phase)" : ""}`;
    case "command_passes": return `${s("observe")} passes`;
    case "metric_threshold": return `${s("key")} ${s("op")} ${s("value")}`;
    case "gate": {
      const what = s("name") || ({ story: "stories done", manual: "manual checks" } as Record<string, string>)[s("level")] || s("level");
      const extra = [d.stories ? `${s("stories")} stories` : "", d.expect === "fail" ? "a failing repro test" : "", d.tests === "repro" ? "repro tests pass" : ""].filter(Boolean);
      return `gate ${what}${extra.length ? ` (${extra.join(", ")})` : ""}`;
    }
    case "visual_verify": return `fresh screenshot${d.newer_than ? " (this phase)" : ""}`;
    case "git_clean": return `git clean${Array.isArray(d.paths) && d.paths.length ? `: ${(d.paths as string[]).join(", ")}` : ""}`;
    case "manual": return `you check: ${s("question") || "the phase result"}`;
    default: return String(d.type);
  }
}

/** The chips of the current phase: each condition with its last result (pending before any check). */
export function phaseChecks(p: PhaseState | undefined): { label: string; status: CheckResult["status"]; detail: string }[] {
  if (!p) return [];
  const res = new Map((p.results ?? []).map((r) => [r.index, r]));
  return p.done_when.map((d, i) => {
    const r = res.get(i);
    return { label: r?.label ?? describeCondition(d), status: r?.status ?? "pending", detail: r?.detail ?? "" };
  });
}

/** Spend vs budget, e.g. "$1.20 / $10". */
export function spendLabel(spent?: number | null, budget?: number | null): string {
  const f = (n: number) => `$${n < 10 && n % 1 ? n.toFixed(2) : n.toFixed(n % 1 ? 2 : 0)}`;
  return budget != null && budget > 0 ? `${f(spent ?? 0)} / ${f(budget)}` : f(spent ?? 0);
}

/** Proportionality (plan §2.9): a short request belongs in a chain, not a campaign. */
export const MIN_CAMPAIGN_WORDS = 20;
export const wordCount = (t: string) => (t.trim() ? t.trim().split(/\s+/).length : 0);

/** Templates offered for a run kind. */
export const templatesFor = (ts: ChainTemplate[], kind: "chain" | "campaign") => ts.filter((t) => t.kinds.includes(kind));

/** Parse `/workflow <id> [request…]` from the composer; null when it isn't one. */
export function parseWorkflowCommand(line: string): { id: string; request: string } | null {
  const m = line.match(/^\/workflow(?:\s+(\S+))?(?:\s+([\s\S]*))?$/);
  if (!m) return null;
  return { id: m[1] ?? "", request: (m[2] ?? "").trim() };
}

/** Lines of a markdown section that are list items ("- …"), without the marker. */
export function listItems(md: string | null | undefined): string[] {
  return (md ?? "").split("\n").map((l) => l.trim()).filter((l) => /^[-*]\s+/.test(l)).map((l) => l.replace(/^[-*]\s+/, ""));
}
