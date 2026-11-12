// Tasks: the Kanban task board the user and the agent share (backend features/task_board.py).
// Board switcher, columns with drag-and-drop cards (native HTML5 DnD), quick add per column, a
// filter bar, a task drawer with every field, and Recently deleted. task.* events keep it live.
import {
  ArchiveRestore, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Bot, CalendarDays, Check, ChevronDown, Ellipsis, ListChecks, MessageSquare,
  Plus, RotateCcw, Search, SquareKanban, Trash2, X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import { del, get, patch, post } from "../lib/api";
import { actions, useStore } from "../lib/store";
import { initials, normalizeCode, personLabel, PRIORITIES } from "../lib/taskCodes";
import { SafeMarkdown } from "../components/SafeMarkdown";
import { Collapsible, Empty, fmtAgo, Menu, type MenuItem } from "../components/ui";

export type Column = { id: string; board_id: string; name: string; sort_order: number; is_done: boolean; count: number };
export type Board = { id: string; name: string; sort_order: number; columns: Column[] };
export type TaskSummary = {
  id: string; code: string; num: number; title: string; board_id: string; board: string; column_id: string; column: string;
  done: boolean; position: number; priority: string; labels: string[]; due: string | null; overdue: boolean; assignees: string[];
  agent_touched: boolean; created_by: string; subtasks: { done: number; total: number }; comments: number; sessions: number;
  archived: boolean; archived_at: number | null; created_at: number; updated_at: number;
};
export type Subtask = { id: string; title: string; done: boolean; items: { id: string; title: string; done: boolean }[] };
export type TaskDetail = TaskSummary & {
  description: string; subtasks_list: Subtask[];
  comments_list: { id: string; author: string; by_agent: boolean; body: string; session_id: string | null; created_at: number }[];
  activity: { actor: string; action: string; text: string; session_id: string | null; ts: number }[];
  linked_sessions: { id: string; title: string; linked_at: number; missing: boolean; in_trash: boolean }[];
};
type Filters = { q: string; assignee: string; label: string; priority: string; due: string };
const NO_FILTERS: Filters = { q: "", assignee: "", label: "", priority: "", due: "" };

export const PRIORITY_COLOR: Record<string, string> = { urgent: "var(--bad)", high: "var(--warn)", medium: "var(--action)", low: "var(--faint)" };

/** "2026-11-15" → "Nov 15" (a date without a time, read in local time). */
export function fmtDue(due: string): string {
  const [y, m, d] = due.split("-").map(Number);
  const date = new Date(y, (m || 1) - 1, d || 1);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", ...(y !== new Date().getFullYear() ? { year: "numeric" } : {}) });
}

const toast = (e: any) => actions.toast(e?.message ?? String(e), "error");

/** Search query for the board view (include_done: the Done column shows too). */
export function searchQuery(boardId: string, f: Filters): string {
  const p = new URLSearchParams({ board: boardId, include_done: "true", limit: "2000" });
  if (f.q.trim()) p.set("q", f.q.trim());
  for (const k of ["assignee", "label", "priority", "due"] as const) if (f[k]) p.set(k, f[k]);
  return `/tasks/search?${p}`;
}

function useTaskEvents(fn: () => void, delay = 120) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const off = actions.onEvent((e) => {
      if (!e.type.startsWith("task.")) return;
      clearTimeout(t);
      t = setTimeout(() => ref.current(), delay);
    });
    return () => { clearTimeout(t); off(); };
  }, [delay]);
}

function InlineInput({ initial = "", placeholder, onSubmit, onCancel, className = "", keepOpen }: {
  initial?: string; placeholder?: string; onSubmit: (v: string) => void | Promise<void>; onCancel: () => void; className?: string; keepOpen?: boolean;
}) {
  const [v, setV] = useState(initial);
  return (
    <input autoFocus className={`input py-1 text-[13px] ${className}`} value={v} placeholder={placeholder} aria-label={placeholder}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => (v.trim() && v.trim() !== initial && !keepOpen ? onSubmit(v.trim()) : onCancel())}
      onKeyDown={async (e) => {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onCancel(); }
        else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
          e.preventDefault();
          if (!v.trim() || v.trim() === initial) return onCancel();
          await onSubmit(v.trim());
          if (keepOpen) setV("");
        }
      }} />
  );
}

export function PriorityPill({ p }: { p: string }) {
  if (!p || p === "none") return null;
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium capitalize" style={{ color: PRIORITY_COLOR[p] }} title={`Priority: ${p}`}>
      <span className="size-1.5 rounded-full" style={{ background: PRIORITY_COLOR[p] }} />{p}
    </span>
  );
}

export function Assignee({ name, size = 20 }: { name: string; size?: number }) {
  const agent = name === "agent";
  return (
    <span className={`inline-flex items-center justify-center rounded-full border border-[var(--panel)] text-[9.5px] font-semibold shrink-0 ${agent ? "bg-action text-[var(--action-text)]" : "bg-sunken text-muted"}`}
      style={{ width: size, height: size }} title={personLabel(name)} aria-label={`Assigned to ${personLabel(name)}`}>
      {agent ? <Bot size={size * 0.6} /> : initials(name)}
    </span>
  );
}

