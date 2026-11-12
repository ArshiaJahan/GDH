import {
  Archive, ArchiveRestore, ArrowLeft, AudioLines, BarChart3, CalendarClock, ChevronRight, ChevronsDownUp, ChevronsUpDown, Copy, Download, Ellipsis, FolderInput,
  Flag, FolderOpen, FolderPlus, FolderSearch, Hand, ListFilter, LoaderCircle, Mail, MailOpen, Monitor, Moon, Pencil, Pin, PinOff, Plus, Puzzle,
  RotateCcw, Search, Settings, Sparkles, SquareKanban, Sun, Trash2, TriangleAlert, X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type DragEvent, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { get } from "../lib/api";
import {
  activity, buildSections, getPrefs, GROUP_COLORS, sessionActions as A, setPrefs, subscribePrefs, visibleOrder,
  type GroupBy, type Section, type SortBy,
} from "../lib/sessions";
import { actions, useStore, type Group, type Page, type Session } from "../lib/store";
import { stripMarkdown } from "../lib/mdlite";
import { Menu, type MenuItem } from "./ui";
import { UpdateBanner } from "./Updates";

/** ⌘N and the "New session" buttons. Joins the current session's group. */
export const newSession = () => A.create();

type Hit = { session_id: string; title: string; archived: boolean; match: "title" | "message"; message_id: string | null; snippet: string | null };

/** What is being dragged (dataTransfer can't be read during dragover, so it's kept here). */
let drag: { kind: "sessions"; ids: string[] } | { kind: "group"; id: string } | null = null;
const SESSION_MIME = "application/x-gamedevworkstation-sessions";

const FADE_MASK = "linear-gradient(to bottom, #000 calc(100% - 28px), transparent)";

const cap = (w: string) => w.charAt(0).toUpperCase() + w.slice(1);

function shortAgo(ts?: number | null): string {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Search snippet: the backend wraps matches in \x02 … \x03 (plain text, never HTML).
 *  Markdown (backticks, emphasis, fences, list markers) is stripped for the preview. */
function Snippet({ text }: { text: string }) {
  const parts = stripMarkdown(text).split(/(\x02[^\x03]*\x03)/g);
  return <>{parts.map((p, i) => (p.startsWith("\x02") ? <mark key={i}>{p.slice(1, -1)}</mark> : <span key={i}>{p}</span>))}</>;
}

const Dot = ({ color, className = "" }: { color: string; className?: string }) => (
  <span className={`inline-block size-2 rounded-full shrink-0 ${className}`} style={{ background: color }} />
);

export function Sidebar() {
  const sessions = useStore((s) => s.sessions);
  const groups = useStore((s) => s.groups);
  const currentId = useStore((s) => s.currentId);
  const page = useStore((s) => s.page);
  const theme = useStore((s) => s.theme);
  const view = useStore((s) => s.sidebarView);
  const selection = useStore((s) => s.selection);
  const renamingId = useStore((s) => s.renamingId);
  const renamingGroupId = useStore((s) => s.renamingGroupId);
  const approvals = useStore((s) => s.approvals);
  const prefs = useSyncExternalStore(subscribePrefs, getPrefs);
  const trashDays = useStore((s) => s.appState?.sessions?.trash_days ?? 30);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null);
  const [drop, setDrop] = useState<string | null>(null);
  // True while sessions are dragged: an empty "Sessions" section then shows, as the drop target that ungroups.
  const [draggingSessions, setDraggingSessions] = useState(false);
  const [, tick] = useState(0);
  const anchor = useRef<string | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  // The list fades out at the bottom while there's more below, so it reads as scrollable.
  const [fade, setFade] = useState(false);
  const updateFade = () => {
    const el = listRef.current;
    if (el) setFade(el.scrollHeight - el.scrollTop - el.clientHeight > 4);
  };
  useEffect(() => {
    const el = listRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(updateFade);
    ro.observe(el);
    const mo = new MutationObserver(updateFade);
    mo.observe(el, { childList: true, subtree: true });
    updateFade();
    return () => { ro.disconnect(); mo.disconnect(); };
  }, []);

  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 60_000); // relative times
    const esc = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented && useStore.getState().selection.length) useStore.setState({ selection: [] });
    };
    window.addEventListener("keydown", esc);
    return () => { clearInterval(t); window.removeEventListener("keydown", esc); };
  }, []);

  const waiting = useMemo(() => new Set(Object.values(approvals).filter((a) => a.status === "pending" && a.session_id).map((a) => a.session_id!)), [approvals]);
  const sections = useMemo(() => buildSections(sessions, groups, prefs, view), [sessions, groups, prefs, view]);
  const counts = useMemo(() => ({
    archived: sessions.filter((s) => !s.deleted && s.archived).length,
    trash: sessions.filter((s) => s.deleted).length,
  }), [sessions]);

  // ------------------------------------------------------------------ search
  const term = q.trim();
  const titleHits = useMemo(() => {
    const t = term.toLowerCase();
    return t ? sessions.filter((s) => !s.deleted && s.title.toLowerCase().includes(t)).sort((a, b) => activity(b) - activity(a)) : [];
  }, [sessions, term]);
  useEffect(() => {
    if (!term) return setHits([]);
    let live = true;
    const t = setTimeout(() => get<Hit[]>(`/sessions/search?q=${encodeURIComponent(term)}`).then((h) => live && setHits(h)).catch(() => {}), 220);
    return () => { live = false; clearTimeout(t); };
  }, [term]);
  const msgHits = hits.filter((h) => h.match === "message" && !titleHits.some((s) => s.id === h.session_id));
  useEffect(() => { // renaming a session the search hides: show the list again so its row (and editor) is there
    if (renamingId && term && !titleHits.some((s) => s.id === renamingId)) setQ("");
  }, [renamingId]); // eslint-disable-line react-hooks/exhaustive-deps
  const openHit = async (h: Hit) => {
    await actions.openSession(h.session_id);
    if (h.message_id) useStore.setState({ focusMessage: h.message_id });
  };

  // ------------------------------------------------------------- selection
  const setSelection = (ids: string[]) => useStore.setState({ selection: ids });
  const onRowClick = (e: MouseEvent, s: Session) => {
    if (e.metaKey || e.ctrlKey) {
      const order = visibleOrder();
      const base = selection.length ? selection : currentId && currentId !== s.id && order.includes(currentId) ? [currentId] : [];
      setSelection(base.includes(s.id) ? base.filter((i) => i !== s.id) : [...base, s.id]);
      anchor.current = s.id;
      return;
    }
    if (e.shiftKey) {
      const order = term ? titleHits.map((x) => x.id) : visibleOrder();
      const a = order.indexOf(anchor.current ?? currentId ?? "");
      const b = order.indexOf(s.id);
      if (a >= 0 && b >= 0) {
        setSelection(order.slice(Math.min(a, b), Math.max(a, b) + 1));
        return;
      }
    }
    setSelection([]);
    anchor.current = s.id;
    actions.openSession(s.id);
  };

  // ------------------------------------------------------------------ menus
  const openMenu = (e: { clientX: number; clientY: number } | HTMLElement, items: MenuItem[]) => {
    if (e instanceof HTMLElement) {
      const r = e.getBoundingClientRect();
      setMenu({ x: r.left, y: r.bottom + 2, items });
    } else setMenu({ x: e.clientX, y: e.clientY, items });
  };
  const moveItems = (ids: string[], current?: string | null): MenuItem[] => [
    ...groups.map((g): MenuItem => ({ label: g.name, icon: <Dot color={GROUP_COLORS[g.color] ?? GROUP_COLORS.gray} className="mt-1" />, checked: current === g.id, onClick: () => A.move(ids, g.id) })),
    ...(groups.length ? (["sep"] as MenuItem[]) : []),
    { label: "New group…", icon: <FolderPlus size={14} />, onClick: () => A.newGroup(ids) },
    ...(current ? [{ label: "Remove from group", icon: <X size={14} />, onClick: () => A.move(ids, null) }] : []),
  ];
  const bulkItems = (ids: string[]): MenuItem[] => {
    const list = sessions.filter((s) => ids.includes(s.id));
    if (view === "trash") return [
      { heading: `${ids.length} selected` },
      { label: "Restore", icon: <RotateCcw size={14} />, onClick: () => { A.restore(ids); setSelection([]); } },
      { label: "Delete forever", icon: <Trash2 size={14} />, danger: true, onClick: () => A.purge(ids) },
    ];
    const allPinned = list.every((s) => s.pinned);
    const allArchived = list.every((s) => s.archived);
    return [
      { heading: `${ids.length} selected` },
      { label: allPinned ? "Unpin" : "Pin", icon: allPinned ? <PinOff size={14} /> : <Pin size={14} />, onClick: () => A.setPinned(ids, !allPinned) },
      { label: "Move to group", icon: <FolderInput size={14} />, submenu: moveItems(ids) },
      { label: allArchived ? "Unarchive" : "Archive", icon: allArchived ? <ArchiveRestore size={14} /> : <Archive size={14} />, onClick: () => A.archive(ids, !allArchived) },
      { label: "Mark as read", icon: <MailOpen size={14} />, onClick: () => A.setRead(ids, true) },
      "sep",
      { label: "Delete", icon: <Trash2 size={14} />, danger: true, kbd: "⌘⌫", onClick: () => A.trash(ids) },
    ];
  };
  const rowItems = (s: Session): MenuItem[] => {
    if (selection.length > 1 && selection.includes(s.id)) return bulkItems(selection);
    if (s.deleted) return [
      { label: "Open", onClick: () => actions.openSession(s.id) },
      { label: "Restore", icon: <RotateCcw size={14} />, onClick: () => A.restore([s.id]) },
      "sep",
      { label: "Delete forever", icon: <Trash2 size={14} />, danger: true, onClick: () => A.purge([s.id]) },
    ];
    return [
      { label: "Open artifacts", icon: <FolderOpen size={14} />, onClick: () => actions.go("artifacts", { sessions: [s.id] }) },
      { label: "Rename", icon: <Pencil size={14} />, kbd: "F2", onClick: () => A.startRename(s.id) },
      { label: "Regenerate title", icon: <Sparkles size={14} />, onClick: () => A.regenerateTitle(s.id) },
      { label: s.pinned ? "Unpin" : "Pin", icon: s.pinned ? <PinOff size={14} /> : <Pin size={14} />, kbd: "⌘⇧P", onClick: () => A.togglePin(s.id) },
      { label: "Move to group", icon: <FolderInput size={14} />, submenu: moveItems([s.id], s.group_id) },
      { label: "Duplicate", icon: <Copy size={14} />, onClick: () => A.duplicate(s.id) },
      { label: s.archived ? "Unarchive" : "Archive", icon: s.archived ? <ArchiveRestore size={14} /> : <Archive size={14} />, onClick: () => A.archive([s.id], !s.archived) },
      s.unread
        ? { label: "Mark as read", icon: <MailOpen size={14} />, onClick: () => A.setRead([s.id], true) }
        : { label: "Mark as unread", icon: <Mail size={14} />, onClick: () => A.setRead([s.id], false) },
      ...(s.folder ? [{ label: "Reveal folder in Finder", icon: <FolderSearch size={14} />, hint: s.folder, onClick: () => A.revealFolder(s.folder!) }] : []),
      { label: "Export as Markdown", icon: <Download size={14} />, onClick: () => A.exportMd(s.id) },
      "sep",
      { label: "Delete", icon: <Trash2 size={14} />, danger: true, kbd: "⌘⌫", onClick: () => A.trash([s.id]) },
    ];
  };
  const groupItems = (g: Group): MenuItem[] => [
    { label: "New session in group", icon: <Plus size={14} />, onClick: () => A.create({ group_id: g.id }) },
    { label: "Rename group", icon: <Pencil size={14} />, onClick: () => useStore.setState({ renamingGroupId: g.id }) },
    { label: "Color", icon: <Dot color={GROUP_COLORS[g.color] ?? GROUP_COLORS.gray} />, submenu: Object.entries(GROUP_COLORS).map(([c, v]) => ({
      label: cap(c), icon: <Dot color={v} className="mt-1" />, checked: g.color === c, onClick: () => A.recolorGroup(g.id, c),
    })) },
    { label: g.collapsed ? "Expand" : "Collapse", icon: g.collapsed ? <ChevronsUpDown size={14} /> : <ChevronsDownUp size={14} />, onClick: () => A.toggleGroup(g) },
    "sep",
    { label: "Delete group", icon: <Trash2 size={14} />, danger: true, hint: "Its sessions stay, ungrouped", onClick: () => A.deleteGroup(g) },
  ];
  const headerItems = (): MenuItem[] => [
    { label: "New session", icon: <Plus size={14} />, kbd: "⌘N", onClick: () => A.create() },
    { label: "New group", icon: <FolderPlus size={14} />, onClick: () => A.newGroup() },
    { heading: "Group by" },
    ...([["groups", "Groups"], ["folder", "Folder"], ["date", "Date"], ["none", "None"]] as [GroupBy, string][]).map(([k, l]) => ({
      label: l, checked: prefs.groupBy === k, onClick: () => setPrefs({ groupBy: k }) })),
    { heading: "Sort by" },
    ...([["activity", "Last activity"], ["created", "Created"], ["name", "Name"]] as [SortBy, string][]).map(([k, l]) => ({
      label: l, checked: prefs.sortBy === k, onClick: () => setPrefs({ sortBy: k }) })),
    "sep",
    { label: `Archived (${counts.archived})`, icon: <Archive size={14} />, onClick: () => A.setView(view === "archived" ? "active" : "archived") },
    { label: `Trash (${counts.trash})`, icon: <Trash2 size={14} />, onClick: () => A.setView(view === "trash" ? "active" : "trash") },
  ];

  // ---------------------------------------------------------- drag and drop
  const acceptsSessions = (sec: Section) => sec.kind === "group" || sec.kind === "ungrouped" || sec.kind === "pinned";
  const sectionDragOver = (e: DragEvent, sec: Section) => {
    if (drag?.kind === "sessions" && acceptsSessions(sec)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDrop(sec.key);
    } else if (drag?.kind === "group" && sec.kind === "group" && drag.id !== sec.group!.id) {
      e.preventDefault();
      const r = e.currentTarget.getBoundingClientRect();
      setDrop(`grp:${sec.group!.id}:${e.clientY < r.top + Math.min(r.height / 2, 16) ? "before" : "after"}`);
    }
  };
  const sectionDrop = (e: DragEvent, sec: Section) => {
    e.preventDefault();
    const d = drag;
    const target = drop;
    drag = null;
    setDrop(null);
    setDraggingSessions(false);
    if (!d) return;
    if (d.kind === "sessions") {
      const pinned = d.ids.filter((id) => sessions.find((s) => s.id === id)?.pinned);
      if (sec.kind === "pinned") A.setPinned(d.ids, true);
      else {
        A.move(d.ids, sec.kind === "group" ? sec.group!.id : null);
        if (pinned.length) A.setPinned(pinned, false); // dragged out of Pinned: lands in the section you see
      }
    } else if (sec.kind === "group" && target?.startsWith("grp:")) {
      const [, id, pos] = target.split(":");
      const ids = groups.map((g) => g.id).filter((g) => g !== d.id);
      ids.splice(ids.indexOf(id) + (pos === "after" ? 1 : 0), 0, d.id);
      A.reorderGroups(ids);
    }
  };
  const pinnedRowDragOver = (e: DragEvent, s: Session) => {
    if (drag?.kind !== "sessions") return;
    e.preventDefault();
    e.stopPropagation();
    const r = e.currentTarget.getBoundingClientRect();
    setDrop(`row:${s.id}:${e.clientY < r.top + r.height / 2 ? "before" : "after"}`);
  };
  const pinnedRowDrop = (e: DragEvent, sec: Section, s: Session) => {
    e.preventDefault();
    e.stopPropagation();
    const d = drag;
    const pos = drop?.endsWith(":after") ? 1 : 0;
    drag = null;
    setDrop(null);
    setDraggingSessions(false);
    if (d?.kind !== "sessions") return;
    const ids = sec.sessions.map((x) => x.id).filter((id) => !d.ids.includes(id));
    const at = ids.indexOf(s.id);
    ids.splice(at < 0 ? ids.length : at + pos, 0, ...d.ids);
    A.reorderPinned(ids);
  };
  const clearDropOnLeave = (e: DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) setDrop(null);
  };

  // --------------------------------------------------------------- keyboard
  const focusRow = (from: HTMLElement, delta: number | "first" | "last") => {
    const rows = [...(listRef.current?.querySelectorAll<HTMLElement>("[data-row]") ?? [])];
    const i = rows.indexOf(from);
    const next = delta === "first" ? rows[0] : delta === "last" ? rows[rows.length - 1] : rows[i + delta];
    next?.focus();
  };
  const onRowKey = (e: KeyboardEvent<HTMLDivElement>, s: Session) => {
    const el = e.currentTarget;
    if (e.target !== el && (e.key === "Enter" || e.key === " ")) return; // a row action button handles its own keys
    if (e.key === "ArrowDown" || e.key === "ArrowUp") focusRow(el, e.key === "ArrowDown" ? 1 : -1);
    else if (e.key === "Home" || e.key === "End") focusRow(el, e.key === "Home" ? "first" : "last");
    else if ((e.key === "Enter" || e.key === "F2") && !s.deleted) A.startRename(s.id);
    else if (e.key === " " || (e.key === "Enter" && s.deleted)) actions.openSession(s.id);
    else if (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey)) openMenu(el, rowItems(s));
    else if ((e.metaKey || e.ctrlKey) && e.key === "Backspace") {
      if (!e.repeat) (s.deleted ? A.purge : A.trash)(selection.includes(s.id) ? selection : [s.id]);
    }
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  // ------------------------------------------------------------------ rows
  // Row actions show on hover and when the keyboard is on the row or its buttons (Tab reaches them).
  const rowAction = "hidden group-hover/row:inline-flex group-focus-visible/row:inline-flex group-has-[:focus-visible]/row:inline-flex btn btn-ghost p-0.5";
  const rowTime = "text-[11px] text-faint shrink-0 tabular-nums group-hover/row:hidden group-focus-visible/row:hidden group-has-[:focus-visible]/row:hidden";
  const renderRow = (s: Session, sec: Section) => {
    if (renamingId === s.id) {
      return (
        <li key={s.id}>
          <input autoFocus className="input my-0.5 py-0.5 text-[13px]" defaultValue={s.title} aria-label="Session name"
            onFocus={(e) => e.currentTarget.select()}
            onBlur={(e) => {
              A.rename(s.id, e.currentTarget.value);
              requestAnimationFrame(() => (listRef.current?.querySelector(`[data-row="${s.id}"]`) as HTMLElement | null)?.focus());
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
              if (e.key === "Escape") { e.preventDefault(); e.currentTarget.value = s.title; e.currentTarget.blur(); }
            }} />
        </li>
      );
    }
    const isCurrent = s.id === currentId && page === "chat";
    const selected = selection.includes(s.id);
    const running = s.status === "running";
    const unread = s.unread && s.id !== currentId && !s.deleted;
    const pinnedRow = sec.kind === "pinned";
    const dropLine = drop === `row:${s.id}:before` ? "inset 0 2px 0 var(--action)" : drop === `row:${s.id}:after` ? "inset 0 -2px 0 var(--action)" : undefined;
    const when = s.deleted ? s.deleted_at : prefs.sortBy === "created" ? s.created_at : activity(s);
    return (
      <li key={s.id}>
        <div role="button" tabIndex={0} data-row={s.id} aria-current={isCurrent ? "page" : undefined} aria-selected={selected || undefined}
          title={s.title}
          className={`group/row w-full flex items-center gap-1.5 pl-2 pr-1 h-[30px] rounded text-[13px] cursor-default select-none focus:outline-none focus-visible:ring-1 focus-visible:ring-action ${
            selected ? "bg-action/15 text-text" : isCurrent ? "bg-sunken text-text" : "text-muted hover:bg-sunken hover:text-text"}`}
          style={{ boxShadow: dropLine }}
          draggable={!s.deleted}
          onDragStart={(e) => {
            const ids = selected ? selection : [s.id];
            drag = { kind: "sessions", ids };
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData(SESSION_MIME, ids.join(","));
            setTimeout(() => setDraggingSessions(true)); // after dragstart: changing the DOM inside it can cancel the drag
          }}
          onDragEnd={() => { drag = null; setDrop(null); setDraggingSessions(false); }}
          onDragOver={pinnedRow ? (e) => pinnedRowDragOver(e, s) : undefined}
          onDrop={pinnedRow ? (e) => pinnedRowDrop(e, sec, s) : undefined}
          onClick={(e) => onRowClick(e, s)}
          onDoubleClick={() => !s.deleted && A.startRename(s.id)}
          onContextMenu={(e) => { e.preventDefault(); openMenu(e, rowItems(s)); }}
          onKeyDown={(e) => onRowKey(e, s)}>
          <span className="w-3 flex justify-center shrink-0">
            {running ? <span title="Working"><LoaderCircle size={11} className="text-action animate-spin motion-reduce:animate-none" /></span>
              : unread ? <span className="size-1.5 rounded-full bg-action" title="Unread reply" /> : null}
          </span>
          <span className={`truncate flex-1 ${unread ? "font-medium text-text" : ""}`}>{s.title}</span>
          {waiting.has(s.id) && <span className="shrink-0 text-warn" title="Waiting for your approval"><Hand size={12} /></span>}
          {s.last_error && !running && <span className="shrink-0 text-bad" title={`Last turn failed: ${s.last_error}`}><TriangleAlert size={12} /></span>}
          {s.pinned && sec.kind !== "pinned" && view === "active" && <Pin size={11} className="text-faint shrink-0" />}
          {s.archived && view !== "archived" && <span className="chip text-[11px] leading-4 px-1">archived</span>}
          {s.deleted ? (
            <>
              <span className={rowTime}>{shortAgo(when)}</span>
              <button className={rowAction} title="Restore" aria-label="Restore" onClick={(e) => { e.stopPropagation(); A.restore([s.id]); }}><RotateCcw size={13} /></button>
              <button className={`${rowAction} text-bad`} title="Delete forever" aria-label="Delete forever" onClick={(e) => { e.stopPropagation(); A.purge([s.id]); }}><Trash2 size={13} /></button>
            </>
          ) : (
            <>
              <span className={rowTime}>{shortAgo(when)}</span>
              <button className={rowAction} title="More actions" aria-label={`Actions for ${s.title}`} aria-haspopup="menu"
                onClick={(e) => { e.stopPropagation(); openMenu(e.currentTarget, rowItems(s)); }}><Ellipsis size={14} /></button>
            </>
          )}
        </div>
      </li>
    );
  };

  const renderHeader = (sec: Section, showUngroupedHeader: boolean) => {
    if (sec.kind === "flat" || (sec.kind === "ungrouped" && !showUngroupedHeader)) return null;
    const g = sec.group;
    const toggle = () => (g ? A.toggleGroup(g) : setPrefs({ collapsed: sec.collapsed ? prefs.collapsed.filter((k) => k !== sec.key) : [...prefs.collapsed, sec.key] }));
    const line = g && drop === `grp:${g.id}:before` ? "inset 0 2px 0 var(--action)" : g && drop === `grp:${g.id}:after` && sec.collapsed ? "inset 0 -2px 0 var(--action)" : undefined;
    return (
      <div className="group/h flex items-center gap-0.5 pl-1 pr-1 pt-2 pb-0.5 rounded" style={{ boxShadow: line }}
        draggable={!!g && renamingGroupId !== g.id}
        onDragStart={g ? (e) => { drag = { kind: "group", id: g.id }; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("application/x-gamedevworkstation-group", g.id); } : undefined}
        onDragEnd={() => { drag = null; setDrop(null); }}
        onContextMenu={g ? (e) => { e.preventDefault(); openMenu(e, groupItems(g)); } : undefined}>
        {g && renamingGroupId === g.id ? (
          <input autoFocus className="input py-0.5 text-[12.5px]" defaultValue={g.name} aria-label="Group name"
            onFocus={(e) => e.currentTarget.select()}
            onBlur={(e) => A.renameGroup(g.id, e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
              if (e.key === "Escape") { e.preventDefault(); e.currentTarget.value = g.name; e.currentTarget.blur(); }
            }} />
        ) : (
          <button className="flex items-center gap-1.5 min-w-0 flex-1 text-left text-[12px] text-muted hover:text-text py-0.5 px-1 rounded"
            onClick={toggle} onDoubleClick={g ? () => useStore.setState({ renamingGroupId: g.id }) : undefined} aria-expanded={!sec.collapsed} title={sec.hint}>
            <ChevronRight size={12} className={`shrink-0 transition-transform ${sec.collapsed ? "" : "rotate-90"}`} />
            {sec.color && <Dot color={sec.color} />}
            {sec.kind === "pinned" && <Pin size={11} className="shrink-0" />}
            <span className="truncate font-medium">{sec.title}</span>
            <span className="text-faint tabular-nums">{sec.sessions.length}</span>
          </button>
        )}
        {g && renamingGroupId !== g.id && (
          <>
            <button className="opacity-0 group-hover/h:opacity-100 focus:opacity-100 btn btn-ghost p-0.5" title="New session in this group" aria-label={`New session in ${g.name}`}
              onClick={() => A.create({ group_id: g.id })}><Plus size={13} /></button>
            <button className="opacity-0 group-hover/h:opacity-100 focus:opacity-100 btn btn-ghost p-0.5" title="Group actions" aria-label={`Actions for group ${g.name}`} aria-haspopup="menu"
              onClick={(e) => openMenu(e.currentTarget, groupItems(g))}><Ellipsis size={13} /></button>
          </>
        )}
      </div>
    );
  };

  // ------------------------------------------------------------------ list
  let list: ReactNode;
  if (term) {
    const flat: Section = { key: "search", kind: "flat", title: "", sessions: titleHits, collapsed: false };
    list = (
      <>
        {titleHits.map((s) => renderRow(s, flat))}
        {msgHits.length > 0 && <li className="label px-2 pt-3 pb-1">In messages</li>}
        {msgHits.map((h) => (
          <li key={`m:${h.session_id}`}>
            <button className="w-full text-left px-2 py-1.5 rounded hover:bg-sunken focus-visible:bg-sunken" onClick={() => openHit(h)}>
              <span className="block truncate text-[13px]">{h.title}{h.archived && <span className="chip text-[11px] leading-4 px-1 ml-1.5">archived</span>}</span>
              {h.snippet && <span className="block text-[12px] text-muted line-clamp-2"><Snippet text={h.snippet} /></span>}
            </button>
          </li>
        ))}
        {!titleHits.length && !msgHits.length && <li className="px-2 py-2 text-[13px] text-muted">No matching sessions.</li>}
      </>
    );
  } else {
    const showUngroupedHeader = sections.length > 1;
    // An empty "Sessions" section next to others is noise; it shows only while dragging sessions (to ungroup them).
    const hideUngrouped = (sec: Section) => sec.kind === "ungrouped" && !sec.sessions.length && sections.length > 1 && !draggingSessions;
    const empty = sections.every((s) => !s.sessions.length) && !(prefs.groupBy === "groups" && groups.length && view === "active");
    list = (
      <>
        {view !== "active" && (
          <li className="flex items-center gap-1 px-1 pt-1 pb-1">
            <button className="btn btn-ghost px-1" onClick={() => A.setView("active")} title="Back to sessions" aria-label="Back to sessions"><ArrowLeft size={14} /></button>
            <span className="font-medium text-[13px]">{view === "trash" ? "Trash" : "Archived"}</span>
            <span className="text-faint text-[12px]">{view === "trash" ? counts.trash : counts.archived}</span>
            {view === "trash" && counts.trash > 0 && <button className="ml-auto btn btn-ghost btn-danger py-0.5 text-[12px]" onClick={A.emptyTrash}>Empty trash</button>}
          </li>
        )}
        {view === "trash" && <li className="px-2 pb-1 text-[12px] text-faint">Deleted sessions stay here for {trashDays} days.</li>}
        {sections.filter((sec) => !hideUngrouped(sec)).map((sec) => (
          <li key={sec.key} className={`rounded ${drop === sec.key ? "bg-action/10 outline-1 outline-action" : ""}`}
            onDragOver={(e) => sectionDragOver(e, sec)} onDragLeave={clearDropOnLeave} onDrop={(e) => sectionDrop(e, sec)}>
            {renderHeader(sec, showUngroupedHeader)}
            {!sec.collapsed && (
              <ul>
                {sec.sessions.map((s) => renderRow(s, sec))}
                {sec.kind === "group" && !sec.sessions.length && <li className="pl-7 py-1 text-[12px] text-faint">Empty. Drag sessions here.</li>}
              </ul>
            )}
          </li>
        ))}
        {empty && (
          <li className="px-2 py-2 text-[13px] text-muted">
            {view === "trash" ? "Trash is empty." : view === "archived" ? "No archived sessions." : "No sessions yet. Start one with +."}
          </li>
        )}
      </>
    );
  }

  const nav: { page: Page; label: string; icon: any }[] = [
    { page: "artifacts", label: "Artifacts", icon: FolderOpen },
    { page: "elevenlabs", label: "ElevenLabs", icon: AudioLines },
    { page: "board", label: "Tasks", icon: SquareKanban },
    { page: "schedule", label: "Schedule", icon: CalendarClock },
    { page: "campaigns", label: "Campaigns", icon: Flag },
    { page: "skills", label: "Skills & MCP", icon: Puzzle },
    { page: "usage", label: "My usage", icon: BarChart3 },
    { page: "settings", label: "Settings", icon: Settings },
  ];
  const ThemeIcon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  const selectedSessions = sessions.filter((s) => selection.includes(s.id));
  const allPinned = selectedSessions.length > 0 && selectedSessions.every((s) => s.pinned);
  const allArchived = selectedSessions.length > 0 && selectedSessions.every((s) => s.archived);
  const barBtn = "btn btn-ghost p-1";

  return (
    <nav className="h-full flex flex-col surface border-r border-line select-none" aria-label="Sessions">
      <div className="px-3 pt-3 pb-2 flex items-center gap-1" data-tauri-drag-region>
        <span className="font-semibold tracking-tight mr-auto">GameDevWorkstation</span>
        <button className="btn btn-ghost px-1.5" onClick={(e) => openMenu(e.currentTarget, headerItems())} title="New group, group by, sort, archived and trash" aria-label="Session list options" aria-haspopup="menu"><ListFilter size={15} /></button>
        <button className="btn btn-ghost px-1.5" onClick={newSession} title="New session (⌘N)" aria-label="New session"><Plus size={16} /></button>
      </div>
      <div className="px-3 pb-2">
        <label className="relative block">
          <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
          <input className="input pl-7 pr-6 py-1 text-[13px]" placeholder="Search sessions and messages" value={q} aria-label="Search sessions and messages"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setQ("");
              if (e.key === "Enter") {
                if (titleHits[0]) actions.openSession(titleHits[0].id);
                else if (msgHits[0]) openHit(msgHits[0]);
              }
              if (e.key === "ArrowDown") { e.preventDefault(); (listRef.current?.querySelector("[data-row], button") as HTMLElement | null)?.focus(); }
            }} />
          {q && <button className="absolute right-1.5 top-1/2 -translate-y-1/2 text-faint hover:text-text" onClick={() => setQ("")} aria-label="Clear search"><X size={13} /></button>}
        </label>
      </div>
      <ul ref={listRef} onScroll={updateFade} className="flex-1 overflow-y-auto scroll-thin px-1.5 pb-2"
        style={fade ? { maskImage: FADE_MASK, WebkitMaskImage: FADE_MASK } : undefined} aria-label={view === "trash" ? "Trash" : view === "archived" ? "Archived sessions" : "Sessions"}>
        {list}
      </ul>
      {selection.length > 0 && (
        <div className="mx-1.5 mb-1.5 flex items-center gap-0.5 rounded-md border border-line surface-raised shadow-sm pl-2.5 pr-1 py-1 text-[12.5px]" role="toolbar" aria-label="Selected sessions">
          <span className="font-medium mr-auto">{selection.length} selected</span>
          {view === "trash" ? (
            <>
              <button className={barBtn} title="Restore" aria-label="Restore selected" onClick={() => { A.restore(selection); setSelection([]); }}><RotateCcw size={14} /></button>
              <button className={`${barBtn} text-bad`} title="Delete forever" aria-label="Delete selected forever" onClick={() => A.purge(selection)}><Trash2 size={14} /></button>
            </>
          ) : (
            <>
              <button className={barBtn} title={allPinned ? "Unpin" : "Pin"} aria-label={allPinned ? "Unpin selected" : "Pin selected"} onClick={() => A.setPinned(selection, !allPinned)}>{allPinned ? <PinOff size={14} /> : <Pin size={14} />}</button>
              <button className={barBtn} title="Move to group" aria-label="Move selected to group" aria-haspopup="menu" onClick={(e) => openMenu(e.currentTarget, moveItems(selection))}><FolderInput size={14} /></button>
              <button className={barBtn} title={allArchived ? "Unarchive" : "Archive"} aria-label={allArchived ? "Unarchive selected" : "Archive selected"} onClick={() => A.archive(selection, !allArchived)}>{allArchived ? <ArchiveRestore size={14} /> : <Archive size={14} />}</button>
              <button className={`${barBtn} text-bad`} title="Move to Trash" aria-label="Move selected to Trash" onClick={() => A.trash(selection)}><Trash2 size={14} /></button>
            </>
          )}
          <button className={barBtn} title="Clear selection (Esc)" aria-label="Clear selection" onClick={() => setSelection([])}><X size={14} /></button>
        </div>
      )}
      {/* Compact footer: Archived and Trash, then the pages as one icon row (names in tooltips). */}
      <div className="border-t border-line p-1.5 text-[13px]">
        <UpdateBanner />
        <div className="flex gap-1 mb-0.5">
          {(["archived", "trash"] as const).map((v) => (
            <button key={v} onClick={() => A.setView(view === v ? "active" : v)} aria-pressed={view === v}
              className={`flex-1 flex items-center gap-1.5 px-2 py-1 rounded text-[12.5px] ${view === v ? "bg-sunken text-text" : "text-muted hover:bg-sunken hover:text-text"}`}>
              {v === "trash" ? <Trash2 size={13} /> : <Archive size={13} />} {v === "trash" ? "Trash" : "Archived"}
              {(v === "trash" ? counts.trash : counts.archived) > 0 && <span className="ml-auto text-faint tabular-nums">{v === "trash" ? counts.trash : counts.archived}</span>}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-0.5" role="group" aria-label="Pages">
          {nav.map((n) => (
            <button key={n.page} onClick={() => actions.go(n.page)} title={n.label} aria-label={n.label} aria-current={page === n.page ? "page" : undefined}
              className={`flex-1 flex items-center justify-center h-8 rounded ${page === n.page ? "bg-sunken text-text" : "text-muted hover:bg-sunken hover:text-text"}`}>
              <n.icon size={16} />
            </button>
          ))}
          <span className="w-px h-4 bg-line" aria-hidden />
          <button onClick={actions.cycleTheme} title={`Theme: ${theme} (click to switch)`} aria-label={`Theme: ${theme}`}
            className="flex-1 flex items-center justify-center h-8 rounded text-muted hover:bg-sunken hover:text-text">
            <ThemeIcon size={16} />
          </button>
        </div>
      </div>
      {menu && <Menu x={menu.x} y={menu.y} onClose={() => setMenu(null)} items={menu.items} />}
    </nav>
  );
}
