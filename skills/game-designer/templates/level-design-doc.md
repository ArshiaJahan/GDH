# Level Design Document: [Level Name / ID]

> One document per level, mission, map, or encounter set. Design the level around a purpose and a small set of mechanics, then plan the pacing, layout, and tests. Delete guidance lines (starting with `>`) when filling in.

| Field | Value |
|---|---|
| Level ID / name | [L03 - The Drowned Archive] |
| Designer / reviewer | [names] |
| Status | [Concept / Blockout / Gameplay-complete / Art pass / Locked] |
| Position in game | [Act 1, level 3 of 8; follows L02, leads to L04] |
| Estimated playtime | [first-time: 20-25 min; speedrun: 8 min] (heuristic until tested) |
| Version / date | [v0.1 / YYYY-MM-DD] |

## Table of Contents

1. [Purpose](#1-purpose)
2. [Mechanics Introduced and Tested](#2-mechanics-introduced-and-tested)
3. [Beat Chart and Intensity Graph](#3-beat-chart-and-intensity-graph)
4. [Layout and Sketch Notes](#4-layout-and-sketch-notes)
5. [Critical Path](#5-critical-path)
6. [Optional Content](#6-optional-content)
7. [Encounters](#7-encounters)
8. [Metrics](#8-metrics)
9. [Wayfinding Plan](#9-wayfinding-plan)
10. [Narrative Beats](#10-narrative-beats)
11. [Assets and Dependencies](#11-assets-and-dependencies)
12. [Playtest Goals and Metrics](#12-playtest-goals-and-metrics)
13. [Production Checklist](#13-production-checklist)
14. [Open Questions and Change Log](#14-open-questions-and-change-log)
15. [Further Reading](#15-further-reading)

---

## 1. Purpose

> Why does this level exist? Answer in one sentence each. If you cannot, the level may not be needed.

- **Role in the game:** [teaches X / tests Y / pacing relief / set piece / boss / hub]
- **Player experience goal:** [the emotional arc, e.g., "dread to relief to triumph"]
- **Pillars served:** [ ]
- **What the player should know/have when they leave:** [new skill, item, story fact, route]
- **What the player should remember (signature moment):** [ ]
- **Theme and setting:** [location, mood, time of day, weather]

## 2. Mechanics Introduced and Tested

> Use the teaching sequence: introduce in safety -> practice -> test under light pressure -> combine -> twist. Record where each happens in the level.

| Mechanic | Role in this level (new / reinforced / combined / twisted) | Where it is taught | Safe practice space | First test | Combined with |
|---|---|---|---|---|---|
| [Grapple hook] | New | [Room 2] | [Low gap, no hazard below] | [Room 3 gap with spikes] | [Wall run in Room 6] |
| [Wall run] | Reinforced | - | - | [ ] | [ ] |

- **Rule for this level:** introduce at most [1-2] new concepts; everything else must be familiar.
- **Fail-safe teaching:** [how failure stays cheap early on]
- **Skill gating:** [knowledge or skill gates vs item gates]

## 3. Beat Chart and Intensity Graph

> The level as a sequence of beats with intended intensity (0 = calm, 10 = peak). Aim for a sawtooth: rising tension, peak, release, repeat at a slightly higher baseline. Place rest points after peaks.

| # | Beat | Type (explore / puzzle / combat / traversal / story / rest / set piece) | Intensity (0-10) | Duration (min) | Mechanics used | Emotion |
|---|---|---|---|---|---|---|
| 1 | [Arrival] | Explore | 2 | 2 | Move, look | Curiosity |
| 2 | [Locked gate puzzle] | Puzzle | 4 | 3 | Grapple (intro) | Discovery |
| 3 | [Ambush in hall] | Combat | 7 | 3 | Combat, cover | Tension |
| 4 | [Safe room] | Rest | 1 | 2 | Save, upgrade | Relief |
| 5 | [Collapse chase] | Set piece | 9 | 2 | Run, jump | Panic |

**Intensity graph (ASCII, replace with your own):**
```
10 |                                   *
 8 |                    *             / \
 6 |                   / \           /   \
 4 |        *         /   \     *   /     \
 2 |   *   / \       /     \   / \ /       \
 0 |__/___/___\_____/_______\_/___V_________\___
     1    2    3    4    5    6    7    8   (beats)
```

- **Pacing rules:** [no more than ___ minutes of one beat type; rest after every peak; variety in verbs]
- **Difficulty curve inside the level:** [starts at ___, peaks at ___, ends at ___ relative to previous level]

## 4. Layout and Sketch Notes

> Describe the spatial structure. Attach top-down sketches or graph diagrams. Define shape language, landmarks, and flow. Think in rooms/areas, connections, loops, and verticality.

- **Topology:** [linear / hub-and-spoke / loop with shortcuts / open / nonlinear "Metroidvania" graph]
- **Area list and flow (node graph):**
  ```
  [Start] -> [Atrium] -> [Library] -> [Flooded Stacks] -> [Vault Door] -> [Exit]
                \-> [Side Study] (optional) -> shortcut back to Atrium
  ```
- **Loops and shortcuts:** [where the player returns to a familiar space, unlocking a shortcut]
- **Verticality and sightlines:** [high points for scouting; reveals of the next goal]
- **Chokepoints and arenas:** [locations, sizes, entry/exit]
- **Safe spaces:** [save points, no-combat zones]
- **Sketches / blockout links:** [image or file links]
- **Shape language and visual identity:** [what each area looks like and why]
- **Reuse of previous spaces:** [revisits and changes]

## 5. Critical Path

> The shortest sequence required to finish. Verify that it is always readable and never blocked by optional content.

| Step | Location | Objective | Gate / lock (skill, item, story, combat) | How the player learns it | Fail/stuck fallback |
|---|---|---|---|---|---|
| 1 | [Atrium] | [Find the library] | None | [Lit doorway] | [NPC hint after 3 min] |
| 2 | [Library] | [Get Archive Key] | [Puzzle] | [Visual clue on key altar] | [Contextual hint] |
| 3 | [Vault Door] | [Open] | [Archive Key] | [Door glows when key held] | [ ] |

- **Alternate routes on the critical path:** [ ]
- **Softlock prevention:** [what ensures the player can never become stuck; respawn of key items; one-way doors have a warning]
- **Checkpoints and save rules:** [positions; max progress lost on death: ~___ min]
- **Estimated time to complete critical path:** [ ]

## 6. Optional Content

> Side paths, secrets, collectibles, and challenge rooms. Each should reward curiosity and be consistent with pillars.

| Item | Location | Discovery cue | Reward | Risk/cost | Intended finder (everyone / explorers / experts) |
|---|---|---|---|---|---|
| [Hidden study] | [Library, behind cracked wall] | [Faint draft sound, cracked texture] | [Lore + upgrade] | [Mini-puzzle] | Explorers |

- **Reward value vs effort:** [rewards scale with difficulty/distance]
- **Optional content share of playtime:** [about ___%]
- **Missable content policy:** [never missable / missable with warning]
- **Mastery/challenge content:** [expert routes, time trials]

## 7. Encounters

> One row per combat, puzzle, or hazard encounter. Specify enemy composition, arena, intended tactics, and difficulty. Teach counterplay before testing it.

| ID | Location | Type | Composition / elements | Arena features (cover, height, hazards) | Intended tactics | Difficulty (relative 1-5) | Telegraph / counter taught? | Reward |
|---|---|---|---|---|---|---|---|---|
| E1 | [Hall] | Ambush | [3 melee, 1 ranged] | [Pillars, balcony] | [Use pillars to split melee] | 3 | [Yes - L02 ranged intro] | [Ammo drop] |
| P1 | [Library] | Puzzle | [3 rotating shelves] | - | [Align shelf symbols] | 2 | [Shown in L01] | [Key] |

- **Encounter pacing:** [intervals; recovery resources between fights]
- **Resource budget (health/ammo/consumables available vs expected spend):** [ ]
- **Spawn and trigger logic:** [ ]
- **AI behavior notes:** [aggro range, flank rules, retreat]
- **Failure modes to prevent:** [cheap damage, off-screen attackers, unavoidable hits]

## 8. Metrics

> Dimensions and numbers that make the level playable with the character. Maintain them in a shared metrics sheet and update when the character changes.

| Metric | Value | Source / note |
|---|---|---|
| Player height / radius | [1.8 m / 0.4 m] | [Character spec] |
| Walk / run speed | [3 / 6 m/s] | [ ] |
| Max jump height / distance | [1.2 m / 4 m] | [Use ~60-75% of max jump for comfortable traversal jumps, ~85-95% only for deliberate challenge jumps (heuristic)] |
| Minimum corridor width | [2.0 m] | [Allows camera + strafing] |
| Door width / height | [1.5 m / 2.5 m] | [ ] |
| Cover height (low / high) | [1.0 / 2.0 m] | [ ] |
| Typical combat distance | [8-15 m] | [Weapon ranges] |
| Sightline length (max in arenas) | [30 m] | [Performance and fairness] |
| Time between checkpoints | [3-5 min] | [ ] |
| Distance landmark-to-landmark | [<= 40 m] | [Wayfinding] |

- **Grid/unit system:** [1 unit = 1 m; modular kit size 4 m]
- **Collision and traversal rules:** [what is climbable/vaultable and how it is signposted]

## 9. Wayfinding Plan

> How players know where to go without UI. Layer several cues; test with fresh players.

- **Primary goal visibility:** [landmark visible from start / revealed progressively]
- **Landmarks:** [unique silhouettes at each junction]
- **Lighting:** [brighter = goal path; warm light on interactables]
- **Color and material language:** [climbable = yellow trim; hazard = red glow]
- **Leading lines and architecture:** [corridors converge, floors/arrows/cracks guide]
- **Audio cues:** [goal emits sound; NPC calls]
- **Environmental storytelling signs:** [damage trail leading forward]
- **Compass/map/objective UI (if any):** [rules; when it appears]
- **Anti-lost systems:** [timed hints, NPC guidance, pathing aid, accessibility toggle for objective marker]
- **Known confusion points to watch in playtests:** [junction at Room 4; vertical shaft]

## 10. Narrative Beats

> What story, lore, or character moments occur and where. Prefer environmental and in-play delivery. Respect pacing: avoid placing exposition at intensity peaks.

| Beat | Location | Delivery (VO / environment / cutscene / item / NPC) | Info revealed | Player agency | Skippable? |
|---|---|---|---|---|---|
| [Opening: flooded archive] | [Atrium] | [Environment + radio] | [Why the archive sank] | [None] | [N/A] |

- **Story purpose of the level:** [ ]
- **Character appearances / dialogue count:** [ ]
- **Choices and consequences:** [ ]
- **Lore collectibles:** [count; where; is anything essential hidden?]

## 11. Assets and Dependencies

> What art, audio, tech, and scripting this level needs. Reuse where possible; flag new items early.

| Category | Asset / requirement | New / reuse | Owner | Status |
|---|---|---|---|---|
| Environment kit | [Flooded library modules] | New | [ ] | [ ] |
| Props | [Rotating shelf] | New | [ ] | [ ] |
| Enemies | [Husk, Archer] | Reuse | [ ] | [ ] |
| VFX | [Water caustics, dust] | New | [ ] | [ ] |
| Audio | [Ambience loop, ambush stinger] | New | [ ] | [ ] |
| Scripting / triggers | [Collapse sequence] | New | [ ] | [ ] |
| Lighting / baking | [ ] | - | [ ] | [ ] |

- **Performance budget (draw calls, entities, memory, streaming zones):** [ ]
- **Loading and streaming plan:** [ ]
- **Localization:** [ ]

## 12. Playtest Goals and Metrics

> Define before the first test what you need to learn. Use `templates/playtest-plan.md` for session scripts and surveys.

**Research questions:**
1. [Do players find the library without help within ___ minutes?]
2. [Do they understand the grapple after first gap, without text?]
3. [Is the ambush perceived as fair? Deaths/attempt?]
4. [Where do players get lost or stop?]

**Targets (adjust after the first tests; these are heuristics):**

| Metric | Target | Measured |
|---|---|---|
| Critical-path completion (first-time players) | [>= 85%] | [ ] |
| Median time to complete | [20-25 min] | [ ] |
| Deaths per encounter (median) | [E1: 1-3] | [ ] |
| Players needing a hint/assist | [<= 15%] | [ ] |
| Optional area discovery | [about 50% find the study] | [ ] |
| Subjective: "I always knew where to go" (1-5) | [>= 4.0] | [ ] |
| Subjective: "The level felt fair" (1-5) | [>= 4.0] | [ ] |

**Telemetry to implement:** `level_started`, `checkpoint_reached`, `player_died` (position, cause, encounter id), `hint_shown`, `level_completed` (time), `secret_found`. Plot a death heatmap and path heatmap after each round.

**Observation checklist:** hesitations at junctions; backtracking; attempts to use mechanics in untaught ways; sequence breaks; fatigue or boredom points; camera problems.

## 13. Production Checklist

- [ ] Purpose, beats, and metrics approved
- [ ] Blockout built with placeholder encounters
- [ ] Critical path playable end-to-end by a fresh tester
- [ ] Teaching sequence verified without text
- [ ] Encounters tuned; resource budget checked
- [ ] Optional content and rewards placed
- [ ] Wayfinding pass (lighting and landmarks) done
- [ ] Narrative and audio hooks in place
- [ ] Softlock and sequence-break pass
- [ ] Performance and memory pass
- [ ] Accessibility pass (colorblind readability, subtitles, assists)
- [ ] Playtest rounds completed; P1/P2 issues closed
- [ ] Final art/lighting pass and re-test
- [ ] Locked

## 14. Open Questions and Change Log

| # | Question | Owner | Decide by | Resolution |
|---|---|---|---|---|
| 1 | [ ] | [ ] | [ ] | [ ] |

| Date | Version | Change | Reason | Author |
|---|---|---|---|---|
| [YYYY-MM-DD] | 0.1 | Initial draft | - | [ ] |

## 15. Further Reading

- `references/06-level-design.md` (layout, flow, wayfinding, gating, encounters, blockouts)
- `references/05-progression-difficulty-onboarding.md` (teaching sequence, pacing)
- `references/07-narrative-design.md` (environmental storytelling)
- `references/12-playtesting-and-analytics.md` (heatmaps, funnels, observation)
- `templates/gdd-template.md`, `templates/playtest-plan.md`
