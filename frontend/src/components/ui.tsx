import { Check, ChevronRight } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { useStore } from "../lib/store";

/** Which provider a model ID belongs to; "user" when there's no model (something the user attached or wrote). */
export function providerOf(model?: string | null): "claude" | "codex" | "eleven" | "user" {
  if (!model) return "user";
  if (model.startsWith("claude")) return "claude";
  if (model.startsWith("eleven") || model.startsWith("scribe") || model.startsWith("music")) return "eleven";
  return "codex";
}

export const providerName = { claude: "Claude", codex: "OpenAI", eleven: "ElevenLabs" } as const;

const cap = (w: string) => w.charAt(0).toUpperCase() + w.slice(1);

/** Name derived from a model ID ("claude-opus-5-5" → "Opus 5.5", "gpt-6.1-sol" → "GPT-6.1 Sol").
 *  Mirrors config.derive_display_name; prefer modelName/modelLabel, which use the config's display_name. */
export function shortModel(model?: string | null): string {
  if (!model) return "";
  const c = model.match(/^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$/);
  if (c) return `${cap(c[1])} ${c[2]}${c[3] ? "." + c[3] : ""}`;
  const g = model.match(/^gpt-(\d+(?:\.\d+)?)(?:-([a-z0-9-]+))?$/);
  if (g) return `GPT-${g[1]}${g[2] ? " " + g[2].split("-").map(cap).join(" ") : ""}`;
  return elevenName(model) ?? model;
}

const ELEVEN_NAMES: Record<string, string> = { eleven_text_to_sound_v3: "Sound Effects v3", eleven_multilingual_sts_v2: "Voice Changer v2" };

/** ElevenLabs model IDs read as names: "eleven_flash_v2_5" → "Eleven Flash v2.5", "scribe_v2" → "Scribe v2". */
function elevenName(id: string): string | null {
  if (ELEVEN_NAMES[id]) return ELEVEN_NAMES[id];
  if (!/^(eleven|scribe|music)_[a-z0-9_]+$/.test(id)) return null;
  return id.replace(/_v(\d+)(?:_(\d+))?(?=_|$)/g, (_, a, b) => ` v${a}${b ? "." + b : ""}`)
    .split(/[_ ]/).filter(Boolean).map((w) => (/^v\d/.test(w) ? w : cap(w))).join(" ");
}

// The model catalog and tiers come from /api/state (config [models.*] and [tiers]); tier keys stay as they are.
const catalog = () => useStore.getState().appState as { tiers?: Record<string, string>; models?: Record<string, { display_name?: string; provider?: string }> } | null;

/** The model a tier key routes to, or undefined when `x` isn't a tier key. */
function tierModel(x: string): string | undefined {
  const t = catalog()?.tiers;
  return t && Object.prototype.hasOwnProperty.call(t, x) ? t[x] : undefined;
}

/** Is this a tier key such as "codex.standard" (rather than a model ID)? */
export function isTier(x?: string | null): boolean {
  return !!x && tierModel(x) !== undefined;
}

/** Tier keys that route to a model, in config order (gpt-6.1-sol → ["codex.standard", "codex.cli"]). */
export function tiersOf(model?: string | null): string[] {
  return Object.entries(catalog()?.tiers ?? {}).filter(([, m]) => m === model).map(([t]) => t);
}

/** A model's real name ("GPT-6.1 Sol"). Accepts a tier key too and names the model it routes to. */
export function modelName(modelOrTier?: string | null): string {
  if (!modelOrTier) return "";
  const id = tierModel(modelOrTier) ?? modelOrTier;
  return catalog()?.models?.[id]?.display_name || shortModel(id);
}

/** Real name plus tier: "GPT-6.1 Sol · codex.standard", "Opus 5.5 · claude.deep".
 *  Takes a model ID or a tier key. `tier` overrides the looked-up tier (the first one routing to the model);
 *  pass null for the name alone. */
export function modelLabel(modelOrTier?: string | null, tier?: string | null): string {
  if (!modelOrTier) return "";
  const t = tier !== undefined ? tier : isTier(modelOrTier) ? modelOrTier : tiersOf(modelOrTier)[0] ?? null;
  const name = modelName(modelOrTier);
  return t && t !== name ? `${name} · ${t}` : name;
}

/** Re-render the calling component when the model catalog or tiers change (the label helpers read the store directly). */
export function useModelCatalog(): void {
  useStore((s) => s.appState?.tiers);
  useStore((s) => s.appState?.models);
}

