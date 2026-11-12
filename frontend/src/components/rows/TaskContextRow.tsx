import { SquareKanban } from "lucide-react";
import { useState } from "react";
import type { Msg } from "../../lib/store";
import { TaskChip } from "../TaskChip";
import { msgText } from "./RowShell";

/** `/task <code>` put a task into the conversation: a collapsed row with the task chip; the full
 *  text the model got shows on demand. */
export function TaskContextRow({ m }: { m: Msg }) {
  const [open, setOpen] = useState(false);
  const code: string = m.meta.task_context;
  return (
    <div className="my-2 text-[12.5px]" role="note" aria-label={`Task attached: ${code}`}>
      <span className="inline-flex items-center gap-1.5 text-muted">
        <SquareKanban size={13} className="text-action" />Task attached <TaskChip code={code} />
        <button className="text-faint hover:text-text" aria-expanded={open} onClick={() => setOpen(!open)}>· {open ? "hide" : "show"}</button>
      </span>
      {open && <pre className="mt-1 ml-4 pl-2 border-l-2 border-line text-muted font-mono text-[11.5px] whitespace-pre-wrap max-h-72 overflow-auto">{msgText(m.content)}</pre>}
    </div>
  );
}
