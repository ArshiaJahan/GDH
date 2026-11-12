import { create } from "zustand";
import { get, post, type WsEvent } from "./api";
import { campaignNotice } from "./campaigns";

export type Session = {
  id: string; title: string; created_at: number; updated_at: number; pinned: boolean;
  folder: string | null; model: string; effort: string; account: string; mode: string;
  harness: string; location: string; status: string; settings: Record<string, any>;
  group_id: string | null; sort_order: number; archived: boolean; archived_at: number | null;
  deleted: boolean; deleted_at: number | null; activity_at: number | null; last_read_at: number | null;
  unread: boolean; last_error: string | null;
  forked_from: { session_id: string; message_id: string; title: string } | null;
};
/** A sidebar group of sessions (backend table session_groups). */
export type Group = { id: string; name: string; color: string; sort_order: number; collapsed: boolean; created_at: number };
export type SidebarView = "active" | "archived" | "trash";
export type Toast = { text: string; kind: "info" | "error"; action?: { label: string; run: () => void } };

/** The key profile a session uses for a provider (mirrors Config.profile_for): its choice in
 *  settings.accounts (older sessions: `account` for Anthropic), else the provider's default. */
export function sessionProfile(s: Session, provider: string, profiles: string[]): string {
  const chosen: string | undefined = s.settings?.accounts?.[provider] ?? (provider === "anthropic" ? s.account : undefined);
  return chosen && profiles.includes(chosen) ? chosen : profiles[0] ?? "default";
}

export type Block = { type: string; [k: string]: any };
export type Msg = { id: string; role: "user" | "assistant"; content: Block[]; meta: Record<string, any>; created_at?: number };

export type ToolRun = { tool_use_id: string; name: string; input?: any; status: "running" | "done"; output?: string; is_error?: boolean; items?: string[] };
export type Approval = { id: string; kind: string; payload: any; status: string; session_id: string | null };
export type Job = { id: string; session_id: string | null; kind: string; title: string; status: string; started_at: number; ended_at: number | null; log_tail: string; meta: any; elapsed_s: number };
export type AssistStep = { id: string; tool: string; label: string; status: "running" | "done" | "error"; output: string };
export type AssistLink = { type: "skill" | "mcp"; name: string; path?: string; action: string; source_url?: string | null };
/** A Skills & MCP assistant run (the Find or create / Find and add boxes). */
export type AssistRun = {
  id: string; kind: "skill" | "mcp"; request: string; status: "running" | "waiting" | "done" | "failed" | "cancelled";
  model: string; effort: string; job_id: string; steps: AssistStep[]; links: AssistLink[]; result: string;
  error: string | null; approval_id: string | null; cost_usd: number; turns: number; started: number; ended: number | null;
};
/** Which slice of a session's history the chat holds (GET /sessions/{id}/messages/page). */
export type Paging = { hasMore: boolean; compacted: number; showCompacted: boolean; loading: boolean };
export type Streaming = { id: string; text: string; thinking: string; model?: string; effort?: string; tools: { id: string; name: string }[] };

/** A newer build in the updates folder (see backend/gamedevworkstation/features/updates.py). */
export type UpdateInfo = { current: string; latest: string; notes: string; built_at: string | null; git_commit: string | null; install_supported?: boolean };
export type Restarting = { version: string; from: string; rollback?: boolean; at: number; log?: string };

/** A spend-limit pause (backend/gamedevworkstation/usage.py global_info / session_info). */
export type LimitPause = { scope: "global" | "session"; session_id?: string; limit_usd: number; spent_usd: number; allowed_usd: number | null; resumed: boolean; reason: string };
export type Limits = { global: LimitPause | null; sessions: Record<string, LimitPause> };
/** A transient status line under the chat (e.g. "Rate limited, retrying in 8s"). */
export type AgentStatus = { kind: string; text: string; retry_in_s?: number; until?: number; attempt?: number; max_attempts?: number };