/** Display names of a provider's configured models ("anthropic" | "openai"), in catalog order. */
export function providerModels(provider: string): { id: string; name: string; tiers: string[] }[] {
  return Object.entries(catalog()?.models ?? {}).filter(([, m]) => m.provider === provider)
    .map(([id]) => ({ id, name: modelName(id), tiers: tiersOf(id) }));
}

/** Provider IDs as the backend names them ("anthropic", "openai", "elevenlabs") → the UI's keys. */
export function providerKey(provider?: string | null, model?: string | null): ReturnType<typeof providerOf> {
  return provider === "anthropic" || provider === "claude" ? "claude" : provider === "openai" || provider === "codex" ? "codex"
    : provider === "elevenlabs" || provider === "eleven" ? "eleven" : providerOf(model);
}

/** Display order of providers everywhere: Claude, OpenAI, ElevenLabs. */
export const PROVIDER_ORDER = ["claude", "codex", "eleven"] as const;

/** "anthropic" → "Claude", "openai" → "OpenAI", "elevenlabs" → "ElevenLabs" (unknown IDs as they are). */
export function providerLabel(provider?: string | null): string {
  const k = providerKey(provider);
  return k === "user" ? provider ?? "" : providerName[k];
}

/** Sort key for PROVIDER_ORDER; unknown providers go last. */
export function providerRank(provider?: string | null): number {
  const i = (PROVIDER_ORDER as readonly string[]).indexOf(providerKey(provider));
  return i < 0 ? PROVIDER_ORDER.length : i;
}

export function ProviderDot({ model, provider }: { model?: string | null; provider?: string | null }) {
  const p = providerKey(provider, model);
  // No provider and no model: something the user attached or wrote — a neutral ring, not a provider colour.
  if (p === "user") return <span className="inline-block size-2 rounded-full shrink-0 border border-faint" title="Not from a model" />;
  return <span className="inline-block size-2 rounded-full shrink-0" style={{ background: `var(--${p})` }} title={providerName[p]} />;
}

export const LEVELS = ["none", "low", "medium", "high", "xhigh", "max"];

/** Effort as a small six-step meter; steps above "high" are drawn in the warning color. */
export function EffortMeter({ effort, title }: { effort?: string; title?: string }) {
  const idx = LEVELS.indexOf(effort ?? "");
  return (
    <span className="inline-flex items-end gap-[2px] h-3" title={title ?? `Effort: ${effort}`} aria-label={`Effort ${effort}`}>
      {LEVELS.slice(1).map((l, i) => (
        <span key={l} className="w-[3px] rounded-[1px]" style={{
          height: `${4 + i * 2}px`,
          background: i + 1 <= idx ? (i >= 3 ? "var(--warn)" : "var(--text)") : "color-mix(in srgb, var(--faint) 50%, transparent)",
        }} />
      ))}
    </span>
  );
}

export function Collapsible({ title, right, children, defaultOpen = false, className = "" }: {
  title: ReactNode; right?: ReactNode; children: ReactNode; defaultOpen?: boolean; className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={className}>
      <div className="flex items-center gap-1">
        <button className="flex items-center gap-1 min-w-0 flex-1 text-left py-1 hover:text-text text-muted" onClick={() => setOpen(!open)} aria-expanded={open}>
          <ChevronRight size={14} className={`shrink-0 transition-transform ${open ? "rotate-90" : ""}`} />
          <span className="truncate">{title}</span>
        </button>
        {right}
      </div>
      {open && <div className="pl-5">{children}</div>}
    </div>
  );
}

export type MenuAction = {
  label: string; onClick: () => void; danger?: boolean; hint?: string; icon?: ReactNode;
  /** Keyboard shortcut shown on the right, e.g. "F2". */
  kbd?: string; disabled?: boolean;
  /** Shows a check mark slot (checked or empty) for radio-like choices. */
  checked?: boolean;
};
/** An item that opens a nested menu (hover, click or →). */
export type MenuSub = { label: string; submenu: MenuItem[]; icon?: ReactNode; disabled?: boolean };
export type MenuItem = MenuAction | MenuSub | { heading: string } | "sep";

const isSub = (it: MenuItem): it is MenuSub => typeof it === "object" && "submenu" in it;

