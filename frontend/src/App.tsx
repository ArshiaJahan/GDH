import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";
import { connect, inTauri, openEvents } from "./lib/api";
import { actions, handleEvent, useStore } from "./lib/store";
import { Chat } from "./components/Chat";
import { newSession, Sidebar } from "./components/Sidebar";
import { SidePanel } from "./components/SidePanel";
import { TerminalDrawer } from "./components/TerminalDrawer";
import { Background } from "./components/Background";
import { SearchPanel } from "./components/SearchPanel";
import { Modal } from "./components/ui";
import { RestartingOverlay, UpdateModal } from "./components/Updates";
import { GlobalLimitBanner } from "./components/LimitsBanner";
import { ConfigErrorBanner, EngineStopped, isBackendExit, useBackendExit, type BackendExit } from "./components/SystemNotices";
import { sessionActions } from "./lib/sessions";
import { ErrorBoundary } from "./components/ErrorBoundary";

const SHORTCUTS: [string, string][] = [["⌘N", "New session (joins the current session's group)"], ["⌘K", "Search artifacts, media, files and links"], ["⌘,", "Settings"],
  ["⌘J", "Show or hide the terminal"], ["⌘/", "This list"], ["Enter", "Send message"], ["⇧Enter", "New line"],
  ["/", "Slash commands: /model /effort /mode /compact /clear /skill /task"],
  ["/task", "Task board: /task new <title> #label !high @column, /task Task00001, /task move <code> <column>, /task done <code>, /task list, /task link <code>"],
  ["⌘⇧[ / ⌘⇧]", "Previous / next session in the sidebar"], ["F2", "Rename the current session"],
  ["⌘⇧P", "Pin or unpin the current session"], ["⌘⌫", "Move the current session to Trash (Undo in the toast)"],
  ["⌘-click / ⇧-click", "Select several sessions for bulk actions; Esc clears"],
  ["↑ ↓ / Space / Enter", "On a focused session: move, open, rename"],
  ["Right-click a session", "All session actions (also the … button on hover)"]];

const editable = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <Modal title="Keyboard shortcuts" onClose={onClose}>
      <table className="w-full text-[13px]"><tbody>
        {SHORTCUTS.map(([k, v]) => <tr key={k} className="border-b border-line"><td className="py-1.5 pr-4 font-mono whitespace-nowrap">{k}</td><td>{v}</td></tr>)}
      </tbody></table>
    </Modal>
  );
}

const ArtifactsPage = lazy(() => import("./pages/Artifacts").then((m) => ({ default: m.ArtifactsPage })));
const ElevenLabsPage = lazy(() => import("./pages/ElevenLabs").then((m) => ({ default: m.ElevenLabsPage })));
const SkillsPage = lazy(() => import("./pages/Skills").then((m) => ({ default: m.SkillsPage })));
const BoardPage = lazy(() => import("./pages/Board").then((m) => ({ default: m.BoardPage })));
const SchedulePage = lazy(() => import("./pages/Schedule").then((m) => ({ default: m.SchedulePage })));
const CampaignsPage = lazy(() => import("./pages/Campaigns").then((m) => ({ default: m.CampaignsPage })));
const UsagePage = lazy(() => import("./pages/Usage").then((m) => ({ default: m.UsagePage })));
const SettingsPage = lazy(() => import("./pages/Settings").then((m) => ({ default: m.SettingsPage })));
function useTheme() {
  const theme = useStore((s) => s.theme);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && mq.matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [theme]);
}

function useShortcuts() {
  useEffect(() => {
    const run = (action: string) => {
      const s = useStore.getState();
      if (action === "new_session") newSession();
      else if (action === "search") useStore.setState({ searchOpen: true });
      else if (action === "settings") actions.go("settings");
      else if (action === "toggle_terminal") useStore.setState({ terminalOpen: !s.terminalOpen });
      else if (action === "help") useStore.setState({ helpOpen: true });
      else if (action === "prev_session") sessionActions.step(-1);
      else if (action === "next_session") sessionActions.step(1);
      else if (s.currentId && action === "rename_session") sessionActions.startRename(s.currentId);
      else if (s.currentId && action === "pin_session") sessionActions.togglePin(s.currentId);
      else if (s.currentId && action === "trash_session") sessionActions.trash([s.currentId]);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F2" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        return run("rename_session");
      }
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
      const session = e.shiftKey ? ({ BracketLeft: "prev_session", BracketRight: "next_session", KeyP: "pin_session" } as Record<string, string>)[e.code]
        : e.key === "Backspace" && !editable(e.target) && !e.repeat ? "trash_session" : undefined; // holding ⌘⌫ trashes one
      if (session) {
        e.preventDefault();
        return run(session);
      }
      const k = e.key.toLowerCase();
      const map: Record<string, string> = { n: "new_session", k: "search", ",": "settings", j: "toggle_terminal", "/": "help" };
      if (map[k]) {
        e.preventDefault();
        run(map[k]);
      }
    };
    window.addEventListener("keydown", onKey);
    let unlisten: (() => void) | undefined;
    if (inTauri()) {
      import("@tauri-apps/api/event").then(({ listen }) => listen<string>("menu", (e) => run(e.payload)).then((u) => (unlisten = u)));
    }
    return () => {
      window.removeEventListener("keydown", onKey);
      unlisten?.();
    };
  }, []);
}

