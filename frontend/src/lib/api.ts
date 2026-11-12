// Backend connection: base URL + session token, REST helpers and the event WebSocket.
//
// In the browser (dev) the backend serves the UI, so it's same-origin and the token
// arrives as ?token=. In the desktop app, Tauri tells us the random port and token.

export type Conn = { base: string; token: string };

let conn: Conn | null = null;

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export const inTauri = () => typeof window !== "undefined" && !!window.__TAURI_INTERNALS__;

export async function connect(): Promise<Conn> {
  if (conn) return conn;
  if (inTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const info = await invoke<{ port: number; token: string }>("backend_info");
    conn = { base: `http://127.0.0.1:${info.port}`, token: info.token };
    return conn;
  }
  const url = new URL(window.location.href);
  let token = url.searchParams.get("token");
  if (token) {
    sessionStorage.setItem("ws-token", token);
    url.searchParams.delete("token");
    history.replaceState(null, "", url.toString()); // keep the token out of the address bar
  } else {
    token = sessionStorage.getItem("ws-token");
  }
  if (!token) throw new Error("Missing session token. Open the link printed by `uv run workspace`.");
  conn = { base: "", token };
  return conn;
}

export function getConn(): Conn {
  if (!conn) throw new Error("not connected");
  return conn;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; raw?: boolean } = {}): Promise<T> {
  const { base, token } = getConn();
  const isForm = opts.body instanceof FormData;
  const res = await fetch(`${base}/api${path}`, {
    method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
    headers: {
      Authorization: `Bearer ${token}`,
      ...(opts.body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
    },
    body: opts.body === undefined ? undefined : isForm ? (opts.body as FormData) : JSON.stringify(opts.body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = j.detail ?? j.error ?? msg;
    } catch {}
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  if (opts.raw) return res as unknown as T;
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body: unknown = {}) => api<T>(p, { method: "POST", body });
export const patch = <T = any>(p: string, body: unknown) => api<T>(p, { method: "PATCH", body });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });

/** URL for a local file served by the backend (media players, downloads, viewers). */
export function fileUrl(path: string, download = false): string {
  const { base, token } = getConn();
  const q = new URLSearchParams({ path, token, ...(download ? { download: "1" } : {}) });
  return `${base}/api/file?${q}`;
}

export async function upload(file: File, sessionId?: string) {
  const fd = new FormData();
  fd.append("file", file);
  // send_path/send_mime: the copy the model gets when the original can't be sent as is (note says why).
  return api<{ path: string; name: string; mime: string; size: number; send_path?: string; send_mime?: string; note?: string }>(
    `/uploads${sessionId ? `?session_id=${sessionId}` : ""}`,
    { method: "POST", body: fd },
  );
}

export type WsEvent = { type: string; session_id: string | null; data: any; ts: number; seq: number | null };

let wsSend: (msg: unknown) => void = () => {};
/** Send a message up the event WebSocket (terminal input etc.). */
export const sendWs = (msg: unknown) => wsSend(msg);

/** One WebSocket for everything; reconnects and replays from the last seen seq. It counts as
 *  open only once the server says the replay is done (`ws.ready`); a client too far behind to
 *  replay gets `ws.resync` and reloads its state, and one that falls behind live is disconnected
 *  by the server (close code 4000) and reconnects here. */
export function openEvents(onEvent: (e: WsEvent) => void, onStatus: (s: "open" | "closed") => void) {
  let since = Number(sessionStorage.getItem("ws-seq") ?? 0);
  let ws: WebSocket | null = null;
  let stopped = false;
  let retry = 500;
  const open = () => {
    const { base, token } = getConn();
    const wsBase = base ? base.replace(/^http/, "ws") : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
    ws = new WebSocket(`${wsBase}/ws?token=${encodeURIComponent(token)}&since=${since}`);
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data) as WsEvent;
      if (ev.seq) {
        since = Math.max(since, ev.seq);
        sessionStorage.setItem("ws-seq", String(since));
      }
      onEvent(ev);
      if (ev.type === "ws.ready") {
        retry = 500;
        onStatus("open");
      }
    };
    ws.onclose = () => {
      onStatus("closed");
      if (!stopped) setTimeout(open, (retry = Math.min(retry * 2, 8000)));
    };
  };
  open();
  wsSend = (msg: unknown) => { if (ws?.readyState === 1) ws.send(JSON.stringify(msg)); };
  return {
    send: wsSend,
    close: () => {
      stopped = true;
      ws?.close();
    },
  };
}

