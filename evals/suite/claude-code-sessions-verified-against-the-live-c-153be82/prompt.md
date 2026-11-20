Claude Code sessions: verified against the live claude CLI

Checked with real turns on claude 2.1.308 (claude.ai login) and fixed what differed:
- Use --setting-sources (empty by default) instead of --safe-mode, which dropped
  GameDevWorkstation's MCP server; ignore the CLI's built-in plugins in the
  isolation check; fail closed when the hook isn't applied.
- Plan mode: allow only the plan file in ~/.claude/plans so ExitPlanMode reaches
  the plan card; AskUserQuestion answers in the CLI's format.
- Join split assistant events, drop empty thinking, show plan rate limits, record
  per-turn tokens plus the conversation cost increase; failed resumes record nothing.
- Claude Code sessions skip the API-billed auto title.
- Test fake now replays redacted real captures (tests/fixtures/claude_stream).
- README and GUIDE: experimental label removed; lists what wasn't checked live.

Interface the tests use (declarations only; the change adds or changes these):
- `plus MCP_TOOL_TIMEOUT (claude_cli.child_env); --bare (API key only) is never passed; nothing is`
- `CLI_MODE`
- `def user_plugins(plugins: Any) -> list:`
- `def plans_dir() -> Path:`
