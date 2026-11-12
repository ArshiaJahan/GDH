// "Markdown-lite" for text people type: fenced code blocks, `inline code`, **bold** and
// *italic*, nothing else (no headings, lists or HTML), so a user's message keeps its own
// line breaks and spacing. Also strips markdown from short previews (sidebar search snippets).
import type { ReactNode } from "react";

const FENCE = /```[^\n`]*\n?([\s\S]*?)(?:```|$)/g;
const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|(?<![\w*])\*[^*\s][^*\n]*\*(?![\w*]))/g;

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(INLINE)) {
    const tok = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const k = `${key}-${i++}`;
    if (tok.startsWith("`")) out.push(<code key={k} className="font-mono text-[0.88em] px-1 py-px rounded bg-[var(--code-bg)]">{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("**") || tok.startsWith("__")) out.push(<strong key={k} className="font-semibold">{tok.slice(2, -2)}</strong>);
    else out.push(<em key={k}>{tok.slice(1, -1)}</em>);
    last = at + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Renders user-typed text with code blocks, inline code and emphasis; whitespace is kept. */
export function MdLite({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(FENCE)) {
    const at = m.index ?? 0;
    if (at > last) parts.push(<span key={`t${i}`}>{inline(text.slice(last, at).replace(/\n$/, ""), `t${i}`)}</span>);
    parts.push(<pre key={`c${i}`} className="my-1.5 font-mono text-[12.5px] leading-normal rounded p-2 overflow-x-auto bg-[var(--code-bg)] whitespace-pre">{m[1].replace(/\n$/, "")}</pre>);
    last = at + m[0].length;
    if (text[last] === "\n") last++;
    i++;
  }
  if (last < text.length) parts.push(<span key={`t${i}`}>{inline(text.slice(last), `t${i}`)}</span>);
  return <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{parts}</div>;
}

/** Plain text for one-line previews: drops code fences, backticks, emphasis, heading and list
 *  markers, link targets and images, and collapses whitespace. */
export function stripMarkdown(text: string): string {
  return text
    .replace(/```[^\n`]*\n?/g, " ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(^|[\s(])[*_]([^*_\s][^*_]*?)[*_](?=[\s).,;:!?]|$)/g, "$1$2")
    .replace(/^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+(\[[ xX]\]\s+)?|\d+\.\s+)/gm, "")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
