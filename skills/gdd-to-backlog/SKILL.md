---
name: gdd-to-backlog
description: Turns a game design doc (game-designer GDD and feature specs) into BACKLOG.md for a Unity 6 (6000.3) 2D roguelike - playable milestones M0-M4, stories, Given/When/Then criteria each with a test type, an observable signal and an owner skill - and lints it. Use when asked to plan, scope or break a GDD down into milestones, stories, tickets or a backlog, or to lint BACKLOG.md after hand edits.
---

# gdd-to-backlog

Convert design intent into a milestone ladder where every milestone is playable and every criterion can be checked by a test, a log line, a screenshot, a metric, or a counted human observation.

Pinned: Unity 6000.3 LTS, Test Framework 1.6.0 (NUnit `[Test]`/`[UnityTest]`, `[Category]`), backlog format checked by `scripts/backlog_lint.py` (Python 3.9+ stdlib).
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. mcp__UnityMCP__run_tests). This skill only writes markdown; it names the tools that later verify each criterion.

## When to use
- A GDD, one-page concept or feature spec exists and implementation should start.
- The user asks for milestones, a backlog, tickets, scope cuts or "what do we build first".
- BACKLOG.md was edited by hand and needs checking.

Not for: writing or critiquing the design itself (use game-designer), implementing stories (unity-router picks the skills), or tracking progress notes (project-memory).

## Inputs
- GDD path (game-designer `templates/gdd-template.md` layout, sections numbered 1-23). Feature specs (`templates/feature-spec.md`) if present.
- Project root (BACKLOG.md goes next to PROJECT.md).
- If no GDD exists: ask for one, or run game-designer to produce at least a one-page concept plus §3 Core Loop, §4 Mechanics, §9 Content Plan. Do not invent a design.

## Procedure
1. Read the GDD. Extract into a scratch list: pillars (§2), verbs table, fail state and retry time (§3), each mechanic's rules/variables/edge cases (§4.x), systems (§5), controls and responsiveness targets (§6), progression (§7), economy faucets/sinks (§8), MVP content counts (§9), procgen rules (§10), accessibility Must rows (§14), technical budgets (§17), analytics events (§18), milestones (§19), top risks (§20), open questions (§21). Note sections marked N/A.
2. Read every linked feature spec. Its §3 Rules, §5 Edge cases, §9 Acceptance Criteria and §10 Test Plan are the main source of criteria.
3. Lay out the milestone ladder. Default for a 2D roguelike:
   - M0 Skeleton / boot: repo, folders, asmdefs, Boot -> Title -> Game, input actions, test + build pipeline, placeholders.
   - M1 Core loop playable: the §3 verbs in one room, enemy, damage, death -> restart.
   - M2 Run structure: seeded procgen, room/floor progression, run end, meta-progression + save.
   - M3 Content and juice: MVP counts from §9, game feel, audio/art import.
   - M4 Polish and ship: menus, settings, accessibility Musts, perf budget, release builds, playtest.
   Adapt to the GDD (merge, rename, reorder) but keep M<n> IDs consecutive from M0 and keep each milestone a playable increment. Move the riskiest mechanic from §20 into M1. Seed stories and adaptation rules: read `references/roguelike-milestones.md` sections 1 and 5.
4. Write stories. One story = one player-visible capability or one pipeline capability, small enough for one implement -> compile-fix-loop -> verify cycle. IDs `M<n>-S01`, `M<n>-S02`, ... Set `- Status: todo` and `- Owner skill:` (the skill to load first for the work, see the table below). Add `- GDD: §4.2, FS-002` for traceability.
5. Write acceptance criteria per story, one table row each: `| M1-S02-AC1 | Given ..., When ..., Then ... | <Test> | <Signal> |`.
   - One rule or edge case per criterion. Quote defaults from the tuning table in Given (`Given MoveSpeed 6`).
   - Then must be measurable: a number, a state, an event count, a scene name. No "feels good", "smooth", "fun" without a threshold. Rewrites: `references/roguelike-milestones.md` section 4.
   - Pick the test type: logic -> EditMode; physics/frames/scenes -> PlayMode; visible behaviour in a running editor -> play-verify; build/CLI/player smoke -> headless; fun/comprehension -> manual with a tester count.
   - Signal kinds: `test:Fixture.Method`, `log:"[Tag] text"`, `screenshot:<name> shows <what>`, `metric:<name> <op> <number>[unit]`, `file:<path>`, `exit:<code>`, `observe:<what a human checks>`. Several signals: separate with `;`. No `|` inside cells.
   - EditMode/PlayMode rows need a `test:` signal. play-verify rows need `log:`, `screenshot:` or `metric:` (prefer log + screenshot so the check is not image-only). For a play-verify `metric:`, plan a `[VERIFY] <name>=<value>` log line in the story, because play-verify reads metric values from those lines.
   - Test names: `M<n>_S<nn>_<Behaviour>` with `[Category("M<n>")]` on the fixture, so a milestone runs with `run_tests(category_names=["M1"])` or `-testCategory "M1"`.
