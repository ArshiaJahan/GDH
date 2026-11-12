import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { get } from "../lib/api";
import { actions, useStore } from "../lib/store";
import { CustomRange, customBounds, defaultCustom } from "./DateRange";
import { ItemRow, jumpToMessage, type Item } from "./items";
import { modelLabel, providerModels, providerName, useModelCatalog } from "./ui";

type Group = { session_id: string | null; session_title: string; items: Item[] };
const CUSTOM = "Custom…";
const DATES: Record<string, number | null> = { "Any time": null, "Past day": 86400, "Past week": 7 * 86400, "Past month": 30 * 86400, [CUSTOM]: null };

/** Cmd+K: one query box over the item index, with scope and filters. */
/** The model filter is an exact ID match; a typed real name ("GPT-6.1 Sol") is turned into its ID. */
function modelFilter(text: string): string {
  const t = text.trim().toLowerCase();
  const hit = [...providerModels("anthropic"), ...providerModels("openai")]
    .find((m) => m.id.toLowerCase() === t || m.name.toLowerCase() === t || modelLabel(m.id).toLowerCase() === t);
  return hit?.id ?? text.trim();
}

export function SearchPanel({ onClose }: { onClose: () => void }) {
  useModelCatalog();
  const sessions = useStore((s) => s.sessions);
  const page = useStore((s) => s.page);
  const tab = useStore((s) => s.artifactsTab);
  const currentId = useStore((s) => s.currentId);
  const [q, setQ] = useState("");
  const [scope, setScope] = useState<"tab" | "all" | "selected">(page === "artifacts" ? "tab" : "all");
  const [picked, setPicked] = useState<string[]>(currentId ? [currentId] : []);
  const [f, setF] = useState({ kind: "", provider: "", model: "", source: "", date: "Any time" });
  const [custom, setCustom] = useState(defaultCustom);
  const [res, setRes] = useState<Group[]>([]);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const params = useMemo(() => {
    const p = new URLSearchParams({ q });
    if (scope === "tab") p.set("tab", tab);
    if (scope === "selected" && picked.length) p.set("sessions", picked.join(","));
    if (f.kind) p.set("kind", f.kind);
    if (f.provider) p.set("provider", f.provider);
    if (f.model) p.set("model", modelFilter(f.model));
    if (f.source) p.set("source", f.source);
    const d = DATES[f.date];
    if (f.date === CUSTOM) {
      const b = customBounds(custom);
      if (b.since != null) p.set("since", String(b.since));
      if (b.until != null) p.set("until", String(b.until));
    } else if (d) p.set("since", String(Date.now() / 1000 - d));
    return p.toString();
  }, [q, scope, picked, f, tab, custom]);

  const needsPick = scope === "selected" && picked.length === 0;
  useEffect(() => {
    if (!q.trim() || needsPick) { setRes([]); return; }
    const t = setTimeout(async () => {
      setBusy(true);
      try { setRes(await get(`/items/search?${params}`)); } finally { setBusy(false); }
    }, 160);
    return () => clearTimeout(t);
  }, [params]);

  const open = (it: Item) => {
    onClose();
    if (it.kind === "link" && it.message_id) jumpToMessage(it);
    else actions.go("artifacts", { item: it.id });
  };
  const sel = "input py-1 w-auto text-[12.5px]";
  const total = res.reduce((a, g) => a + g.items.length, 0);

  return (
    <div className="fixed inset-0 z-40 bg-black/30 dark:bg-black/50 flex items-start justify-center pt-[10vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-label="Search" className="surface-raised border border-line rounded-lg shadow-xl w-[92vw] max-w-3xl max-h-[78vh] flex flex-col">
        <div className="flex items-center gap-2 px-3 border-b border-line">
          <Search size={16} className="text-muted" />
          <input ref={input} className="flex-1 bg-transparent outline-none focus-visible:outline-none py-3 text-[15px]" placeholder="Search titles, file names, links, PDF text, transcripts…"
            value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && res[0]?.items[0] && open(res[0].items[0])} />
          {busy && <span className="text-[12px] text-faint">Searching…</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-line text-[12.5px]">
          <div className="inline-flex rounded border border-line overflow-hidden" role="group" aria-label="Scope">
            {([["tab", `This tab (${tab})`], ["all", "All chats"], ["selected", "Selected chats"]] as const).map(([v, l]) => (
              <button key={v} className={`px-2 py-0.5 ${scope === v ? "bg-sunken font-medium" : ""}`} aria-pressed={scope === v} onClick={() => setScope(v)}>{l}</button>
            ))}
          </div>
          {scope === "selected" && (
            <select multiple className="input w-56 h-20 py-0.5 text-[12.5px]" value={picked} aria-label="Chats to search"
              onChange={(e) => setPicked(Array.from(e.target.selectedOptions).map((o) => o.value))}>
              {sessions.filter((s) => !s.deleted).map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
            </select>
          )}
          <select className={sel} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })} aria-label="Kind">
            <option value="">Any kind</option><option value="artifact">Artifacts</option><option value="media">Media</option><option value="file">Files</option><option value="link">Links</option>
          </select>
          <select className={sel} value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })} aria-label="Provider">
            <option value="">Any provider</option><option value="claude">{providerName.claude}</option><option value="codex" title={providerModels("openai").map((m) => m.name).join(", ")}>{providerName.codex}</option><option value="elevenlabs">{providerName.eleven}</option>
          </select>
          <input className={`${sel} w-36`} placeholder="Model" list="search-models" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} aria-label="Model" />
          <datalist id="search-models">
            {[...providerModels("anthropic"), ...providerModels("openai")].map((m) => <option key={m.id} value={m.id}>{modelLabel(m.id)}</option>)}
          </datalist>
          <select className={sel} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} aria-label="Source">
            <option value="">Any source</option><option value="user">Attached by me</option><option value="agent">Made by agents</option><option value="tool">Generated by tools</option>
          </select>
          <select className={sel} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} aria-label="Date range">
            {Object.keys(DATES).map((d) => <option key={d}>{d}</option>)}
          </select>
          {f.date === CUSTOM && <CustomRange value={custom} onChange={setCustom} className={sel} />}
        </div>
        <div className="overflow-y-auto scroll-thin p-2">
          {needsPick && <div className="px-2 py-6 text-center text-muted">Pick one or more chats to search.</div>}
          {q.trim() && !busy && !needsPick && total === 0 && <div className="px-2 py-6 text-center text-muted">No matches. Try fewer words or widen the scope.</div>}
          {!q.trim() && <div className="px-2 py-6 text-center text-muted text-[13px]">Search everything your agents made and you attached.</div>}
          {res.map((g) => (
            <div key={g.session_id ?? "none"} className="mb-2">
              <div className="px-2 py-1 label">{g.session_title} · {g.items.length}</div>
              {g.items.map((it) => <ItemRow key={it.id} it={it} onOpen={() => open(it)} />)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
