// Session management for the sidebar, the chat and the shortcuts: preferences, how sessions are
// grouped and ordered, and the actions (each one an API call; the backend's session.* and
// groups.updated events update every open window).
import { del, patch, post } from "./api";
import { downloadFile } from "./native";
import { revealInFinder } from "./native";
import { actions, useStore, type Group, type Session, type SidebarView } from "./store";

export type GroupBy = "groups" | "folder" | "date" | "none";
export type SortBy = "activity" | "created" | "name";
export type Prefs = { groupBy: GroupBy; sortBy: SortBy; collapsed: string[] };

/** Group colors (backend store.GROUP_COLORS) → design tokens. */
export const GROUP_COLORS: Record<string, string> = {
  gray: "var(--faint)", blue: "var(--s1)", teal: "var(--codex)", green: "var(--ok)",
  yellow: "var(--grp-yellow)", orange: "var(--grp-orange)", red: "var(--bad)", violet: "var(--eleven)",
};

const PREFS_KEY = "sidebar.prefs";
const DEFAULT_PREFS: Prefs = { groupBy: "groups", sortBy: "activity", collapsed: [] };

export function loadPrefs(): Prefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

let prefs = loadPrefs();
const prefListeners = new Set<() => void>();
export const getPrefs = () => prefs;
export function setPrefs(p: Partial<Prefs>) {
  prefs = { ...prefs, ...p };
  localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  prefListeners.forEach((f) => f());
}
export function subscribePrefs(f: () => void) {
  prefListeners.add(f);
  return () => { prefListeners.delete(f); };
}

// ------------------------------------------------------------------ ordering

export const activity = (s: Session) => s.activity_at ?? s.created_at;

export function inView(s: Session, view: SidebarView): boolean {
  return view === "trash" ? s.deleted : view === "archived" ? !s.deleted && s.archived : !s.deleted && !s.archived;
}

function sortKey(s: Session, sortBy: SortBy): number {
  return sortBy === "created" ? s.created_at : activity(s);
}

export function sortSessions(list: Session[], sortBy: SortBy): Session[] {
  const out = list.slice();
  if (sortBy === "name") out.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base", numeric: true }));
  else out.sort((a, b) => sortKey(b, sortBy) - sortKey(a, sortBy));
  return out;
}

export type Section = {
  key: string;
  kind: "pinned" | "group" | "ungrouped" | "folder" | "date" | "flat";
  title: string;
  hint?: string;
  group?: Group;
  color?: string;
  sessions: Session[];
  collapsed: boolean;
};

const DAY = 86400;
function dateBucket(ts: number): [string, string] {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const today = start.getTime() / 1000;
  if (ts >= today) return ["d0", "Today"];
  if (ts >= today - DAY) return ["d1", "Yesterday"];
  if (ts >= today - 7 * DAY) return ["d7", "Previous 7 days"];
  return ["d9", "Older"];
}

/** The sidebar's sections for a view, in display order. */
export function buildSections(sessions: Session[], groups: Group[], p: Prefs, view: SidebarView): Section[] {
  const live = sessions.filter((s) => inView(s, view));
  const col = (k: string) => p.collapsed.includes(k);
  if (view === "trash") {
    return [{ key: "flat", kind: "flat", title: "", collapsed: false, sessions: live.slice().sort((a, b) => (b.deleted_at ?? 0) - (a.deleted_at ?? 0)) }];
  }
  if (view === "archived" || p.groupBy === "none") {
    const pinned = view === "active" ? sortPinned(live.filter((s) => s.pinned)) : [];
    const rest = sortSessions(live.filter((s) => !pinned.includes(s)), p.sortBy);
    return [{ key: "flat", kind: "flat", title: "", collapsed: false, sessions: [...pinned, ...rest] }];
  }
  const out: Section[] = [];
  const pinned = sortPinned(live.filter((s) => s.pinned));
  if (pinned.length) out.push({ key: "pinned", kind: "pinned", title: "Pinned", sessions: pinned, collapsed: col("pinned") });
  const rest = sortSessions(live.filter((s) => !s.pinned), p.sortBy);
  if (p.groupBy === "groups") {
    const known = new Set(groups.map((g) => g.id));
    for (const g of groups) {
      out.push({ key: `g:${g.id}`, kind: "group", title: g.name, group: g, color: GROUP_COLORS[g.color] ?? GROUP_COLORS.gray,
        sessions: rest.filter((s) => s.group_id === g.id), collapsed: g.collapsed });
    }
    const loose = rest.filter((s) => !s.group_id || !known.has(s.group_id));
    out.push({ key: "ungrouped", kind: "ungrouped", title: "Sessions", sessions: loose, collapsed: col("ungrouped") });
  } else if (p.groupBy === "folder") {
    const by = new Map<string, Session[]>();
    for (const s of rest) by.set(s.folder ?? "", [...(by.get(s.folder ?? "") ?? []), s]);
    const keys = [...by.keys()].sort((a, b) => (a === "" ? 1 : b === "" ? -1 : 0) || activity(by.get(b)![0]) - activity(by.get(a)![0]));
    for (const k of keys) {
      const name = k ? k.split("/").filter(Boolean).pop() ?? k : "No folder";
      out.push({ key: `f:${k}`, kind: "folder", title: name, hint: k || "Chat only (no folder)", sessions: by.get(k)!, collapsed: col(`f:${k}`) });
    }
  } else {
    const by = new Map<string, Section>();
    for (const s of rest) {
      const [k, title] = dateBucket(sortKey(s, p.sortBy === "created" ? "created" : "activity"));
      if (!by.has(k)) by.set(k, { key: k, kind: "date", title, sessions: [], collapsed: col(k) });
      by.get(k)!.sessions.push(s);
    }
    out.push(...[...by.values()].sort((a, b) => a.key.localeCompare(b.key)));
  }
  return out;
}

