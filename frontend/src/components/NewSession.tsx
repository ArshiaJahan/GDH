// The new-session screen (the chat page with no session open): "What should we work on, <name>?",
// a composer card with the session's settings, and recent folders. Every new session runs Claude
// Code on the user's own Claude subscription (harness claude_code). Chat only = no folder: Claude
// Code works in a private scratch folder; Folder = it works in that project folder. The session is
// created when the first message is sent.
import { Folder } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { get } from "../lib/api";
import { pickFolder } from "../lib/native";
import { sessionActions } from "../lib/sessions";
import { useStore, type Session } from "../lib/store";
import { ClaudeStatusNotice, useClaudeStatus } from "./ClaudeCode";
import { EffortSelect, EFFORTS, folderName, ModelSelect, ModeSelect, NEW_SESSION_MODES, TextSelect, tilde } from "./ClaudeCard";
import { Composer, type ComposerDraft } from "./Composer";
import { providerModels, useModelCatalog } from "./ui";

export { folderName, NEW_SESSION_MODES };

export type Location = "chat" | "folder";
export const PLACEHOLDER = "Describe a task, or type / for commands and skills, /task for a Kanban card…";
const PREFS_KEY = "newSession.prefs";
const RECENT_MAX = 6;

type Prefs = { location: Location; folder: string | null; model: string | null; effort: string | null; mode: string | null };
const NO_PREFS: Prefs = { location: "chat", folder: null, model: null, effort: null, mode: null };

/** The last choices on this screen (this window's browser storage; a convenience only). */
function loadPrefs(): Prefs {
  try {
    return { ...NO_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return NO_PREFS;
  }
}
function savePrefs(p: Prefs) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* private window: not remembered */ }
}


/** Folders of recent sessions, most recently active first (Trash left out). */
export function recentFolders(sessions: Session[], max = RECENT_MAX): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const s of sessions.filter((x) => x.folder && !x.deleted).sort((a, b) => (b.activity_at ?? b.created_at) - (a.activity_at ?? a.created_at))) {
    if (!seen.has(s.folder!)) { seen.add(s.folder!); out.push(s.folder!); }
    if (out.length >= max) break;
  }
  return out;
}