/** One card on the board. */
export function TaskCard({ t, onOpen, dragging, onDragStart, onDragEnd }: {
  t: TaskSummary; onOpen: (code: string) => void; dragging?: boolean;
  onDragStart?: (e: DragEvent, t: TaskSummary) => void; onDragEnd?: () => void;
}) {
  return (
    <div data-card={t.code} draggable={!!onDragStart} role="button" tabIndex={0} aria-label={`${t.code}: ${t.title}`}
      onDragStart={(e) => onDragStart?.(e, t)} onDragEnd={onDragEnd}
      onClick={() => onOpen(t.code)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(t.code); } }}
      className={`group rounded-md border border-line surface-raised px-2.5 py-2 text-[13px] cursor-pointer shadow-sm hover:border-faint ${dragging ? "opacity-40" : ""} ${t.done ? "opacity-80" : ""}`}>
      <div className="flex items-center gap-1.5 text-[11.5px] text-faint">
        <span className="font-mono">{t.code}</span>
        {t.agent_touched && <span className="inline-flex items-center gap-0.5 text-action" title="The agent created or changed this task" aria-label="Agent touched"><Bot size={12} /></span>}
        <span className="ml-auto"><PriorityPill p={t.priority} /></span>
      </div>
      <div className={`mt-0.5 leading-snug break-words ${t.done ? "line-through decoration-faint" : ""}`}>{t.title}</div>
      {t.labels.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">{t.labels.map((l) => <span key={l} className="chip leading-[18px] text-[11px]">#{l}</span>)}</div>
      )}
      {(t.due || t.subtasks.total > 0 || t.comments > 0 || t.assignees.length > 0) && (
        <div className="mt-1.5 flex items-center gap-2.5 text-[11.5px] text-muted">
          {t.due && (
            <span className={`inline-flex items-center gap-1 ${t.overdue ? "text-bad font-medium" : ""}`} title={t.overdue ? `Overdue: was due ${t.due}` : `Due ${t.due}`} data-overdue={t.overdue || undefined}>
              <CalendarDays size={12} />{fmtDue(t.due)}
            </span>
          )}
          {t.subtasks.total > 0 && (
            <span className={`inline-flex items-center gap-1 ${t.subtasks.done === t.subtasks.total ? "text-ok" : ""}`} title="Subtasks done">
              <ListChecks size={12} />{t.subtasks.done}/{t.subtasks.total}
            </span>
          )}
          {t.comments > 0 && <span className="inline-flex items-center gap-1" title="Comments"><MessageSquare size={12} />{t.comments}</span>}
          {t.assignees.length > 0 && (
            <span className="ml-auto flex -space-x-1">{t.assignees.slice(0, 4).map((a) => <Assignee key={a} name={a} />)}</span>
          )}
        </div>
      )}
    </div>
  );
}

type DropAt = { col: string; before: string | null };

