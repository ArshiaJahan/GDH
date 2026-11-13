// The Claude-style composer card's controls, shared by the new-session screen and the chat box of
// a Claude Code session: Chat only / the folder, the model, effort and permission mode, as plain
// text with a chevron (native <select>s underneath). In a session they PATCH it; the place is
// fixed once the session has started (Claude Code's conversation lives in that folder).
import { ChevronDown, Folder, MessageSquare } from "lucide-react";
import type { ReactNode } from "react";
import { patch } from "../lib/api";
import { revealInFinder } from "../lib/native";
import { actions, type Session } from "../lib/store";
import { modelLabel, providerModels, useModelCatalog } from "./ui";

export const EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"];
/** The permission modes a Claude Code session can have, in menu order (no bypass mode: see store.SESSION_MODES). */
export const NEW_SESSION_MODES: [string, string][] = [["plan", "Plan only"], ["ask", "Ask before edits"], ["accept_edits", "Accept edits"]];

/** "/Users/me/Games/Forklift" → "Forklift". */
export const folderName = (f: string) => f.replace(/\/+$/, "").split("/").pop() || f;
export const tilde = (f: string) => f.replace(/^\/Users\/[^/]+/, "~");

/** A borderless dropdown that reads as text with a chevron (a native <select> underneath). */
export function TextSelect({ label, value, onChange, children, className = "", title }: {
  label: string; value: string; onChange: (v: string) => void; children: ReactNode; className?: string; title?: string;
}) {
  return (
    <span className={`relative inline-flex items-center rounded-md hover:bg-sunken focus-within:bg-sunken ${className}`} title={title}>
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}
        className="appearance-none bg-transparent text-text text-[14px] leading-6 pl-2 pr-7 py-1 rounded-md cursor-pointer outline-none focus-visible:outline-2 focus-visible:outline-action max-w-full truncate">
        {children}
      </select>
      <ChevronDown size={15} className="absolute right-2 text-muted pointer-events-none" aria-hidden />
    </span>
  );
}

/** The model dropdown: Claude models by name (the tier is in the tooltip); an unknown current model stays listed. */
export function ModelSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  useModelCatalog();
  const models = providerModels("anthropic");
  return (
    <TextSelect label="Model" value={value} onChange={onChange} className="ml-auto min-w-0" title={modelLabel(value)}>
      {!models.some((m) => m.id === value) && <option value={value}>{modelLabel(value, null)}</option>}
      {models.map((m) => <option key={m.id} value={m.id}>{modelLabel(m.id, null)}</option>)}
    </TextSelect>
  );
}

export function EffortSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <TextSelect label="Effort" value={value} onChange={onChange}
      title={["xhigh", "max"].includes(value) ? "Effort above high asks for approval on each turn" : "How hard Claude thinks"}>
      {!EFFORTS.includes(value) && <option value={value}>{value} effort</option>}
      {EFFORTS.map((e) => <option key={e} value={e}>{e} effort</option>)}
    </TextSelect>
  );
}

export function ModeSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <TextSelect label="Permission mode" value={value} onChange={onChange}>
      {!NEW_SESSION_MODES.some(([v]) => v === value) && <option value={value}>{value}</option>}
      {NEW_SESSION_MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </TextSelect>
  );
}

/** The card's two control rows for a Claude Code session that has started. */
export function sessionCardRows(s: Session): [ReactNode, ReactNode] {
  const upd = async (body: { model?: string; effort?: string; mode?: string }) => {
    try { await patch(`/sessions/${s.id}`, body); } catch (e: any) { actions.toast(e.message, "error"); }
  };
  return [
    <>
      {s.folder ? (
        <button className="btn btn-ghost gap-1.5 px-2 text-[14px] min-w-0" title={`${tilde(s.folder)} (show in Finder)`}
          onClick={() => void revealInFinder(s.folder!)} data-testid="session-place">
          <Folder size={15} className="shrink-0" aria-hidden /><span className="truncate max-w-[220px]">{folderName(s.folder)}</span>
        </button>
      ) : (
        <span className="inline-flex items-center gap-1.5 px-2 text-[14px] text-text" title="No folder: Claude Code works in a private scratch folder" data-testid="session-place">
          <MessageSquare size={15} className="shrink-0 text-muted" aria-hidden />Chat only
        </span>
      )}
      <ModelSelect value={s.model} onChange={(v) => upd({ model: v })} />
    </>,
    <>
      <EffortSelect value={s.effort} onChange={(v) => upd({ effort: v })} />
      <ModeSelect value={s.mode} onChange={(v) => upd({ mode: v })} />
    </>,
  ];
}
