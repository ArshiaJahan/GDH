import { CheckCircle2, Circle, KeyRound, X } from "lucide-react";
import { useEffect, useState } from "react";
import { get } from "../lib/api";
import { actions, useStore, type Msg } from "../lib/store";

type Setup = { keys: Record<string, boolean>; folder: boolean; skill: boolean };
const DISMISSED = "setupChecklistDismissed";

/** First-run checklist on the empty chat: keys, a folder for code sessions, a skill. Re-checked when
 *  settings change; gone once the required steps are done, or for good when dismissed. */
export function SetupChecklist() {
  const [setup, setSetup] = useState<Setup | null>(null);
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISSED) === "1");
  // Re-checked when settings change or a session gets a folder (keys: when the chat shows again after Settings).
  const settings = useStore((s) => s.appState);
  const anyFolder = useStore((s) => (s.sessions ?? []).some((x) => !!x.folder));
  useEffect(() => {
    if (dismissed) return;
    get<Setup>("/setup").then(setSetup).catch(() => {});
  }, [dismissed, settings, anyFolder]);
  if (dismissed || !setup) return null;
  const steps: { done: boolean; label: string; hint: string; optional?: boolean; action?: [string, () => void] }[] = [
    { done: setup.keys.anthropic, label: "Add your Anthropic API key", hint: "Claude is the main agent; nothing runs without it.",
      action: ["Settings → Accounts", () => actions.go("settings", { section: "accounts" })] },
    { done: setup.keys.openai && setup.keys.elevenlabs, optional: true, label: "Add OpenAI and ElevenLabs keys",
      hint: "OpenAI for Codex subagents, ElevenLabs for speech, transcripts, sound and music.",
      action: ["Settings → Accounts", () => actions.go("settings", { section: "accounts" })] },
    { done: setup.folder, label: "Pick a folder for code sessions",
      hint: "Choose a folder in the side panel's Environment card; the agent works there and the Changes card tracks its edits." },
    { done: setup.skill, label: "Try a skill", hint: "Press the sparkles button in the composer, or type /skill.",
      action: ["Browse skills", () => actions.go("skills")] },
  ];
  const required = steps.filter((s) => !s.optional);
  if (required.every((s) => s.done)) return null;
  const left = steps.filter((s) => !s.done).length;
  return (
    <section aria-label="Getting started" className="mb-6 rounded-lg border border-line surface-raised p-3 text-[13px]">
      <div className="flex items-center mb-2">
        <h2 className="font-medium">Getting started</h2>
        <span className="ml-2 text-faint">{left} step{left === 1 ? "" : "s"} left</span>
        <button className="ml-auto btn btn-ghost px-1 py-0.5" aria-label="Dismiss the getting started checklist" title="Don't show again"
          onClick={() => { localStorage.setItem(DISMISSED, "1"); setDismissed(true); }}><X size={14} /></button>
      </div>
      <ul className="space-y-2">
        {steps.map((s) => (
          <li key={s.label} className="flex items-start gap-2">
            {s.done ? <CheckCircle2 size={15} className="text-ok mt-0.5 shrink-0" aria-hidden /> : <Circle size={15} className="text-faint mt-0.5 shrink-0" aria-hidden />}
            <div className="flex-1 min-w-0">
              <div className={s.done ? "text-muted line-through" : ""}>
                {s.label}{s.optional && <span className="text-faint"> (optional)</span>}
                <span className="sr-only">{s.done ? " (done)" : " (to do)"}</span>
              </div>
              {!s.done && <div className="text-muted text-[12.5px]">{s.hint}</div>}
            </div>
            {!s.done && s.action && <button className="btn py-0.5 shrink-0" onClick={s.action[1]}>{s.action[0]}</button>}
          </li>
        ))}
      </ul>
    </section>
  );
}

const PROVIDER = { anthropic: "Anthropic", openai: "OpenAI" } as Record<string, string>;

/** The reply to a message sent without an API key: a plain note and a way to add one. */
export function NoKeyNotice({ m }: { m: Msg }) {
  const name = PROVIDER[m.meta?.provider] ?? "API";
  return (
    <div role="alert" className="my-4 flex items-start gap-2 rounded-md border border-line surface-raised px-3 py-2 text-[13px]">
      <KeyRound size={15} className="text-warn mt-0.5 shrink-0" aria-hidden />
      <div className="flex-1 min-w-0">
        <div className="font-medium">Add your {name} key to start chatting</div>
        <div className="text-muted">GameDevWorkstation needs your own {name} API key. It's saved in the macOS Keychain, never in files or logs. Then send your message again.</div>
      </div>
      <button className="btn btn-primary py-0.5 shrink-0" onClick={() => actions.go("settings", { section: "accounts" })}>Open Settings → Accounts</button>
    </div>
  );
}
