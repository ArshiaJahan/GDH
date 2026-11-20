Fix what the Unity demo run turned up

Problems found while recording the README demo on a real Unity project:

- Ladder: L3 went green for a replay criterion from an EditMode run that
  "covered" the milestone but never ran LogMatchesCheckpoints. A replay
  verification test now counts only through a tool-observed
  replay_verified report; a criterion naming both kinds needs both.
- Replay: a batch verify had no Editor log (the CLI prints only JSON), so
  the report's log_sha256 was empty and L3 refused real evidence. The
  Editor is now asked for -logFile.
- Replay: every batch run reported environment "differs" (os, project_id)
  on the machine that recorded it: Unity writes "Mac OS X 26.6.2", and an
  unset applicationIdentifier ({}) was read literally instead of Unity's
  default com.<company>.<product>.
- Replay: record takes max_seconds for this run (capped by
  [unity.replay] max_seconds). One stop timer per session, replaced by a
  new recording and cleared by stop, so an old timer can't stop a later run.
- Claude Code sessions: GDW's MCP server gets a per-server timeout, so the
  CLI's 300 s idle limit no longer aborts a Unity batch run or a tool call
  waiting on an approval card.
- Approvals: a card whose waiting tool call is cancelled is closed instead
  of staying open looking live.
- Prompt improver: replies with raw newlines inside JSON strings, or an
  object wrapped in prose, parse instead of failing as "malformed".
- Chat: a plan-limit notice showed "retrying in 546594s"; waits now read
  as 6d 7h and plan-limit notices keep their own text and reset time.

Interface the tests use (declarations only; the change adds or changes these):
- `def loads_reply(text: str) -> Any:`
- `def _os_family(name: str) -> str:`
- `def _record_seconds(args: dict, replay_cfg: dict) -> int:`
- `raise ReplayOpError("bad_max_seconds",`
- `def _disarm_record_limit(session_id: str) -> None:`
- `def _arm_record_limit(app: "AppState", session: dict, run_id: str, replay_cfg: dict,`
- `export function formatWait(seconds: number): string`
- `export function statusText(s: AgentStatus, nowMs: number): string`
- `const left = s.until ? Math.max(0, Math.ceil(s.until - nowMs / 1000)) : null`
- `const text = statusText(s, now)`
