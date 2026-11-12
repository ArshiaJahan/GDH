// Task board codes (Task00001, …) and the composer's /task command. Mirrors the backend
// (backend/workspace/features/task_board.py: parse_code, MENTION): a reference may be the code in
// any case, the bare number ("1", "00001") or "#1"; a code inside text is "Task" plus 5+ digits.

export const PRIORITIES = ["none", "low", "medium", "high", "urgent"] as const;
export type Priority = (typeof PRIORITIES)[number];

const CODE = /^\s*#?\s*(?:task\s*[-_ ]?\s*)?0*(\d{1,12})\s*$/i;

/** The number a task reference names, or null. */
export function parseCode(ref: string | number | null | undefined): number | null {
  if (typeof ref === "number") return Number.isInteger(ref) && ref > 0 ? ref : null;
  const m = CODE.exec(ref ?? "");
  const n = m ? Number(m[1]) : 0;
  return n > 0 ? n : null;
}

export function formatCode(n: number): string {
  return `Task${String(n).padStart(5, "0")}`;
}

/** "task1", "#1", "00001" → "Task00001"; null when it isn't a task reference. */
export function normalizeCode(ref: string | number | null | undefined): string | null {
  const n = parseCode(ref);
  return n == null ? null : formatCode(n);
}

/** Codes mentioned in text: Task + at least five digits, not inside a longer word. */
export const MENTION = /(?<![A-Za-z0-9_])task(\d{5,})(?![A-Za-z0-9_])/gi;

export type Piece = string | { code: string; raw: string };