export type Page = "chat" | "artifacts" | "elevenlabs" | "board" | "schedule" | "campaigns" | "skills" | "usage" | "settings";
export type Theme = "system" | "light" | "dark";

type State = {
  connected: boolean;
  appState: any;
  /** Every session, including archived ones and those in Trash (the sidebar filters by view). */
  sessions: Session[];
  groups: Group[];
  /** null: the new-session screen (when the chat page shows). */
  currentId: string | null;
  /** The group a session started from the new-session screen joins (⌘N in a grouped session). */
  draftGroup: string | null;
  sidebarView: SidebarView;
  /** Multi-selection in the sidebar (⌘-click / ⇧-click). */
  selection: string[];
  /** Session or group whose name is being edited inline in the sidebar. */
  renamingId: string | null;
  renamingGroupId: string | null;
  messages: Record<string, Msg[]>;
  paging: Record<string, Paging>;
  streaming: Record<string, Streaming | null>;
  toolRuns: Record<string, ToolRun>;
  approvals: Record<string, Approval>;
  jobs: Record<string, Job>;
  jobLogs: Record<string, string>;
  subagents: Record<string, any>;
  assistantRuns: Record<string, AssistRun>;
  focusMessage: string | null;
  artifactsTab: string;
  drafts: Record<string, ({ path: string; name: string; mime: string; item_id?: string; text?: string } | { kind: "text"; text: string })[]>;
  /** Skill chip on each session's composer draft (sent as the message's invoked skill). */
  skillChips: Record<string, string | null>;
  page: Page;
  pageArgs: Record<string, any>;
  theme: Theme;
  sidePanelOpen: boolean;
  terminalOpen: boolean;
  searchOpen: boolean;
  helpOpen: boolean;
  toast: Toast | null;
  update: UpdateInfo | null;
  updateOpen: boolean;
  restarting: Restarting | null;
  limits: Limits;
  agentStatus: Record<string, AgentStatus | null>;
  listeners: Set<(e: WsEvent) => void>;
};

const savedTheme = (localStorage.getItem("theme") as Theme) || "system";
/** The side panel's state: the user's own choice once they've toggled it, else open only in a
 *  window at least 1200px wide (it takes ~300px; below that the chat gets too narrow). */
export const SIDE_PANEL_MIN_WINDOW = 1200;
function sidePanelDefault(): boolean {
  const saved = localStorage.getItem("sidePanel");
  if (saved != null) return saved !== "0";
  return typeof window === "undefined" || window.innerWidth >= SIDE_PANEL_MIN_WINDOW;
}

export const useStore = create<State>(() => ({
  connected: false,
  appState: null,
  sessions: [],
  groups: [],
  currentId: localStorage.getItem("currentSession"),
  draftGroup: null,
  sidebarView: "active",
  selection: [],
  renamingId: null,
  renamingGroupId: null,
  messages: {},
  paging: {},
  streaming: {},
  toolRuns: {},
  approvals: {},
  jobs: {},
  jobLogs: {},
  subagents: {},
  assistantRuns: {},
  drafts: {},
  skillChips: {},
  focusMessage: null,
  artifactsTab: "artifacts",
  page: "chat",
  pageArgs: {},
  theme: savedTheme,
  sidePanelOpen: sidePanelDefault(),
  terminalOpen: false,
  searchOpen: false,
  helpOpen: false,
  toast: null,
  update: null,
  updateOpen: false,
  restarting: null,
  limits: { global: null, sessions: {} },
  agentStatus: {},
  listeners: new Set(),
}));

const set = useStore.setState;
// Until the user shows or hides the side panel themselves, it follows the window width.
if (typeof window !== "undefined") {
  window.addEventListener("resize", () => {
    if (localStorage.getItem("sidePanel") == null && st().sidePanelOpen !== sidePanelDefault()) set({ sidePanelOpen: sidePanelDefault() });
  });
}
// When the last update.* event arrived: a /state response requested before it is older news.
let lastUpdateEvent = 0;
/** Appearance edits the Settings page has applied live but not yet saved (or whose save is in
 *  flight). refreshState keeps them over the server copy, so a save of an earlier slider position
 *  (or its settings.updated event) doesn't make the background jump back mid-drag. */
