New-session screen: Claude-style composer, Claude subscription by default

- New screen: greeting with your Mac account's name, a large composer with
  Chat only / Folder, folder chip, Claude model, effort, mode (Plan / Ask /
  Accept edits) and Tools, plus recent-folder pills. The session is created on Send.
- New sessions run on the Claude Code harness (your Claude subscription);
  [sessions].default_harness = "claude_code". Scheduled tasks, campaigns, fleet
  and subagents keep the built-in loop; existing sessions keep their harness.
- Chat-only sessions work in a private per-session folder; older ones keep theirs
  so --resume still finds the conversation.
- Workflows are hidden in Claude subscription sessions (they need the API loop).
- A failed first message keeps your text; header no longer overflows the resume chip.
- README and GUIDE updated.

Interface the tests use (declarations only; the change adds or changes these):
- `backend/gamedevworkstation/features/claude_code.py`:
  - `def work_dir(sid: str) -> Path:`
  - `def session_cwd(s: dict) -> Path:`
- `backend/gamedevworkstation/features/session_routes.py`:
  - `@cache def account_full_name() -> str:`
  - `def greeting_name(full: str) -> str | None:`
  - `@api.get("/greeting") async def greeting() -> dict:`
- `backend/gamedevworkstation/server.py`:
  - `def new_session_harness(config: Any) -> str:`
- `frontend/src/components/ClaudeCode.tsx`:
  - `export function harnessName(v: string): string`
  - `export function ClaudeStatusNotice(`
- `frontend/src/components/Composer.tsx`:
  - `export function Composer(`
- `frontend/src/components/NewSession.tsx` (new file):
  - `export function recentFolders(sessions: Session[], max = RECENT_MAX): string[]`
  - `export function NewSession()`
