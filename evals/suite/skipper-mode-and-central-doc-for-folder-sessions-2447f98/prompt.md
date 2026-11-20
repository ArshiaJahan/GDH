Skipper mode and Central doc for folder sessions

A Modes menu on the new-session screen turns them on for a Claude Code
folder session.

- Skipper: after each turn the app asks Claude Code for a handoff, saves
  it under <folder>/.gdw/sessions/<id>/, and continues the work in a fresh
  Claude Code conversation that starts from that handoff.
- Central doc: one summary doc for the session that Claude Code updates
  after each turn. With Skipper on, the doc is the handoff.

Also: the location menu on the new-session screen, a "+ New session"
button in the sidebar, and stable code signing for local builds
([new file]; build_mac.sh refuses ad-hoc unless
GDW_ALLOW_ADHOC=1).

Interface the tests use (declarations only; the change adds or changes these):
- `return Path(str(path)).read_text(encoding="utf-8", errors="replace")[-limit:] if path else ""`
- `const folders = folder && !recents.includes(folder) ? [folder, ...recents] : recents`
- `const started = await sessionActions.start(`