let liveAppearance: any = null;
const withLiveAppearance = (appState: any) => (liveAppearance && appState ? { ...appState, appearance: liveAppearance } : appState);
const updateFrom = (appState: any, requestedAt: number) => (requestedAt >= lastUpdateEvent ? { update: appState.update ?? null } : {});
const st = useStore.getState;
const PAGE = 150;
type MsgPage = { messages: Msg[]; has_more: boolean; compacted: number };
const pageUrl = (id: string, o: { before?: string; limit?: number; compacted?: boolean } = {}) =>
  `/sessions/${id}/messages/page?limit=${o.limit ?? PAGE}${o.before ? `&before=${encodeURIComponent(o.before)}` : ""}${o.compacted ? "&compacted=1" : ""}`;

export const actions = {
  async loadAll() {
    const requestedAt = Date.now();
    const [appState, sessions, groups, approvals] = await Promise.all([get("/state"), get<Session[]>("/sessions?view=all"),
      get<Group[]>("/groups"), get<Approval[]>("/approvals")]);
    const approvalsById: Record<string, Approval> = {};
    approvals.forEach((a) => (approvalsById[a.id] = a));
    set({ appState, sessions, groups, approvals: approvalsById, ...updateFrom(appState, requestedAt) });
    sessionStorage.setItem("ws-seq", String(appState.last_seq));
    actions.loadLimits().catch(() => {});
    const cur = st().currentId;
    const live = sessions.filter((s) => !s.deleted && !s.archived);
    if (cur && sessions.some((s) => s.id === cur && !s.deleted)) await actions.openSession(cur);
    else if (live[0]) await actions.openSession(live[0].id);
    else set({ currentId: null });
  },
  async refreshState() {
    const requestedAt = Date.now();
    const appState = await get("/state");
    set({ appState: withLiveAppearance(appState), ...updateFrom(appState, requestedAt) });
  },
  /** The Settings page's unsaved appearance (null once everything is saved). */
  setLiveAppearance(a: any) {
    liveAppearance = a;
  },
  async openSession(id: string) {
    localStorage.setItem("currentSession", id);
    set({ currentId: id, page: "chat" });
    if (st().sessions.find((s) => s.id === id)?.unread) actions.markRead(id);
    const showCompacted = st().paging[id]?.showCompacted ?? false;
    const [page, jobs, subs] = await Promise.all([get<MsgPage>(pageUrl(id, { compacted: showCompacted })), get<Job[]>(`/jobs?session_id=${id}`), get<any[]>(`/subagents?session_id=${id}`)]);
    set((x) => ({ subagents: { ...x.subagents, ...Object.fromEntries(subs.map((s) => [s.id, s])) } }));
    const jobsById = { ...st().jobs };
    jobs.forEach((j) => (jobsById[j.id] = j));
    set((s) => ({ messages: { ...s.messages, [id]: page.messages }, jobs: jobsById,
      paging: { ...s.paging, [id]: { hasMore: page.has_more, compacted: page.compacted, showCompacted, loading: false } } }));
  },
  /** Prepend the next older page (scrolling up in a long session). Resolves false when there's nothing more. */
  async loadOlder(id: string): Promise<boolean> {
    const pg = st().paging[id];
    const first = st().messages[id]?.[0];
    if (!pg?.hasMore || pg.loading || !first) return false;
    set((x) => ({ paging: { ...x.paging, [id]: { ...pg, loading: true } } }));
    try {
      const page = await get<MsgPage>(pageUrl(id, { before: first.id, compacted: pg.showCompacted }));
      set((x) => {
        const cur = x.messages[id] ?? [];
        const have = new Set(cur.map((m) => m.id));
        return { messages: { ...x.messages, [id]: [...page.messages.filter((m) => !have.has(m.id)), ...cur] },
          paging: { ...x.paging, [id]: { ...(x.paging[id] ?? pg), hasMore: page.has_more, loading: false } } };
      });
      return true;
    } catch {
      set((x) => ({ paging: { ...x.paging, [id]: { ...(x.paging[id] ?? pg), loading: false } } }));
      return false;
    }
  },
  /** "N earlier messages compacted · Show": page in the summarized originals too. */
  async showCompacted(id: string, show = true) {
    set((x) => ({ paging: { ...x.paging, [id]: { ...(x.paging[id] ?? { hasMore: false, compacted: 0, loading: false }), showCompacted: show } } }));
    await actions.reloadMessages(id);
  },
  /** The event stream fell too far behind to replay (ws.resync): reload state over REST. */
  async resync() {
    const requestedAt = Date.now();
    const [appState, sessions, groups, approvals] = await Promise.all([get("/state"), get<Session[]>("/sessions?view=all"),
      get<Group[]>("/groups"), get<Approval[]>("/approvals")]);
    set((x) => ({ appState: withLiveAppearance(appState), sessions, groups, approvals: Object.fromEntries(approvals.map((a) => [a.id, a])),
      ...updateFrom(appState, requestedAt), streaming: {}, agentStatus: {},
      // Other sessions' cached messages may be stale: they reload when opened.
      messages: x.currentId && x.messages[x.currentId] ? { [x.currentId]: x.messages[x.currentId] } : {} }));
    if (appState?.last_seq != null) sessionStorage.setItem("ws-seq", String(appState.last_seq));
    actions.loadLimits().catch(() => {});
    const cur = st().currentId;
    if (cur && !sessions.some((s) => s.id === cur && !s.deleted)) {
      // The open session was deleted while we were offline: open the next live one (or the empty
      // state), staying on whatever page is showing.
      const page = st().page;
      const live = sessions.find((s) => !s.deleted && !s.archived);
      if (live) await actions.openSession(live.id);
      else set({ currentId: null });
      if (st().page !== page) set({ page });
    } else if (cur) {
      const [jobs, subs] = await Promise.all([get<Job[]>(`/jobs?session_id=${cur}`), get<any[]>(`/subagents?session_id=${cur}`), actions.reloadMessages(cur)]);
      set((x) => ({ jobs: { ...x.jobs, ...Object.fromEntries(jobs.map((j) => [j.id, j])) },
        subagents: { ...x.subagents, ...Object.fromEntries(subs.map((s) => [s.id, s])) } }));
    }
  },
  /** Re-read spend-limit pauses (also lifts a daily pause after midnight on the backend). */
  async loadLimits() {
    set({ limits: await get<Limits>("/limits") });
  },
  /** "Resume anyway" on a limit banner: the daily pause, or one session's. */
  async resumeLimits(sessionId?: string) {
    try {
      const r = await post<Limits>("/limits/resume", sessionId ? { session_id: sessionId } : {});
      set({ limits: { global: r.global, sessions: r.sessions } });
    } catch (e: any) {
      actions.toast(e.message, "error");
    }
  },
  /** Re-read one session's messages (e.g. after compaction) without switching pages. */
  async reloadMessages(id: string) {
    const pg = st().paging[id];
    // As many as are shown now (older pages included), so the view doesn't jump.
    const limit = Math.min(Math.max(st().messages[id]?.length ?? 0, PAGE), 1000);
    const page = await get<MsgPage>(pageUrl(id, { limit, compacted: pg?.showCompacted }));
    set((s) => ({ messages: { ...s.messages, [id]: withLater(page.messages, s.messages[id]) },
      paging: { ...s.paging, [id]: { hasMore: page.has_more, compacted: page.compacted, showCompacted: pg?.showCompacted ?? false, loading: false } } }));
  },
  upsertAssistantRun(r: AssistRun) {
    set((x) => ({ assistantRuns: { ...x.assistantRuns, [r.id]: r } }));
  },
  /** Re-read open approval cards (e.g. one raised while this page wasn't listening). */
  async loadApprovals() {
    const list = await get<Approval[]>("/approvals");
    set((x) => ({ approvals: { ...x.approvals, ...Object.fromEntries(list.map((a) => [a.id, a])) } }));
  },
  go(page: Page, args: Record<string, any> = {}) {
    set({ page, pageArgs: args });
    // Back to the chat of an open session that got a reply meanwhile: it's being read now.
    const id = st().currentId;
    if (page === "chat" && id && viewing(id) && st().sessions.find((s) => s.id === id)?.unread) actions.markRead(id);
  },
  /** Replace the queued text and attachments for a session's composer. */
  setDrafts(sessionId: string, drafts: State["drafts"][string]) {
    set((x) => ({ drafts: { ...x.drafts, [sessionId]: drafts } }));
  },
  /** Put a file on a session's composer (from the Artifacts or ElevenLabs page). */
  attachToChat(sessionId: string, att: { path: string; name: string; mime: string; item_id?: string; text?: string }, warning?: string | null) {
    set((x) => ({ drafts: { ...x.drafts, [sessionId]: [...(x.drafts[sessionId] ?? []), att] } }));
    actions.openSession(sessionId);
    if (warning) actions.toast(warning);
  },
  /** Attach (or with null, remove) a skill chip on a session's composer. */
  setSkillChip(sessionId: string, name: string | null) {
    set((x) => ({ skillChips: { ...x.skillChips, [sessionId]: name } }));
  },
  /** "Use in chat" on the Skills page: the current session (or a new one) with the skill chip attached. */
  async useSkillInChat(name: string) {
    let sid = st().currentId;
    if (!sid || !st().sessions.some((s) => s.id === sid)) {
      const s = await post<Session>("/sessions", {});
      upsertSession(s);
      sid = s.id;
    }
    actions.setSkillChip(sid, name);
    await actions.openSession(sid);
    requestAnimationFrame(() => document.getElementById("composer")?.focus());
  },
  /** Put text in the composer. */
  setComposerText(text: string) {
    requestAnimationFrame(() => {
      const ta = document.getElementById("composer") as HTMLTextAreaElement | null;
      if (!ta) return;
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(ta, (ta.value ? ta.value + "\n\n" : "") + text);
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      ta.focus();
    });
  },
  toast(text: string, kind: "info" | "error" = "info", action?: Toast["action"]) {
    const t: Toast = { text, kind, action };
    set({ toast: t });
    setTimeout(() => st().toast === t && set({ toast: null }), action ? 7000 : 4000);
  },
  /** The user has seen this session's latest reply. */
  markRead(id: string) {
    post(`/sessions/${id}/read`).catch(() => {});
  },
  setTheme(theme: Theme) {
    localStorage.setItem("theme", theme);
    set({ theme });
  },
  cycleTheme() {
    const order: Theme[] = ["system", "light", "dark"];
    actions.setTheme(order[(order.indexOf(st().theme) + 1) % 3]);
  },
  toggleSidePanel() {
    const v = !st().sidePanelOpen;
    localStorage.setItem("sidePanel", v ? "1" : "0");
    set({ sidePanelOpen: v });
  },
  onEvent(fn: (e: WsEvent) => void) {
    st().listeners.add(fn);
    return () => { st().listeners.delete(fn); };
  },
};

