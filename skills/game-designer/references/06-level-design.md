# Level Design

## Table of Contents

1. [Goals and Mindset](#1-goals-and-mindset)
2. [The Level Design Process](#2-the-level-design-process)
3. [Metrics](#3-metrics)
4. [Flow and Pacing](#4-flow-and-pacing)
5. [Wayfinding](#5-wayfinding)
6. [Affordances and Signposting](#6-affordances-and-signposting)
7. [Gating and Progression Structures](#7-gating-and-progression-structures)
8. [Level Structures: Linear, Hub, Open, Non-Linear](#8-level-structures-linear-hub-open-non-linear)
9. [Encounter Design](#9-encounter-design)
10. [Teaching Through Levels: Kishotenketsu and the Four-Beat Pattern](#10-teaching-through-levels-kishotenketsu-and-the-four-beat-pattern)
11. [Risk, Reward, Secrets and Exploration](#11-risk-reward-secrets-and-exploration)
12. [Multiplayer Map Design](#12-multiplayer-map-design)
13. [Architecture and Space: Totten's Approach](#13-architecture-and-space-tottens-approach)
14. [Environmental Storytelling Hand-Off](#14-environmental-storytelling-hand-off)
15. [Lessons from Valve's Commentary and Playtesting Culture](#15-lessons-from-valves-commentary-and-playtesting-culture)
16. [Worked Examples](#16-worked-examples)
17. [Checklists and Common Pitfalls](#17-checklists-and-common-pitfalls)
18. [References](#18-references)

---

## 1. Goals and Mindset

A level is a **designed sequence of player decisions and emotions delivered through space**. Geometry is the delivery mechanism, not the point.

A level must do five jobs at once:

| Job | Question to ask |
|---|---|
| **Teach** | What does the player know at the end that they did not at the start? |
| **Test** | Where does the player have to use it under pressure? |
| **Pace** | What is the intensity curve, and where does the player breathe? |
| **Orient** | Does the player always know where to go and where they have been? |
| **Express** | What does the place say about the world, the fiction, the mood? |

Core stance:
- **Level design is verb design applied to space.** A level exists to exercise the player's verbs (jump, shoot, hide, trade). If the verbs are not in the space's vocabulary, the level is a museum. Start from the verbs (see `references/03-core-loops-and-mechanics.md`).
- **Each level (and each room) has one stated purpose.** Write it as a sentence: "This room teaches that grapple points can be used on moving targets." Cut anything that does not serve the sentence.
- **Design for the player's attention, not the camera's view.** Where will they look, how long will they take, what do they know and what do they believe? Level design is largely expectation management.
- **Players do not read, do not look up, and take the shortest-looking route.** Design for the lazy, hurried, curious-but-distractible player. Playtesting will confirm (see `references/12-playtesting-and-analytics.md`).
- **Spaces are only tested by players.** You will be wrong about sightlines, timings and where people walk. Iterate with observation.

## 2. The Level Design Process

A standard production pipeline (exact names vary by studio; this is industry practice, not a standard).

| Stage | Output | What you decide | Typical cost of change |
|---|---|---|---|
| **1. Brief / intent** | One paragraph + pillars for the level | Purpose, new mechanic taught, emotional arc, length target, constraints | Trivial |
| **2. Paper design** | Top-down sketch, flow diagram, beat list | Macro layout, critical path, key encounters, gating, loops | Cheap |
| **3. Blockout / greybox** | Untextured primitives, scripted placeholder gameplay | Metrics, sightlines, pacing, encounter spaces, traversal | Moderate |
| **4. Gameplay playtest passes** | Iterated greybox | Cut dead space, fix flow, tune difficulty | Moderate |
| **5. Art/lighting/audio pass** | Dressed level | Landmarks, mood, affordance readability, environmental story | Expensive |
| **6. Polish / optimization / bug** | Shippable level | Performance, collision, soft-locks, secrets verification | Expensive |

### 2.1 Paper design
- Sketch **topology before geometry**: nodes (rooms/arenas/beats) and edges (paths). Draw the critical path, then optional branches, loops and shortcuts.
- Write a **beat sheet**: numbered beats with player goal, expected time, intensity (1-10), and what is taught or tested.
- Draw the **player's knowledge state** at each beat (what they have seen, what they hold). Many gating bugs are knowledge bugs.
- Estimate time per beat and total time. Heuristic: designers underestimate first-time-player duration by 1.5-3x; measure in playtests.

### 2.2 Blockout / greybox
- Use consistent primitives and a **metrics sheet** (section 3). Never block out without agreed dimensions.
- **Make the level playable end-to-end as early as possible**, even if ugly. A playable blockout reveals pacing problems that no document can.
- Add **placeholder gameplay** (enemy spawns, triggers, pickups) before art. A blockout without encounters is only a map.
- Keep geometry **modular and cheaply changeable**. Avoid detailing anything that has not survived two playtests.
- Test on **cold players** (never seen the level). Internal designers cannot un-know the level.
- Establish **landmark placeholders** (a tall red cube) early so wayfinding is designed, not hoped for.

### 2.3 Playtest cycles
- Observe silently: where do players hesitate, backtrack, look up, die, and idle? Record paths (heatmaps or simple video review).
- Ask after, not during: "What was your goal in that room?" reveals whether signposting worked.
- Prioritize by severity: soft-locks and total lost-ness > frustrating deaths > pacing dips > polish.
- Re-test after every fix; fixes frequently create new problems.

### 2.4 Art pass hand-off
- Provide the art team with: a **readability brief** (what must be visible/readable: paths, interactables, hazards), landmark list, lighting intentions, and a **do-not-move list** (collision, sightlines, cover that gameplay depends on).
- Establish **visual language** early: what color/shape/material means "climbable", "destructible", "dangerous", "interactable". Keep it consistent across the whole game.
- Re-test after the art pass: dressing routinely hides paths, adds clutter that blocks sightlines, or lights the wrong place.

## 3. Metrics

**Metrics** are the agreed numbers that define player capability in space. All values below are **heuristic starting points** in meters assuming an engine where 1 unit is about 1 m and a human-scale character; derive your own from your game's movement.

### 3.1 Character and basic space
| Metric | Starting heuristic | Notes |
|---|---|---|
| Character height | about 1.8 m | Standing; crouch about 1.0-1.2 m |
| Character width/capsule | about 0.5-0.7 m radius x2 | Collision capsule often smaller than the visual |
| Eye height (FPS) | about 1.6-1.7 m | Drives sightline and cover calculations |
| Single door width | about 1.0-1.2 m | Wider for large characters/vehicles/co-op throughput |
| Door height | about 2.1-2.4 m | Exceed head height plus camera margin in TPS |
| Corridor width (FPS) | 3-4 m comfortable; under 2 m feels claustrophobic | Horror deliberately narrows |
| Corridor width (TPS) | 4-6 m | Camera needs room |
| Stair step | about 0.15-0.2 m rise | Use ramps/auto-step for gameplay stairs |
| Max walkable slope | about 40-45 degrees | Engine/gameplay dependent |

### 3.2 Jump math (engine-agnostic)
For a jump with initial vertical velocity v, gravity g, and horizontal speed s:
- **Height** = v^2 / (2g)
- **Airtime** = 2v / g (flat ground)
- **Horizontal distance** = s x airtime
- Always compute from your actual movement values. Then define:
  - **Max jump** (gap/height the character can just clear, with perfect input)
  - **Comfortable jump** heuristic: about 60-75% of max; use for common/critical-path gaps.
  - **Challenge jump** heuristic: about 85-95% of max; optional or late in the game.
- Account for **coyote time**, **jump buffering**, **variable jump height**, **air control** and **camera**: they widen what the player can survive. In platformers, add **landing margin** so the edge of the platform is legible.
- Document: max jump height, max gap (walk, run, dash, double-jump), wall-jump spacing, climb height (mantle height), vault height. Make these **grid-snapped** so modular kits fit.

### 3.3 Combat and cover metrics
| Metric | Heuristic | Notes |
|---|---|---|
| Low cover height | about 0.9-1.1 m | Crouch-cover; player can fire over |
| High cover height | about 1.8 m+ | Full-body; requires peek/lean |
| Cover spacing (shooters) | clusters every 4-8 m in engagement zones | Allows hop-to-hop movement under fire |
| Typical engagement range | Set per weapon class: close under 10 m, mid 10-30 m, long 30 m+ | Adjust by genre; pick ranges deliberately |
| Flanking route | About 1.3-2x the length of the direct route (heuristic) | Much longer and players ignore it; much shorter and it becomes the main path |
| Arena size | Scale to enemy count x mobility; large enough for the player to kite, small enough to read | Verify in playtests |

### 3.4 Camera and readability
- **Camera distance and FOV** change perceived scale. Test blockouts in-game camera, not in the editor free-cam.
- **Draw distance for readability**: landmarks should be readable at the distance you want players to orient from.
- **Time-to-cross** is a better design unit than meters. Define target times: "cross this room in 4-6 seconds at run speed," then derive size.
- **Unit tests for levels**: a repeatable jump-test map (every gap and height), a "can the AI reach this?" test, and a "can the player get stuck here?" test.

### 3.5 Metrics hygiene
- Publish a **metrics document and test map** to every level designer and artist. Update it when movement changes.
- When movement changes (new dash, new speed), every level's metrics are invalidated: schedule a re-validation pass.
- Use **modular kit grids** (for example, 0.5 m or 1 m snap, 2-4 m wall modules) so art and design agree.

## 4. Flow and Pacing

### 4.1 Intensity graph
Plot expected **intensity** (threat, effort, emotional load) over time. A good level looks like a **sawtooth with a rising baseline** (see `references/05-progression-difficulty-onboarding.md`), not a flat line and not a monotone ramp.

```
Intensity
 10 |                                   /\      <- climax / boss
  8 |            /\            /\    /\ /  \
  6 |     /\    /  \     /\    /  \  /  \/    \
  4 |    /  \  /    \   /  \  /    \/          \  <- release/reward
  2 |___/    \/      \_/    \/                    \___ <- cooldown
    +---------------------------------------------------> time
      intro  1st test  twist  big set-piece  climax  wrap
```

Beats usually alternate among: **exploration / traversal**, **puzzle/thinking**, **combat/pressure**, **story/spectacle**, **rest/reward**. Vary the type, not only the magnitude.

### 4.2 Pacing rules (heuristics)
- **Never run the same beat type for too long.** If a player has done three combat arenas in a row, the fourth needs something different (traversal, puzzle, spectacle).
- **After a peak, give a valley.** Recovery lets the player process, spend resources, read the story, and feel competent.
- **Escalate by changing the question, not just the numbers.** More enemies is the cheapest escalation; new enemy combos, terrain, or constraints are better.
- **Front-load the fantasy.** Show the signature verb or spectacle early so players know why they are there.
- **Resource economy is a pacing tool.** Health, ammo and checkpoint placement set tension (see `references/04-balance-and-economy.md`). Scarcity before a fight raises its intensity; replenishment after it signals the valley.
- **Checkpoints and save frequency** set how much a failure costs. Place checkpoints after the story/rest beats, before big fights, and avoid forcing replays of long non-interactive stretches.
- **Time to first fun**: in a level, the first meaningful interaction should arrive in seconds, not minutes.

### 4.3 Flow channel in space
Use the challenge-vs-skill channel (Csikszentmihalyi; see `references/02-design-frameworks.md`) at level scale: introduce a skill, test it with low cost, escalate, then demand mastery. Include **optional difficulty** (side routes, challenge rooms) so both ends of the audience stay in their channel.

### 4.4 Rhythm and tempo
- Traversal has tempo: a platformer level has a rhythm of jumps and landings; a shooter has movement-then-engagement. Keep the rhythm consistent within a segment, and break it deliberately.
- **Gating through time**: slow-down moments (elevators, doors, crawl spaces) can hide loading and give narrative beats, but overuse feels like padding.

## 5. Wayfinding

Wayfinding is how the player answers: **Where am I? Where do I need to go? How do I get there? Where have I been?** Lynch's *The Image of the City* (1960) provides the vocabulary of **paths, edges, districts, nodes, landmarks** and is a foundation for spatial legibility in games.

### 5.1 Toolkit
| Tool | How it works | Notes |
|---|---|---|
| **Landmarks / "weenies"** | A distinctive, visible-from-afar structure the player is drawn to | Walt Disney's "wienie" principle from the theme parks (the castle at the end of the street); applies to games as the visible goal (Wienie, Wikipedia) |
| **Sightlines** | Controlled long views that reveal the goal or the next area | Frame the destination early, then require the player to work out the route |
| **Leading lines** | Architecture, rails, roads, cables, rivers pointing to the goal | Converging lines draw the eye |
| **Light** | Players move toward brighter areas; dark = danger or dead end | Use light cones, windows, fires; or invert deliberately in horror |
| **Color** | Warm/saturated vs cool/desaturated contrast; consistent hue for "go here" | Do not rely on color alone (accessibility; see `references/08-player-psychology-ux-accessibility.md`) |
| **Contrast / composition** | The goal differs in value, saturation, or shape from its surroundings | Squint test: blur the screenshot and see what stands out |
| **Motion** | Moving elements (birds, flags, particles, NPCs) attract attention | Use sparingly |
| **Audio** | Sound source direction and distance guide players | Strong in horror and stealth; spatialized |
| **NPC guides** | Companion walks toward the goal and gestures | Alyx-style companions; avoid rubber-banding or blocking |
| **Breadcrumbs** | Pickups or marks along the route | Good for long linear stretches |
| **Funnels and chokepoints** | Geometry narrows to compel choices | Do not funnel so hard it reads as a corridor |
| **Map / compass / waypoint** | UI-based guidance | A fallback and an accessibility option, not a substitute for spatial design |
| **Reveal beats** | A vista, a turn, a gate opening | Reward the player for orientation |

### 5.2 Principles
1. **Show the goal, hide the path** (or the other way round) depending on how much puzzle you want. A visible goal with an unknown route creates intrigue.
2. **Create a distinct identity per district**: each area has a different silhouette, palette, and sound so the player can build a mental map.
3. **Landmarks must be visible from decision points**, not just from the end.
4. **Mark progress**: doors that stay open, shortcuts, changed lighting, collapsed bridges. Players need to know where they have been.
5. **Avoid symmetrical, repetitive spaces** in places where players must orient (unless symmetry is the puzzle, like in some horror or mazes).
6. **Vertical orientation**: players rarely look up/down. Place critical cues at the level of the camera's natural framing, or use character animation/UI to prompt looks.
7. **Backtracking orientation**: when a player returns, the landmark should be visible from the other side, or a visual cue should say "you've been here".
8. **Failure signal**: if the player is going the wrong way, the world should push back softly (dead-end clutter, darker lighting, NPC comment) before they are lost for minutes.
9. **A lost player is a design bug**, not a player failing. Measure time-between-progress in playtests.

### 5.3 Testing wayfinding
- **Think-aloud**: ask the player to state their goal every time they stop.
- **Time-to-progress**: flag segments where cold players take more than about 2x the designer's expected time (heuristic).
- **Screenshot test**: at each decision point, ask a naive observer to point to where they'd go.
- **No-HUD test**: remove waypoints and see if the level still communicates.

## 6. Affordances and Signposting

**Affordance** (Gibson; Norman): the perceived possibilities for action. In games, **signifiers** tell the player what is interactive or what an action will do.

### 6.1 Signposting toolkit
- **Consistent visual vocabulary**: a specific color, shape, texture or lighting for "climbable ledge", "breakable wall", "interactive object". Establish with a safe introduction, repeat reliably.
- **Teach by contrast**: show the climbable ledge in a safe context first.
- **Cause-and-effect previews**: show a hazard working on an NPC or on a safe object before the player is exposed.
- **Environmental telegraphing**: cracks, scorch marks, rope, ladders, handholds, bloodstains.
- **Diegetic vs non-diegetic**: diegetic cues (paint, lights, signs) preserve immersion; UI prompts are clearer. Mix by genre and audience.

### 6.2 The "yellow paint" debate
Many AAA games mark climbable edges and interactables in bright yellow or white paint, which is widely criticized as immersion-breaking and widely defended as clear and accessible.
- **For:** reduces lost players and increases accessibility; cheaper than bespoke solutions; players with low vision or low spatial literacy benefit.
- **Against:** homogenizes games; cheapens exploration; trains players to "follow the paint"; reveals that the world is constructed.
- **Practical guidance (judgment):** pick a **consistent language** and make it **configurable** (options to dim or hide). Prefer diegetic lighting, color script and composition first, add UI/paint as a layer. Do not use paint to hide a layout problem.

### 6.3 Interaction readability
- A **prompt** is a promise: when the player sees "Press X" they expect a visible result. Delay or ambiguity breaks trust.
- **Hazards must read before they hurt.** First exposure should be survivable and visible.
- **Do not reuse a visual signal for two meanings** (for example, red barrels that are explosive and also decoration).
- **Fairness rule**: if the player dies, they should be able to say "I see what I should have done."

## 7. Gating and Progression Structures

A **gate** blocks progress until a condition is met. Gating controls pacing, teaches skills, and paces rewards.

### 7.1 Gate types
| Gate | Description | Example | Pitfall |
|---|---|---|---|
| **Lock and key** | A physical or logical key (literal key, item, switch) opens a door | Zelda dungeons (small key, boss key) | Players who cannot find the key assume the game is broken |
| **Ability gate** | A capability the player acquired (double jump, grapple, bomb) is required | Metroidvanias (Metroid, Hollow Knight, Super Metroid) | Backtracking padding; ensure each new ability opens enough content |
| **Knowledge gate** | A fact or insight is the key (code, route, enemy weakness) | Outer Wilds, Fez, Return of the Obra Dinn | Needs enough hints; avoid pure guesswork |
| **Skill gate** | A difficulty test must be passed | Boss doors, platforming challenges | Allow assist options and alternatives |
| **Progress/narrative gate** | A story event unlocks the path | Chapter doors, escorts | Make it feel earned; do not leave players standing around |
| **Resource gate** | Requires currency, level, or items | Level-gated RPG zones, paywalls | Watch for grind; avoid F2P impatience gates unless ethical (see `references/09-monetization-and-live-ops.md`) |
| **Soft gate** | Strong enemies or hazard discourage but do not block | Dark Souls (a too-early area is survivable only with skill), Breath of the Wild (cold/heat zones, enemy tiers, stamina and heart requirements; its towers are map reveals, not gates) | Preserves player freedom |
| **Time/world-state gate** | Day/night, tides, schedules | Majora's Mask, Outer Wilds | Communicate clearly |

### 7.2 Lock-and-key design (Metroidvania lens)
1. **Build a dependency graph**: nodes = areas, edges = abilities/keys; check it is solvable and has no dead-end soft-locks.
2. **Show locks before keys.** The player sees the unreachable ledge, the sealed door, the red gate first; later the key recontextualizes the earlier space. This gives the player goals and makes the reward satisfying.
3. **Reuse the key repeatedly** in different contexts (teach, apply, twist; see section 10).
4. **Provide shortcuts that connect back to hubs**, turning the world into a loop network (see section 8.3).
5. **Sequence breaks**: decide which ones you allow. Intentional skill-based breaks reward mastery and enable speedrunning; unintentional ones can soft-lock.
6. **Safeguards**: guard against irreversible states (a consumed key, a closed door behind the player) with checks, return paths, or auto-saves.
7. **Map and breadcrumbs**: Metroidvanias need a good map with markable unreached spots. Many players quit when they forget where the locked door was.

### 7.3 Gating checklist
- Does the player understand why they cannot pass?
- Is it clear what category of solution applies (key, skill, knowledge)?
- Is there always at least one thing to do (no "everything is gated" dead spot)?
- Can the player reverse into a non-winnable state?
- Is the gate fair on first encounter and not repetitive on the third?

## 8. Level Structures: Linear, Hub, Open, Non-Linear

| Structure | Description | Strengths | Risks | Examples |
|---|---|---|---|---|
| **Linear (corridor)** | A single path with local variation | Tight pacing, authored spectacle, easy to balance, cheap to test | Feels on rails, low replay value | Half-Life 2, Uncharted, Call of Duty campaigns |
| **Linear with branches ("string of pearls" or "beads")** | Linear sequence of arenas, with optional side paths | Pacing control plus exploration | Branching must reward without breaking the flow | Doom 2016, Resident Evil 4 |
| **Hub and spoke** | Central hub, with levels radiating out | Player chooses order; hub persistence offers a base and a sense of progress | Hub UX friction; loading; spokes must have good entry/exit | Super Mario 64, Hades (House), Dark Souls (Firelink Shrine), Hitman |
| **Interconnected loop world** | Zones connected by shortcuts and doors that loop back | Strong mental map, sense of place, rewards exploration | Hard to author and test; sequence breaks | Dark Souls, Metroid, Hollow Knight, Resident Evil (Spencer Mansion) |
| **Open world** | Large traversable space, many points of interest (POI) | Freedom, emergent stories | Empty space, content treadmill, pacing loss, scope cost | Breath of the Wild, Elden Ring, Red Dead Redemption 2 |
| **Open-zone / semi-open** | Large zones with a guided macro-structure | Balance of freedom and pacing | Zone transitions may feel arbitrary | The Witcher 3, Horizon, Mass Effect 1 |
| **Non-linear / mission-based** | Levels are sandboxes with multiple solutions | Replayability, player expression | Content multiplies; harder to guarantee pacing | Deus Ex, Dishonored, Hitman |
| **Procedural / modular** | Levels assembled from rules or pre-made chunks | Replay value | Needs strong constraints; weaker authored pacing | Spelunky, Hades, Dead Cells, Slay the Spire map |

### 8.1 Choosing a structure
Ask: How much **authored pacing** does the experience need? How much **player agency**? What is your **content budget**? Linear structures amplify authored beats; open structures amplify discovery. Hybrid designs (linear within open, open within linear) are common.

### 8.2 Open-world design heuristics
- **Triangle rule** (heuristic from Breath of the Wild's design commentary): use hills and landmarks so that players always see a point of interest and a path to it; avoid long flat views with nothing to draw attention.
- **Density over size**: a smaller map with something interesting every 30-60 seconds of travel beats a huge empty one (heuristic).
- **Points of interest need variety** of type and reward; avoid checklist-style repeats.
- **Terrain is the pacing tool**: climb, glide, ride, swim, and fast travel must each be tuned.
- **Guide through curiosity** (visible mystery) rather than quest markers where you can.
- **Mix hand-crafted and systemic**: dynamic encounters add life, authored set pieces add memory.

### 8.3 Interconnection (Dark Souls model)
- Build **zones as spatial puzzles** with a hub, branching routes and **shortcuts that unlock** (lift, door opened from the other side, ladder kicked down).
- The shortcut converts risk into safety: it reframes the previous journey and compresses travel.
- **Vertical layering** (seeing the later zone from an earlier vantage point) shows the geography and gives anticipatory goals. The map is a single contiguous space where far-away places can be seen from afar.
- Bonfires/checkpoints are placed as **pacing anchors**: after a hard stretch, before a boss.

## 9. Encounter Design

An **encounter** is a localized, bounded challenge: enemies, hazards or puzzle elements placed in a space to test specific skills.

### 9.1 Encounter anatomy
1. **Intent**: what skill is being tested? (target prioritization, movement, resource use, positioning)
2. **Space**: arena shape, cover, verticality, entrances, exits.
3. **Cast**: enemy types and roles, and counts.
4. **Rules**: spawn rules, waves, triggers, alert states.
5. **Resources**: ammo, health, pickups, checkpoint.
6. **Telegraphs**: what warns the player of each threat?
7. **Resolution**: win condition and reward, then transition into the next beat.

### 9.2 Enemy roles
Design enemies as **roles** that force different responses, then combine them. Typical shooter/action roles (industry vocabulary, names vary):

| Role | Function | Forces the player to | Counterplay |
|---|---|---|---|
| **Grunt / fodder** | Baseline damage, fills space | Basic aim/positioning | Any weapon |
| **Ranged / sniper** | Punishes standing still | Break line of sight, use cover | Close distance, flank |
| **Charger / rusher** | Closes distance fast | Move, create space, use melee/shotgun | Dodge, bait |
| **Tank / heavy** | Soaks damage, controls space | Use right weapon, target weak points | Exploit rear/weakness |
| **Flanker** | Attacks from sides/behind | Keep awareness, rotate | Corners, sensors |
| **Support / healer / buffer** | Amplifies others | Target prioritization | Kill first |
| **Summoner / spawner** | Adds enemies over time | Be proactive; prioritize | Kill quickly, deny spawns |
| **Suppressor / area denier** | Denies positions | Break stalemates, use mobility | Grenades, flanks |
| **Artillery / zoner** | Hits areas over time | Keep moving, read telegraphs | Reposition |
| **Stealth / ambusher** | Reveals itself suddenly | Pay attention to cues | Audio/visual tells |

### 9.3 Combinations
- **Role combos create tactics**: ranged + charger (stay in cover vs get flushed out), tank + support (kill the support first), artillery + flanker (keep moving, but do not turn your back).
- **Introduce each role alone, then in pairs, then in triples** (see section 10).
- **Counterpick tension**: each player tool should handle some roles well and others poorly so players switch.
- **Avoid "all-damage-sponge" combos**; vary time-to-kill per role (see TTK in `scripts/design_calc.py`).

### 9.4 Arenas and cover
- **Arena shape**: circular/open arenas favor kiting and mobility; rectangular with cover favors positional play; vertical arenas favor mobility and flanking.
- **Cover rule of thumb (heuristic)**: enough cover to create decisions, not so much that the fight becomes whack-a-mole. Destructible cover forces movement.
- **Entrances/exits**: more than one, to enable flanking and retreat; make spawn points invisible to the player's current view (spawn behind or off-screen) unless the fiction supports otherwise.
- **Combat zones with "push-forward" incentives**: reward aggression (for example, health from melee finishers) to avoid camp-and-peek; reward caution when you want tactical play.
- **Safe zones / refuge**: players need a place to reload and think. Pair a defensible refuge with prospect (see section 13).

### 9.5 Flanking
- A flank is only meaningful if the **flanking route is visible, viable, and slightly riskier or longer** than the direct route (heuristic: roughly 1.3-2x length).
- Enemy AI that flanks must **telegraph** (audio barks, shadows, markers) so the player can react.
- Give players the means to flank too: alternate routes, grapples, vents.

### 9.6 Encounter pacing
- **Setup (introduction of space), engagement, climax, aftermath.** Let players see the arena before triggering it; leave a short beat after for looting and breathing.
- **Wave structures**: 2-4 waves, each changing the question (new role, new direction, new terrain). Avoid waves that are the same fight again.
- **Reinforcement and escalation**: add elements the player is capable of handling due to the tools they have already.
- **Ammo and health logic**: supply the tools needed to beat the encounter close to it, not far from it. Prevent "death-by-resource" where earlier mistakes silently kill later encounters.
- **Failure recovery**: a short retry path (checkpoint near encounter), fast restart, and optional easing.

### 9.7 Non-combat encounters
The same anatomy applies to puzzles, stealth routes, platforming gauntlets, negotiation scenes. Define intent, space, cast, rules, telegraph and resolution.

## 10. Teaching Through Levels: Kishotenketsu and the Four-Beat Pattern

### 10.1 Kishotenketsu
**Kishotenketsu** is a four-part structure from East Asian narrative and poetry: **ki** (introduction), **sho** (development), **ten** (twist), **ketsu** (conclusion/reconciliation). Unlike Western three-act structures, it does not rely on conflict as its engine (Kishotenketsu, Wikipedia). Nintendo designers have described a four-step level design approach along these lines for the Mario 3D games, and Mario level design is commonly analyzed through it.

Applied to a mechanic in a level (design pattern, not a rule):
1. **Introduce (ki):** present the mechanic in a safe context. No fail state or a trivially forgiving one.
2. **Develop (sho):** variations that deepen understanding, with mild risk.
3. **Twist (ten):** recontextualize: a new combination, a trick that breaks an assumption.
4. **Conclude (ketsu):** a final challenge that uses everything, with a sense of mastery.

This also maps to "teach, test, combine, twist" in `references/05-progression-difficulty-onboarding.md`.

### 10.2 Practical use
- Build each level around **one core idea** and explore it from several angles rather than adding unrelated mechanics.
- Use **safe introduction spaces**: a pit that cannot kill, a hazard behind glass, an enemy that cannot reach you.
- Use **demonstration**: let an NPC, a trap or a scripted event show the mechanic first.
- Use **space as the teacher**: the geometry makes the intended action the only one that makes sense.
- Skip text; if a tutorial prompt is necessary, put it at the point of use.

## 11. Risk, Reward, Secrets and Exploration

### 11.1 Risk-reward placement
- **Reward should be proportional to risk and visible before commitment** (the player sees the chest on the ledge, then works out how to reach it).
- **Place a reward where it recontextualizes the route**: a pickup behind a risky jump, a health pack on a dangerous flank.
- **Safe choice vs greedy choice**: put a safe path and a risky path with a better payoff side by side so the decision is authored by the player.
- **Reward ladder**: tiny rewards on the main path (guaranteed), medium for off-path detours, large for deep exploration, unique for mastery.
- **Do not punish exploration** with unavoidable, unfair traps for "wandering off".
- **Make the greedy choice recoverable** unless the fiction is about irreversible stakes.

### 11.2 Secrets
| Type | Purpose | Guidelines |
|---|---|---|
| **Soft secrets** (visible, require thought) | Reward observation | Always hinted by sight or sound |
| **Hard secrets** (hidden, community-solved) | Reward obsession and conversation | Not required for completion; avoid pixel-hunt |
| **Skill secrets** | Reward mastery | Hard-to-reach but clearly visible |
| **Narrative secrets** | Reward curiosity with lore | Environmental storytelling; avoid text walls |

Principles:
- **Secrets are a dialogue with the player**: "I noticed that you noticed." The level should offer clues ("this wall looks different").
- **Reward must be worthy**: a secret leading to nothing trains players to stop exploring.
- **Make rewards diverse**: upgrade, shortcut, lore, shortcut-to-boss, cosmetic, challenge.
- **Signal the presence of secrets in general**: a "secrets found" counter or sound cue on the first discovery teaches the game's language.
- **Keep required progress out of hard secrets** (unless the game is designed around it, like Fez or Outer Wilds).

### 11.3 Exploration rewards
- **Discovery is its own reward** if the world is well-designed: vista, new silhouette, strange NPC.
- **Curiosity gap**: show something not understood and let players resolve it (the odd tower, the unreachable island).
- **Make exploration efficient**: fast travel, markers, clear "completed" state for areas.
- **Systemic discovery** (Breath of the Wild's physics) supplements POIs: players find solutions the designers did not enumerate.

## 12. Multiplayer Map Design

See also `references/10-multiplayer-and-social.md`.

### 12.1 Core concepts
| Concept | Description | Design implication |
|---|---|---|
| **Lanes** | Principal routes connecting spawns/objectives | 2-3 lanes common; each with a distinct character (long/short, open/covered) |
| **Chokepoints** | Narrow spaces where lanes converge | Create set-piece fights; need counters (smokes, flanks, angles) |
| **Flow / rotations** | How players move between lanes and objectives | Provide rotation paths of varying length and risk |
| **Sightlines** | Long lines of sight | Define weapon ranges and power positions; break them with cover |
| **Power positions** | High-ground or well-covered spots | Must be contestable and punishable; avoid unreachable dominance |
| **Spawn design** | Where and when players enter | See below |
| **Objectives** | Flags, sites, control points, payloads | Define the map's pace and attack/defense geometry |
| **Landmarks and callouts** | Names for places so teams can communicate | A good map is easy to call out |

### 12.2 Principles
1. **Readable at a glance**: players must build a mental map in a handful of matches (heuristic: three to five) and recognize their location from a screenshot.
2. **Multiple viable routes and options** prevent a single dominant path; but too many routes dilute fights.
3. **Counterplay for every strong position**: if there is a sniper nest, there must be a way to approach, suppress, or avoid it.
4. **Verticality adds options but complicates readability** and audio; use it purposefully.
5. **Risk/reward in the middle**: central control gives better angles and map control but exposes the player.
6. **Control pickups** (power-ups, heavy weapons, health) pull players into contested areas; their respawn timers pace the match. Put them where they require a trade-off.
7. **Test with the actual game's movement and weapons**. A map designed for one TTK can fail at another.
8. **Metrics tied to weapon ranges**: distances between common positions determine which weapons are viable (see section 3.3).

### 12.3 Spawn design
- **Spawn safety**: spawn points must not be in enemy line of sight or immediate fire; use spawn-protection and dynamic selection.
- **Spawn flow**: avoid spawn-trapping; with objective modes, use staged or dynamic spawns that shift forward as the objective advances.
- **Spawn distance**: far enough from enemies for safety, close enough to rejoin the action quickly (target time-to-action is a mode-specific heuristic).
- **Spawn selection**: weigh enemy proximity, teammate proximity and recent spawn use; test with logged data.
- **Respawn timers** are a pacing lever: short = constant action; long = more weight on each life.

### 12.4 Symmetry vs asymmetry
| | Symmetric | Asymmetric |
|---|---|---|
| Fairness | Inherently fair, easier to balance | Requires careful balancing per side |
| Learnability | Learn once, apply to both sides | Learn each side and role |
| Identity | Often blander; mirrored | Strong identity, stories, memorable spaces |
| Use | Competitive FPS, CTF, MOBAs (roughly symmetric lanes), arenas | Attack/defense modes, objective maps, battle royale, asymmetric games |

Hybrid: **mirrored layout with differing dressing and sightlines**, or **asymmetric structure with symmetric opportunities** (equal total routes with different shapes).

### 12.5 Mode-specific notes
- **Deathmatch / arena**: central control, item timing, fast rotations.
- **CTF**: flags need defendable bases with at least two entrances and flank routes.
- **Control point / King of the Hill**: shape of the zone matters (open = frantic; covered = tactical).
- **Attack/defend (bomb or push)**: clear choke between spawn and objective; defenders need rotation time.
- **Battle royale**: points of interest ladder from high-risk/high-loot to low; routes between POIs matter more than the buildings.
- **Co-op PvE**: encounter design principles plus group positioning; give each player a role or space.

## 13. Architecture and Space: Totten's Approach

Christopher Totten, in *An Architectural Approach to Level Design* (2014), argues that architects and level designers solve related problems: shaping space for use, movement and meaning. Key ideas to borrow (summarized; consult the book for the full treatment):

- **Prospect-refuge theory** (Appleton, *The Experience of Landscape*, 1975): people prefer places where they can see without being seen (prospect) and retreat to protection (refuge). In games: sniper perches, safe rooms, cover positions. Fights are tense when the player has refuge but must leave it for prospect. Horror inverts it: prospect without refuge.
- **Spatial sequence**: compression and release (tight corridor opening into a vista) shapes emotion; **threshold** moments (doors, gates) mark transitions.
- **Circulation**: how people move through space (paths, nodes, loops, dead ends). Plan circulation as a graph.
- **Legibility**: the ability of a space to be understood (Lynch). Consistent structural logic, distinctive nodes.
- **Scale and proportion**: large spaces make characters feel small (awe, vulnerability); low spaces feel oppressive or intimate.
- **Function and fiction**: a believable place has plausible function (kitchens near dining rooms, guard posts at gates). Players read these cues, which also serve as wayfinding and storytelling.
- **Materials and light as mood**: texture, color and lighting direct emotion and attention.
- **Pre-visualization**: use floorplans, sections and elevations (as architects do) for vertical and sightline planning, not only top-down maps.
- **Orientation devices and "mental maps"**: like architects, design **axes**, **focal points** and **cardinal logic** so players can reason about space.

## 14. Environmental Storytelling Hand-Off

Level design provides the **stage**; narrative design provides the **script** (see `references/07-narrative-design.md`). Define a clean hand-off.

| Level design delivers | Narrative / art adds |
|---|---|
| Space, sightlines, pacing, safe spots for beats | Props, scenes, audio logs, graffiti, set dressing |
| **Story beats mapped to locations** (a "reveal moment" point on the paper map) | Content for each beat: what the scene implies |
| Camera framing and approach routes to key vignettes | Vignette staging (a table set for two; one chair knocked over) |
| Rest spaces where players can read/listen | Written/audio lore (short; see narrative file) |

Principles:
- **Show the aftermath, not the event** (cold open on the scene of a past incident). The player reconstructs the story.
- **One vignette, one idea**: simple, readable, 3-5 props max.
- **Place story where players already look**: sightline endpoints, rest spots, thresholds.
- **Never block gameplay for story**. Give the player the choice to linger.
- **Make the space tell the same story as the mechanics** (ludonarrative harmony).
- **Plan for the budget**: each vignette costs art and testing time.

## 15. Lessons from Valve's Commentary and Playtesting Culture

Valve's developer-commentary modes (Half-Life 2, Episode One/Two, Portal, Left 4 Dead) are public, practical lessons in design thinking. Recurring themes (paraphrased from the commentary tracks; verify specifics by playing with commentary on):

- **Playtest early and watch silently.** Many design choices in the commentary are described as responses to what testers did, not to what designers expected.
- **Teach by doing and by environment.** Introduce mechanics in situations where the only reasonable action is the intended one. Portal's early chambers are the textbook case.
- **Light and composition guide the player.** Lighting, color and framing are used to point to the route.
- **Companion AI as guidance and emotion.** Characters lead through space and attach feelings to places.
- **Pacing through variety of gameplay types**, and by changing the tool (gravity gun, vehicles) not just the enemy count.
- **Signposting through consistent visual language** (for example, in Left 4 Dead, safe rooms and lit paths) and audio cues.
- **Cut ruthlessly.** Anything not tested to be fun is removed.
- **Player agency inside a controlled stage**: giving the feeling of freedom within a designed funnel.

For a modern, practical treatment of many of these topics, see *The Level Design Book* (Level Design Book).

## 16. Worked Examples

Treat these as analysis summaries based on commonly discussed features of the games; verify details by playing the games.

### 16.1 Super Mario Bros. World 1-1 (teach, test, combine, safe failure)
- The first screen presents Mario at the left edge with open space to the right: direction of travel is implied by composition and scrolling.
- The first enemy (Goomba) approaches from the right on flat ground; the player either jumps or dies once, cheaply, and learns the jump-on-enemy relationship.
- A row of blocks, with a question block, gives the first reward; hitting from below teaches the block mechanic, and the mushroom that moves and bounces teaches power-ups in a space where the player cannot easily avoid it (a low ceiling forces interaction).
- Pipes and gaps are introduced with increasing risk; early gaps are wide and forgiving.
- **Lesson:** the level is an interactive tutorial with no text; each element is introduced in a safe context, repeated, and then combined. The same applies at the scale of levels in later worlds (kishotenketsu, section 10).

### 16.2 Half-Life 2 (pacing, variety, guidance)
- The game alternates between **on-foot combat, vehicle sections, puzzles using physics, and set-piece spectacle**, always while introducing or re-introducing a tool (crowbar, gravity gun, buggy, antlion pheromone pods).
- **Ravenholm** is a self-contained, theme-driven chapter in which the Gravity Gun and saw blades are the intended weapons: the environment supplies the mechanic.
- **Guidance** relies on lighting, composition, and NPCs; the player seldom needs a map or a waypoint.
- **Lesson:** change the question the player has to answer from chapter to chapter, with the environment teaching each new tool.

### 16.3 Dark Souls (interconnection, soft gating, shortcuts)
- The world is a **single contiguous map**; zones are seen from afar before they are reached, and shortcuts (lifts, doors, ladders) open loops back to bonfires.
- **Soft gates**: wandering into an area too early is possible but punishing; difficulty communicates "not yet" without a lock.
- **Checkpoint placement** (bonfires) defines risk: the walk between bonfire and boss is itself a tension tool.
- **Lesson:** knowledge of space is the primary progression; the player's mental map is the reward.

### 16.4 Doom (2016) arenas (combat loop shaping space)
- Arenas are **bounded combat spaces** with verticality, traversal (mantle ledges, climb poles) and multiple enemy roles; the sequence is typically "enter, lock, fight, exit".
- **Push-forward combat**: glory kills drop health, the chainsaw drops ammo, and the player is rewarded for engaging rather than hiding. The level geometry is designed to support constant movement (no long static cover chains).
- Between arenas are traversal and exploration segments with secrets, collectibles and upgrade rewards, giving valleys in the intensity graph.
- **Lesson:** design the arena around the combat loop's resource flow (health, ammo, armor from kills), not only around cover.

### 16.5 Counter-Strike: Dust2 (multiplayer lanes and chokepoints)
- Two bomb sites (A and B) and a roughly three-route structure: long A, middle, and B tunnels. Chokepoints (long doors, mid doors, tunnels) are the points where timing, utility (smokes, flashes) and information play out.
- The map is not strictly symmetric but is balanced by long-term play. Callout names (long, catwalk, mid doors, B tunnels) emerged from the community and are easy to say and remember.
- Multiple rotation paths let teams commit or fake, producing mind games.
- **Lesson:** simple topology, clear callouts and balanced rotation times make a map learnable and deep. Its longevity comes from iteration plus community testing, not from visual fidelity.

## 17. Checklists and Common Pitfalls

### 17.1 Design review checklist
- [ ] One-sentence purpose for the level and for each major room.
- [ ] Metrics sheet agreed, and the blockout complies.
- [ ] Intensity graph drawn; beat types vary; there are valleys.
- [ ] Each new mechanic follows teach, test, combine, twist.
- [ ] Landmarks visible from decision points; each district has a distinct identity.
- [ ] Critical path has no ambiguity; optional paths are signposted.
- [ ] Gates are explainable; no soft-locks; dependency graph checked.
- [ ] Encounters have intent, readable telegraphs, fair retry.
- [ ] Rewards proportional to risk; at least one memorable discovery.
- [ ] Multiplayer: callouts, lanes, spawn safety, counterplay for power positions.
- [ ] Accessibility: nothing depends on color alone; options for guidance.
- [ ] Playtested with cold players after each major change, including after the art pass.

### 17.2 Pitfalls
| Pitfall | Why it happens | Fix |
|---|---|---|
| **Designer-blind spots** | Designer knows the route | Cold playtests, silent observation |
| **Over-detailed too early** | Art before validation | Greybox until playtests pass |
| **Same encounter repeated** | Content shortcuts | Change the question each time |
| **Empty space / padding** | Scale ambition | Cut or fill with purpose; use travel tools |
| **Corridor of waves** | Linear + arenas only | Add traversal, puzzles, spectacle, exploration |
| **Hidden critical path** | Overreliance on subtlety | Add stronger lighting, landmark, or NPC guide |
| **Unfair deaths on first exposure** | Unseen hazards | First exposure must be readable and survivable |
| **Breaking sequence unintentionally** | Open connectivity without checks | Dependency graph; test with sequence-break playthroughs |
| **Backtracking tedium** | No shortcuts or fast travel | Loops, shortcuts, teleports; each return trip needs something new |
| **Metrics drift** | Movement changed | Re-validate all levels; use test maps |
| **Art hides gameplay** | Dressing clutter | Readability passes; gameplay-critical collision/visibility locked |
| **Multiplayer: one dominant route/position** | Insufficient counterplay | Telemetry heatmaps, add angles, adjust cover |
| **Spawn trap or spawn kill** | Weak spawn logic | Dynamic spawn rules and telemetry |
| **Story stops the game** | Narrative placed in dead zones | Environmental beats at natural pause points |

### 17.3 How to apply: requests for help
1. Ask for the purpose, verbs, platform, camera, and movement values.
2. Produce a beat sheet with intensity numbers and a topology diagram (text/ASCII).
3. Provide a metrics table derived from their movement stats.
4. Specify encounter intents and cast roles.
5. List wayfinding tools used per decision point.
6. Provide a playtest plan (cold players, questions, success metrics). Use `templates/level-design-doc.md` for the formal document.

## 18. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Books**
- Lynch, K., 1960, *The Image of the City*, MIT Press.
- Appleton, J., 1975, *The Experience of Landscape*, John Wiley & Sons.
- Totten, C. W., 2014, *An Architectural Approach to Level Design*, CRC Press (Taylor & Francis). ISBN 978-1-4665-8541-6.
- Rogers, S., 2014, *Level Up! The Guide to Great Video Game Design*, 2nd ed., Wiley.
- Swink, S., 2009, *Game Feel: A Game Designer's Guide to Virtual Sensation*, Morgan Kaufmann.
- Schell, J., 2019, *The Art of Game Design: A Book of Lenses*, 3rd ed., CRC Press.

**Websites and articles (URLs verified)**
- The Level Design Book (online, open): https://book.leveldesignbook.com/
- Wienie (Disney theme-park landmark principle), Wikipedia: https://en.wikipedia.org/wiki/Wienie
- Kishotenketsu, Wikipedia: https://en.wikipedia.org/wiki/Kish%C5%8Dtenketsu

**Games analyzed (play to verify)**: Super Mario Bros., Half-Life 2 (with developer commentary), Dark Souls, Doom (2016), Counter-Strike (Dust2), Portal, Left 4 Dead, The Legend of Zelda series, Metroid / Super Metroid, Hollow Knight, Breath of the Wild.

Note: the heuristics in this file (metrics, ratios, time targets) are industry rules of thumb and the author's judgment, not measured standards; tune them to your game.
