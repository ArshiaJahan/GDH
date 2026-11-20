Claude Code sessions: paperclip attachments

Attached images, PDFs and text files go to the claude CLI inline in the
stream-json user message (Anthropic content blocks, each after an
[Attached <kind>: name] label), so Claude Code reads them without a path
outside its folder. Over ~20 MB the oldest become a note. The new-session
screen gets the paperclip, drop and paste; a failed first message keeps
its files as the session's draft. Checked live against the claude CLI.

Interface the tests use (declarations only; the change adds or changes these):
- `MAX_TURN_MEDIA`
- `def _user_content(msgs: list[Message], recap: str | None) -> list[dict]:`
- `const ups = await Promise.all(Array.from(files).map((f)`
- `const started = await sessionActions.start(`
