# Game Design Document: [Game Title]

> A lean, living GDD. Write what the team needs to build and decide, not everything you can imagine. Prefer short sections, tables, diagrams, and links to feature specs (`templates/feature-spec.md`) and level docs (`templates/level-design-doc.md`) over long prose. Mark each section with a status: `Draft | Reviewed | Locked`. Delete guidance lines (starting with `>`) and any section that does not apply, noting "N/A" so readers know it was considered.

| Field | Value |
|---|---|
| Version | [0.1] |
| Last updated | [YYYY-MM-DD] |
| Owner | [Lead designer] |
| Contributors | [names] |
| Source of truth for | [design intent; implementation lives in code/spec links] |

## Table of Contents

1. [Overview](#1-overview)
2. [Design Pillars](#2-design-pillars)
3. [Core Loop](#3-core-loop)
4. [Mechanics](#4-mechanics)
5. [Systems](#5-systems)
6. [Controls and Input](#6-controls-and-input)
7. [Progression and Difficulty](#7-progression-and-difficulty)
8. [Economy](#8-economy)
9. [Content Plan](#9-content-plan)
10. [Levels and World](#10-levels-and-world)
11. [Narrative](#11-narrative)
12. [Art and Audio Direction](#12-art-and-audio-direction)
13. [UI and UX](#13-ui-and-ux)
14. [Accessibility](#14-accessibility)
15. [Multiplayer and Social](#15-multiplayer-and-social)
16. [Monetization and Live Operations](#16-monetization-and-live-operations)
17. [Technical Constraints](#17-technical-constraints)
18. [Analytics and Playtesting](#18-analytics-and-playtesting)
19. [Milestones and Scope](#19-milestones-and-scope)
20. [Risks](#20-risks)
21. [Open Questions](#21-open-questions)
22. [Changelog](#22-changelog)
23. [Further Reading](#23-further-reading)

---

## 1. Overview

> The 1-page summary. Anyone should understand the game after reading this section. Link the one-page concept.

- **Title / working title:** [ ]
- **Genre, perspective, platform(s):** [ ]
- **Hook / logline:** [ ]
- **Player fantasy:** [I am a ___ who ___.]
- **Target audience:** [ ]
- **Session length and total playtime:** [ ]
- **Comparable titles and differentiation:** [ ]
- **Business model:** [ ]
- **One-page concept:** [link]

## 2. Design Pillars

> 3-5 pillars with "means / does not mean" so they resolve disputes. Every feature in this document should trace to at least one pillar; cut what does not.

| # | Pillar | Means | Does not mean | Features that serve it |
|---|---|---|---|---|
| 1 | [ ] | [ ] | [ ] | [ ] |
| 2 | [ ] | [ ] | [ ] | [ ] |
| 3 | [ ] | [ ] | [ ] | [ ] |

**Target aesthetics (MDA):** [e.g., Challenge, Discovery, Expression] -> **Dynamics we want:** [e.g., risk-taking, improvisation] -> **Mechanics that produce them:** see Section 4.

## 3. Core Loop

> Verbs, loops at three time scales, and the main tension. Include a diagram (ASCII or linked image).

**Moment-to-moment loop (seconds):** `[Action] -> [Feedback] -> [Reward] -> [New state/goal]`

**Session loop (minutes):** [ ]

**Long-term loop (days/weeks):** [ ]

| Verb | Input | Purpose | Cost / risk | Feedback |
|---|---|---|---|---|
| [e.g., Dash] | [Shift] | [Evade, reposition] | [Stamina 20] | [Trail VFX, whoosh, 100 ms hit-stop on collision] |

- **Primary tension:** [ ]
- **Meaningful choices at the core:** [ ]
- **Fail state, retry time, and cost of failure:** [ ]
- **Win condition / end state:** [ ]

## 4. Mechanics

> One subsection per mechanic. State rules precisely (what, when, how much). For anything non-trivial, create a feature spec and link it here. Include edge cases.

### 4.1 [Mechanic name]

- **Purpose (pillar served):** [ ]
- **Rules:** [ ]
- **Key variables (defaults):** [ ] (full table in the feature spec)
- **Interactions with other mechanics:** [ ]
- **Edge cases:** [ ]
- **Spec link:** [ ]

### 4.2 [Mechanic name]

[Repeat.]

## 5. Systems

> Rules that govern many objects (combat, AI, crafting, physics, procedural generation, status effects, saves). Describe inputs, outputs, state, and feedback loops (positive/negative).

| System | Purpose | Inputs | Outputs | Feedback loops | Owner | Spec |
|---|---|---|---|---|---|---|
| [Combat] | [ ] | [ ] | [ ] | [ ] | [ ] | [link] |
| [AI] | [ ] | [ ] | [ ] | [ ] | [ ] | [link] |

- **System interactions diagram:** [link or ASCII]
- **Emergence we want / expect:** [ ]
- **Exploit and degenerate-strategy watchlist:** [ ]

## 6. Controls and Input

> Per platform and input method. Include a full input map, responsiveness targets, and remapping support.

| Action | Keyboard/Mouse | Gamepad | Touch | Notes |
|---|---|---|---|---|
| [Move] | [WASD] | [Left stick] | [Virtual stick] | [ ] |
| [Interact] | [E] | [A / Cross] | [Tap] | [ ] |

- **Responsiveness targets:** [input-to-visible-response under ~100 ms; coyote time ___ ms; input buffer ___ ms]
- **Aim assist / camera rules:** [ ]
- **Remapping, hold vs toggle, one-handed options:** [ ]
- **Context sensitivity and conflicts:** [ ]

## 7. Progression and Difficulty

> What changes over time: player power, knowledge, content access. Include the onboarding sequence and difficulty curve.

- **Progression types:** [skill / character power / unlock / narrative / mastery]
- **Progression structure:** [linear, hub, open, run-based with meta progression]
- **Onboarding sequence:** introduce -> practice safely -> test under light pressure -> combine -> twist. List each mechanic and the moment/level that teaches it.

| Order | Mechanic / concept | Taught in | Safe practice | First test | Combined with |
|---|---|---|---|---|---|
| 1 | [ ] | [Level 1] | [ ] | [ ] | [ ] |

- **Difficulty curve:** [sawtooth description; link to chart]
- **Difficulty options / assist modes / DDA:** [ ]
- **Reward schedule:** [what is given, how often, variable vs fixed]
- **XP / level curve (formula and table):** [ ]
- **Estimated playtime per stage:** [ ]

## 8. Economy

> Resources, faucets (sources), sinks, conversion rates, and caps. Provide target rates per hour and a plan to detect inflation.

| Resource | Type (soft/hard/time/energy/item) | Faucets | Sinks | Cap | Target net per hour |
|---|---|---|---|---|---|
| [Gold] | [Soft] | [Enemy drops, quests] | [Repairs, upgrades] | [None] | [+0 to +50 in mid-game] |

- **Pricing / cost curve:** [formula or table; link to spreadsheet]
- **Drop tables and odds:** [ ]
- **Trading / player markets (if any):** [ ]
- **Balance tools:** [`python scripts/design_calc.py` or spreadsheet link]
- **Economy health metrics:** [balance distribution, source/sink ratio, inflation per day]

## 9. Content Plan

> Inventory of content, per category with counts, production cost, and priority. Content is where scope explodes; plan it explicitly.

| Category | Count (MVP / Target / Stretch) | Cost per unit | Template or pipeline | Priority |
|---|---|---|---|---|
| Enemies | [8 / 20 / 30] | [3 days] | [Behavior template] | High |
| Items | [ ] | [ ] | [ ] | [ ] |
| Levels | [ ] | [ ] | [ ] | [ ] |
| Quests / missions | [ ] | [ ] | [ ] | [ ] |

- **Reuse strategy (kits, modular assets, procedural generation):** [ ]
- **Cut list in order:** [ ]

## 10. Levels and World

> Structure of the world, regions, level types, and how they connect. Each level gets its own doc.

- **World structure and map:** [ ]
- **Level list:** [Name - purpose - mechanics introduced - est. length - doc link]
- **Level design rules (metrics):** [jump distance, cover spacing, corridor width, sightline length]
- **Wayfinding approach:** [landmarks, lighting, color, audio]
- **Procedural generation rules (if any):** [seed, constraints, validators]

## 11. Narrative

> Story premise, structure, characters, and how story is delivered through play. Keep it proportional to its role in the game.

- **Premise and themes:** [ ]
- **Structure:** [beats, acts, branches]
- **Characters:** [name - role - arc - voice notes]
- **Delivery methods:** [cutscene, dialogue, environmental, audio logs, systemic]
- **Player agency in narrative:** [choices and consequences]
- **Ludonarrative alignment check:** [do verbs and theme agree?]
- **Localization considerations:** [word counts, text expansion, cultural review]

## 12. Art and Audio Direction

> Pillars of the look and sound, with references. Detail belongs in separate art/audio bibles.

- **Visual style and references:** [moodboard link]
- **Color language and readability rules:** [what must be readable at a glance; friend/foe coding]
- **Camera and framing:** [ ]
- **Animation style and feel priorities:** [anticipation, impact frames]
- **VFX principles:** [clarity before spectacle]
- **Music direction:** [adaptive layers, tempo ties to intensity]
- **SFX and feedback sound rules:** [every key action has a distinct sound]
- **Voice:** [language, VO scope]
- **Technical budgets:** [poly count, texture size, audio memory]

## 13. UI and UX

> Information architecture, HUD, menus, onboarding prompts. Define what the player must always be able to see.

- **HUD elements and priority:** [always / contextual / on request]
- **Menu flow diagram:** [link]
- **Feedback rules (hit, damage, reward, error):** [ ]
- **Tutorial and hint system:** [ ]
- **Text size, contrast, scaling:** [ ]
- **Platform specifics:** [TV safe area, touch target size, cursor vs focus navigation]

## 14. Accessibility

> Decide early; retrofitting is expensive. Check against the Game Accessibility Guidelines and platform requirements (see `references/08-player-psychology-ux-accessibility.md`).

| Area | Commitment | Priority |
|---|---|---|
| Motor | [Remappable controls, hold/toggle options, no QTE-only progress] | [Must] |
| Visual | [Colorblind-safe palette, scalable text, high contrast mode] | [Must] |
| Auditory | [Subtitles with speaker names, visual cues for key audio] | [Must] |
| Cognitive | [Objective reminders, adjustable pace, skip puzzle option] | [Should] |
| Difficulty | [Granular assists] | [Should] |
| Photosensitivity | [Flash/shake reduction toggles] | [Must] |

## 15. Multiplayer and Social

> Skip if single-player. Otherwise: mode list, match structure, matchmaking, netcode model, anti-cheat, anti-toxicity, social features.

- **Modes and player counts:** [ ]
- **Match structure and win conditions:** [ ]
- **Matchmaking and ranking:** [ ]
- **Netcode model and latency targets:** [ ]
- **Communication tools and moderation:** [ ]
- **Anti-cheat / fairness approach:** [ ]

## 16. Monetization and Live Operations

> State the model and the player-respecting guardrails. See `references/09-monetization-and-live-ops.md`.

- **Model:** [premium / F2P / subscription / DLC]
- **What is sold and what never is (e.g., no pay-to-win):** [ ]
- **Pricing and regional pricing:** [ ]
- **Live-ops cadence (events, seasons, patches):** [ ]
- **Ethics guardrails:** [no deceptive dark patterns; spending limits; loot-box odds disclosure; age-appropriate design]
- **Regulatory notes:** [ratings, odds disclosure, children's privacy]

## 17. Technical Constraints

> Constraints design must respect. Feasibility notes agreed with engineering.

- **Engine and version:** [ ]
- **Target hardware and performance budget:** [fps, memory, load times, build size]
- **Platform requirements:** [certification, achievements, cloud saves]
- **Networking:** [ ]
- **Save system and data migration:** [ ]
- **Tools and pipeline:** [ ]
- **Known technical risks:** [ ]

## 18. Analytics and Playtesting

> What you will measure and when you will test. See `references/12-playtesting-and-analytics.md` and `templates/playtest-plan.md`.

- **Design questions to answer with data:** [ ]
- **Core events (tracking plan link):** [`level_started`, `level_failed` (position, cause), `currency_earned/spent` (source/sink)]
- **KPIs and targets:** [tutorial completion >= __%; D1/D7 retention; average session length; fail rate per level range]
- **Playtest schedule:** [per milestone; internal weekly; external monthly]
- **Success criteria for the vertical slice:** [ ]

## 19. Milestones and Scope

> Dated, outcome-based milestones with explicit exit criteria. Scope in tiers.

| Milestone | Date | Exit criteria (testable) | Scope included | Playtest |
|---|---|---|---|---|
| First playable | [ ] | [Core loop fun in grey-box for 5 of 6 testers] | [One room] | [Internal] |
| Vertical slice | [ ] | [One level at ship quality] | [ ] | [External] |
| Alpha | [ ] | [Feature complete] | [ ] | [Closed] |
| Beta | [ ] | [Content complete] | [ ] | [Open/closed] |
| Release | [ ] | [Zero P1 bugs] | [ ] | [ ] |

- **Scope tiers:** Must / Should / Could / Won't (this release).

## 20. Risks

| Risk | Likelihood | Impact | Mitigation / prototype | Owner |
|---|---|---|---|---|
| [ ] | [L/M/H] | [L/M/H] | [ ] | [ ] |

## 21. Open Questions

> Keep a running list with owner and decision date. Move resolved items into the Changelog with the decision and rationale.

| # | Question | Owner | Decide by | Status |
|---|---|---|---|---|
| 1 | [ ] | [ ] | [ ] | Open |

## 22. Changelog

> Record every substantive design change: what changed and why. Keep the "why"; teams forget it.

| Date | Version | Section(s) | Change | Reason | Author |
|---|---|---|---|---|---|
| [YYYY-MM-DD] | 0.1 | All | Initial draft | - | [ ] |

## 23. Further Reading

- `references/01-design-process.md` (pillars, prototyping, documentation approaches)
- `references/03-core-loops-and-mechanics.md`, `references/04-balance-and-economy.md`
- `references/05-progression-difficulty-onboarding.md`, `references/06-level-design.md`
- `references/07-narrative-design.md`, `references/08-player-psychology-ux-accessibility.md`
- `references/09-monetization-and-live-ops.md`, `references/10-multiplayer-and-social.md`
- `references/12-playtesting-and-analytics.md`
- Companions: `templates/one-page-concept.md`, `templates/feature-spec.md`, `templates/level-design-doc.md`, `templates/playtest-plan.md`