export function BoardPage() {
  const pageArgs = useStore((s) => s.pageArgs);
  const [boards, setBoards] = useState<Board[] | null>(null);
  const [people, setPeople] = useState<string[]>(["me", "agent"]);
  const [boardId, setBoardId] = useState<string | null>(() => localStorage.getItem("taskBoard"));
  const [tasks, setTasks] = useState<TaskSummary[] | null>(null);
  const [deleted, setDeleted] = useState<TaskSummary[]>([]);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [view, setView] = useState<"board" | "deleted">("board");
  const [openCode, setOpenCode] = useState<string | null>(null);
  const [drag, setDrag] = useState<string | null>(null);
  const [dropAt, setDropAt] = useState<DropAt | null>(null);
  const [adding, setAdding] = useState<string | null>(null); // column id with the quick-add field open
  const [naming, setNaming] = useState<{ kind: "board" | "rename-board" | "column" | "rename-column"; id?: string } | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null);
  const [seenLabels, setSeenLabels] = useState<string[]>([]);

  const board = boards?.find((b) => b.id === boardId) ?? boards?.[0] ?? null;
  const loadBoards = useCallback(() => get("/tasks/boards").then((r) => { setBoards(r.boards); setPeople(r.people); }).catch(toast), []);
  const loadTasks = useCallback(() => {
    if (!board) return;
    get(searchQuery(board.id, filters)).then((r) => {
      setTasks(r.tasks);
      setSeenLabels((cur) => [...new Set([...cur, ...r.tasks.flatMap((t: TaskSummary) => t.labels)])].sort((a, b) => a.localeCompare(b)));
    }).catch(toast);
  }, [board?.id, filters]); // eslint-disable-line react-hooks/exhaustive-deps
  const loadDeleted = useCallback(() => get("/tasks/archived").then((r) => setDeleted(r.tasks)).catch(() => {}), []);

  useEffect(() => { loadBoards(); loadDeleted(); }, [loadBoards, loadDeleted]);
  useEffect(() => {
    const t = setTimeout(loadTasks, filters.q ? 180 : 0);
    return () => clearTimeout(t);
  }, [loadTasks]); // eslint-disable-line react-hooks/exhaustive-deps
  useTaskEvents(() => { loadBoards(); loadTasks(); loadDeleted(); });
  useEffect(() => {
    if (pageArgs?.task) setOpenCode(normalizeCode(pageArgs.task) ?? String(pageArgs.task));
    if (typeof pageArgs?.q === "string") { setFilters({ ...NO_FILTERS, q: pageArgs.q }); setView("board"); }
  }, [pageArgs]);
  useEffect(() => { if (board) localStorage.setItem("taskBoard", board.id); }, [board?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const byColumn = useMemo(() => {
    const m: Record<string, TaskSummary[]> = {};
    for (const t of tasks ?? []) (m[t.column_id] ??= []).push(t);
    return m;
  }, [tasks]);
  const filtered = Object.values(filters).some(Boolean);

  // ------------------------------------------------------------------ drag and drop
  const onDragStart = (e: DragEvent, t: TaskSummary) => {
    e.dataTransfer.setData("text/x-task-code", t.code);
    e.dataTransfer.setData("text/plain", t.code);
    e.dataTransfer.effectAllowed = "move";
    setDrag(t.code);
  };
  const onDragEnd = () => { setDrag(null); setDropAt(null); };
  const overColumn = (e: DragEvent<HTMLElement>, col: Column) => {
    if (!drag) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const cards = [...e.currentTarget.querySelectorAll<HTMLElement>("[data-card]")].filter((el) => el.dataset.card !== drag);
    const next = cards.find((el) => { const r = el.getBoundingClientRect(); return e.clientY < r.top + r.height / 2; });
    const before = next?.dataset.card ?? null;
    if (dropAt?.col !== col.id || dropAt.before !== before) setDropAt({ col: col.id, before });
  };
  const drop = async (e: DragEvent, col: Column) => {
    e.preventDefault();
    const code = drag ?? e.dataTransfer.getData("text/x-task-code");
    const at = dropAt;
    onDragEnd();
    if (!code || !tasks) return;
    const t = tasks.find((x) => x.code === code);
    if (!t) return;
    const before = at?.col === col.id ? at.before : null;
    const b = before ? tasks.find((x) => x.code === before) : null;
    // Index among the column's other tasks (cards hidden by a filter keep their places).
    let index: number | null = b ? b.position : null;
    if (index != null && t.column_id === col.id && t.position < index) index -= 1;
    if (t.column_id === col.id && (before === null ? (byColumn[col.id] ?? []).at(-1)?.code === code : index === t.position)) return;
    // Show it there at once; the reload that follows has the server's order.
    setTasks((cur) => {
      if (!cur) return cur;
      const rest = cur.filter((x) => x.code !== code);
      const moved = { ...t, column_id: col.id, column: col.name, done: col.is_done };
      const i = before ? rest.findIndex((x) => x.code === before) : -1;
      if (i >= 0) rest.splice(i, 0, moved);
      else {
        const last = rest.map((x) => x.column_id).lastIndexOf(col.id);
        rest.splice(last >= 0 ? last + 1 : rest.length, 0, moved);
      }
      return rest;
    });
    try {
      await patch(`/tasks/items/${code}`, { column: col.id, ...(index != null ? { index } : { position: "bottom" }) });
    } catch (err) {
      toast(err);
    }
    loadTasks();
  };

  // ------------------------------------------------------------------ boards and columns
  const columnMenu = (col: Column, el: HTMLElement): void => {
    if (!board) return;
    const cols = board.columns;
    const i = cols.findIndex((c) => c.id === col.id);
    const order = (j: number) => {
      const ids = cols.map((c) => c.id);
      [ids[i], ids[j]] = [ids[j], ids[i]];
      post(`/tasks/boards/${board.id}/order`, { column_ids: ids }).then(loadBoards).catch(toast);
    };
    const r = el.getBoundingClientRect();
    setMenu({ x: r.left, y: r.bottom + 4, items: [
      { label: "Rename", icon: <SquareKanban size={14} />, onClick: () => setNaming({ kind: "rename-column", id: col.id }) },
      { label: col.is_done ? "Not a done column" : "Mark as done column", icon: <Check size={14} />,
        hint: "Tasks here count as done and are left out of searches unless asked for",
        onClick: () => patch(`/tasks/columns/${col.id}`, { is_done: !col.is_done }).then(loadBoards).catch(toast) },
      { label: "Move left", icon: <ArrowLeft size={14} />, disabled: i === 0, onClick: () => order(i - 1) },
      { label: "Move right", icon: <ArrowRight size={14} />, disabled: i === cols.length - 1, onClick: () => order(i + 1) },
      "sep",
      { label: "Delete column", icon: <Trash2 size={14} />, danger: true, disabled: cols.length <= 1,
        hint: col.count ? `Its ${col.count} task(s) move to ${cols.find((c) => c.id !== col.id)?.name}` : undefined,
        onClick: () => { if (confirm(`Delete column "${col.name}"?${col.count ? ` Its ${col.count} task(s) move to ${cols.find((c) => c.id !== col.id)?.name}.` : ""}`)) del(`/tasks/columns/${col.id}`).then(loadBoards).catch(toast); } },
    ] });
  };
  const boardMenu = (el: HTMLElement) => {
    if (!board || !boards) return;
    const r = el.getBoundingClientRect();
    setMenu({ x: r.left, y: r.bottom + 4, items: [
      ...boards.map((b) => ({ label: b.name, checked: b.id === board.id, onClick: () => setBoardId(b.id) })),
      "sep",
      { label: "New board…", icon: <Plus size={14} />, onClick: () => setNaming({ kind: "board" }) },
      { label: "Rename board", icon: <SquareKanban size={14} />, onClick: () => setNaming({ kind: "rename-board", id: board.id }) },
      { label: "Delete board", icon: <Trash2 size={14} />, danger: true, disabled: boards.length <= 1, onClick: async () => {
        const n = board.columns.reduce((s, c) => s + c.count, 0);
        if (!confirm(`Delete board "${board.name}"${n ? ` and its ${n} task(s)` : ""}? This can't be undone.`)) return;
        try {
          await del(`/tasks/boards/${board.id}?force=true`);
          setBoardId(null);
          loadBoards();
        } catch (e) { toast(e); }
      } },
    ] });
  };
  const submitName = async (v: string) => {
    const n = naming;
    setNaming(null);
    try {
      if (n?.kind === "board") { const b = await post("/tasks/boards", { name: v }); setBoardId(b.id); }
      else if (n?.kind === "rename-board" && n.id) await patch(`/tasks/boards/${n.id}`, { name: v });
      else if (n?.kind === "column" && board) await post(`/tasks/boards/${board.id}/columns`, { name: v });
      else if (n?.kind === "rename-column" && n.id) await patch(`/tasks/columns/${n.id}`, { name: v });
      loadBoards();
    } catch (e) { toast(e); }
  };
  const quickAdd = (col: Column) => async (title: string) => {
    try {
      await post("/tasks/items", { title, board: board!.id, column: col.id });
      loadTasks();
    } catch (e) { toast(e); }
  };

  const sel = "input py-1 text-[12.5px] w-auto";
  return (
    <div className="h-full flex flex-col min-w-0 relative">
      <header className="flex items-center gap-2 px-4 h-11 border-b border-line surface shrink-0" data-tauri-drag-region>
        <SquareKanban size={16} className="text-muted" />
        <h1 className="font-medium">Tasks</h1>
        {naming?.kind === "board" || naming?.kind === "rename-board" ? (
          <InlineInput className="max-w-[220px]" placeholder="Board name" initial={naming.kind === "rename-board" ? board?.name : ""} onSubmit={submitName} onCancel={() => setNaming(null)} />
        ) : (
          <button className="btn btn-ghost px-2 font-medium" aria-haspopup="menu" aria-label={`Board: ${board?.name ?? ""}`} onClick={(e) => boardMenu(e.currentTarget)}>
            {board?.name ?? "…"}<ChevronDown size={14} className="text-muted" />
          </button>
        )}
        <div className="ml-auto flex items-center gap-1">
          <button className={`btn ${view === "deleted" ? "" : "btn-ghost"} text-[12.5px]`} aria-pressed={view === "deleted"} onClick={() => setView(view === "deleted" ? "board" : "deleted")}>
            <Trash2 size={13} /> Recently deleted{deleted.length > 0 && <span className="text-faint tabular-nums">{deleted.length}</span>}
          </button>
        </div>
      </header>

      {view === "board" && (
        <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-line surface shrink-0" role="search" aria-label="Filter tasks">
          <label className="relative block w-[240px] max-w-full">
            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
            <input className="input pl-7 py-1 text-[12.5px]" placeholder="Filter: words or Task00001" aria-label="Filter tasks by text or code" value={filters.q}
              onChange={(e) => setFilters({ ...filters, q: e.target.value })} onKeyDown={(e) => e.key === "Escape" && setFilters({ ...filters, q: "" })} />
          </label>
          <select className={sel} aria-label="Assignee" value={filters.assignee} onChange={(e) => setFilters({ ...filters, assignee: e.target.value })}>
            <option value="">Anyone</option>
            {people.map((p) => <option key={p} value={p}>{personLabel(p)}</option>)}
            <option value="unassigned">Unassigned</option>
          </select>
          <select className={sel} aria-label="Label" value={filters.label} onChange={(e) => setFilters({ ...filters, label: e.target.value })}>
            <option value="">Any label</option>
            {[...new Set([...seenLabels, ...(filters.label ? [filters.label] : [])])].map((l) => <option key={l} value={l}>#{l}</option>)}
          </select>
          <select className={sel} aria-label="Priority" value={filters.priority} onChange={(e) => setFilters({ ...filters, priority: e.target.value })}>
            <option value="">Any priority</option>
            {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <select className={sel} aria-label="Due" value={filters.due} onChange={(e) => setFilters({ ...filters, due: e.target.value })}>
            <option value="">Any due date</option><option value="overdue">Overdue</option><option value="today">Due today</option>
            <option value="week">Due within 7 days</option><option value="none">No due date</option>
          </select>
          {filtered && <button className="btn btn-ghost text-[12.5px]" onClick={() => setFilters(NO_FILTERS)}><X size={13} /> Clear</button>}
        </div>
      )}

      {view === "deleted" ? (
        <DeletedList tasks={deleted} onOpen={setOpenCode} reload={() => { loadDeleted(); loadTasks(); loadBoards(); }} />
      ) : (
        <div className="flex-1 min-h-0 overflow-x-auto overflow-y-hidden scroll-thin">
          <div className="h-full flex items-stretch gap-3 p-4 w-max min-w-full">
            {board?.columns.map((col) => {
              const list = byColumn[col.id] ?? [];
              const over = dropAt?.col === col.id;
              return (
                <section key={col.id} aria-label={`Column ${col.name}`} data-column={col.name}
                  className={`w-[272px] shrink-0 flex flex-col rounded-lg border ${over ? "border-action" : "border-line"} bg-sunken/60 max-h-full`}
                  onDragOver={(e) => overColumn(e, col)} onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDropAt(null); }}
                  onDrop={(e) => drop(e, col)}>
                  <div className="flex items-center gap-1.5 px-2.5 pt-2 pb-1.5">
                    {naming?.kind === "rename-column" && naming.id === col.id ? (
                      <InlineInput initial={col.name} placeholder="Column name" onSubmit={submitName} onCancel={() => setNaming(null)} />
                    ) : (
                      <>
                        {col.is_done && <Check size={13} className="text-ok shrink-0" aria-label="Done column" />}
                        <h2 className="text-[13px] font-semibold truncate" onDoubleClick={() => setNaming({ kind: "rename-column", id: col.id })}>{col.name}</h2>
                        <span className="text-[12px] text-faint tabular-nums" title={filtered ? `${list.length} shown of ${col.count}` : undefined}>{filtered ? `${list.length}/${col.count}` : col.count}</span>
                        <button className="btn btn-ghost p-0.5 ml-auto" aria-label={`Column ${col.name} options`} aria-haspopup="menu" onClick={(e) => columnMenu(col, e.currentTarget)}><Ellipsis size={14} /></button>
                      </>
                    )}
                  </div>
                  <div className="flex-1 min-h-[40px] overflow-y-auto scroll-thin px-2 pb-2 space-y-1.5">
                    {list.map((t) => (
                      <div key={t.code}>
                        {over && dropAt?.before === t.code && <div className="h-0.5 rounded bg-action mb-1.5" aria-hidden />}
                        <TaskCard t={t} onOpen={setOpenCode} dragging={drag === t.code} onDragStart={onDragStart} onDragEnd={onDragEnd} />
                      </div>
                    ))}
                    {over && dropAt?.before === null && <div className="h-0.5 rounded bg-action" aria-hidden />}
                    {tasks && list.length === 0 && !over && <div className="text-[12px] text-faint px-1 py-2">{filtered ? "No matching tasks" : "No tasks"}</div>}
                  </div>
                  <div className="px-2 pb-2">
                    {adding === col.id ? (
                      <InlineInput keepOpen placeholder={`New task in ${col.name}`} onSubmit={quickAdd(col)} onCancel={() => setAdding(null)} />
                    ) : (
                      <button className="w-full flex items-center gap-1.5 rounded px-1.5 py-1 text-[12.5px] text-muted hover:bg-sunken hover:text-text" onClick={() => setAdding(col.id)}>
                        <Plus size={13} /> Add task
                      </button>
                    )}
                  </div>
                </section>
              );
            })}
            {board && (
              <div className="w-[220px] shrink-0">
                {naming?.kind === "column" ? (
                  <InlineInput placeholder="Column name" onSubmit={submitName} onCancel={() => setNaming(null)} />
                ) : (
                  <button className="btn btn-ghost text-muted" onClick={() => setNaming({ kind: "column" })}><Plus size={14} /> Add column</button>
                )}
              </div>
            )}
          </div>
        </div>
      )}
      {openCode && <TaskDrawer code={openCode} boards={boards ?? []} people={people} onClose={() => setOpenCode(null)} />}
      {menu && <Menu x={menu.x} y={menu.y} items={menu.items} onClose={() => setMenu(null)} />}
    </div>
  );
}

function DeletedList({ tasks, onOpen, reload }: { tasks: TaskSummary[]; onOpen: (c: string) => void; reload: () => void }) {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto scroll-thin">
      <div className="max-w-[860px] mx-auto px-6 py-5">
        <h2 className="font-semibold mb-1">Recently deleted</h2>
        <p className="text-[13px] text-muted mb-3">Archived tasks. Restore puts a task back at the bottom of its column. Deleting one for good can't be undone; its code is never used again.</p>
        {tasks.length === 0 && <Empty>Nothing here.</Empty>}
        <div className="space-y-1.5">
          {tasks.map((t) => (
            <div key={t.code} className="flex items-center gap-2 rounded-md border border-line surface-raised px-3 py-2 text-[13px]">
              <button className="flex-1 min-w-0 text-left flex items-center gap-2" onClick={() => onOpen(t.code)}>
                <span className="font-mono text-[12px] text-faint shrink-0">{t.code}</span>
                <span className="truncate">{t.title}</span>
                <span className="text-[12px] text-faint shrink-0">{t.board} › {t.column}</span>
              </button>
              <span className="text-[12px] text-faint shrink-0">{fmtAgo(t.archived_at)}</span>
              <button className="btn py-0.5" onClick={() => post(`/tasks/items/${t.code}/restore`).then(reload).catch(toast)}><RotateCcw size={13} /> Restore</button>
              <button className="btn btn-ghost btn-danger px-1.5" aria-label={`Delete ${t.code} for good`} title="Delete for good"
                onClick={() => confirm(`Delete ${t.code} for good? This can't be undone.`) && del(`/tasks/items/${t.code}`).then(reload).catch(toast)}><Trash2 size={14} /></button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[92px_1fr] items-center gap-2 min-h-8">
      <span className="label">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Chips with a remove button and a field to add more (labels, assignees). */
function ChipEditor({ values, render, onChange, placeholder, suggestions }: {
  values: string[]; render: (v: string) => ReactNode; onChange: (v: string[]) => void; placeholder: string; suggestions?: string[];
}) {
  const [v, setV] = useState("");
  const id = useMemo(() => `dl-${Math.random().toString(36).slice(2)}`, []);
  const add = () => {
    const x = v.trim().replace(/^[#@]/, "");
    setV("");
    if (x && !values.some((o) => o.toLowerCase() === x.toLowerCase())) onChange([...values, x]);
  };
  return (
    <div className="flex flex-wrap items-center gap-1">
      {values.map((x) => (
        <span key={x} className="chip text-text">{render(x)}<button aria-label={`Remove ${x}`} onClick={() => onChange(values.filter((o) => o !== x))}><X size={11} /></button></span>
      ))}
      <input className="input py-0.5 text-[12.5px] w-[130px]" placeholder={placeholder} aria-label={placeholder} value={v} list={suggestions ? id : undefined}
        onChange={(e) => setV(e.target.value)} onBlur={add} onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }} />
      {suggestions && <datalist id={id}>{suggestions.filter((s) => !values.includes(s)).map((s) => <option key={s} value={s}>{personLabel(s)}</option>)}</datalist>}
    </div>
  );
}

export function TaskDrawer({ code, boards, people, onClose }: { code: string; boards: Board[]; people: string[]; onClose: () => void }) {
  const [d, setD] = useState<TaskDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [title, setTitle] = useState("");
  const [editDesc, setEditDesc] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [newSub, setNewSub] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [addingItem, setAddingItem] = useState<string | null>(null);
  const currentId = useStore((s) => s.currentId);
  const sessions = useStore((s) => s.sessions);
  const load = useCallback(() => get<TaskDetail>(`/tasks/items/${code}`).then((x) => { setD(x); setTitle(x.title); setMissing(false); })
    .catch(() => setMissing(true)), [code]);
  useEffect(() => { setD(null); setEditDesc(null); load(); }, [load]);
  useTaskEvents(load);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && !e.defaultPrevented && !document.querySelector("[data-modal], [role=menu]")) onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  const save = async (changes: Record<string, unknown>) => {
    try { setD(await patch<TaskDetail>(`/tasks/items/${code}`, changes)); } catch (e) { toast(e); load(); }
  };
  const ops = async (list: Record<string, unknown>[]) => {
    try { setD(await post<TaskDetail>(`/tasks/items/${code}/subtasks`, { ops: list })); } catch (e) { toast(e); load(); }
  };
  const act = (path: string, body?: unknown) => post<TaskDetail>(`/tasks/items/${code}/${path}`, body ?? {}).then(setD).catch(toast);

  const board = boards.find((b) => b.id === d?.board_id);
  const subsDone = d?.subtasks_list.filter((s) => s.done).length ?? 0;
  const linkedHere = !!d?.linked_sessions.some((s) => s.id === currentId);
  const current = sessions.find((s) => s.id === currentId && !s.deleted);

  return (
    <>
      <div className="absolute inset-0 z-10 bg-black/10 dark:bg-black/30" onMouseDown={onClose} aria-hidden />
      <aside role="dialog" aria-label={d ? `${d.code}: ${d.title}` : `Task ${code}`}
        className="absolute right-0 top-0 bottom-0 z-20 w-[min(560px,100%)] border-l border-line surface-raised shadow-xl flex flex-col">
        <div className="flex items-center gap-2 px-4 h-11 border-b border-line shrink-0">
          <span className="font-mono text-[13px] text-muted">{d?.code ?? code}</span>
          {d?.agent_touched && <span className="chip text-action" title="The agent created or changed this task"><Bot size={12} />agent</span>}
          {d && !d.archived && <button className="btn btn-ghost ml-auto text-[12.5px]" onClick={() => act("archive")} title="Move to Recently deleted (restorable)"><Trash2 size={13} /> Archive</button>}
          <button className={`btn btn-ghost px-1.5 ${d && !d.archived ? "" : "ml-auto"}`} aria-label="Close" onClick={onClose}><X size={16} /></button>
        </div>
        {missing && <div className="p-4 text-[13px] text-muted">Task {code} doesn't exist (it may have been deleted for good).</div>}
        {d && (
          <div className="flex-1 overflow-y-auto scroll-thin px-4 py-3 space-y-4 text-[13px]">
            {d.archived && (
              <div className="flex items-center gap-2 rounded-md border border-line bg-sunken px-3 py-1.5">
                <Trash2 size={13} className="text-muted" /><span className="flex-1">In Recently deleted since {fmtAgo(d.archived_at)}.</span>
                <button className="btn py-0.5" onClick={() => act("restore")}><ArchiveRestore size={13} /> Restore</button>
                <button className="btn btn-ghost btn-danger py-0.5" onClick={() => { if (confirm(`Delete ${d.code} for good? This can't be undone.`)) del(`/tasks/items/${d.code}`).then(onClose).catch(toast); }}>Delete for good</button>
              </div>
            )}
            <textarea className="w-full resize-none bg-transparent outline-none text-[16px] font-semibold leading-snug focus:bg-sunken rounded px-1 -mx-1" rows={Math.min(4, Math.ceil(title.length / 48) || 1)}
              aria-label="Title" value={title} onChange={(e) => setTitle(e.target.value)}
              onBlur={() => title.trim() && title.trim() !== d.title ? save({ title }) : setTitle(d.title)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); (e.target as HTMLTextAreaElement).blur(); } }} />
            <div className="space-y-1">
              <Field label="Status">
                <div className="flex gap-1.5">
                  {boards.length > 1 && (
                    <select className="input py-1 text-[12.5px] w-auto" aria-label="Board" value={d.board_id} onChange={(e) => save({ board: e.target.value })}>
                      {boards.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                    </select>
                  )}
                  <select className="input py-1 text-[12.5px] w-auto" aria-label="Column" value={d.column_id} onChange={(e) => save({ column: e.target.value, board: d.board_id })}>
                    {(board?.columns ?? [{ id: d.column_id, name: d.column }]).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
              </Field>
              <Field label="Priority">
                <select className="input py-1 text-[12.5px] w-auto" aria-label="Priority" value={d.priority} onChange={(e) => save({ priority: e.target.value })}>
                  {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </Field>
              <Field label="Due">
                <div className="flex items-center gap-1.5">
                  <input type="date" className={`input py-1 text-[12.5px] w-auto ${d.overdue ? "text-bad" : ""}`} aria-label="Due date" value={d.due ?? ""} onChange={(e) => save({ due: e.target.value || null })} />
                  {d.due && <button className="btn btn-ghost px-1" aria-label="Remove due date" onClick={() => save({ due: null })}><X size={13} /></button>}
                  {d.overdue && <span className="text-bad text-[12px] font-medium">Overdue</span>}
                </div>
              </Field>
              <Field label="Labels">
                <ChipEditor values={d.labels} render={(l) => `#${l}`} placeholder="Add label" onChange={(labels) => save({ labels })} />
              </Field>
              <Field label="Assignees">
                <ChipEditor values={d.assignees} render={(a) => <><Assignee name={a} size={16} />{personLabel(a)}</>} placeholder="Add person"
                  suggestions={people} onChange={(assignees) => save({ assignees })} />
              </Field>
            </div>

            <section aria-label="Description">
              <div className="flex items-center mb-1"><h3 className="label font-medium">Description</h3>
                {editDesc === null && <button className="btn btn-ghost py-0 ml-auto text-[12px]" onClick={() => setEditDesc(d.description)}>Edit</button>}</div>
              {editDesc !== null ? (
                <div>
                  <textarea autoFocus className="input font-mono text-[12.5px] h-40" aria-label="Description (Markdown)" value={editDesc} onChange={(e) => setEditDesc(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { save({ description: editDesc }); setEditDesc(null); } }} />
                  <div className="flex justify-end gap-1.5 mt-1">
                    <button className="btn" onClick={() => setEditDesc(null)}>Cancel</button>
                    <button className="btn btn-primary" onClick={() => { save({ description: editDesc }); setEditDesc(null); }}>Save</button>
                  </div>
                </div>
              ) : d.description.trim() ? (
                <div className="prose-ws rounded px-1 -mx-1 hover:bg-sunken cursor-text" onDoubleClick={() => setEditDesc(d.description)}><SafeMarkdown text={d.description} /></div>
              ) : <button className="text-faint hover:text-text" onClick={() => setEditDesc("")}>Add a description (Markdown)…</button>}
            </section>

            <section aria-label="Subtasks">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="label font-medium">Subtasks</h3>
                {d.subtasks_list.length > 0 && (
                  <>
                    <span className="text-[12px] text-faint tabular-nums">{subsDone}/{d.subtasks_list.length}</span>
                    <progress className="h-1.5 w-24" max={d.subtasks_list.length} value={subsDone} aria-label="Subtasks done" />
                  </>
                )}
              </div>
              <ul className="space-y-0.5">
                {d.subtasks_list.map((s, i) => (
                  <li key={s.id} className="group/st">
                    <div className="flex items-center gap-2 rounded px-1 hover:bg-sunken">
                      <input type="checkbox" checked={s.done} aria-label={`Done: ${s.title}`} onChange={() => ops([{ op: "toggle", id: s.id, done: !s.done }])} />
                      {renaming === s.id ? (
                        <InlineInput initial={s.title} placeholder="Subtask" onSubmit={(v) => { setRenaming(null); return ops([{ op: "rename", id: s.id, title: v }]); }} onCancel={() => setRenaming(null)} />
                      ) : <span className={`flex-1 min-w-0 py-0.5 ${s.done ? "line-through text-muted" : ""}`} onDoubleClick={() => setRenaming(s.id)}>{s.title}</span>}
                      {s.items.length > 0 && <span className="text-[11.5px] text-faint tabular-nums">{s.items.filter((x) => x.done).length}/{s.items.length}</span>}
                      <span className="flex opacity-0 group-hover/st:opacity-100 focus-within:opacity-100">
                        <button className="btn btn-ghost p-0.5" aria-label="Add checklist item" title="Add checklist item" onClick={() => setAddingItem(s.id)}><ListChecks size={13} /></button>
                        <button className="btn btn-ghost p-0.5" aria-label="Move up" disabled={i === 0} onClick={() => ops([{ op: "move", id: s.id, index: i - 1 }])}><ArrowUp size={13} /></button>
                        <button className="btn btn-ghost p-0.5" aria-label="Move down" disabled={i === d.subtasks_list.length - 1} onClick={() => ops([{ op: "move", id: s.id, index: i + 1 }])}><ArrowDown size={13} /></button>
                        <button className="btn btn-ghost p-0.5 text-bad" aria-label={`Remove subtask ${s.title}`} onClick={() => ops([{ op: "remove", id: s.id }])}><X size={13} /></button>
                      </span>
                    </div>
                    {(s.items.length > 0 || addingItem === s.id) && (
                      <ul className="ml-6 border-l border-line pl-2 space-y-0.5">
                        {s.items.map((it) => (
                          <li key={it.id} className="group/it flex items-center gap-2 text-[12.5px]">
                            <input type="checkbox" checked={it.done} aria-label={`Checked: ${it.title}`} onChange={() => ops([{ op: "toggle_item", subtaskId: s.id, id: it.id, done: !it.done }])} />
                            <span className={`flex-1 min-w-0 ${it.done ? "line-through text-muted" : ""}`}>{it.title}</span>
                            <button className="btn btn-ghost p-0.5 opacity-0 group-hover/it:opacity-100 focus:opacity-100" aria-label={`Remove item ${it.title}`} onClick={() => ops([{ op: "remove_item", subtaskId: s.id, id: it.id }])}><X size={12} /></button>
                          </li>
                        ))}
                        {addingItem === s.id && (
                          <li><InlineInput keepOpen placeholder="Checklist item" onSubmit={(v) => ops([{ op: "add_item", subtaskId: s.id, title: v }])} onCancel={() => setAddingItem(null)} /></li>
                        )}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
              <input className="input py-1 text-[12.5px] mt-1" placeholder="Add a subtask" aria-label="Add a subtask" value={newSub} onChange={(e) => setNewSub(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && newSub.trim()) { ops([{ op: "add", title: newSub.trim() }]); setNewSub(""); } }} />
            </section>

            <section aria-label="Linked sessions">
              <h3 className="label font-medium mb-1">Sessions</h3>
              {d.linked_sessions.length === 0 && <div className="text-faint text-[12.5px]">No linked sessions.</div>}
              <div className="flex flex-wrap gap-1.5">
                {d.linked_sessions.map((s) => (
                  <span key={s.id} className="chip text-text">
                    <button className="hover:underline underline-offset-2 truncate max-w-[220px]" disabled={s.missing} title={s.missing ? "Deleted session" : "Open session"} onClick={() => actions.openSession(s.id)}>
                      {s.title}{s.in_trash ? " (in Trash)" : ""}
                    </button>
                    <button aria-label={`Unlink ${s.title}`} onClick={() => del(`/tasks/items/${d.code}/sessions/${s.id}`).then(setD).catch(toast)}><X size={11} /></button>
                  </span>
                ))}
                {current && !linkedHere && (
                  <button className="btn btn-ghost py-0 text-[12px]" onClick={() => act("sessions", { session_id: current.id })}><Plus size={12} /> Link “{current.title}”</button>
                )}
              </div>
            </section>

            <section aria-label="Comments">
              <h3 className="label font-medium mb-1">Comments</h3>
              <div className="space-y-2">
                {d.comments_list.map((c) => (
                  <div key={c.id} className="rounded-md border border-line px-2.5 py-1.5">
                    <div className="flex items-center gap-1.5 text-[11.5px] text-muted mb-0.5">
                      {c.by_agent ? <span className="inline-flex items-center gap-1 text-action font-medium"><Bot size={12} />Agent</span> : <span className="font-medium">{personLabel(c.author)}</span>}
                      <span className="text-faint">· {fmtAgo(c.created_at)}</span>
                      {c.session_id && <button className="ml-auto text-faint hover:text-text" onClick={() => actions.openSession(c.session_id!)}>session</button>}
                    </div>
                    <div className="prose-ws text-[13px]"><SafeMarkdown text={c.body} /></div>
                  </div>
                ))}
              </div>
              <textarea className="input mt-1.5 h-16 text-[13px]" placeholder="Write a comment (Markdown). ⌘Enter to post" aria-label="Write a comment" value={comment}
                onChange={(e) => setComment(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && comment.trim()) { act("comments", { body: comment }); setComment(""); } }} />
              <div className="flex justify-end mt-1">
                <button className="btn btn-primary" disabled={!comment.trim()} onClick={() => { act("comments", { body: comment }); setComment(""); }}>Comment</button>
              </div>
            </section>

            <section aria-label="History">
              <Collapsible title={<span className="label font-medium">History ({d.activity.length})</span>}>
                <ul className="space-y-0.5 text-[12px] text-muted">
                  {d.activity.map((a, i) => (
                    <li key={i}><span className="text-faint">{fmtAgo(a.ts)}</span> · {a.actor === "agent" ? <span className="text-action">Agent</span> : personLabel(a.actor)}: {a.text}</li>
                  ))}
                </ul>
              </Collapsible>
              <div className="text-[11.5px] text-faint mt-1">Created {fmtAgo(d.created_at)} by {personLabel(d.created_by)} · updated {fmtAgo(d.updated_at)}</div>
            </section>
          </div>
        )}
      </aside>
    </>
  );
}