export default function App() {
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [engineExit, setEngineExit] = useState<BackendExit | null>(null);
  useBackendExit(setEngineExit); // the backend died while the app runs
  const connected = useStore((s) => s.connected);
  const page = useStore((s) => s.page);
  const sidePanelOpen = useStore((s) => s.sidePanelOpen);
  const terminalOpen = useStore((s) => s.terminalOpen);
  const toast = useStore((s) => s.toast);
  const searchOpen = useStore((s) => s.searchOpen);
  const helpOpen = useStore((s) => s.helpOpen);
  const termRef = usePanelRef();
  const wasConnected = useRef(false); // "Connecting…" until the first replay is done, then "Reconnecting…"
  if (connected) wasConnected.current = true;
  useTheme();
  useShortcuts();

  useEffect(() => {
    let ev: { close: () => void } | undefined;
    (async () => {
      try {
        await connect();
        await actions.loadAll();
        ev = openEvents(handleEvent, (st) => useStore.setState({ connected: st === "open" }));
        setReady(true);
      } catch (e: any) {
        if (isBackendExit(e)) setEngineExit(e); // the desktop shell says why: exited (at once) or never answered
        else setError(e?.message ?? String(e));
      }
    })();
    return () => ev?.close();
  }, []);

  useEffect(() => {
    const p = termRef.current;
    if (!p) return;
    if (terminalOpen && p.isCollapsed()) p.expand();
    if (!terminalOpen && !p.isCollapsed()) p.collapse();
  }, [terminalOpen, ready]);

  if (engineExit) return <EngineStopped exit={engineExit} />;
  if (error) return <div className="h-full flex items-center justify-center p-8 text-center"><div><p className="font-medium mb-2">Can't reach the GameDevWorkstation backend</p><p className="text-muted">{error}</p></div></div>;
  if (!ready) return <div className="h-full flex items-center justify-center text-muted">Starting GameDevWorkstation…</div>;

  const main = page === "chat" ? <Chat /> : page === "artifacts" ? <ArtifactsPage /> : page === "elevenlabs" ? <ElevenLabsPage />
    : page === "board" ? <BoardPage /> : page === "schedule" ? <SchedulePage /> : page === "campaigns" ? <CampaignsPage /> : page === "skills" ? <SkillsPage /> : page === "usage" ? <UsagePage /> : <SettingsPage />;

  return (
    <>
      <Background />
      <div className="relative h-full">
        <Group orientation="horizontal" className="h-full">
          <Panel id="sidebar" defaultSize="248px" minSize="180px" maxSize="420px"><Sidebar /></Panel>
          <Separator className="rh" />
          <Panel id="center" minSize="360px">
            <Group orientation="vertical" className="h-full">
              <Panel id="main" minSize="160px"><main className="h-full min-h-0 flex flex-col"><ConfigErrorBanner /><GlobalLimitBanner /><div className="flex-1 min-h-0"><ErrorBoundary resetKey={page}><Suspense fallback={<div className="p-6 text-muted">Loading…</div>}>{main}</Suspense></ErrorBoundary></div></main></Panel>
              <Separator className="rh" />
              <Panel id="terminal" panelRef={termRef} defaultSize="0px" minSize="120px" collapsible collapsedSize="0px"
                onResize={(sz) => { const open = sz.inPixels > 2; if (open !== useStore.getState().terminalOpen) useStore.setState({ terminalOpen: open }); }}>
                <TerminalDrawer />
              </Panel>
            </Group>
          </Panel>
          {page === "chat" && sidePanelOpen && (
            <>
              <Separator className="rh" />
              <Panel id="side" defaultSize="300px" minSize="260px" maxSize="560px"><SidePanel /></Panel>
            </>
          )}
        </Group>
        {!connected && <div role="status" className="fixed bottom-3 left-1/2 -translate-x-1/2 chip bg-[var(--text)] text-[var(--bg)]" title="Live updates are paused; anything missed is replayed when the connection is back">{wasConnected.current ? "Reconnecting…" : "Connecting…"}</div>}
        {toast && (
          <div role="status" className={`fixed bottom-4 right-4 z-50 max-w-sm px-3 py-2 rounded-md shadow-lg text-[13px] border flex items-center gap-3 ${toast.kind === "error" ? "border-bad text-bad" : "border-line"} surface-raised`}>
            <span className="min-w-0">{toast.text}</span>
            {toast.action && (
              <button className="btn py-0.5 shrink-0" onClick={() => { toast.action!.run(); useStore.setState({ toast: null }); }}>{toast.action.label}</button>
            )}
          </div>
        )}
        {searchOpen && <SearchPanel onClose={() => useStore.setState({ searchOpen: false })} />}
        {helpOpen && <Shortcuts onClose={() => useStore.setState({ helpOpen: false })} />}
        <UpdateModal />
        <RestartingOverlay />
      </div>
    </>
  );
}