// ------------------------------------------------------------------------------------------------
// Hooks & gates, quality ladder, campaigns, fleet: wire types shared by the chat rows, side-panel
// cards and the Campaigns page. They mirror the backend contracts (features/hookbus.py, db.py
// migration v3, approvals.py); later features fill in the UI that uses them.

/** Approval payload of any kind without a dedicated renderer (hook_trust, gate escalations,
 *  campaign plan approval, ...): ApprovalCard's generic card. Answer: POST /approvals/{id}
 *  {decision, choice?: button id, note?}. */
export type ApprovalButton = { id: string; label: string; decision: "approve" | "deny"; style?: "primary" | "ghost" };
export type GenericApprovalPayload = {
  subject?: string;
  markdown?: string;
  buttons?: ApprovalButton[];
  note?: { label?: string; placeholder?: string };
  role?: string;
  [k: string]: unknown;
};

export type GateStatus = "pass" | "fail" | "skipped" | "error";
/** meta.gate on the user message the loop adds when a pre_complete gate fails. */
export type GateMeta = { id: string; status: GateStatus; attempt: number; max: number; hook?: string; level?: string | null };
/** `gate.result` event data (one gate_runs row). */
export type GateResult = { id: string; gate: string; status: GateStatus; attempt: number; level: string | null; subjects: string[]; summary: string; hook: string };
/** `gate.exhausted` event data (a notice meta.notice = "gate_exhausted" goes with it). */
export type GateExhausted = { gates: string[]; reasons: Record<string, string> };
/** `hooks.error` event data: a hook that raised (fail open: the turn goes on). */
export type HookError = { event: string; hook: string; error: string; fail: "open" | "closed"; tool: string | null };

/** meta.skill_load: a skill's text loaded into the conversation (the skill name). */
export type SkillLoadMeta = string;
/** meta.campaign_brief / meta.campaign_continue on harness-written user messages. */
export type CampaignBriefMeta = { campaign_id: string; phase?: number; title?: string };
export type CampaignContinueMeta = { campaign_id: string; phase?: number };

export type LadderLevel = "L1" | "L2" | "L3" | "L4" | "manual";
export type LadderPill = "pass" | "fail" | "stale" | "pending" | "n/a";
/** One ladder_evidence row. observed: tool | command | human | gate. */
export type LadderEvidence = {
  id: string; project: string; session_id: string | null; campaign_id: string | null; level: LadderLevel; status: GateStatus;
  subjects: string[]; source: string; observed: string; path: string | null; item_id: string | null; detail: Record<string, unknown>; ts: number;
};

export type CampaignKind = "chain" | "campaign";
export type CampaignStatus = "draft" | "planning" | "validating" | "awaiting_approval" | "running" | "paused" | "waiting_user"
  | "interrupted" | "done" | "parked" | "abandoned";
export type DoneWhen = { type: "file_exists" | "command_passes" | "metric_threshold" | "gate" | "visual_verify" | "git_clean" | "manual"; [k: string]: unknown };
export type CampaignPhase = { name: string; type: string; skills: string[]; done_when: DoneWhen[]; status?: string; retries?: number };
/** A campaigns row (phases decoded). */
export type Campaign = {
  id: string; slug: string; title: string; kind: CampaignKind; template: string; folder: string; file: string | null; status: CampaignStatus;
  phase: number; phases: CampaignPhase[]; autopilot: boolean; model: string | null; effort: string | null; mode: string | null; group_id: string | null;
  budget_usd: number | null; max_sessions: number | null; auto_turns: number; stall: number;
  claim_session: string | null; claim_heartbeat: number | null; created_at: number; updated_at: number;
};

export type FleetUnit = { wave_id: string; sub_id: string; scope: string[]; read_only: boolean; status: string; merged: boolean; discoveries: string | null };
export type FleetWave = { id: string; session_id: string; campaign_id: string | null; n: number; status: string; strikes: number; created_at: number; closed_at: number | null; units?: FleetUnit[] };