6. Put GDD §9 Target/Stretch content and Should-tier items under `## Later (not scheduled)`. Copy §21 open questions under `## Open questions` and mark blocked stories `- Status: blocked`.
7. Write BACKLOG.md at the project root from `references/BACKLOG.template.md`. Set `Current milestone: M0` (or the first milestone not done). Set the current milestone `Status: active`.
8. Run the linter (see Verify). Fix every ERROR. Fix WARNs unless you can say why they are acceptable.
9. Hand off: tell project-memory to set the `Current milestone:` pointer in PROJECT.md, then return to unity-router for the M0 loop. Optional: mirror stories to a Kanban board if the user asks (one card per story, criteria as checklist items).

## Owner skill by story kind
| Story kind | Owner skill |
|---|---|
| Repo, .gitignore, LFS, merge driver | vcs-hygiene |
| PROJECT.md, conventions, ADRs | project-memory |
| Gameplay code, data assets, events, input, save, scene flow | architecture-patterns |
| Scene/prefab authoring or bulk edits | scene-prefab-safety |
| Import settings, atlases, audio, placeholders, Addressables | asset-pipeline |
| Juice: hit-stop, shake, flashes, particles, SFX timing | game-feel-pass |
| Frame time, GC, draw calls, physics cost | perf-pass |
| Batchmode test runner, CI scripts, editor entry points | headless-ops |
| Player builds, versioning, changelog, smoke tests | build-ship |
| Tuning numbers, playtest plans | game-designer |
| Playtest sessions, sign-off | human |

## Rules
Stories may include optional `- Visual: yes|no` to override the harness's file-glob detection of whether screenshot evidence is required, and `- Critique: yes|no` to enable or disable the design-critique quality tier for that story. Values are case-insensitive; each field may appear once per story. Omit a field to keep the harness default; `--json` emits `visual` and `critique` as booleans, or `null` when absent.

- Every milestone has `Goal:`, a testable `Exit:` and `Status:` (todo|active|done). Exactly one milestone is `active`.
- Every story has `- Status:` (todo|doing|done|blocked|cut), `- Owner skill:` and at least one criterion.
- Every criterion has Given/When/Then, a test type and at least one observable signal. No signal, no criterion.
- IDs never change once work starts. Cut stories get `- Status: cut`; do not delete or renumber.
- Keep design numbers in the GDD/spec and data assets. Criteria quote only the defaults they test.
- Do not schedule Stretch content before M4 is done.
- Do not add stories the GDD does not justify. Ask, or put them under Later with a note.

## Failure handling
- GDD lacks §3/§4 detail: write M0 fully, write M1 stories with criteria marked `- Status: blocked`, and list the missing decisions under Open questions. Ask the user or game-designer for them.
- A criterion cannot be made observable: split it (measurable part + a manual row with `observe:`), or move it to Open questions.
- The linter fails on format you did not write (hand edits): fix the format, keep the meaning, and report the changes.
- More than ~60 stories: the scope is too big for one ladder. Move Target/Stretch content to Later and report the cut list.

## Verify
1. Run `python3 <skill-dir>/scripts/backlog_lint.py <project>/BACKLOG.md`. Pass: exit code 0 and the last line starts with `RESULT: OK`, and it shows the expected milestone, story and criterion counts and the current milestone.
2. Run `python3 <skill-dir>/scripts/backlog_lint.py <project>/BACKLOG.md --milestone M0`. Pass: every M0 criterion is listed under a test type, with a signal and an owner.
3. Report the counts, the current milestone, any WARN lines you kept (with the reason), and the Later and Open questions lists.