/** Text split into plain runs and task codes (for chips). */
export function splitTaskCodes(text: string): Piece[] {
  const out: Piece[] = [];
  let last = 0;
  for (const m of text.matchAll(MENTION)) {
    const at = m.index ?? 0;
    if (Number(m[1]) === 0) continue;
    if (at > last) out.push(text.slice(last, at));
    out.push({ code: formatCode(Number(m[1])), raw: m[0] });
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out.length ? out : [text];
}

// ------------------------------------------------------------------------------- /task command

export type TaskCommand =
  | { kind: "board" }
  | { kind: "new"; title: string; labels: string[]; priority?: Priority; column?: string }
  | { kind: "open"; code: string }
  | { kind: "move"; code: string; column: string }
  | { kind: "done"; code: string }
  | { kind: "list"; query: string }
  | { kind: "link"; code: string }
  | { kind: "error"; message: string };

export const TASK_SUBCOMMANDS: [string, string][] = [
  ["new", "Create a task: /task new <title> #label !high @column"],
  ["move", "Move a task: /task move <code> <column>"],
  ["done", "Move a task to its board's done column"],
  ["list", "Find tasks on the Tasks page: /task list [words]"],
  ["link", "Link this session to a task"],
];

export const TASK_USAGE = "Use /task new <title>, /task <code>, /task move <code> <column>, /task done <code>, /task list [words] or /task link <code>.";

/** Parse a `/task …` line. `/task new Fix jump #player !high @todo` → title "Fix jump", labels
 *  ["player"], priority high, column "todo" (the backend matches column names loosely). */
export function parseTaskCommand(line: string): TaskCommand {
  const body = line.trim().replace(/^\/task\b/i, "").trim();
  if (!body) return { kind: "board" };
  const [first, ...rest] = body.split(/\s+/);
  const sub = first.toLowerCase();
  const needCode = (kind: "done" | "link"): TaskCommand => {
    const code = normalizeCode(rest[0]);
    return code ? { kind, code } : { kind: "error", message: `Usage: /task ${kind} <code>, e.g. /task ${kind} Task00001` };
  };
  switch (sub) {
    case "new": {
      const labels: string[] = [];
      let priority: Priority | undefined;
      let column: string | undefined;
      const words: string[] = [];
      for (const w of rest) {
        const p = w.slice(1).toLowerCase();
        if (w.length > 1 && w.startsWith("#")) labels.push(w.slice(1));
        else if (w.length > 1 && w.startsWith("!") && (PRIORITIES as readonly string[]).includes(p)) priority = p as Priority;
        else if (w.length > 1 && w.startsWith("@")) column = w.slice(1).replace(/[-_]/g, " ");
        else words.push(w);
      }
      const title = words.join(" ").trim();
      if (!title) return { kind: "error", message: "Usage: /task new <title> [#label] [!priority] [@column]" };
      return { kind: "new", title, labels, ...(priority ? { priority } : {}), ...(column ? { column } : {}) };
    }
    case "move": {
      const code = normalizeCode(rest[0]);
      const column = rest.slice(1).join(" ").trim();
      if (!code || !column) return { kind: "error", message: "Usage: /task move <code> <column>, e.g. /task move Task00001 In progress" };
      return { kind: "move", code, column };
    }
    case "done":
    case "link":
      return needCode(sub);
    case "list":
      return { kind: "list", query: rest.join(" ") };
  }
  const code = normalizeCode(first);
  if (code && rest.length === 0) return { kind: "open", code };
  return { kind: "error", message: `Unknown /task command. ${TASK_USAGE}` };
}

export type Suggestion = { value: string; label: string; hint: string };
export type TaskHit = { code: string; title: string; column?: string };

/** What the code (or column) being typed in a /task line is, for fetching suggestions:
 *  { field: "code", partial } or { field: "column", partial, code } or null. */
export type Completion = { field: "first"; partial: string } | { field: "code"; partial: string } | { field: "column"; partial: string; code: string };

export function taskCompletion(text: string): Completion | null {
  if (!/^\/task\s/i.test(text) || text.includes("\n")) return null;
  const parts = text.slice(5).replace(/^\s+/, "").split(" ");
  if (parts.length === 1) return { field: "first", partial: parts[0] };
  const sub = parts[0].toLowerCase();
  if (["move", "done", "link"].includes(sub) && parts.length === 2) return { field: "code", partial: parts[1] };
  if (sub === "move" && parts.length >= 3) return { field: "column", partial: parts.slice(2).join(" "), code: parts[1] };
  return null;
}

/** Autocomplete rows for a /task line: subcommands, task codes (from `hits`, already matched to
 *  what's typed by the backend) and column names. */
export function taskSuggestions(text: string, hits: TaskHit[], columns: string[]): Suggestion[] {
  const c = taskCompletion(text);
  if (!c) return [];
  const codeRows = (prefix: string, trail = "") => hits.map((h) => ({ value: `${prefix}${h.code}${trail}`, label: h.code, hint: h.title }));
  if (c.field === "first") {
    const p = c.partial.toLowerCase();
    const subs = TASK_SUBCOMMANDS.filter(([s]) => s.startsWith(p)).map(([s, hint]) => ({ value: `/task ${s} `, label: s, hint }));
    return [...subs, ...(["new", "list"].some((s) => s === p) ? [] : codeRows("/task "))].slice(0, 12);
  }
  const sub = text.slice(5).trim().split(/\s+/)[0].toLowerCase();
  if (c.field === "code") return codeRows(`/task ${sub} `, sub === "move" ? " " : "").slice(0, 12);
  const p = c.partial.trim().toLowerCase();
  const code = normalizeCode(c.code) ?? c.code;
  return [...new Set(columns)].filter((col) => !p || col.toLowerCase().includes(p))
    .map((col) => ({ value: `/task move ${code} ${col}`, label: col, hint: "column" })).slice(0, 12);
}

/** On Enter in a /task line: should the highlighted suggestion be taken (true) instead of running
 *  the line? Yes while a code or column is still half-typed. */
export function taskPick(text: string, columns: string[]): boolean {
  const c = taskCompletion(text);
  if (!c) return false;
  if (c.field === "first") {
    const p = c.partial.toLowerCase();
    return !!p && !normalizeCode(p) && !TASK_SUBCOMMANDS.some(([s]) => s === p);
  }
  if (c.field === "code") return !normalizeCode(c.partial);
  const p = c.partial.trim().toLowerCase();
  return !!p && !columns.some((col) => col.toLowerCase() === p);
}

/** Initials for an assignee chip: "me" → "Me", "agent" → "AI", "Ana Ruiz" → "AR". */
export function initials(name: string): string {
  if (name === "me") return "Me";
  if (name === "agent") return "AI";
  const w = name.trim().split(/\s+/).filter(Boolean);
  return ((w[0]?.[0] ?? "?") + (w.length > 1 ? w[w.length - 1][0] : w[0]?.[1] ?? "")).toUpperCase();
}

/** "me" → "You", "agent" → "Agent", others as they are. */
export function personLabel(name: string): string {
  return name === "me" ? "You" : name === "agent" ? "Agent" : name;
}
