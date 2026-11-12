// Claude Code sessions (harness claude_code): the harness picker shared by the new-session flow and
// the Environment card, the session header chip (login status, `claude --resume <id>` to copy), the
// "log in" card, and Settings → Claude Code. The session runs the user's own `claude` CLI on their own
// Claude login; GameDevWorkstation never sees their tokens.
import { Check, Copy, KeyRound, RefreshCw, TerminalSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { get, post } from "../lib/api";
import { actions, useStore, type Msg, type Session } from "../lib/store";

export const HARNESSES: [string, string][] = [
  ["builtin", "Built-in loop"], ["agent_sdk", "Claude Agent SDK"], ["codex_cli", "Codex CLI"],
  ["claude_code", "Claude Code (subscription)"],
];
export const HARNESS_HINT: Record<string, string> = {
  claude_code: "Runs your own claude CLI with your own Claude login. API key logins count toward spend limits.",
};

export type ClaudeStatus = {
  installed: boolean; path: string | null; version: string | null; logged_in: boolean; auth_method: string | null;
  auth: Record<string, unknown> | null; bills_api: boolean; error: string | null; login_hint: string;
  settings?: { cli_path: string; load_user_mcp: boolean; setting_sources: string }; processes?: number;
};

/** The CLI and login status (GET /claude-code/status); refresh() re-checks right away. */
export function useClaudeStatus(enabled = true): [ClaudeStatus | null, () => void] {
  const [st, setSt] = useState<ClaudeStatus | null>(null);
  const load = (refresh = false) => { get<ClaudeStatus>(`/claude-code/status${refresh ? "?refresh=1" : ""}`).then((x) => setSt(x ?? null)).catch(() => setSt(null)); };
  useEffect(() => { if (enabled) load(); }, [enabled]);
  return [st, () => load(true)];
}

export function loginLabel(st: ClaudeStatus | null): string {
  if (!st) return "Checking…";
  if (!st.installed) return "claude CLI not found";
  if (!st.logged_in) return "Not logged in";
  return st.bills_api ? "Logged in with an API key" : `Logged in${st.auth_method ? ` (${st.auth_method})` : ""}`;
}

/** The harness <select>. `available` is /environment's harnesses map (missing → not offered as installed). */
export function HarnessSelect({ value, onChange, available, disabled, title, label = (v, l) => l }: {
  value: string; onChange: (v: string) => void; available?: Record<string, boolean> | null; disabled?: boolean; title?: string;
  label?: (v: string, l: string, full: boolean) => string;
}) {
  return (
    <select className="input py-0.5" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} aria-label="Harness" title={title}>
      {HARNESSES.map(([v, l]) => (
        <option key={v} value={v} disabled={!!available && !available[v]} title={HARNESS_HINT[v] ?? label(v, l, true)}>
          {label(v, l, false)}{available && !available[v] ? " (not installed)" : ""}
        </option>
      ))}
    </select>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button className="btn btn-ghost px-1 py-0.5" aria-label={label} title={label}
      onClick={async () => {
        try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }
        catch { actions.toast("Couldn't copy to the clipboard", "error"); }
      }}>{done ? <Check size={13} /> : <Copy size={13} />}</button>
  );
}

/** The session header chip of a Claude Code session: login status and `claude --resume <id>`. */
export function ClaudeCodeChip({ s }: { s: Session }) {
  const [st] = useClaudeStatus(true);
  const id: string | undefined = s.settings?.claude_code_session ?? undefined;
  const cmd = typeof id === "string" && /^[0-9a-f-]{36}$/i.test(id) ? `claude --resume ${id}` : null;
  const ok = !!st?.installed && st.logged_in;
  return (
    <span className="chip whitespace-nowrap shrink-0 gap-1" data-testid="claude-code-chip"
      title={cmd ? `Continue this conversation in a terminal: ${cmd}` : "Claude Code (your CLI login)"}>
      <TerminalSquare size={12} aria-hidden />
      <span>Claude Code</span>
      <span className={ok ? "text-ok" : "text-warn"}>· {loginLabel(st)}</span>
      {cmd && <><code className="font-mono text-[11.5px] text-muted hidden md:inline">{cmd}</code><CopyButton text={cmd} label="Copy the claude --resume command" /></>}
    </span>
  );
}