function sortPinned(list: Session[]): Session[] {
  return list.slice().sort((a, b) => a.sort_order - b.sort_order || activity(b) - activity(a));
}

/** Session ids in the order the sidebar shows them (collapsed sections left out). */
export function visibleOrder(): string[] {
  const x = useStore.getState();
  return buildSections(x.sessions, x.groups, prefs, x.sidebarView).filter((s) => !s.collapsed).flatMap((s) => s.sessions.map((v) => v.id));
}

// -------------------------------------------------------------------- actions

const st = useStore.getState;
const set = useStore.setState;
const find = (id: string) => st().sessions.find((s) => s.id === id);
const plural = (n: number, w: string) => (n === 1 ? `1 ${w}` : `${n} ${w}s`);

async function attempt<T>(fn: () => Promise<T>): Promise<T | undefined> {
  try {
    return await fn();
  } catch (e: any) {
    actions.toast(e?.message ?? String(e), "error");
    return undefined;
  }
}

const bulk = (ids: string[], action: string, extra: Record<string, unknown> = {}) => post("/sessions/bulk", { ids, action, ...extra });

/** The session to open when `ids` leave the list: the next one below, else the one above. */
function neighbourOf(ids: string[]): string | null {
  const order = visibleOrder();
  const cur = st().currentId;
  if (!cur || !ids.includes(cur)) return cur;
  const i = order.indexOf(cur);
  const after = order.slice(i + 1).find((id) => !ids.includes(id));
  const before = order.slice(0, Math.max(i, 0)).reverse().find((id) => !ids.includes(id));
  return after ?? before ?? null;
}

/** Plan where to go when `ids` leave the list (computed now, before events reorder it); call the result once they're gone. */
function planLeave(ids: string[]): () => void {
  const wasCurrent = ids.includes(st().currentId ?? "");
  const next = neighbourOf(ids);
  return () => {
    set((x) => ({ selection: x.selection.filter((i) => !ids.includes(i)) }));
    if (!wasCurrent) return;
    if (next) actions.openSession(next);
    else set({ currentId: null });
  };
}

let creating: Promise<void> | null = null;

/** Untitled, never used, idle and not yet set up (no folder, no skills beyond the defaults every new
 *  session starts with, no connectors or shared tools turned on): what "+" reuses rather than making
 *  another empty session. A session already pointed at a folder isn't blank, so "+" for another
 *  folder never hands it back. `defaults` is /api/state's default_skills. */
export function isBlank(s: Session, messages: Record<string, unknown[]> = st().messages as Record<string, unknown[]>,
  defaults: string[] = st().appState?.default_skills ?? ["delegation"]): boolean {
  const cfg = s.settings ?? {};
  const skills: string[] = cfg.skills ?? [];
  const sameSkills = skills.length === 0 || (skills.length === defaults.length && skills.every((k) => defaults.includes(k)));
  return s.title === "New session" && !s.deleted && !s.archived && !s.pinned && !s.forked_from && s.status !== "running"
    && !s.activity_at && !(messages[s.id]?.length) && !s.folder
    && sameSkills && !Object.values(cfg.connectors ?? {}).some(Boolean) && !cfg.shared_tools;
}

