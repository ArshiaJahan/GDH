# Feature Spec: [Feature / Mechanic Name]

> A single feature or mechanic specified so that a designer, engineer, artist, and QA engineer can each build and verify their part without a meeting. Be explicit with numbers, states, and edge cases. Delete guidance lines (starting with `>`) when filling in.

| Field | Value |
|---|---|
| Spec ID | [FS-001] |
| Status | [Draft / In review / Approved / Implemented / Retired] |
| Owner (design) | [name] |
| Engineering / art / audio contacts | [names] |
| Target milestone | [e.g., Vertical slice] |
| Last updated / version | [YYYY-MM-DD / v0.1] |
| Related GDD section | [link to templates/gdd-template.md Section 4.x] |

## Table of Contents

1. [Goal](#1-goal)
2. [Player Story](#2-player-story)
3. [Rules](#3-rules)
4. [Variables and Tuning Table](#4-variables-and-tuning-table)
5. [States and Edge Cases](#5-states-and-edge-cases)
6. [UI and Feedback](#6-ui-and-feedback)
7. [Dependencies](#7-dependencies)
8. [Telemetry](#8-telemetry)
9. [Acceptance Criteria](#9-acceptance-criteria)
10. [Test Plan](#10-test-plan)
11. [Open Questions](#11-open-questions)
12. [Change Log](#12-change-log)
13. [Further Reading](#13-further-reading)

---

## 1. Goal

> Why this exists. Which pillar it serves, which player experience it creates, and how you will know it worked (a measurable success signal).

- **Problem or opportunity:** [e.g., "Players have no way to recover from a bad engagement."]
- **Pillar(s) served:** [ ]
- **Intended player experience / emotion:** [ ]
- **Success signal (observable or measurable):** [e.g., "At least 70% of testers use it voluntarily within the first 3 minutes of combat."]
- **Non-goals (what this feature will not do):** [ ]

## 2. Player Story

> Describe from the player's view in plain language. Include the moment-to-moment experience.

- **As a** [player type], **I want to** [action], **so that** [outcome/feeling].
- **Typical use case (narrative walk-through):** [Step-by-step description of a normal use, with what the player sees, hears, and feels.]
- **Skill expression:** [How can a novice use it vs how an expert gets more from it?]

## 3. Rules

> Precise, ordered, testable statements. Use "When X, then Y" and avoid ambiguous words ("quickly", "some"). Number the rules for reference in tests and bugs.

1. **Activation:** [Trigger condition and input.]
2. **Preconditions:** [What must be true to start, e.g., stamina >= cost, not stunned.]
3. **Effect:** [What happens; with durations and magnitudes referencing the variables table.]
4. **Cost:** [Resources consumed and when (on start / over time / on hit).]
5. **Cooldown / limits:** [Cooldown, charges, global limits.]
6. **Interrupts and cancels:** [What stops it; what it can be canceled into.]
7. **Targeting / area / range:** [Shape, size, line-of-sight rules.]
8. **End conditions:** [Expiry, success, failure.]
9. **Interaction with other systems:** [Stacking rules, priority, counters.]
10. **Multiplayer rules (if any):** [Authority, prediction, rollback expectations.]

**Pseudocode (optional):**
```
on input(DASH):
  if state in {Idle, Run} and stamina >= DASH_COST and cooldown == 0:
      stamina -= DASH_COST
      start_dash(direction, DASH_DISTANCE, DASH_TIME)
      grant_invulnerability(IFRAME_START, IFRAME_END)
```

## 4. Variables and Tuning Table

> Every number the designer may tune, with default, safe range, unit, and effect when raised/lowered. Put these in data (config/ScriptableObject/JSON), not code. Note which variables are player-facing (visible stats) vs hidden.

| Variable | Description | Default | Min | Max | Unit | If increased | If decreased | Tunable at runtime? |
|---|---|---|---|---|---|---|---|---|
| `DASH_DISTANCE` | Distance traveled | 4.0 | 2.0 | 8.0 | m | More escape, less precision | Weaker escape | Yes |
| `DASH_TIME` | Duration | 0.18 | 0.10 | 0.30 | s | Floaty, more committal | Snappier, harder to read | Yes |
| `DASH_COST` | Stamina cost | 25 | 10 | 50 | stamina | Fewer dashes | Spammable | Yes |
| `DASH_COOLDOWN` | Lockout after dash | 0.4 | 0.0 | 2.0 | s | Slower rhythm | Spam risk | Yes |
| `IFRAME_START/END` | Invulnerability window | 0.02 / 0.14 | - | - | s | Easier | Harder, more skill | Yes |

(The above rows are an illustrative example; replace them.)

- **Derived values and formulas:** [e.g., effective DPS = damage x hits per second; time-to-kill = health / DPS.]
- **Tuning priorities (what to adjust first):** [ ]
- **Balance targets:** [e.g., "A fully charged shot should kill a basic enemy in 2 hits at default."]
- **Scaling with progression:** [how values change with upgrades/levels]

## 5. States and Edge Cases

> Draw the state machine (table or diagram). List every awkward situation and the intended result. Most bugs and exploits live here.

**State table:**

| State | Entered by | Exits to | On exit conditions | Notes |
|---|---|---|---|---|
| Idle | [ ] | [ ] | [ ] | [ ] |
| Active | [ ] | [ ] | [ ] | [ ] |
| Cooldown | [ ] | [ ] | [ ] | [ ] |
| Disabled | [ ] | [ ] | [ ] | [ ] |

**Edge cases checklist (decide each; record the answer):**

- [ ] Used at 0 resource / exactly the cost
- [ ] Used while stunned / knocked back / dead / in a cutscene / in a menu
- [ ] Used against walls, ledges, moving platforms, or hazards
- [ ] Interrupted mid-action by damage, state change, or level transition
- [ ] Two inputs on the same frame; input buffering and priority
- [ ] Spam, hold, and release timing
- [ ] Stacking with buffs/debuffs; multiple copies; duplicate pickups
- [ ] Save/load while active; checkpoint behavior
- [ ] Pause, alt-tab, controller disconnect
- [ ] Network lag, desync, host migration (multiplayer)
- [ ] Extreme values (min/max of every variable)
- [ ] AI interactions: can enemies use or counter it fairly?
- [ ] Exploit paths: sequence breaking, infinite loops, duplication
- [ ] Accessibility alternatives (hold vs toggle, assist mode)

## 6. UI and Feedback

> What the player sees, hears, and feels at each stage. Every action needs anticipation, execution, and result feedback proportional to importance. Also state the reading-at-a-glance requirement.

| Moment | Visual | Audio | Haptics | UI / HUD | Camera |
|---|---|---|---|---|---|
| Input accepted | [ ] | [ ] | [ ] | [ ] | [ ] |
| Active | [ ] | [ ] | [ ] | [ ] | [ ] |
| Success / hit | [ ] | [ ] | [ ] | [ ] | [hit-stop ___ ms (sparingly)] |
| Failure / blocked | [ ] | [ ] | [ ] | [error message] | [ ] |
| Cooldown / ready | [ ] | [ ] | [ ] | [ ] | [ ] |

- **Input-to-feedback latency target:** [under ~100 ms]
- **Telegraphing for enemies/hazards using this feature:** [ ]
- **Text strings and localization keys:** [ ]
- **Tooltips and tutorial hooks:** [where and how it is taught]
- **Accessibility:** [non-color cues, caption for sounds, reduced-motion option]

## 7. Dependencies

> What this needs and what needs this. Surface cross-team blockers.

| Dependency | Type (system/art/audio/tech/content) | Direction (needs / needed by) | Owner | Status / risk |
|---|---|---|---|---|
| [Stamina system] | System | Needs | [ ] | [Exists] |
| [Dash animation set] | Art | Needs | [ ] | [Not started] |
| [Level 3 gaps] | Content | Needed by | [ ] | [ ] |

- **Engineering notes (feasibility, perf cost, tooling needed):** [ ]
- **Order of implementation / milestones:** [ ]
- **Fallback if dependencies slip:** [minimum viable version]

## 8. Telemetry

> What to log to evaluate the success signal and diagnose problems. Define events with properties; keep names consistent with the tracking plan (`references/12-playtesting-and-analytics.md`).

| Event | Trigger | Properties | Question answered |
|---|---|---|---|
| `dash_used` | On dash start | `player_id`, `session_id`, `level_id`, `position`, `stamina_before`, `context` (combat / traversal) | How often and where is it used? |
| `dash_blocked` | Input rejected | `reason` (cooldown / stamina / state) | Are rules unclear or too strict? |
| `damage_avoided_by_dash` | Hit would have landed during i-frames | `enemy_type`, `attack_id` | Is it effective? |

- **KPIs / thresholds:** [e.g., usage per minute in combat; % of players who use it in first 5 minutes; deaths within 1 s after dash]
- **Dashboards or queries:** [link]

## 9. Acceptance Criteria

> Pass/fail statements. Use Given/When/Then or checklists. Cover function, feel, performance, and platform. A feature is "done" only when all are met.

**Functional:**
- [ ] Given stamina >= `DASH_COST` and state Idle/Run, when the player presses Dash, then the player moves `DASH_DISTANCE` in `DASH_TIME` and stamina decreases by `DASH_COST`.
- [ ] Given cooldown > 0, when Dash is pressed, then nothing happens and `dash_blocked` is logged.
- [ ] [Add per rule and per edge case]

**Feel / experience:**
- [ ] Input-to-motion latency is within target on all supported platforms.
- [ ] In playtest, at least [N of M] testers can describe what the feature does without help.
- [ ] No more than [X]% of testers report it as "confusing" or "unfair".

**Technical:**
- [ ] No frame-time regression above [x] ms; memory within budget.
- [ ] Works with save/load, pause, and disconnect.
- [ ] Telemetry events fire with correct properties (verified in a test build).

**Accessibility:**
- [ ] Alternatives implemented and verified (remap, toggle, caption).

## 10. Test Plan

> How QA and design will verify. Include both functional tests and playtest questions.

- **Functional test cases:** [Table or checklist mapped to rules and edge cases; include IDs.]
- **Automated tests:** [Unit tests for formulas; simulation of values; soak tests]
- **Balance test method:** [Spreadsheet/sim run, bot matches, sample sizes; see `references/04-balance-and-economy.md`]
- **Playtest questions (see `templates/playtest-plan.md`):**
  1. [Do players discover it without prompting? When?]
  2. [Do they understand its limits?]
  3. [Does it create interesting decisions or one dominant tactic?]
  4. [What failure states frustrate?]
- **Metrics to review after first external test:** [ ]
- **Rollback / feature flag plan:** [ ]

## 11. Open Questions

| # | Question | Owner | Decide by | Resolution |
|---|---|---|---|---|
| 1 | [ ] | [ ] | [ ] | [ ] |

## 12. Change Log

| Date | Version | Change | Reason | Author |
|---|---|---|---|---|
| [YYYY-MM-DD] | 0.1 | Initial draft | - | [ ] |

## 13. Further Reading

- `references/03-core-loops-and-mechanics.md` (mechanics, game feel)
- `references/04-balance-and-economy.md` (tuning, cost curves)
- `references/12-playtesting-and-analytics.md` (telemetry and testing)
- `templates/gdd-template.md`, `templates/playtest-plan.md`
