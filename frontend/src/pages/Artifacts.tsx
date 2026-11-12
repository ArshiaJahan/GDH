import { ChevronRight, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { get } from "../lib/api";
import { openExternal } from "../lib/native";
import { actions, useStore } from "../lib/store";
import { ItemRow, ItemViewer, type Item } from "../components/items";
import { Empty, providerModels, providerName, useModelCatalog } from "../components/ui";

const TABS = [["artifacts", "Artifacts"], ["media", "Media"], ["files", "Files"], ["links", "Links"]];
const PROVIDERS = [["all", "All"], ["claude", providerName.claude], ["codex", providerName.codex], ["elevenlabs", providerName.eleven]];
// Filter keys stay "claude"/"codex"; the buttons name the models behind them.
const PROVIDER_KEY: Record<string, string> = { claude: "anthropic", codex: "openai" };

type Group = { session_id: string | null; session_title: string; items: Item[]; count: number };

export function ArtifactsPage() {
  useModelCatalog();
  const args = useStore((s) => s.pageArgs);
  const tab = useStore((s) => s.artifactsTab);
  const sessions = useStore((s) => s.sessions);
  const [provider, setProvider] = useState("all");
  const [groups, setGroups] = useState<Group[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [viewing, setViewing] = useState<string | null>(args.item ?? null);
  const scope: string[] = args.sessions ?? [];

  const qs = () => {
    const p = new URLSearchParams({ tab });
    if (provider !== "all") p.set("provider", provider);
    if (scope.length) p.set("sessions", scope.join(","));
    return p.toString();
  };
  const load = async () => {
    const [g, c] = await Promise.all([
      get<Group[]>(`/items?${qs()}`),
      get(`/items/counts?${new URLSearchParams({ ...(provider !== "all" ? { provider } : {}), ...(scope.length ? { sessions: scope.join(",") } : {}) })}`),
    ]);
    setGroups(g);
    setCounts(c);
  };
  useEffect(() => { load(); }, [tab, provider, scope.join(",")]);
  useEffect(() => { if (args.item) setViewing(args.item); }, [args.item]);
  useEffect(() => actions.onEvent((e) => { if (e.type === "item.created" || e.type === "item.updated" || e.type === "item.deleted") load(); }), [tab, provider, scope.join(",")]);

  const scopeTitle = scope.map((id) => sessions.find((s) => s.id === id)?.title ?? id).join(", ");

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[1080px] mx-auto px-6 py-5">
        <div className="flex items-center gap-3 mb-4">
          <h1 className="text-lg font-semibold">Artifacts</h1>
          {scope.length > 0 && (
            <span className="chip text-[12.5px]">{scopeTitle}<button aria-label="Show all sessions" onClick={() => actions.go("artifacts", {})}><X size={12} /></button></span>
          )}
          <button className="btn ml-auto" onClick={() => useStore.setState({ searchOpen: true })}><Search size={14} /> Search <kbd className="text-faint text-[11px]">⌘K</kbd></button>
        </div>
        <div className="flex items-center gap-4 mb-3 flex-wrap">
          <div className="inline-flex rounded border border-line overflow-hidden text-[13px]" role="group" aria-label="Provider">
            {PROVIDERS.map(([v, l]) => (
              <button key={v} className={`px-3 py-1 ${provider === v ? "bg-sunken font-medium" : "hover:bg-sunken"}`} aria-pressed={provider === v} onClick={() => setProvider(v)}
                title={PROVIDER_KEY[v] ? providerModels(PROVIDER_KEY[v]).map((m) => m.name).join(", ") : undefined}>{l}</button>
            ))}
          </div>
          <div className="flex gap-1 text-[13px]" role="tablist">
            {TABS.map(([v, l]) => (
              <button key={v} role="tab" aria-selected={tab === v} onClick={() => useStore.setState({ artifactsTab: v })}
                className={`px-2.5 py-1 rounded ${tab === v ? "bg-sunken text-text font-medium" : "text-muted hover:text-text"}`}>
                {l} <span className="text-faint tabular-nums">{counts[v] ?? ""}</span>
              </button>
            ))}
          </div>
        </div>
        {groups.length === 0 && <Empty>{tab === "links" ? "No links cited, fetched or mentioned yet." : `No ${tab} yet. Things the agents make or you attach show up here.`}</Empty>}
        {groups.map((g) => {
          const key = g.session_id ?? "none";
          const closed = collapsed[key];
          return (
            <section key={key} className="mb-3">
              <button className="flex items-center gap-1.5 w-full text-left py-1.5 border-b border-line" aria-expanded={!closed}
                onClick={() => setCollapsed({ ...collapsed, [key]: !closed })}>
                <ChevronRight size={14} className={`text-muted ${closed ? "" : "rotate-90"}`} />
                <span className="font-medium">{g.session_title}</span>
                <span className="chip">{g.count}</span>
                {g.session_id && <span className="ml-auto text-[12px] text-muted hover:text-action" role="link" onClick={(e) => { e.stopPropagation(); actions.openSession(g.session_id!); }}>Open session</span>}
              </button>
              {!closed && <div className="py-1">{g.items.map((it) => <ItemRow key={it.id} it={it} onOpen={() => it.kind === "link" && !it.path ? openExternal(it.url!) : setViewing(it.id)} onDeleted={load} />)}</div>}
            </section>
          );
        })}
      </div>
      {viewing && <ItemViewer id={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}
