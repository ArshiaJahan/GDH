import { useRef, type KeyboardEvent } from "react";
import { actions, useStore, type SessionTab } from "../lib/store";
import { Chat } from "./Chat";
import { GalleryEntriesContext, GalleryTab, useGallery } from "./GalleryView";
import { PrefabsTab } from "./PrefabsTab";
import { tabsFor } from "../lib/prefabs";
import { isLive, SubagentsTab, useSessionSubagents } from "./SubagentsTab";

const LABEL: Record<SessionTab, string> = { chat: "Chat", subagents: "Subagents", gallery: "Gallery", prefabs: "Prefabs" };

function Badge({ n, label, running }: { n: number; label: string; running?: boolean }) {
  if (!n) return null;
  return (
    <span className={`rounded-full px-1.5 text-[11px] leading-[16px] tabular-nums ${running ? "bg-action text-action-text" : "bg-sunken text-muted"}`} aria-label={label}>{n}</span>
  );
}

function Strip({ sid, tab, tabs: TABS, running, items }: { sid: string; tab: SessionTab; tabs: SessionTab[]; running: number; items: number }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const onKey = (e: KeyboardEvent) => {
    const i = TABS.indexOf(tab);
    const next = e.key === "ArrowRight" ? TABS[(i + 1) % TABS.length] : e.key === "ArrowLeft" ? TABS[(i + TABS.length - 1) % TABS.length]
      : e.key === "Home" ? TABS[0] : e.key === "End" ? TABS[TABS.length - 1] : null;
    if (!next) return;
    e.preventDefault();
    actions.setSessionTab(sid, next);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label="Session views" onKeyDown={onKey} className="flex items-end gap-1 px-3 h-9 border-b border-line surface shrink-0" data-tauri-drag-region>
      {TABS.map((t) => (
        <button key={t} ref={(el) => { refs.current[t] = el; }} role="tab" id={`session-tab-${t}`} aria-selected={tab === t} aria-controls={`session-panel-${t}`}
          tabIndex={tab === t ? 0 : -1} onClick={() => actions.setSessionTab(sid, t)}
          className={`flex items-center gap-1.5 px-2.5 h-8 text-[13px] border-b-2 -mb-px ${tab === t ? "border-action font-medium" : "border-transparent text-muted hover:text-[var(--text)]"}`}>
          {LABEL[t]}
          {t === "subagents" && <Badge n={running} label={`${running} running`} running />}
          {t === "gallery" && <Badge n={items} label={`${items} items`} />}
        </button>
      ))}
    </div>
  );
}

/** The chat with tabs for the session's subagents and gallery. Chat stays mounted (hidden) so its scroll and draft survive. */
export function SessionView() {
  const sid = useStore((s) => s.currentId);
  const session = useStore((s) => s.sessions.find((x) => x.id === sid));
  if (!sid || !session) return <Chat />; // the new-session screen has no tabs
  return <Tabs key={sid} sid={sid} />;
}

function Tabs({ sid }: { sid: string }) {
  const session = useStore((s) => s.sessions.find((x) => x.id === sid))!;
  const tabs = tabsFor(session.settings?.unity_project);
  const stored = useStore((s) => s.sessionTabs[sid]) ?? "chat";
  const tab = tabs.includes(stored) ? stored : "chat";
  const subs = useSessionSubagents(sid);
  const gallery = useGallery(sid);
  const panel = (t: SessionTab, body: React.ReactNode) => (
    <div role="tabpanel" id={`session-panel-${t}`} aria-labelledby={`session-tab-${t}`} hidden={tab !== t} className="flex-1 min-h-0">{body}</div>
  );
  return (
    <div className="h-full flex flex-col min-w-0">
      <Strip sid={sid} tab={tab} tabs={tabs} running={subs.filter((x) => isLive(x.status)).length} items={gallery.entries.length} />
      {panel("chat", <GalleryEntriesContext.Provider value={gallery.entries}><Chat /></GalleryEntriesContext.Provider>)}
      {panel("subagents", tab === "subagents" && <SubagentsTab sessionId={sid} />)}
      {panel("gallery", tab === "gallery" && <GalleryTab s={session} entries={gallery.entries} setEntries={gallery.setEntries} />)}
      {tabs.includes("prefabs") && panel("prefabs", tab === "prefabs" && <PrefabsTab s={session} />)}
    </div>
  );
}