/** Insert or replace; the sidebar does its own ordering (lib/sessions.ts). */
function upsertSession(s: Session) {
  if (!s?.id) return;
  set((x) => {
    const i = x.sessions.findIndex((o) => o.id === s.id);
    if (i < 0) return { sessions: [s, ...x.sessions] };
    const all = x.sessions.slice();
    all[i] = s;
    return { sessions: all };
  });
}

/** Is the user looking at this session right now (open, chat page, window visible)? */
const viewing = (sid: string) => st().currentId === sid && st().page === "chat" && document.visibilityState === "visible";
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    const id = st().currentId;
    if (id && viewing(id) && st().sessions.find((s) => s.id === id)?.unread) actions.markRead(id);
  });
}

/** A freshly loaded page plus any messages that arrived live (message.created) while it loaded. */
function withLater(page: Msg[], cur: Msg[] | undefined): Msg[] {
  const last = page[page.length - 1]?.id;
  const at = cur && last ? cur.findIndex((m) => m.id === last) : -1;
  if (!cur || at < 0) return page;
  const have = new Set(page.map((m) => m.id));
  return [...page, ...cur.slice(at + 1).filter((m) => !have.has(m.id))];
}

function appendMessage(sid: string, m: Msg) {
  set((x) => {
    const cur = x.messages[sid];
    if (!cur) return {};
    if (cur.some((o) => o.id === m.id)) return { messages: { ...x.messages, [sid]: cur.map((o) => (o.id === m.id ? m : o)) } };
    return { messages: { ...x.messages, [sid]: [...cur, m] } };
  });
}

