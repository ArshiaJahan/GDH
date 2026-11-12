import { useEffect, useState } from "react";
import { get } from "../../lib/api";
import { actions, type Session } from "../../lib/store";
import { Card } from "../SidePanel";
import { ItemIcon, ItemViewer, type Item } from "../items";

export function OutputsCard({ s }: { s: Session }) {
  const [items, setItems] = useState<Item[]>([]);
  const [viewing, setViewing] = useState<string | null>(null);
  const load = () => get<Item[]>(`/items?sessions=${s.id}&grouped=false`).then((r) => setItems(r.filter((i) => i.kind !== "link" && i.source !== "user")));
  useEffect(() => { load(); }, [s.id]);
  useEffect(() => actions.onEvent((e) => { if (((e.type === "item.created" || e.type === "item.updated") && e.session_id === s.id) || e.type === "item.deleted") load(); }), [s.id]);
  return (
    <Card id="outputs" title={`Outputs${items.length ? ` (${items.length})` : ""}`}
      right={<button className="text-[12px] text-action hover:underline" onClick={() => actions.go("artifacts", { sessions: [s.id] })}>Open in Artifacts page</button>}>
      {items.length === 0 && <div className="text-muted">Nothing produced yet.</div>}
      {items.slice(0, 12).map((it) => (
        <button key={it.id} className="w-full flex items-center gap-2 py-1 text-left hover:text-action" onClick={() => setViewing(it.id)} title={it.path ?? undefined}>
          <ItemIcon it={it} size={13} /><span className="truncate flex-1">{it.title}</span>
          {it.version > 1 && <span className="text-faint text-[11.5px]">v{it.version}</span>}
        </button>
      ))}
      {items.length > 12 && <div className="text-[12px] text-muted pt-1">+{items.length - 12} more on the Artifacts page</div>}
      {viewing && <ItemViewer id={viewing} onClose={() => setViewing(null)} />}
    </Card>
  );
}