/** The reply when the claude CLI isn't logged in: how to log in, then Retry. */
export function ClaudeLoginNotice({ m, sessionId }: { m: Msg; sessionId?: string }) {
  const current = useStore((x) => x.currentId);
  const sid = sessionId ?? current ?? "";
  const latestLogin = useStore((x) => x.messages[sid]?.filter((msg) => msg.meta?.error_kind === "claude_login").at(-1)?.id);
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    setBusy(true);
    try {
      const r = await post<{ started: boolean }>(`/claude-code/sessions/${sid}/retry`, {});
      if (!r?.started) actions.toast("Still not logged in. Run claude auth login in a terminal first.", "error");
    } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <div role="alert" className="my-4 flex items-start gap-2 rounded-md border border-line surface-raised px-3 py-2 text-[13px]">
      <KeyRound size={15} className="text-warn mt-0.5 shrink-0" aria-hidden />
      <div className="flex-1 min-w-0">
        <div className="font-medium">Claude Code isn't logged in</div>
        <div className="text-muted">
          Run <code className="font-mono">claude auth login</code> in a terminal, then retry. It uses your own Claude account;
          GameDevWorkstation never sees your login.
        </div>
        {m.meta?.detail && <div className="text-faint text-[12px] mt-1 break-words">{m.meta.detail}</div>}
      </div>
      <CopyButton text="claude auth login" label="Copy claude auth login" />
      {latestLogin === m.id && <button className="btn btn-primary py-0.5 shrink-0" disabled={busy} onClick={retry}>Retry</button>}
    </div>
  );
}

/** Settings → Claude Code. */
export function ClaudeCodeSettings({ st, save, Row, TextSetting }: {
  st: any; save: (body: any, field?: string) => unknown;
  Row: (p: { label: string; hint?: string; children: any; noMark?: boolean }) => any;
  TextSetting: (p: { value: string; onSave: (v: string) => unknown; label: string; placeholder?: string }) => any;
}) {
  const c = st.claude_code ?? {};
  const [cli, refresh] = useClaudeStatus(true);
  const sources: string = c.setting_sources ?? "";
  return (
    <div>
      <h2 className="text-base font-semibold mb-1">Claude Code</h2>
      <p className="text-[12.5px] text-muted mb-3">
        "Claude Code (subscription)" sessions run your own <code className="font-mono">claude</code> CLI with your own Claude login.
        Checked against claude 2.1.308 on a claude.ai subscription login. Subscription usage is shown as an estimate;
        API key logins count toward API spend limits. GameDevWorkstation passes no API key and never reads your tokens.
      </p>
      <Row label="claude CLI" noMark>
        <div className="text-[13px] min-w-0" data-testid="claude-cli">
          {!cli ? <span className="text-muted">Checking…</span>
            : !cli.installed ? <span className="text-muted">{cli.error ?? "Not found"}</span>
            : <><span className="font-mono break-all">{cli.path}</span>{cli.version && <span className="chip ml-2">{cli.version}</span>}</>}
        </div>
      </Row>
      <Row label="Login" noMark>
        <div className="flex items-center gap-2 text-[13px] min-w-0">
          <span className={cli?.logged_in ? "text-ok" : "text-warn"} data-testid="claude-login">{loginLabel(cli)}</span>
          {cli && cli.installed && !cli.logged_in && <span className="text-muted">Run <code className="font-mono">claude auth login</code> in a terminal.</span>}
          <button className="btn btn-ghost px-1 py-0.5" aria-label="Check again" title="Check again" onClick={refresh}><RefreshCw size={13} /></button>
        </div>
      </Row>
      <Row label="CLI path" hint="Empty: look it up (PATH, ~/.local/bin, ~/.claude/local, /opt/homebrew/bin)">
        <TextSetting value={c.cli_path ?? ""} label="claude CLI path" placeholder="/opt/homebrew/bin/claude"
          onSave={async (v) => { await save({ claude_code: { cli_path: v } }, "CLI path"); refresh(); }} />
      </Row>
      <Row label="Your MCP servers" hint="Off: strict MCP config, only GameDevWorkstation's tools. On: permits your MCP servers when customization loading is enabled">
        <input type="checkbox" checked={!!c.load_user_mcp} aria-label="Load my Claude Code MCP servers"
          onChange={(e) => save({ claude_code: { load_user_mcp: e.target.checked } }, "Your MCP servers")} />
      </Row>
      <Row label="Settings files" hint="None loads no user, project or local settings: no custom CLAUDE.md, skills, agents, plugins or their hooks; admin policies still apply">
        <select className="input max-w-full" value={sources} aria-label="Claude Code setting sources"
          onChange={(e) => save({ claude_code: { setting_sources: e.target.value } }, "Settings files")}>
          <option value="">None (your ~/.claude hooks, plugins and settings files are ignored)</option>
          <option value="user">User (~/.claude)</option>
          <option value="user,project">User and project</option>
          <option value="user,project,local">User, project and local</option>
          {!["", "user", "user,project", "user,project,local"].includes(sources) && <option value={sources}>{sources}</option>}
        </select>
      </Row>
    </div>
  );
}