export function handleEvent(ev: WsEvent) {
  const sid = ev.session_id ?? "";
  const d = ev.data;
  switch (ev.type) {
    case "ws.resync": // offline longer than the event log is kept: reload over REST instead of replaying
      actions.resync().catch(() => {});
      break;
    case "session.created":
    case "session.updated":
      upsertSession(d);
      break;
    case "session.deleted": // deleted for good (moving to Trash is a session.updated with deleted: true)
      set((x) => ({ sessions: x.sessions.filter((s) => s.id !== d.id), currentId: x.currentId === d.id ? null : x.currentId,
        selection: x.selection.filter((i) => i !== d.id) }));
      break;
    case "groups.updated":
      set({ groups: d.groups });
      break;
    case "session.cleared":
      if (st().messages[sid]) actions.reloadMessages(sid).catch(() => {});
      break;
    case "session.compacted":
      // Summary message inserted and older turns marked compacted server-side (session_routes.compact).
      if (st().messages[sid]) actions.reloadMessages(sid).catch(() => {});
      if (viewing(sid)) actions.markRead(sid); // compacted while open: nothing unread
      break;
    case "message.started":
      set((x) => ({ streaming: { ...x.streaming, [sid]: { id: d.id, text: "", thinking: "", model: d.model, effort: d.effort, tools: [] } } }));
      break;
    case "message.delta":
      set((x) => {
        const s = x.streaming[sid];
        return s && s.id === d.id ? { streaming: { ...x.streaming, [sid]: { ...s, text: s.text + d.text } } } : {};
      });
      break;
    case "thinking.delta":
      set((x) => {
        const s = x.streaming[sid];
        return s && s.id === d.id ? { streaming: { ...x.streaming, [sid]: { ...s, thinking: s.thinking + d.text } } } : {};
      });
      break;
    case "tool.input_delta":
      set((x) => {
        const s = x.streaming[sid];
        return s && s.id === d.id ? { streaming: { ...x.streaming, [sid]: { ...s, tools: [...s.tools, { id: d.tool_use_id, name: d.name }] } } } : {};
      });
      break;
    case "message.created":
    case "message.updated": {
      const m = d.message as Msg;
      appendMessage(sid, m);
      set((x) => (x.streaming[sid]?.id === m.id ? { streaming: { ...x.streaming, [sid]: null } } : {}));
      break;
    }
    case "message.failed":
      set((x) => ({ streaming: { ...x.streaming, [sid]: null } }));
      break;
    case "agent.idle":
    case "agent.stopped":
      set((x) => ({ streaming: { ...x.streaming, [sid]: null }, agentStatus: { ...x.agentStatus, [sid]: null } }));
      if (ev.type === "agent.idle" && viewing(sid)) actions.markRead(sid); // replied while open: not unread
      break;
    case "agent.status":
      set((x) => ({ agentStatus: { ...x.agentStatus, [sid]: d.kind ? d : null } }));
      break;
    case "session.stopped": {
      const parts = [d.subagents && `${d.subagents} subagent${d.subagents > 1 ? "s" : ""}`, d.jobs && `${d.jobs} background task${d.jobs > 1 ? "s" : ""}`,
        d.approvals && `${d.approvals} approval${d.approvals > 1 ? "s" : ""}`].filter(Boolean);
      if (parts.length) actions.toast(`Stopped. Cancelled ${parts.join(", ")}.`);
      break;
    }
    case "tool.started":
      set((x) => ({ toolRuns: { ...x.toolRuns, [d.tool_use_id]: { ...d, status: "running" } } }));
      break;
    case "tool.finished":
      set((x) => ({ toolRuns: { ...x.toolRuns, [d.tool_use_id]: { ...x.toolRuns[d.tool_use_id], ...d, status: "done" } } }));
      break;
    case "approval.requested":
      set((x) => ({ approvals: { ...x.approvals, [d.id]: { ...d, session_id: ev.session_id } } }));
      break;
    case "approval.resolved":
      set((x) => ({ approvals: { ...x.approvals, [d.id]: { ...x.approvals[d.id], status: d.status } } }));
      break;
    case "job.updated":
      set((x) => ({ jobs: { ...x.jobs, [d.id]: d } }));
      break;
    case "subagent.updated":
      set((x) => ({ subagents: { ...x.subagents, [d.id]: d } }));
      break;
    case "assistant.updated":
      set((x) => ({ assistantRuns: { ...x.assistantRuns, [d.id]: d } }));
      break;
    case "job.log":
      set((x) => ({ jobLogs: { ...x.jobLogs, [d.id]: ((x.jobLogs[d.id] ?? "") + d.text).slice(-4000) } }));
      break;
    case "settings.updated":
      actions.refreshState();
      actions.loadLimits().catch(() => {});
      break;
    case "update.available": {
      lastUpdateEvent = Date.now();
      if (d.latest === st().appState?.version?.version) break; // already running it
      const isNew = st().update?.latest !== d.latest;
      set({ update: d });
      if (isNew) actions.toast(d.install_supported === false ? `Update v${d.latest} available. See what's new in the sidebar.` : `Update v${d.latest} ready. Install it from the sidebar.`);
      break;
    }
    case "update.cleared":
      lastUpdateEvent = Date.now();
      if (st().update?.latest === d.version) set({ update: null, updateOpen: false });
      break;
    case "update.installing":
      if (!st().restarting) set({ restarting: { version: d.version, from: d.from, rollback: d.rollback, at: Date.now() }, updateOpen: false });
      break;
    case "mcp.auto_enabled": // a skill turned on the MCP servers it uses (live only, never replayed)
      actions.toast(d.message ?? `Enabled MCP server ${(d.servers ?? []).join(", ")} for this session`);
      break;
    case "limits.paused":
      set((x) => (d.scope === "global" ? { limits: { ...x.limits, global: d } } : { limits: { ...x.limits, sessions: { ...x.limits.sessions, [sid]: d } } }));
      actions.toast(d.scope === "global" ? "Daily spend limit reached. All agents are paused." : "This session reached its spend limit and is paused.", "error");
      break;
    case "limits.resumed":
      set((x) => {
        if (d.scope === "global") return { limits: { ...x.limits, global: null } };
        const rest = { ...x.limits.sessions };
        delete rest[sid];
        return { limits: { ...x.limits, sessions: rest } };
      });
      if (d.reason === "new_day") actions.toast("A new day: the daily spend limit has reset and agents can run again.");
      break;
    case "campaign.paused": // done, parked, waiting for you: shown on any page, with a way to the campaign
    case "campaign.done": {
      const n = campaignNotice(ev.type, d);
      if (n) actions.toast(n.text, n.kind, { label: "Open", run: () => actions.go("campaigns", { id: n.id }) });
      break;
    }
  }
  st().listeners.forEach((fn) => fn(ev));
}