export const sessionActions = {
  /** ⌘N: a new session; it joins the current session's group. */
  async create(opts: { group_id?: string | null } = {}) {
    if (creating) return creating; // a double click makes one session, not two
    creating = (async () => {
      const cur = find(st().currentId ?? "");
      const group_id = opts.group_id !== undefined ? opts.group_id : cur && !cur.deleted && !cur.archived ? cur.group_id : null;
      // An untitled session with no messages in the same group is reused instead of adding another
      // empty "New session": the current one first, else the newest such session.
      const reuse = cur && isBlank(cur) && (cur.group_id ?? null) === (group_id ?? null) ? cur
        : st().sessions.filter((x) => isBlank(x) && (x.group_id ?? null) === (group_id ?? null)).sort((a, b) => b.created_at - a.created_at)[0];
      const s = reuse ?? await attempt(() => post<Session>("/sessions", group_id ? { group_id } : {}));
      if (!s) return;
      if (st().sidebarView !== "active") set({ sidebarView: "active" });
      if (st().currentId !== s.id || st().page !== "chat") await actions.openSession(s.id);
      requestAnimationFrame(() => document.getElementById("composer")?.focus());
    })();
    try { await creating; } finally { creating = null; }
  },
  async rename(id: string, title: string) {
    set({ renamingId: null });
    const s = find(id);
    if (s && title.trim() && title.trim() !== s.title) await attempt(() => patch(`/sessions/${id}`, { title: title.trim() }));
  },
  startRename(id: string) {
    const s = find(id);
    if (!s || s.deleted) return;
    const view = s.archived ? "archived" : "active";
    // The row must be on screen for the inline editor: open the section it's in. (The sidebar
    // also clears a search that hides it.)
    const sec = buildSections(st().sessions, st().groups, prefs, view).find((x) => x.sessions.some((v) => v.id === id));
    if (sec?.collapsed) {
      if (sec.group) {
        set((x) => ({ groups: x.groups.map((g) => (g.id === sec.group!.id ? { ...g, collapsed: false } : g)) }));
        patch(`/groups/${sec.group.id}`, { collapsed: false });
      } else setPrefs({ collapsed: prefs.collapsed.filter((k) => k !== sec.key) });
    }
    set({ renamingId: id, sidebarView: view });
  },
  async regenerateTitle(id: string) {
    actions.toast("Naming the session…");
    const s = await attempt(() => post<Session>(`/sessions/${id}/title`));
    if (s) actions.toast(`Renamed to “${s.title}”`);
  },
  async setPinned(ids: string[], pinned: boolean) {
    await attempt(() => bulk(ids, pinned ? "pin" : "unpin"));
  },
  async togglePin(id: string) {
    const s = find(id);
    if (s) await sessionActions.setPinned([id], !s.pinned);
  },
  async move(ids: string[], group_id: string | null) {
    await attempt(() => bulk(ids, "move", { group_id }));
  },
  /** A new group (named inline right away), optionally with sessions moved into it. */
  async newGroup(sessionIds: string[] = []) {
    const g = await attempt(() => post<Group>("/groups", { name: "New group", session_ids: sessionIds }));
    if (!g) return;
    set((x) => ({ groups: x.groups.some((o) => o.id === g.id) ? x.groups : [...x.groups, g], renamingGroupId: g.id, sidebarView: "active" }));
    if (getPrefs().groupBy !== "groups") setPrefs({ groupBy: "groups" });
  },
  async renameGroup(id: string, name: string) {
    set({ renamingGroupId: null });
    const g = st().groups.find((x) => x.id === id);
    if (g && name.trim() && name.trim() !== g.name) await attempt(() => patch(`/groups/${id}`, { name: name.trim() }));
  },
  async recolorGroup(id: string, color: string) {
    await attempt(() => patch(`/groups/${id}`, { color }));
  },
  async toggleGroup(g: Group) {
    set((x) => ({ groups: x.groups.map((o) => (o.id === g.id ? { ...o, collapsed: !g.collapsed } : o)) })); // instant
    await attempt(() => patch(`/groups/${g.id}`, { collapsed: !g.collapsed }));
  },
  async deleteGroup(g: Group) {
    const n = st().sessions.filter((s) => s.group_id === g.id && !s.deleted).length;
    if (n && !confirm(`Delete the group “${g.name}”? Its ${plural(n, "session")} stay, ungrouped.`)) return;
    await attempt(() => del(`/groups/${g.id}`));
  },
  async reorderGroups(ids: string[]) {
    set((x) => ({ groups: ids.map((id) => x.groups.find((g) => g.id === id)!).filter(Boolean) }));
    await attempt(() => post("/groups/reorder", { ids }));
  },
  async reorderPinned(ids: string[]) {
    const unpinned = ids.filter((id) => !find(id)?.pinned);
    if (unpinned.length) await attempt(() => bulk(unpinned, "pin"));
    await attempt(() => post("/sessions/reorder", { ids }));
  },
  async duplicate(id: string) {
    const s = await attempt(() => post<Session>(`/sessions/${id}/duplicate`));
    if (s) {
      set({ sidebarView: "active" });
      await actions.openSession(s.id);
    }
  },
  async fork(id: string, messageId: string) {
    const s = await attempt(() => post<Session>(`/sessions/${id}/fork`, { message_id: messageId }));
    if (s) {
      set({ sidebarView: "active" });
      await actions.openSession(s.id);
      actions.toast("Forked. The new session continues from that message.");
    }
  },
  async archive(ids: string[], archived = true) {
    const leave = archived && st().sidebarView === "active" ? planLeave(ids) : null;
    const r = await attempt(() => bulk(ids, archived ? "archive" : "unarchive"));
    if (r) leave?.();
    if (r && archived) actions.toast(`Archived ${plural(ids.length, "session")}.`, "info", { label: "Undo", run: () => bulk(ids, "unarchive") });
  },
  async setRead(ids: string[], read: boolean) {
    await attempt(() => bulk(ids, read ? "read" : "unread"));
  },
  /** Delete = move to Trash, with Undo. */
  async trash(ids: string[]) {
    ids = ids.filter((id) => find(id) && !find(id)!.deleted);
    if (!ids.length) return;
    const leave = planLeave(ids);
    const r = await attempt(() => bulk(ids, "delete"));
    if (r) leave();
    if (r) actions.toast(`Moved ${ids.length === 1 ? `“${find(ids[0])?.title ?? "session"}”` : plural(ids.length, "session")} to Trash.`, "info",
      { label: "Undo", run: () => bulk(ids, "restore") });
  },
  async restore(ids: string[]) {
    const r = await attempt(() => bulk(ids, "restore"));
    if (r) actions.toast(`Restored ${plural(ids.length, "session")}.`);
  },
  async purge(ids: string[]) {
    const what = ids.length === 1 ? `“${find(ids[0])?.title ?? "this session"}”` : plural(ids.length, "session");
    if (!confirm(`Delete ${what} forever? Messages and outputs are removed from the app. This can't be undone.`)) return;
    const leave = planLeave(ids);
    if (await attempt(() => bulk(ids, "purge"))) leave();
  },
  async emptyTrash() {
    const n = st().sessions.filter((s) => s.deleted).length;
    if (!n || !confirm(`Delete ${plural(n, "session")} in Trash forever? This can't be undone.`)) return;
    const cur = find(st().currentId ?? "");
    if (cur?.deleted) set({ currentId: null });
    await attempt(() => post("/trash/empty"));
  },
  exportMd(id: string) {
    const s = useStore.getState().sessions.find((x) => x.id === id);
    downloadFile(`/sessions/${id}/export`, `${(s?.title ?? "").replace(/[^\w\- ]/g, "").slice(0, 60) || "session"}.md`);
  },
  async revealFolder(folder: string) {
    if (!(await revealInFinder(folder))) {
      await navigator.clipboard?.writeText(folder).catch(() => {});
      actions.toast("Reveal in Finder works in the app. The folder path was copied.");
    }
  },
  /** ⌘⇧[ / ⌘⇧]: previous / next session in sidebar order. */
  step(delta: 1 | -1) {
    const order = visibleOrder();
    if (!order.length) return;
    const i = order.indexOf(st().currentId ?? "");
    const next = order[i < 0 ? 0 : (i + delta + order.length) % order.length];
    if (next) actions.openSession(next);
  },
  setView(view: SidebarView) {
    set({ sidebarView: view, selection: [] });
  },
};