/** Context menu at (x, y). With `above`, it grows upward from y (for buttons near the bottom, like the composer's).
 *  Arrow keys move between items, → / ← open and close submenus, Esc closes. */
export function Menu({ x, y, onClose, items, above, width, sub, onBack, flipX, autoFocus = true }: {
  x: number; y: number; onClose: () => void; items: MenuItem[]; above?: boolean; width?: number;
  /** Internal: this is a submenu (`onBack` closes just it; `flipX` is where it goes if there's no room on the right). */
  sub?: boolean; onBack?: () => void; flipX?: number;
  /** Focus the first item on open (submenus opened by hover don't, so focus stays in the parent). */
  autoFocus?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<{ i: number; x: number; y: number; flipX: number; focus: boolean } | null>(null);
  const w = width ?? 200;
  const [pos, setPos] = useState<CSSProperties>(() => above
    ? { left: Math.max(8, Math.min(x, window.innerWidth - w - 8)), bottom: window.innerHeight - y, maxHeight: Math.max(y - 16, 160), width }
    : { left: x, top: y, maxHeight: window.innerHeight - 16, visibility: "hidden" });
  useEffect(() => {
    if (sub) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && !e.defaultPrevented && onClose();
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [onClose, sub]);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!above) {
      const r = el.getBoundingClientRect();
      let left = x;
      if (left + r.width > window.innerWidth - 8) left = sub && flipX !== undefined ? Math.max(8, flipX - r.width) : Math.max(8, window.innerWidth - r.width - 8);
      const top = y + r.height > window.innerHeight - 8 ? Math.max(8, window.innerHeight - r.height - 8) : y;
      Object.assign(el.style, { left: `${left}px`, top: `${top}px`, visibility: "visible" }); // now, so focus() below works
      setPos({ left, top, maxHeight: window.innerHeight - 16 });
    }
    if (autoFocus) (el.querySelector(":scope > [role=menuitem]:not([disabled])") as HTMLElement | null)?.focus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const openSub = (i: number, el: HTMLElement, focus = false) => {
    const r = el.getBoundingClientRect();
    if (focus && open?.i === i) { // already open (by hover): just move focus into it
      (ref.current?.querySelector("[data-submenu] [role=menuitem]") as HTMLElement | null)?.focus();
      return;
    }
    setOpen({ i, x: r.right - 2, y: r.top - 5, flipX: r.left + 2, focus });
  };
  const onKey = (e: ReactKeyboardEvent) => {
    const own = [...(ref.current?.querySelectorAll<HTMLElement>(":scope > [role=menuitem]:not([disabled])") ?? [])];
    const at = own.indexOf(document.activeElement as HTMLElement);
    const go = (i: number) => own[(i + own.length) % own.length]?.focus();
    if (e.key === "ArrowDown") go(at + 1);
    else if (e.key === "ArrowUp") go(at < 0 ? -1 : at - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(-1);
    else if (e.key === "ArrowRight" && at >= 0 && own[at].dataset.sub) openSub(Number(own[at].dataset.sub), own[at], true);
    else if ((e.key === "ArrowLeft" || e.key === "Escape") && sub) onBack?.();
    else return;
    e.preventDefault();
    e.stopPropagation();
  };
  return (
    <div ref={ref} role="menu" data-submenu={sub ? "" : undefined} onKeyDown={onKey}
      className="fixed z-50 min-w-44 py-1 rounded-md border border-line bg-raised shadow-lg text-[13px] overflow-y-auto scroll-thin"
      style={pos}>
      {items.map((it, i) =>
        it === "sep" ? <div key={i} className="my-1 border-t border-line" />
        : "heading" in it ? <div key={i} className="label px-3 pt-1.5 pb-0.5">{it.heading}</div>
        : isSub(it) ? (
          <button key={i} role="menuitem" aria-haspopup="menu" aria-expanded={open?.i === i} data-sub={i} disabled={it.disabled}
            className={`flex w-full items-center gap-2 text-left px-3 py-1.5 hover:bg-sunken focus:bg-sunken focus:outline-none disabled:opacity-50 ${open?.i === i ? "bg-sunken" : ""}`}
            onMouseEnter={(e) => open?.i !== i && openSub(i, e.currentTarget)} onClick={(e) => openSub(i, e.currentTarget, true)}>
            {it.icon && <span className="shrink-0 text-muted">{it.icon}</span>}
            <span className="flex-1 min-w-0 truncate">{it.label}</span>
            <ChevronRight size={13} className="text-muted shrink-0" />
          </button>
        ) : (
          <button key={i} role="menuitem" disabled={it.disabled}
            className={`flex w-full gap-2 text-left px-3 py-1.5 hover:bg-sunken focus:bg-sunken focus:outline-none disabled:opacity-50 ${it.danger ? "text-bad" : ""}`}
            onMouseEnter={(e) => {
              if (!open) return;
              if (ref.current?.querySelector("[data-submenu]")?.contains(document.activeElement)) e.currentTarget.focus(); // keep focus in this menu
              setOpen(null);
            }}
            onClick={() => { onClose(); it.onClick(); }}>
            {it.checked !== undefined && <span className="shrink-0 w-3.5 mt-0.5 text-action">{it.checked && <Check size={14} />}</span>}
            {it.icon && <span className="shrink-0 mt-0.5 text-muted">{it.icon}</span>}
            <span className="min-w-0 flex-1">
              <span className="block">{it.label}</span>
              {it.hint && <span className="text-[12px] text-muted line-clamp-2">{it.hint}</span>}
            </span>
            {it.kbd && <span className="shrink-0 pl-3 text-[12px] text-faint font-mono">{it.kbd}</span>}
          </button>
        ))}
      {open && isSub(items[open.i]) && (
        <Menu key={open.i} sub autoFocus={open.focus} x={open.x} y={open.y} flipX={open.flipX} items={(items[open.i] as MenuSub).submenu} onClose={onClose}
          onBack={() => {
            const i = open.i;
            setOpen(null);
            (ref.current?.querySelector(`:scope > [data-sub="${i}"]`) as HTMLElement | null)?.focus();
          }} />
      )}
    </div>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

/** Tab-focusable elements inside `root`, in order (hidden ones left out). */
export function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => {
    if (el.closest("[hidden], [inert]")) return false;
    const cs = getComputedStyle(el);
    return cs.display !== "none" && cs.visibility !== "hidden";
  });
}

/** Dialog: focus moves into it (its first text field, else the dialog itself, so a screen reader
 *  reads its title) and Tab stays inside; Esc or Close closes it and focus returns to where it was. */
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const el = ref.current;
    if (el && !el.contains(document.activeElement)) {
      const field = focusables(el).find((x) => x.matches("input, select, textarea, [contenteditable='true']"));
      (field ?? el).focus();
    }
    return () => {
      if (opener && opener.isConnected) opener.focus();
    };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = ref.current;
      const dialogs = document.querySelectorAll("[data-modal]");
      if (!el || dialogs[dialogs.length - 1] !== el) return; // only the topmost dialog handles keys
      if (e.key === "Escape") {
        if (!e.defaultPrevented) close.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusables(el);
      const active = document.activeElement;
      if (!items.length) {
        e.preventDefault();
        el.focus();
        return;
      }
      const first = items[0], last = items[items.length - 1];
      if (!el.contains(active)) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && (active === first || active === el)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="fixed inset-0 z-40 bg-black/30 dark:bg-black/50 flex items-start justify-center pt-[8vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} data-modal="" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className={`surface-raised border border-line rounded-lg shadow-xl w-[92vw] ${wide ? "max-w-5xl" : "max-w-xl"} max-h-[84vh] flex flex-col outline-none`}>
        <div className="px-4 py-2.5 border-b border-line font-medium flex items-center"><h2 id={titleId} className="min-w-0 truncate">{title}</h2>
          <button className="ml-auto btn btn-ghost" onClick={onClose}>Close</button></div>
        <div className="overflow-auto scroll-thin p-4">{children}</div>
      </div>
    </div>
  );
}

/** The one footer layout for modals: right-aligned buttons, the primary action last.
 *  `start` holds an optional left-aligned note or secondary control. */
export function ModalFooter({ children, start, className = "" }: { children: ReactNode; start?: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-wrap items-center justify-end gap-2 mt-4 ${className}`}>
      {start != null && <div className="mr-auto min-w-0 text-[12.5px] text-muted">{start}</div>}
      {children}
    </div>
  );
}

export function fmtUsd(n?: number | null): string {
  if (n == null) return "—";
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export function fmtTokens(n?: number | null): string {
  if (!n) return "0";
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
}

export function fmtAgo(ts?: number | null): string {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export function fmtDuration(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-muted text-[13px] py-2">{children}</div>;
}
