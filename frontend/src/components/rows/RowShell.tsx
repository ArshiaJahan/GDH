import { ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";

/** A compact, expandable one-line chat row for harness-written messages (skill loads, gate
 *  results, campaign briefs). `details` shows under the line when expanded. */
export function RowShell({ icon, children, details, tone = "muted", label }: {
  icon: ReactNode; children: ReactNode; details?: ReactNode; tone?: "muted" | "warn" | "bad"; label?: string;
}) {
  const [open, setOpen] = useState(false);
  const color = tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "text-muted";
  return (
    <div className="my-2 text-[12.5px]" role="note" aria-label={label}>
      {details ? (
        <button className={`flex items-center gap-1.5 ${color} hover:text-text`} onClick={() => setOpen(!open)} aria-expanded={open}>
          <ChevronRight size={13} className={open ? "rotate-90" : ""} />{icon}<span className="text-left">{children}</span>
        </button>
      ) : <div className={`flex items-center gap-1.5 ${color}`}>{icon}<span>{children}</span></div>}
      {open && details && <div className="mt-1 ml-4 pl-2 border-l-2 border-line text-muted">{details}</div>}
    </div>
  );
}

/** The text blocks of a message, joined. */
export const msgText = (content: { type: string; text?: string }[]) => content.filter((b) => b.type === "text").map((b) => b.text ?? "").join("\n");