export function NewSession() {
  useModelCatalog();
  const appState = useStore((s) => s.appState);
  const sessions = useStore((s) => s.sessions);
  const [prefs, setPrefsState] = useState<Prefs>(loadPrefs);
  const setPrefs = (p: Partial<Prefs>) => setPrefsState((cur) => { const next = { ...cur, ...p }; savePrefs(next); return next; });
  const [name, setName] = useState<string | null>(null);
  useEffect(() => { get<{ name: string | null }>("/greeting").then((r) => setName(r?.name ?? null)).catch(() => setName(null)); }, []);
  const [cli, recheck] = useClaudeStatus(true);

  // Claude models only (Claude Code runs Claude); the default is the orchestrator's model when it's a Claude one.
  const models = providerModels("anthropic");
  const fallbackModel = (() => {
    const o: string | undefined = appState?.orchestrator?.model;
    const deep: string | undefined = appState?.tiers?.["claude.deep"];
    return [o, deep, models[0]?.id].find((m) => m && models.some((x) => x.id === m)) ?? o ?? "claude-opus-5-5";
  })();
  const model = prefs.model && models.some((m) => m.id === prefs.model) ? prefs.model : fallbackModel;
  const effort = prefs.effort && EFFORTS.includes(prefs.effort) ? prefs.effort : appState?.orchestrator?.effort ?? "medium";
  const defaultMode: string = appState?.modes?.default ?? "ask";
  const mode = prefs.mode && NEW_SESSION_MODES.some(([m]) => m === prefs.mode) ? prefs.mode
    : NEW_SESSION_MODES.some(([m]) => m === defaultMode) ? defaultMode : "ask";
  const location: Location = prefs.location === "folder" ? "folder" : "chat";
  const folder = location === "folder" ? prefs.folder : null;
  const recents = useMemo(() => recentFolders(sessions), [sessions]);

  const choose = async () => {
    const f = await pickFolder(prefs.folder ?? undefined);
    if (f === null) return; // cancelled: nothing changes
    if (f) setPrefs({ location: "folder", folder: f });
    else setPrefs({ location: "chat" }); // the browser prompt left empty: chat only
  };
  const setLocation = (v: string) => {
    if (v !== "folder") return setPrefs({ location: "chat" });
    const known = prefs.folder ?? recents[0] ?? null;
    if (known) setPrefs({ location: "folder", folder: known });
    else void choose();
  };

  const subtitle = folder
    ? <>The project stays in <span className="text-text" title={tilde(folder)}>{folderName(folder)}</span>. Claude Code reads, edits and runs commands there.</>
    : "Chat only: no folder; Claude Code works in a private scratch folder.";

  const draftSession = { id: "new", title: "New session", folder, model, effort, mode, harness: "claude_code", settings: {} } as unknown as Session;
  const draft: ComposerDraft = {
    placeholder: PLACEHOLDER,
    set: (b) => {
      const m = b.model ? appState?.tiers?.[b.model] ?? b.model : undefined; // a tier key names its model
      if (m && !models.some((x) => x.id === m)) throw new Error("New sessions run Claude Code: pick a Claude model.");
      if (b.mode && !NEW_SESSION_MODES.some(([v]) => v === b.mode)) throw new Error("Mode must be plan, ask or accept_edits.");
      setPrefs({ ...(m ? { model: m } : {}), ...(b.effort ? { effort: b.effort } : {}), ...(b.mode ? { mode: b.mode } : {}) });
    },
    start: async (text, skill, attachments) => {
      const started = await sessionActions.start({ text, skill, attachments, folder, model, effort, mode });
      if (!started) setPrefsState(loadPrefs()); // a missing folder resets saved preferences to Chat only
      return started;
    },
    rows: [
      <>
        <TextSelect label="Location" value={location} onChange={setLocation}
          title={location === "folder" ? "Claude Code works in a project folder" : "No folder: Claude Code works in a private scratch folder"}>
          <option value="chat">Chat only</option>
          <option value="folder">Folder</option>
        </TextSelect>
        {location === "folder" && (
          <button className="btn btn-ghost gap-1.5 px-2 text-[14px] min-w-0" onClick={choose} title={folder ? `${folder} (choose another folder)` : "Choose a folder"}
            aria-label={folder ? `Folder ${folderName(folder)}` : "Choose a folder"} data-testid="folder-chip">
            <Folder size={15} className="shrink-0" aria-hidden /><span className="truncate max-w-[220px]">{folder ? folderName(folder) : "Choose a folder…"}</span>
          </button>
        )}
        <ModelSelect value={model} onChange={(v) => setPrefs({ model: v })} />
      </>,
      <>
        <EffortSelect value={effort} onChange={(v) => setPrefs({ effort: v })} />
        <ModeSelect value={mode} onChange={(v) => setPrefs({ mode: v })} />
      </>,
    ],
  };

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="min-h-full flex flex-col items-center px-4 sm:px-6 pt-[14vh] pb-10">
        <div className="w-full max-w-[760px]">
          <h1 className="text-center text-[28px] sm:text-[32px] font-medium tracking-[-0.015em] leading-tight text-balance">
            {name ? `What should we work on, ${name}?` : "What should we work on?"}
          </h1>
          <p className="mt-3 mx-auto max-w-[640px] text-center text-[15px] leading-relaxed text-muted text-balance" data-testid="new-session-subtitle">{subtitle}</p>
          {cli && !(cli.installed && cli.logged_in) && (
            <div className="mt-4 flex justify-center"><ClaudeStatusNotice st={cli} retry={recheck} /></div>
          )}
          <div className="mt-6">
            <Composer session={draftSession} running={false} draft={draft} />
          </div>
          {recents.length > 0 && (
            <div className="mt-4 flex flex-wrap justify-center gap-2" aria-label="Recent folders" role="group">
              {recents.map((f) => {
                const on = folder === f;
                return (
                  <button key={f} title={f} aria-pressed={on} onClick={() => setPrefs({ location: "folder", folder: f })}
                    className={`rounded-full px-3 py-0.5 text-[13px] leading-6 border transition-colors max-w-[240px] truncate ${on
                      ? "border-transparent text-action bg-[color-mix(in_srgb,var(--action)_13%,transparent)]"
                      : "border-line text-text surface-raised hover:border-faint"}`}>
                    {folderName(f)}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
