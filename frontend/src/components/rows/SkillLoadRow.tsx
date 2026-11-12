import { Sparkles } from "lucide-react";
import { useState } from "react";
import type { Msg } from "../../lib/store";
import { msgText } from "./RowShell";

/** Full skill protocols stay in history, behind a collapsed chip. */
export function SkillLoadRow({ m }: { m: Msg }) {
  const [open, setOpen] = useState(false);
  const name: string = m.meta.skill_load;
  return (
    <div className="my-2 text-[12.5px]" role="note" aria-label={`Skill loaded: ${name}`}>
      <button className="chip inline-flex items-center gap-1.5 hover:text-text" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Sparkles size={13} className="text-action" />
        <span>Skill loaded: {name} · {open ? "hide" : "show"}</span>
      </button>
      {open && <pre className="mt-1 ml-4 pl-2 border-l-2 border-line text-muted font-mono text-[11.5px] whitespace-pre-wrap max-h-72 overflow-auto">{msgText(m.content)}</pre>}
    </div>
  );
}
