import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { Bot, Plus, SquareTerminal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { get, sendWs } from "../lib/api";
import { actions, useStore } from "../lib/store";

type Tab = { id: string; title: string; agent: boolean; exited?: boolean };

// Terminals live outside React so switching tabs or pages keeps their buffers.
const terms = new Map<string, { term: Terminal; fit: FitAddon; el: HTMLDivElement }>();

function cssVar(n: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(n).trim();
}

function themeColors() {
  return { background: cssVar("--sunken"), foreground: cssVar("--text"), cursor: cssVar("--action"),
           selectionBackground: cssVar("--line"), black: "#1a1f26", brightBlack: "#6c7682" };
}

function ensureTerm(tab: Tab): { term: Terminal; fit: FitAddon; el: HTMLDivElement } {
  let t = terms.get(tab.id);
  if (t) return t;
  const term = new Terminal({
    fontFamily: '"IBM Plex Mono", Menlo, monospace', fontSize: 12.5, lineHeight: 1.25, cursorBlink: !tab.agent,
    disableStdin: tab.agent, convertEol: tab.agent, scrollback: 10000, theme: themeColors(), allowProposedApi: true,
  });
  const fit = new FitAddon();
  term.loadAddon(fit);
  const el = document.createElement("div");
  el.style.cssText = "position:absolute;inset:6px 8px;";
  term.open(el);
  if (!tab.agent) {
    term.onData((data) => sendWs({ op: "term.input", tab: tab.id, data }));
    term.onResize(({ cols, rows }) => sendWs({ op: "term.resize", tab: tab.id, cols, rows }));
  }
  t = { term, fit, el };
  terms.set(tab.id, t);
  return t;
}

let shellCount = 0;

/** True while the user is typing somewhere other than the terminal (composer, inputs). */
function typingElsewhere(host: HTMLElement | null): boolean {
  const el = document.activeElement as HTMLElement | null;
  if (!el || el === document.body || host?.contains(el)) return false;
  return el.isContentEditable || ["TEXTAREA", "INPUT", "SELECT"].includes(el.tagName);
}

export function TerminalDrawer() {
  const open = useStore((s) => s.terminalOpen);
  const session = useStore((s) => s.sessions.find((x) => x.id === s.currentId));
  const theme = useStore((s) => s.theme);
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const host = useRef<HTMLDivElement>(null);

  const newShell = () => {
    const id = `shell-${Date.now().toString(36)}`;
    const tab = { id, title: `zsh ${++shellCount}`, agent: false };
    setTabs((t) => [...t, tab]);
    setActive(id);
    const { term, fit } = ensureTerm(tab);
    requestAnimationFrame(() => {
      try { fit.fit(); } catch {}
      sendWs({ op: "term.open", tab: id, cwd: session?.folder ?? undefined, cols: term.cols, rows: term.rows });
    });
  };

  const closeTab = (id: string) => {
    const t = tabs.find((x) => x.id === id);
    if (t && !t.agent) sendWs({ op: "term.close", tab: id });
    terms.get(id)?.term.dispose();
    terms.delete(id);
    const rest = tabs.filter((x) => x.id !== id);
    setTabs(rest);
    if (active === id) setActive(rest.at(-1)?.id ?? null);
  };

  // Output and agent command tabs.
  useEffect(() => actions.onEvent((ev) => {
    const d = ev.data;
    if (ev.type === "terminal.output") {
      const t = terms.get(d.tab);
      if (t) t.term.write(d.data);
    } else if (ev.type === "terminal.agent_command") {
      const tab: Tab = { id: `agent:${d.job_id}`, title: d.command.slice(0, 28), agent: true };
      ensureTerm(tab).term.write(`\x1b[2m${d.cwd} $\x1b[0m ${d.command}\r\n`);
      setTabs((x) => (x.some((y) => y.id === tab.id) ? x : [...x, tab]));
      // Other sessions' commands get a tab but never take over the view; the open session's
      // only does when the user isn't typing in a shell tab (switching would drop its focus).
      const mine = !ev.session_id || ev.session_id === useStore.getState().currentId;
      if (mine && !host.current?.contains(document.activeElement)) setActive(tab.id);
    } else if (ev.type === "terminal.agent_exit") {
      const t = terms.get(`agent:${d.job_id}`);
      t?.term.write(`\r\n\x1b[2m[exit ${d.exit_code}]\x1b[0m\r\n`);
      setTabs((x) => x.map((y) => (y.id === `agent:${d.job_id}` ? { ...y, exited: true } : y)));
    } else if (ev.type === "terminal.exit") {
      setTabs((x) => x.map((y) => (y.id === d.tab ? { ...y, exited: true } : y)));
      terms.get(d.tab)?.term.write("\r\n\x1b[2m[process exited]\x1b[0m\r\n");
    }
  }), []);

  // Reattach shells that survived a reload.
  useEffect(() => {
    get<{ tab: string; scrollback: string }[]>("/terminal/tabs").then((list) => {
      if (!list.length) return;
      const restored = list.map((x, i) => ({ id: x.tab, title: `zsh ${++shellCount}`, agent: false }));
      restored.forEach((t, i) => ensureTerm(t).term.write(list[i].scrollback));
      setTabs((cur) => [...restored.filter((r) => !cur.some((c) => c.id === r.id)), ...cur]);
      setActive((a) => a ?? restored[0].id);
    }).catch(() => {});
  }, []);

  // First open: start a shell.
  useEffect(() => { if (open && tabs.length === 0) newShell(); }, [open]);

  // Mount the active terminal and keep it fitted. Focus moves to a shell only when the user
  // switched tabs or opened the drawer, never because a tab was added in the background, and
  // never away from the composer or another field while typing.
  const focused = useRef<{ active: string | null; open: boolean }>({ active: null, open: false });
  useEffect(() => {
    const h = host.current;
    if (!h || !active) return;
    const tab = tabs.find((t) => t.id === active);
    if (!tab) return;
    const t = ensureTerm(tab);
    if (h.firstChild !== t.el) h.replaceChildren(t.el);
    const refit = () => { if (h.clientHeight > 20) { try { t.fit.fit(); } catch {} } };
    refit();
    const ro = new ResizeObserver(refit);
    ro.observe(h);
    const opened = open && !focused.current.open; // ⌘J or dragging the drawer open: the user asked for it
    const switched = focused.current.active !== active;
    focused.current = { active, open };
    if (open && !tab.agent && (opened || (switched && !typingElsewhere(h)))) t.term.focus();
    return () => ro.disconnect();
  }, [active, tabs.length, open]);

  useEffect(() => { terms.forEach((t) => (t.term.options.theme = themeColors())); }, [theme]);

  return (
    <div className="h-full flex flex-col surface border-t border-line" aria-label="Terminal">
      <div className="flex items-center gap-0.5 px-1.5 h-8 border-b border-line overflow-x-auto scroll-thin shrink-0" role="tablist">
        {tabs.map((t) => (
          <div key={t.id} role="tab" aria-selected={t.id === active}
            className={`group flex items-center gap-1 pl-2 pr-1 h-6 rounded text-[12px] cursor-pointer shrink-0 ${t.id === active ? "bg-sunken text-text" : "text-muted hover:text-text"}`}
            onClick={() => setActive(t.id)} title={t.agent ? `Agent command: ${t.title}` : t.title}>
            {t.agent ? <Bot size={12} /> : <SquareTerminal size={12} />}
            <span className={`max-w-[180px] truncate ${t.exited ? "opacity-60" : ""}`}>{t.title}</span>
            <button className="opacity-0 group-hover:opacity-100 focus:opacity-100 p-0.5 rounded hover:bg-line" aria-label={`Close ${t.title}`}
              onClick={(e) => { e.stopPropagation(); closeTab(t.id); }}><X size={11} /></button>
          </div>
        ))}
        <button className="btn btn-ghost px-1 py-0.5 shrink-0" onClick={newShell} title="New shell tab" aria-label="New shell tab"><Plus size={13} /></button>
        <button className="btn btn-ghost px-1 py-0.5 ml-auto shrink-0" onClick={() => useStore.setState({ terminalOpen: false })} title="Hide terminal (⌘J)" aria-label="Hide terminal"><X size={13} /></button>
      </div>
      <div ref={host} className="relative flex-1 min-h-0" style={{ background: "var(--sunken)" }} />
    </div>
  );
}
