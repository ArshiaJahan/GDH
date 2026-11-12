import { useEffect, useState } from "react";
import { get } from "../lib/api";
import { actions } from "../lib/store";
import { TaskChip } from "./TaskChip";

type Linked = { code: string; title: string; column: string; done: boolean };

/** The board tasks linked to a session, as chips in the chat header (live via task.* events). */
export function SessionTasks({ sessionId }: { sessionId: string }) {
  const [tasks, setTasks] = useState<Linked[]>([]);
  useEffect(() => {
    let gone = false;
    let t: ReturnType<typeof setTimeout> | undefined;
    const load = () => get<Linked[]>(`/tasks/by-session/${sessionId}`).then((r) => !gone && setTasks(r)).catch(() => {});
    load();
    const off = actions.onEvent((e) => {
      if (!e.type.startsWith("task.")) return;
      clearTimeout(t);
      t = setTimeout(load, 200);
    });
    return () => { gone = true; clearTimeout(t); off(); };
  }, [sessionId]);
  if (!tasks.length) return null;
  const shown = tasks.slice(0, 3);
  return (
    <span className="flex items-center gap-1 min-w-0 shrink" aria-label="Linked tasks">
      {shown.map((t) => (
        <span key={t.code} className={`shrink-0 ${t.done ? "opacity-70" : ""}`} title={`${t.code}: ${t.title} (${t.column})`}><TaskChip code={t.code} /></span>
      ))}
      {tasks.length > shown.length && <span className="text-[12px] text-faint" title={tasks.slice(3).map((t) => t.code).join(", ")}>+{tasks.length - shown.length}</span>}
    </span>
  );
}
