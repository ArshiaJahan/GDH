import { SquareKanban } from "lucide-react";
import type { ReactNode } from "react";
import { actions } from "../lib/store";
import { splitTaskCodes } from "../lib/taskCodes";

/** A task code in text (chat, comments, descriptions): opens the task on the Tasks page. */
export function TaskChip({ code, label }: { code: string; label?: string }) {
  return (
    <button type="button" data-task-chip={code} title={`Open ${code}`} aria-label={`Open task ${code}`}
      className="inline-flex items-center gap-1 align-baseline rounded px-1 font-mono text-[0.86em] leading-[1.45] bg-sunken text-action hover:underline underline-offset-2"
      onClick={(e) => { e.stopPropagation(); actions.go("board", { task: code }); }}>
      <SquareKanban size={11} aria-hidden className="shrink-0 self-center" />{label ?? code}
    </button>
  );
}

/** Plain text with every task code turned into a chip. */
export function withTaskChips(text: string, key: string): ReactNode[] {
  return splitTaskCodes(text).map((p, i) => (typeof p === "string" ? p : <TaskChip key={`${key}-k${i}`} code={p.code} label={p.raw} />));
}

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };

/** remark plugin: task codes in Markdown text become `#task:<code>` links, which SafeMarkdown
 *  renders as chips. Code spans, code blocks and existing links are left alone. */
export function remarkTaskCodes() {
  const walk = (node: MdNode) => {
    if (!node.children || node.type === "link" || node.type === "linkReference") return;
    const out: MdNode[] = [];
    for (const child of node.children) {
      if (child.type === "text" && child.value) {
        for (const p of splitTaskCodes(child.value)) {
          out.push(typeof p === "string" ? { type: "text", value: p } : { type: "link", url: `#task:${p.code}`, children: [{ type: "text", value: p.raw }] });
        }
      } else {
        walk(child);
        out.push(child);
      }
    }
    node.children = out;
  };
  return (tree: MdNode) => walk(tree);
}
