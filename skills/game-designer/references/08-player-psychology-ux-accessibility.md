# Player Psychology, UX and Accessibility

How players think, feel and perceive, and how to design interfaces, feedback, controls and options so that the game is understandable, motivating and playable by as many people as possible.

## Table of Contents

1. [How to Use This File](#1-how-to-use-this-file)
2. [Motivation: SDT, PENS, Intrinsic vs Extrinsic](#2-motivation-sdt-pens-intrinsic-vs-extrinsic)
   - [2.1 Self-Determination Theory](#21-self-determination-theory)
   - [2.2 PENS and what it predicts](#22-pens-and-what-it-predicts)
   - [2.3 Intrinsic vs extrinsic rewards](#23-intrinsic-vs-extrinsic-rewards)
   - [2.4 Applying SDT: a design audit](#24-applying-sdt-a-design-audit)
3. [Cognition: Attention, Perception, Memory, Load](#3-cognition-attention-perception-memory-load)
   - [3.1 Attention and perception](#31-attention-and-perception)
   - [3.2 Memory, chunking, Miller and Cowan](#32-memory-chunking-miller-and-cowan)
   - [3.3 Cognitive load](#33-cognitive-load)
   - [3.4 Learning curves](#34-learning-curves)
4. [Game UX Frameworks](#4-game-ux-frameworks)
   - [4.1 Hodent's pillars: usability and engage-ability](#41-hodents-pillars-usability-and-engage-ability)
   - [4.2 Nielsen heuristics adapted to games](#42-nielsen-heuristics-adapted-to-games)
   - [4.3 Affordances, signifiers, mappings (Norman)](#43-affordances-signifiers-mappings-norman)
5. [HUD and Interface Architecture](#5-hud-and-interface-architecture)
   - [5.1 The four HUD spaces](#51-the-four-hud-spaces)
   - [5.2 HUD design rules](#52-hud-design-rules)
   - [5.3 Menus and information architecture](#53-menus-and-information-architecture)
6. [Feedback and Timing](#6-feedback-and-timing)
7. [Controls, Input Mapping and Camera](#7-controls-input-mapping-and-camera)
    - [7.3 Input and Interaction Laws](#73-input-and-interaction-laws)
8. [Readability](#8-readability)
9. [Biases, Persuasion and Ethical Use](#9-biases-persuasion-and-ethical-use)
10. [The Fun of Failure](#10-the-fun-of-failure)
11. [Accessibility](#11-accessibility)
    - [11.1 Why and how to start](#111-why-and-how-to-start)
    - [11.2 Game Accessibility Guidelines](#112-game-accessibility-guidelines)
    - [11.3 Xbox Accessibility Guidelines](#113-xbox-accessibility-guidelines)
    - [11.4 AbleGamers APX patterns](#114-ablegamers-apx-patterns)
    - [11.5 CVAA and legal context](#115-cvaa-and-legal-context)
    - [11.6 Case studies](#116-case-studies)
    - [11.7 Colorblind design](#117-colorblind-design)
    - [11.8 Subtitles and captions](#118-subtitles-and-captions)
    - [11.9 Motor accessibility checklist](#119-motor-accessibility-checklist)
    - [11.10 Cognitive accessibility checklist](#1110-cognitive-accessibility-checklist)
    - [11.11 Vision, hearing and testing](#1111-vision-hearing-and-testing)
12. [Worked Examples and Diagnostics](#12-worked-examples-and-diagnostics)
13. [Common Pitfalls](#13-common-pitfalls)
14. [References](#14-references)

---

## 1. How to Use This File

Load this file when the question is "why do players feel/do X", "is this UI clear", "how should the HUD/menus/controls work", or "is this accessible". Pair it with `05-progression-difficulty-onboarding.md` (teaching, difficulty), `03-core-loops-and-mechanics.md` (game feel) and `09-monetization-and-live-ops.md` (ethics of persuasion).

Evidence labels used below:
- **Established**: replicated research or a formal standard.
- **Industry practice**: widely used, field-tested, not a law.
- **Heuristic**: a rule of thumb or a number to be validated by your own playtests.

Core stance: players do not fail because they are lazy or stupid. When many players misread something, the design failed to communicate. Treat every confusion in a playtest as a bug in the game's signals.

---

## 2. Motivation: SDT, PENS, Intrinsic vs Extrinsic

### 2.1 Self-Determination Theory

**Established.** Self-Determination Theory (Deci and Ryan 2000) proposes three basic psychological needs whose satisfaction drives well-being and sustained, high-quality motivation:

| Need | Meaning | Game design levers |
|---|---|---|
| **Competence** | Feeling effective, growing in skill | Clear feedback, scalable challenge, readable cause/effect, visible mastery (skill, not just stats), fair failure |
| **Autonomy** | Volition; acting in line with one's own values | Meaningful choices, multiple viable strategies, build/loadout/expression, non-forced pacing, opt-in optional content |
| **Relatedness** | Connection with others | Co-op, guilds, NPC companions with real bonds, shared goals, safe social spaces, being seen/appreciated |

Needs are satisfied by the experience of play itself; this is why SDT is an explanation of *intrinsic* motivation to play.

### 2.2 PENS and what it predicts

Ryan, Rigby and Przybylski (2006) built the **Player Experience of Need Satisfaction (PENS)** model across several studies. Key findings (established, studies mostly on specific game samples):

- Satisfaction of competence, autonomy and relatedness in play predicted enjoyment, preference for future play, and self-reported well-being after play.
- A fourth construct, **presence/immersion** (physical, emotional, narrative), added to the model, and intuitive controls were linked to competence and presence.
- Players' motivations are more than "fun in the moment": need satisfaction predicted willingness to play again.

Practical reading: the PENS scale (subscales: competence, autonomy, relatedness, presence/immersion, intuitive controls) can be adapted into a playtest survey (see `12-playtesting-and-analytics.md`). Items are agree/disagree statements ("The game controls were intuitive", "I felt free to play the way I wanted"). Use validated wording from the paper's appendix if you need research-grade results; otherwise paraphrase for internal tests.

### 2.3 Intrinsic vs extrinsic rewards

| Aspect | Intrinsic | Extrinsic |
|---|---|---|
| Source | The activity itself (mastery, discovery, expression) | Outcomes separable from activity (points, loot, badges, currency) |
| Effect when removed | Behavior persists | Behavior often stops |
| Risk | Hard to "guarantee" | **Overjustification / crowding out**: tangible, expected, contingent rewards for an already-enjoyed activity can lower later interest (Deci, Koestner and Ryan 1999 meta-analysis) |
| Best use | Core verbs, exploration, creativity | Onboarding nudges, acknowledging progress, structure for repetitive tasks |

Heuristics:
1. **Informational over controlling.** A reward that says "you got better" supports competence; a reward that says "do this to get paid" is controlling. Frame rewards as feedback (e.g., a mastery mark for a perfect parry) rather than bribes.
2. **Reward the interesting thing, not the grind.** If players take the reward-giving action only for the reward, ask whether the action is fun on its own; if not, fix the action.
3. **Unexpected, verbal/feedback rewards crowd out less than expected, tangible, performance-contingent ones** (Deci et al. 1999). Surprise bonuses and praise are safer than "do X 10 times for Y".
4. **Extrinsic rewards are not evil.** Many games survive on loot loops (Diablo-likes); the loot is intertwined with the intrinsic joy of build experimentation. Problem cases are rewards that *replace* the fun.
5. **Variable-ratio schedules** drive repetition strongly (behaviorist literature). Use them with awareness; see section 9 and `05-progression-difficulty-onboarding.md` for reward schedules.

### 2.4 Applying SDT: a design audit

Run this for each major feature:

1. **Competence**: Can the player tell what they did right/wrong in 1-2 seconds? Is there a path from novice to expert with visible stepping stones? Does the difficulty adapt via player choice (modes, assists) rather than hidden tuning?
2. **Autonomy**: Are there at least 2-3 viable approaches to the main challenge? Can the player skip, defer or decline? Do rewards force a single "optimal" path (kills autonomy)? Is anything forced by timers or FOMO?
3. **Relatedness**: Does the game offer a way to share progress, help or be helped without being forced into toxic exchanges? Do characters respond to the player?
4. **Thwarting check** (SDT also studies need *frustration*): list places where the player is controlled (unskippable repeated content), made to feel incompetent (opaque deaths), or excluded (pay walls in group content).

Worked example - *Celeste*: competence from short retries and fast respawn; autonomy from optional strawberries and assist mode; relatedness from Madeline's character arc. Failure is cheap, so competence is felt rather than threatened.

---

## 3. Cognition: Attention, Perception, Memory, Load

### 3.1 Attention and perception

**Established basics, applied as industry practice.**

- **Attention is scarce and selective.** Players attend to what is *moving, high-contrast, novel, or relevant to their current goal*. Unattended elements may be missed completely (inattentional blindness: Simons and Chabris 1999 showed that observers counting passes in a video often missed a person in a gorilla suit). Implication: in a high-focus moment (boss fight), do not rely on a peripheral HUD change to deliver critical information; use audio, screen-space effects near focus, or world-space telegraphs.
- **Change blindness**: changes during blinks/cuts/flashes are missed. Do not communicate state changes by a tiny edit in a busy scene; add motion, sound or highlight.
- **Preattentive features** (color, motion, size, orientation, flicker) are processed fast. Use *one* feature to mark the thing that matters (e.g., red outline for the current threat); marking everything dilutes it.
- **Gestalt principles** (proximity, similarity, closure, common fate, figure/ground) govern how UI and levels are grouped. Group related HUD elements; align and space consistently.
- **Visual hierarchy** is size, contrast, position and motion. Tune so the top-3 pieces of information are readable at a glance at the intended viewing distance (TV at 3 m vs handheld).
- **Auditory attention**: sound is omnidirectional and can cut through when eyes are busy. Critical alerts should have an audio channel *and* a visual channel (also required for accessibility).
- **Peripheral vision** carries low-resolution motion and contrast. Low-health vignettes and directional damage indicators work because they use periphery.
- **Reaction times** (heuristic ranges, individual and context dependent): simple visual reaction time is roughly 200-250 ms for many adults; choice reaction is longer. Telegraphs for enemy attacks usually need to exceed ~300-500 ms to be fair at standard difficulty; tune by playtest.

### 3.2 Memory, chunking, Miller and Cowan

- **Working memory** is the small, volatile store used to hold goals, numbers, and plans. Miller (1956) proposed "seven plus or minus two" items; later work (Cowan 2001) argues the capacity of the focus of attention is closer to **about four chunks** when rehearsal and grouping are controlled. Treat "4 +/- 1" as a safer design target for things the player must hold in mind simultaneously.
- **Chunking**: grouping items into meaningful units extends effective capacity (phone numbers, chess patterns). Offer chunkable structures: color-coded item tiers, familiar iconography, named combos, suit-like categories.
- **Recognition beats recall.** Show options (menus, inventory icons, move lists in-pause) rather than requiring players to remember commands. Provide in-game reminders: a re-readable tutorial, a codex, a quest log with "next step", a "previously on..." recap after a break.
- **Long-term memory** benefits from spaced repetition, distinct cues (unique sounds, shapes, colors) and meaningful context. Introduce a mechanic, revisit it within a few minutes, then again later in a new context (see the skill atoms approach in `05-progression-difficulty-onboarding.md`).
- **Return-after-break problem**: players leaving for weeks forget controls and plot. Provide: objective reminders, optional refresher tutorials, lower-stakes re-entry content.
- **Prospective memory** (remembering to do something later) is fragile. If a task depends on remembering (return to this NPC), use a map marker or journal entry.

### 3.3 Cognitive load

From Sweller's Cognitive Load Theory (established for instructional design; use by analogy in games):

| Load type | Source | Design response |
|---|---|---|
| **Intrinsic** | The inherent complexity of the task (e.g., chess rules) | Break into skill atoms, sequence from simple to compound |
| **Extraneous** | Poor presentation: clutter, hidden info, inconsistent UI | Remove; this is the designer's main target |
| **Germane** | Effort that builds schemas (understanding the system) | Encourage with good challenge and reflection |

Checklist for lowering extraneous load:
1. One new idea at a time; the first screen the player sees has one call to action.
2. Consistent iconography, colors, button placement; never reuse a symbol for two meanings.
3. Progressive disclosure: hide advanced options until needed (collapsible panels, "advanced" tabs).
4. Offload memory to the interface: highlight selected items, show previous choices, persistent objective.
5. Provide defaults (recommended loadout, auto-sort) that experts can override.
6. Limit simultaneous demands: do not ask the player to learn a new control, a new enemy and a new UI at once.
7. In real-time games, remember divided attention: any text that must be read during action (tutorial prompts) needs to be short, large and persistent for long enough, or paused.
8. Count simultaneous variables in a decision. Strategy games with 7+ unlabelled numbers per decision need summaries ("net +3 food/turn", color-coded outcomes).

### 3.4 Learning curves

- The **power law of practice**: performance improves fast at first and then slowly. Players perceive the early learning as the most satisfying; later gains need new content or depth to stay noticeable.
- **Zone of proximal development** (Vygotsky): the best challenge sits slightly beyond current competence with support. Use hints that escalate (nudge -> pointer -> demonstration) rather than abrupt walls.
- **Depth vs complexity**: depth is the number of meaningful strategies achievable from the rules; complexity is how many rules to learn. Aim for **low barrier, high ceiling** (Tetris, Rocket League, Hades).
- **Learning style variety**: some learn by reading, some by trying, some by watching. Offer a short interactive tutorial, a re-viewable reference, and a safe practice space.
- **Skill transfer**: reuse verbs and UI conventions from genre peers so veterans skip learning; mark where you deviate (see affordances, below).
- Measuring: track time-to-first-success per mechanic, failure counts per encounter, and quit points; see `12-playtesting-and-analytics.md`.

---

## 4. Game UX Frameworks

### 4.1 Hodent's pillars: usability and engage-ability

Celia Hodent (2017/2020, *The Gamer's Brain*) applies cognitive psychology to game UX. She frames user experience as having two broad components that must both be good:

**Usability**: how easy it is to interact with the game and understand it without friction. Subcomponents (her *Game UX* model):
- **Cognitive** (learnability, understanding, mental models, memory, perception)
- **Ergonomics** (physical interaction: controls, input devices, comfort)
- **Accessibility** (see section 11)
- **Game-specific usability**: onboarding, interface, controls, and "flow" of information.

**Engage-ability**: the motivation and desire to keep playing; what makes the game compelling. Elements include **motivation** (SDT), **emotions**, **game flow** (challenge/skill balance, clear goals, feedback), **meaning**, and **fun**. Hodent also stresses that UX is a *process* (research, testing) not a fixed attribute, and warns against treating "usability" as reducing all friction; some friction is the challenge.

How to apply:
1. Treat usability as a *prerequisite* for engage-ability: frustrating controls or opaque UI waste the motivation you built.
2. Distinguish **good friction** (the game's challenge) from **bad friction** (fighting the interface). Only remove the latter.
3. Run usability tests focused on observation (what players do), not opinion (what they say). Use think-aloud and task completion.
4. Ground decisions in how brains actually work (attention, memory, perception), not "players are smart".

### 4.2 Nielsen heuristics adapted to games

Nielsen's ten usability heuristics (Nielsen 1994, updated 2020 at NN/g) were adapted for games by Pinelle, Wong and Stach (2008, "Heuristic Evaluation for Games"), Desurvire et al. (HEP, 2004), and others. Below, the ten original heuristics with a game reading:

| # | Nielsen heuristic | Game adaptation | Example check |
|---|---|---|---|
| 1 | Visibility of system status | Show health, ammo, cooldowns, objectives, loading, matchmaking state, save status | Is the player ever unsure whether input was received, a save occurred, or they are in a queue? |
| 2 | Match between system and real world | Use genre/world language, familiar metaphors, consistent fiction | Does "Armor" reduce damage in the way the name suggests? |
| 3 | User control and freedom | Undo, cancel, skip cutscene, pause, remap, retreat, quick-save | Can a misclicked purchase be reversed? Can any cutscene be skipped on replay? |
| 4 | Consistency and standards | Same button, same icon, same color for the same meaning; follow genre conventions (left stick moves, right stick aims) | Does "B" cancel everywhere? |
| 5 | Error prevention | Confirm destructive or irreversible actions; make safe defaults; forgiving hitboxes (coyote time, input buffering) | Can the player sell their best item in one stray press? |
| 6 | Recognition rather than recall | Persistent objective, in-pause move list, tooltips, visible inventory | Must the player memorize a combo with no reference? |
| 7 | Flexibility and efficiency of use | Shortcuts for veterans, bulk actions, quick-swap, scalable difficulty/assists | Can experts sell 50 items quickly? |
| 8 | Aesthetic and minimalist design | Show only relevant info, declutter HUD, contextual UI | Are there more than ~5-7 persistent HUD elements competing? (heuristic) |
| 9 | Help users recognize, diagnose, recover from errors | Explain *why* the player failed; death recap; helpful messages | "You died" vs "Killed by poison; antidote at Merchant" |
| 10 | Help and documentation | Searchable codex, replayable tutorial, contextual hints | Can a lapsed player relearn without outside wikis? |

Pinelle et al. (2008) analyzed 108 PC game reviews to identify the most common usability problems in games; the recurring categories were **unpredictable/inconsistent response to input, unclear goals/objectives, bad visual representation/interface, poor tutorial or help, and difficulty/challenge not suited to the player** (as summarized in that paper; consult the paper for exact ranks). Use these as a pre-release checklist.

Games-specific additions:
- **Challenge must be fair and learnable**, not a result of poor communication ("fair" = the player could have known).
- **Mastery and game feel**: immediate, consistent feedback to input.
- **Pacing**: respect time (skippable, fast restart, fast travel).
- **Don't punish exploration** (instant death with no cue).

### 4.3 Affordances, signifiers, mappings (Norman)

Don Norman (*The Design of Everyday Things*, revised 2013):

- **Affordance**: a relationship between an object's properties and the agent's abilities that allows an action (a ledge affords climbing *to a character that can climb*).
- **Signifier**: a perceivable cue that tells you where/how to act (a handle, a glowing edge, yellow paint on climbable surfaces). In games, the designer's main tool is the signifier, because affordances are defined by the rules and must be *communicated*.
- **Mapping**: relationship between controls and effects (spatial analogy: stick up = move forward; button layout matching on-screen layout).
- **Feedback**: immediate, informative results of an action.
- **Constraints**: physical, logical, semantic, cultural limits that guide action.
- **Conceptual model**: the player's mental model of how things work; the designer must lead it to match the system's real model.
- **Gulf of execution** (how do I do what I want?) and **gulf of evaluation** (what happened?). Find both gulfs in every feature.

Game applications:
- **Consistent visual language** for interactables: *The Last of Us*, *Uncharted*, *Tomb Raider* use paint/cloth/highlight (often called "yellow paint") for climbables; *Mirror's Edge* uses "runner vision" red for the route. Whatever your language, consistency is more important than the particular color. Teach it early, then never break it without a reason.
- **Signifier vs decoration**: if a surface looks like a ledge but is not, you trained a false affordance. Playtest for false positives (wasted attempts) and false negatives (missed routes).
- **Natural mapping**: map weapon-wheel items to stick direction in a stable position; keep menu orientation consistent.
- **Genre conventions** are shared mental models; deviate deliberately and teach.

---

## 5. HUD and Interface Architecture

### 5.1 The four HUD spaces

Fagerholt and Lorentzon (2009, *Beyond the HUD*) classify UI by two questions: is it **in the game fiction** (does the character know about it?) and is it **in the 3D game space** (does it exist in the world geometry)?

| Type | In fiction? | In 3D space? | Examples | Use for |
|---|---|---|---|---|
| **Diegetic** | Yes | Yes | *Dead Space* health on suit's spine and holographic ammo; car dashboards in sims; *Metro* wrist watch and gas mask timer; in-world signs | Immersion; information that characters would plausibly see |
| **Non-diegetic** | No | No | Classic health bars, minimaps, ability bars, menus | Dense, precise, frequently-referenced data; accessibility; competitive clarity |
| **Spatial** | No | Yes | Waypoints in world, enemy outlines, floating names, selection circles under units, *Mirror's Edge* runner vision | Linking info to world positions; objective markers; 3D clarity |
| **Meta** | Yes | No | Blood on screen when hit, cracked visor, vignette, screen shake, rain on camera | Visceral feedback of state, strong feeling, short-term events |

Rules of thumb (industry practice):
1. **Immersion vs clarity is a trade-off, not a rule.** Diegetic UI adds mood and costs legibility, localization flexibility and accessibility. Use diegetic *and* provide an optional non-diegetic fallback for critical information.
2. **Information frequency and precision** decides placement: frequently-read, precise numbers (ammo count in a competitive shooter) belong in a stable HUD location; rare events can be meta or diegetic.
3. **Spatial UI needs occlusion and scale rules**: fade distant markers, avoid z-fighting with world, keep legible at distance.
4. **Genre priors**: strategy and MOBA expect dense non-diegetic UI; horror and survival often reduce HUD to heighten tension (compensated by audio and meta cues).

### 5.2 HUD design rules

1. **Hierarchy of need**: critical-now (health, ammo, immediate prompts) in the main field of attention, secondary (minimap, cooldowns) at the periphery, tertiary (quest log, stats) on demand.
2. **Safe zones**: keep key elements inside the TV-safe/title-safe region (commonly ~90-95% of the screen; heuristic and platform-specific - check platform requirements). Provide a HUD margin slider.
3. **Scalability**: text size options; HUD scale; readable at 10-foot distance on a TV and on handheld at arm's length. Minimum readable text size is a platform and viewing distance question - test it.
4. **Contextual display**: show ammo only when armed/firing/reloading; show health when changed or low. Offer a toggle (full, minimal, off) for players who want a clean screen.
5. **Redundant encoding**: never encode status by color alone (see 11.7). Add shape, icon, number, position or animation.
6. **Persistent vs transient**: persist what is needed for decisions; time-limit what is only informative, with a log to reread (chat/notification history).
7. **Do not obscure** the play area center; place notifications away from threats; avoid modal popups during gameplay.
8. **Feedback layering for damage**: directional indicator + sound + screen-edge vignette is more reliable than any one alone.
9. **Number readability**: group digits, align, use tabular numbers for changing values; avoid letting numbers jitter.
10. **Localization**: allow 30-50% text expansion (heuristic common in localization guidance); avoid text baked into textures; support right-to-left and CJK fonts when relevant.

### 5.3 Menus and information architecture

Principles:
- **Depth/breadth balance**: prefer broader, shallower menus (fewer clicks) up to the limit of scannability; deep nesting hides features. For controller navigation, minimize lateral jumps.
- **Predictable navigation**: consistent back/confirm; remember last cursor position; allow tab/shoulder-button switching for sections.
- **Categories by player goals**, not by internal data structure ("Upgrade my weapon" vs "Item database").
- **Show comparisons**: in equipment menus, show deltas (green/red arrows plus number change, with non-color cues) between current and candidate items.
- **Search/filter/sort** once an inventory can exceed ~20-30 items (heuristic). Favorites and auto-sort help.
- **Confirmations** for irreversible actions only; too many confirmations teach players to ignore them.
- **Pause menus** should open instantly and offer: resume, settings, controls, accessibility, quit with a save reminder. Accessibility settings must be reachable from first launch and in-game.
- **First-launch flow**: language -> accessibility/display basics (subtitles, text size, brightness, colorblind, input) -> play. Games like *The Last of Us Part II* and *Forza* present accessibility early.
- **Store and economy UX** (shops): see `09-monetization-and-live-ops.md` for ethical presentation.
- **Loading and queues**: show progress and estimated time; allow interaction (a mini-game, a lobby) while waiting.
- **Settings**: group (Gameplay, Controls, Audio, Video, Accessibility), search if long, "reset to default" per section, preview changes live (subtitle size sample, colorblind filter preview).

Information architecture worksheet:
1. List every task the player does outside gameplay (equip, craft, party up, buy).
2. Rank by frequency x importance.
3. Give the top tasks at most 2 inputs from the main screen.
4. Card-sort labels with 5+ players; rename anything that more than one misreads.
5. Test with controller-only, mouse-only, and touch as relevant.

---

## 6. Feedback and Timing

Response-time limits (Nielsen 1993, adapted from Miller 1968 and Card et al. 1991; established for GUIs, applied to games as heuristics):

| Time | Perceived as | Design use |
|---|---|---|
| ~0.1 s (100 ms) | Instantaneous: cause and effect feels directly connected | Button press -> visible/audible response. The skill's rule: respond within ~100 ms |
| ~1 s | Flow of thought uninterrupted, user notices delay | Menus, interaction results, simple loading; show a spinner after ~1 s |
| ~10 s | Limit of keeping attention | Longer waits need progress feedback and ideally allow other actions |

Games add tighter requirements for **action games**: input latency budgets of well under 100 ms end to end (display, input device and engine all count). Many fighting-game and rhythm-game communities target one or two frames at 60 fps (16.7-33 ms) for input response; treat as practice, not law. For rhythm games provide latency calibration.

Feedback design:
1. **Acknowledge every input** immediately, even if the action cannot occur (error sound/animation for "cannot do that", with the reason).
2. **Layer feedback** by channel: animation, VFX, audio, camera, controller haptics, UI. Scale with importance (a headshot kill > a grazing hit).
3. **Anticipation, action, follow-through**: wind-up (telegraph) -> impact (hit-stop of a few frames, heuristic) -> recovery. Feedback after the fact must still link to the cause.
4. **Latency tolerance differs by channel**: audio-to-visual out-of-sync beyond roughly a few tens of ms is noticeable (heuristic); keep hit sound and hit flash aligned.
5. **Distinguish three feedback types**: *confirmation* (I did it), *result* (what happened), *state* (what's the world like now).
6. **Don't overload**: feedback that is always maximal teaches the player to ignore it. Reserve the loudest for the rarest.
7. **Uncertainty feedback**: for AI turns, long loads or matchmaking, show activity and an ETA.
8. **Reward feedback** should be fast (within the same action cycle) but may be staged (impact -> numbers -> loot drop -> summary).
9. **Haptics** are an accessibility channel too (DualSense adaptive triggers can encode state); never make them the only channel.
10. **Telegraph vs reaction**: if the player cannot react in time, they cannot learn. A fair attack has telegraph length >= human reaction time + input time + a margin; tune to difficulty.

Game-feel details are in `03-core-loops-and-mechanics.md`.

---

## 7. Controls, Input Mapping and Camera

### 7.1 Controls

1. **Match input to verb frequency**: most frequent action on the most accessible control (e.g., face button under the thumb), rare actions on harder-to-hit ones (stick clicks, d-pad).
2. **Reduce simultaneous demands**: avoid requiring two thumbs to leave sticks while still aiming; offer toggle alternatives to hold inputs (sprint, aim, crouch).
3. **Consistency across contexts**: confirm/cancel, interact, and menu navigation uniform in-world and in UI.
4. **Remapping is a baseline** (Game Accessibility Guidelines basic tier covers control remapping/alternatives): allow rebinding of all inputs for all supported devices, including mouse buttons and controller. Allow two controls to share a key where logical.
5. **Input buffering, coyote time, and forgiveness windows**: accept input slightly early or late (often 3-8 frames for platformers; heuristic) to match player intent.
6. **Aim assist** and targeting help on gamepad shooters are standard fairness mechanisms; expose strength options.
7. **Dead zones and sensitivity**: configurable stick dead zones, response curves, invert Y, per-axis sensitivity, FOV.
8. **Contextual actions**: one button, many meanings is efficient but risks mis-inputs (jumping vs vaulting vs climbing). Give strong signifiers for the current context and consistency in prioritization.
9. **Avoid rapid mashing** and long holds as the only option; provide alternatives (hold vs toggle, mash-free "auto" option, reduced QTE).
10. **Platform conventions**: confirm/cancel positions differ by region and platform (e.g., Japan vs West on some consoles); follow platform requirements and offer swap.
11. **Cross-device parity**: mouse+keyboard, gamepad, touch, adaptive controllers (Xbox Adaptive Controller) all supported by remappable input layers.
12. **Touch controls**: large hit targets (platform HIG guidelines suggest roughly 44-48 pt/dp minimum), thumb reach zones, no precision at screen edges, avoid occluding the action with your own thumbs.
13. **Show the controls on-screen** with the actual device glyphs (auto-detect last input device), not generic "press A".
14. **Tutorial prompts** should be removable once learned and re-showable on demand.
15. **Cooldown and charge indicators** should map to the button's position or icon.

### 7.2 Camera

- **Camera is a UX system**: it determines what the player can perceive. Principles from third-person action and platformer practice: keep the player visible, avoid blocking by geometry (collision/occlusion fade), minimize unexpected automatic rotation, keep horizon stable, and let the player recenter.
- **Control authority**: player-controlled cameras need sensitivity/inversion options; auto-cameras should be gentle, predictable and overridable.
- **Field of view**: provide an FOV slider on PC (and consider console); wide FOV can reduce discomfort for some players, narrow for others. Motion sickness triggers include head bob, camera shake, motion blur, low frame rate and FOV mismatch; provide toggles (see 11.11).
- **Framing for readability**: keep important enemies and hazards on screen; add off-screen indicators; zoom to the density of threats (many action games and strategy cams).
- **Cutscene transitions**: avoid sudden camera snaps that cause disorientation; preserve the orientation when handing back control.
- **Lock-on and soft target** options reduce motor demands.
- **VR**: comfort modes (snap turning, vignette on movement, teleport locomotion), seated mode, adjustable height, avoid forced camera movement.

### 7.3 Input and Interaction Laws

Three well-tested models of human movement and choice time. They give relative estimates for comparing designs, not exact predictions; fit `a` and `b` from your own playtest data per device (mouse, stick, touch).

- **Fitts's law** (Fitts 1954): movement time to a target `MT = a + b * log2(D/W + 1)` (the common Shannon form), where `D` is distance to the target and `W` its size along the movement axis. Bigger and closer targets are faster to acquire; doubling `W` saves about one "bit" of difficulty.
  - UI: make frequent or critical buttons large and close to where the cursor or thumb already is; use screen edges and corners (infinite depth for mouse cursors); keep destructive actions small, far, or confirmed.
  - Aim assist: it works partly by enlarging effective `W` (target stickiness, bullet magnetism, slowdown over targets) or shrinking effective `D` (snap to target); tune its strength by genre and input device, since sticks are far slower than mice.
  - Touch: use targets of roughly 7-10 mm (about 44-48 pt or dp as platform guidelines suggest); leave spacing so fingers do not hit neighbours; place primary actions in the thumb zone; remember the finger occludes the target.
- **Hick-Hyman law** (Hick 1952, later extended by Hyman): choice reaction time `RT = a + b * log2(n + 1)` for `n` equally likely options. Time grows with the logarithm of the number of choices, so splitting a big flat list into a few well-chosen groups can beat a long list.
  - Menus: group into categories with 5-9 items (a heuristic, not a law), put frequent items first; use search or favourites for very long lists.
  - Radial menus: 6-8 slots keep selection fast and direction-based (Fitts-friendly because angle is large); beyond that, nest or use pages.
  - Ability bars: a handful of readily available abilities with consistent slots lets players act by habit; the law applies to unpracticed choices, and expert players with practiced mappings and predictable options react faster than it predicts.
- **Steering law** (a Fitts extension for path movement): time to move through a constrained path of width `W` and length `A` grows with `A/W`. It applies to tunnels, narrow corridors, drag-through-menu paths (cascading submenus), and racing lines; wide, forgiving paths and diagonal-tolerant submenus keep movement fast.
- **Practical implications**: make targets bigger before making them faster; reduce the number of simultaneous choices at decision points; speed and accuracy trade off, so decide whether a task should reward precision (small targets, tight paths) or flow (large targets); validate by measuring selection time and error rate in tests.

---

## 8. Readability

Readability is whether players can quickly and correctly interpret what is on screen and what will happen next. Particularly vital in action, competitive and strategy games.

### 8.1 Silhouettes and shape language

- **Silhouette test**: fill characters/enemies with solid black; can you tell classes apart? *Team Fortress 2* designed classes with distinct silhouettes (Valve, Mitchell et al. 2007, "Illustrative Rendering in Team Fortress 2", and Valve's design talks) so players identify roles at a glance, with color temperature separating teams.
- **Shape language**: round = friendly/safe, square = stable/sturdy, triangle = dangerous/fast. Use consistently as a heuristic, not a law.
- **Size communicates threat and role** (big = tanky or slow).

### 8.2 Color coding

- **Limited, consistent palette** with semantic meaning: team colors, rarity tiers, threat levels, interactables.
- **Value (brightness) contrast** is more robust than hue contrast for all players, including those with color vision deficiency.
- **Rarity tiers**: the conventional white/green/blue/purple/orange scheme works because of convention; add icons/borders/sparkle so that it does not depend on color alone.
- **Avoid color collisions**: gameplay colors against environment colors (red enemy in red lava). Use outlines or rim light for contrast guarantee.
- **Ensure sufficient contrast** for text and UI: WCAG 2.2 suggests 4.5:1 for normal text and 3:1 for large text and UI components (W3C 2023); a useful baseline for in-game UI.

### 8.3 Telegraphs

- Enemy attack telegraph = **wind-up animation + audio cue + optional ground marker/color flash**. Attack types can be mapped to distinct cues (e.g., unblockable flash in *Sekiro*'s "Perilous Attack" kanji warning and sound; red/yellow flash in *Dark Souls*-likes; ground AoE decals in MMOs and *Hades*).
- **Telegraph consistency**: the same visual means the same response (parry, dodge, jump). Teach each in safe conditions.
- **Telegraph duration vs difficulty**: shorten the telegraph (or add fakes) to raise difficulty, rather than inflating damage.
- **Off-screen threats** need directional audio/visual indicators.
- **Time-to-read**: players should be able to distinguish the telegraph from "visual noise" from VFX; reduce particle clutter around key signals.

### 8.4 Clutter management

- Cap simultaneous high-saliency effects. *Overwatch* and *Apex Legends* set rules for VFX opacity and color for friendly vs enemy abilities (friendly effects are dimmer; enemy effects are bright and sharp), a pattern widely cited in shooters (industry practice).
- Provide an option for reduced effects/particles, and for high-contrast enemy outlines (see 11).
- **Readability at distance and low resolution**: test at the lowest supported resolution and on handhelds.
- **Strategy and MOBA readability**: unit icons and health bars at low zoom, selection circles, attack ranges, fog-of-war states, minimap pings.

### 8.5 Readability checklist

1. Can I tell friend from foe in 200 ms in the busiest scene?
2. Can I tell what threatens me and from which direction?
3. Can I tell what I can interact with?
4. Can I tell what an attack will do before it lands?
5. Does it pass a grayscale screenshot test? A colorblind simulation test? A small-screen test?
6. Can a viewer (spectator, streamer) understand the state? (esports value)

---

## 9. Biases, Persuasion and Ethical Use

Behavioral economics and psychology document systematic biases. Games can use them to create tension and meaning, or to exploit players. Industry practice: use them to *clarify and motivate*, never to deceive or to push spending beyond informed intent.

| Bias / effect | Description (established unless noted) | Legitimate use | Exploitative use |
|---|---|---|---|
| **Loss aversion** (Kahneman and Tversky 1979, Prospect Theory) | Losses feel larger than equivalent gains (commonly estimated around 2x; varies by context - heuristic for design) | Risk/reward tension (roguelike run loss, banked vs unbanked loot), meaningful stakes | Streak-loss pressure, "your items expire", limited-time purchase pressure |
| **Endowment effect** | Valuing what you own more | Housing, collection customization, item attachment | Free trials of power items then removal |
| **Sunk cost fallacy** | Continuing due to past investment | Long-term goals, commitment to characters | Making quitting painful via spent currency, streaks |
| **Variable-ratio reinforcement** (Skinner) | Unpredictable rewards sustain repetition | Loot excitement, discovery | Gacha without transparent odds and safeguards |
| **Near-miss effect** (gambling research) | Almost winning is motivating | Subtle: nearly-cleared run encourages retry | Slot-machine style near-miss displays in paid randomization |
| **Anchoring** | First number shapes perceived value | Price comparison of item tiers | Inflated "was" prices and manufactured discounts |
| **Scarcity / FOMO** | Rarity increases perceived value | Seasonal flavor with fair return or catch-up | Hard limited-time pressure on the young or compulsive |
| **Social proof** | Others' behavior guides ours | Leaderboard ranks, "popular builds" | Fake counters, urgency messages |
| **Zeigarnik effect** (heuristic evidence) | Unfinished tasks remain mentally active | Quest logs, cliffhangers | Endless checklists and daily-login chains |
| **Goal gradient** | Effort increases near the goal | Progress bars toward rewards | Placing paywall just before the end |
| **Default effect** | People accept presets | Safe defaults for accessibility and privacy | Pre-checked purchases, auto-renew without clarity |
| **Hyperbolic discounting** | Prefer rewards now | Instant feedback | Time-skip purchases ("pay to avoid waiting") |
| **Mental accounting / currency obfuscation** | Premium currency detaches from real money | Convenient currency for multi-region pricing | Bundle sizes that never match item prices, hiding real cost |
| **Reciprocity** | Gifts create obligations | Welcome gifts | Guilt gifts that lead to spending |

Ethical principles (my judgment, consistent with the Dark Patterns literature, see references/09):
1. **Informed**: the player understands what they get, when and at what cost, including odds and real-money equivalents.
2. **Voluntary**: no mechanism that works only because the player is fatigued, rushed, impaired or a child.
3. **Reversible**: refunds, undo, parental controls, spend limits.
4. **Beneficial**: the design should leave the player better off by their own reflective standards; ask "would a player thank us for this if they saw the telemetry?"
5. **Test for exploitation**: if a technique stops working once explained to the player, it is manipulation.

---

## 10. The Fun of Failure

Failure is the engine of learning, tension and stories - when it is *legible, fair and cheap*.

- **Fun of failure (Juul 2013, *The Art of Failure*)** describes the "paradox of failure": players seek out games that make them fail and feel inadequate, because failure is tied to challenge, learning and improvement. Juul argues players want failure to be **their fault** (attributable to skill), and to be able to improve. Unfairness or randomness that is not attributable breaks this contract.
- **Properties of good failure**: (1) clear cause (I know what killed me), (2) reachable improvement (I know what to change), (3) fast retry (seconds, not minutes), (4) proportional penalty (lost time, not lost hours), (5) preserved progress (learned info, partial unlocks, meta progress), (6) respectful tone (no mocking unless tone-appropriate).
- **Failure as content**: *Hades* writes new dialogue for deaths; *Dark Souls* keeps the sting yet offers corpse runs; *Dead Cells*/*Spelunky* make failure a loop with variance; *Super Meat Boy* and *Celeste* make retries nearly instant; *Hitman* and *XCOM* generate stories from failure.
- **Failure types**: skill failure (execution), decision failure (strategy), knowledge failure (didn't know), and luck failure (variance). Luck failure is acceptable when stakes are low or the player has mitigating tools; avoid it as the sole cause of costly losses.
- **Learned helplessness risk**: repeated failures with no learnable pattern produce disengagement; adaptive hints, assist options and rubber-banding of resources can restore agency.
- **Death/penalty design**: choose between punishing (lose resources, rewind to checkpoint), neutral (restart quickly), and productive (death yields progress). Match to genre and audience; allow adjustment where possible (see 11 and `05-progression-difficulty-onboarding.md`).
- **Post-failure UX**: show a recap (what happened, how to improve), immediate retry on the same button, and let players change settings or loadouts without leaving the flow.
- **Social failure**: in multiplayer, protect players from public humiliation (see `10-multiplayer-and-social.md`).

---

## 11. Accessibility

### 11.1 Why and how to start

Why: Around 1 in 4 US adults reports some disability (CDC estimate, 2022 data from the CDC's Disability and Health data system; verify the current figure when quoting). Disability includes permanent, temporary (broken arm) and situational (holding a baby, bright sun, noisy room) conditions. Accessible design widens the audience, improves usability for everyone (curb-cut effect) and is increasingly an expectation and, for some features (chat, communications), a legal requirement.

Principles:
1. **Plan from day one.** Retrofitting remapping, subtitles and difficulty options late is costly.
2. **Offer options, not one "accessible mode".** Different needs combine; granular settings (as in *The Last of Us Part II*) beat a single toggle.
3. **Don't make the player apply for help**: surface settings at first launch and in-game.
4. **Never rely on a single sensory channel** (color only, sound only, haptics only).
5. **Consult and test with disabled players** early and throughout. "Nothing about us without us."
6. **Preserve intent**: accessibility options should help players reach the experience, not necessarily dilute it. Let players choose.
7. **Document** accessibility features in store pages and release notes (Steam and console stores have accessibility tags/ratings).

Process steps:
1. Audit for the Game Accessibility Guidelines basic tier.
2. Add intermediate-tier items by priority (impact vs cost).
3. Build an accessibility settings menu with preview.
4. Test with disabled players or consultancies (e.g., AbleGamers, Can I Play That?, Games for All, SpecialEffect).
5. Publish an accessibility statement.

### 11.2 Game Accessibility Guidelines

The Game Accessibility Guidelines (gameaccessibilityguidelines.com), a collaborative reference of game developers, academics and specialists, organizes recommendations in three tiers (**Basic**, **Intermediate**, **Advanced**) across **motor, cognitive, vision, hearing, speech and general** categories. Tier definitions (paraphrased from the site): Basic = easy to implement and broadly useful; Intermediate = needs some planning; Advanced = needs substantial resources or is design-specific.

Examples by category (representative, not exhaustive; check the site for the current full list and exact wording):

| Category | Basic | Intermediate | Advanced |
|---|---|---|---|
| **Motor** | Allow controls to be remapped/reconfigured; ensure that all areas of the user interface can be accessed using the same input method as gameplay; avoid requiring repeated rapid button presses (provide alternative); include an option to adjust the sensitivity of controls | Include a cool-down or timeout period for commands; avoid hold inputs without toggle alternative; allow assist to complete complex gestures | Allow gameplay to be paused and resumed in real time; support input devices like switches, eye tracking |
| **Cognitive** | Allow the game to be started without needing to navigate through multiple levels of menus; use an easily readable default font size; ensure that no essential information is conveyed by a persistent flashing or strobe | Provide an option to turn off or alter any time limits; offer a way to review tutorials and objectives; provide in-game guidance | Include a mode that allows simplification of complex game mechanics; offer adaptive difficulty with clear explanations |
| **Vision** | Ensure that no essential information is conveyed by color alone; provide high contrast between text/UI and background; allow brightness/contrast adjustment | Provide a choice of colour palette or a high-contrast mode; allow HUD scaling; provide audio cues for visual-only info | Provide a screen reader or text-to-speech for menus and gameplay; implement audio navigation aids |
| **Hearing** | Provide subtitles for all important speech; make sure that all important information conveyed by sound is also conveyed visually; separate volume controls | Provide subtitle options (size, color, background); provide closed captions for non-speech audio and indicate speaker; visual indicators for directional sound | Provide sign language options or full captioning with directional audio visualization |
| **Speech** | Do not make voice input required; provide alternatives for voice chat (text, pings) | Provide text-to-speech and speech-to-text for chat | Provide quick chat wheels, context-sensitive messaging |
| **General** | Let players save at any time or provide generous autosaves; provide details on accessibility features on the platform page/packaging; offer difficulty settings | Allow players to turn off screen shake, motion blur, flashing; provide a way to skip or fast-forward cutscenes | Include accessibility in playtests; support platform-level accessibility features |

Use the site as a checklist: it provides rationale, examples of games implementing each item and links.

### 11.3 Xbox Accessibility Guidelines

Microsoft's **Xbox Accessibility Guidelines (XAG)** are a set of numbered guidelines (XAG 101 to XAG 123 in the published list) and best-practice guidance for game developers, intended to be used from concept through certification (Microsoft Learn, "Xbox Accessibility Guidelines"). Topics include (check the documentation for exact numbering): text display and size, audio and visual cues, input (remapping, simple alternatives, adaptive controller), UI navigation, difficulty and gameplay settings, communications (chat transcription / text-to-speech), photosensitivity, motion, and accessibility feature descriptions in store. Each guideline includes a goal, scope, rationale, implementation guidance, and tests, which makes them usable as QA checklists. They overlap strongly with the Game Accessibility Guidelines; use whichever your platform requires, and map between them.

Practical way to use XAG:
1. Add accessibility acceptance criteria to every feature spec (e.g., "text >= XAG minimum size; contrast verified").
2. Add accessibility test cases to QA test plans (remap everything, subtitles on all dialogue, colorblind pass).
3. Use the "Accessibility feature tags" in the Microsoft Store to advertise support.

### 11.4 AbleGamers APX patterns

The AbleGamers Charity's **Accessible Player Experiences (APX)** (accessible.games) is a set of design patterns (a pattern-language format: problem, solution, examples) for common accessibility needs, written by AbleGamers with consultants. Patterns are organized by the barrier they address, e.g.:

- Alternative control schemes and input remapping; multiple input methods simultaneously.
- Controller/hold-to-toggle conversions, reduced input complexity, one-handed layouts.
- Adjustable timing and pause in real-time contexts.
- Presentation: subtitles and captions, color options, UI scaling, audio cues, haptics.
- Difficulty: assist modes, auto-aim, guide aids.
- Communication: alternatives to voice (text, ping/wheel).

How to apply: read the pattern relevant to a mechanic you are designing (for example, an aiming mechanic), then check implementation examples and ensure your design supports the alternatives from the start.

### 11.5 CVAA and legal context

- **CVAA (21st Century Communications and Video Accessibility Act, US, 2010)**: in games, it requires that **advanced communications services** (voice chat, text chat, and similar player-to-player communications) in games be accessible to people with disabilities (usable by deaf/hard-of-hearing, blind, motor-impaired players), with menu navigation for communications features covered as well. FCC waivers for video game software expired on 31 December 2018; the requirements apply from 1 January 2019. Common compliance: text-to-speech for text chat, speech-to-text for voice chat, accessible UI navigation for chat features, and accessible sign-in. The FCC maintains consumer guidance on the CVAA. This is a summary, not legal advice; confirm obligations with counsel.
- **European Accessibility Act (EAA, Directive (EU) 2019/882)**: covers certain consumer products and services (including e-commerce services and some communications services) with a compliance date of June 2025; applicability to games depends on features (e.g., store, communications). Seek legal advice.
- **Platform requirements**: console certifications increasingly reference accessibility (check current platform docs).
- Treat law as the floor. Design to the guidelines above.

### 11.6 Case studies

**The Last of Us Part II (Naughty Dog, 2020)**: shipped with 60+ accessibility options (the developer and press cited "more than 60"), including presets for vision, hearing and motor needs; a first-launch screen offering to enable presets; extensive remapping; hold-to-toggle options; high-contrast display mode that shows allies, enemies, objects and environment in distinct colors; text-to-speech for menus and cutscenes; navigation assistance; audio cues for pickups, combat and navigation; adjustable enemy and ally "lock on", infinite breath, and the ability to adjust enemy aggression, resources and so on separately instead of one difficulty slider; and it was reportedly playable by blind players using audio cues. It also won accessibility awards (e.g., Game Awards 2020 Innovation in Accessibility). Lessons: granularity, early surfacing, deep audio design, and consulting disabled players during development (the studio worked with accessibility consultants including blind and deaf players).

**Celeste (Maddy Makes Games, 2018) Assist Mode**: optional adjustments to game speed (50%-100% in steps), infinite stamina, air dashes (extra), invincibility, skip chapters. The game's own assist menu text frames the options as a way for each player to enjoy the game their own way (read the in-game wording before quoting). Lessons: letting players adjust challenge without shaming; assist is granular and adjustable mid-game; the fiction supports the theme (self-compassion). Intent preserved by being optional, and by not locking achievements arbitrarily.

**Forza Motorsport / Forza Horizon (Turn 10 / Playground)**: includes blind driving assistance (audio cues for corners/steering), ASL (American Sign Language) in-game support for cutscenes and ASL interpreter videos for cutscenes in Forza Horizon 5, customizable difficulty and assists (braking, steering, traction), high contrast and large text, and visual/haptic cues. Lessons: audio-based interpretation of a visual-spatial task; identifying core player needs (feedback about road ahead) and translating them to another sense.

**Gears of War / Gears 5 (The Coalition)**: a large menu of accessibility settings: high-contrast mode with distinct colors for allies, enemies, objects; text size and subtitles options; narration of menus; hold/toggle/auto options; "Game Speed" slider; "Aim assist" options; "Skip" for sections; and later in Gears 5, Game Speed, Auto Aim, and "Hold to Toggle". Lessons: AAA action games can maintain challenge while giving numerous access tools; ship a high-contrast mode where readability is shooter-critical.

Other noteworthy: *God of War Ragnarok* (2022) large option set and presets; *Spider-Man* series (accessibility presets, QTE removal, audio cues); *Hades* God Mode (incremental damage resistance after each death); *Madden*/*FIFA* style sports games with adjustable assist; *Fortnite* Sound Visualization, which displays footsteps, chests and gunfire as on-screen visual markers for deaf and hard-of-hearing players (and benefits all players).

Verify specific features and numbers against the developers' official posts before stating them as facts in deliverables.

### 11.7 Colorblind design

Facts (established): About 8% of men and 0.5% of women of Northern European descent have some form of color vision deficiency (CVD); prevalence differs by population. The most common are red-green types: **deuteranomaly/deuteranopia** (green-weak/blind), **protanomaly/protanopia** (red-weak/blind); **tritan** (blue-yellow) types are rare.

Design rules:
1. **Redundant encoding**: pair color with shape, icon, pattern, text, position, or animation. Team colors: add emblem/outline shapes, name tags and different silhouettes.
2. **Use luminance (value) contrast** in addition to hue; test in grayscale.
3. **Avoid red-green pairs** as the only difference (health vs shield, friend vs foe, safe vs danger). Blue/orange pairs are generally more distinguishable across common CVDs (heuristic; validate by simulation).
4. **Offer colorblind modes** (deuteranopia, protanopia, tritanopia filters) and *custom* color pickers for key elements (team, outline, UI); filters that shift the entire screen can harm art direction, so prefer palette swaps for gameplay-critical elements. Provide a live preview.
5. **Simulate** during development (in-engine post-process, Photoshop/Coblis/Color Oracle/Sim Daltonism, console system filters), but simulations are approximations; test with real CVD players.
6. **Legends and labels**: charts, graphs and maps must be labelled, not just coloured.
7. **Rarity, status effects, minimap markers** are frequent offenders: add icons.
8. **Poker/card games**: suit colors vs shapes, use four distinct colors or shape-based indicators.

### 11.8 Subtitles and captions

Best practices (drawing from the Game Accessibility Guidelines, XAG and subtitle research by the Games Accessibility community):
1. **On by default**, or ask at first launch (many players need or want them).
2. **Subtitles** = dialogue; **closed captions** = dialogue plus non-speech audio ("[explosion]", "[footsteps behind you]"), music mood, and off-screen sound with direction.
3. **Size options**: at least 3 sizes with the default relatively large; testing shows many games ship defaults too small for TV viewing (verify via your own tests).
4. **Contrast and background**: provide an opaque or semi-transparent background box (adjustable opacity), plus color/outline options; ensure contrast per WCAG-like guidance.
5. **Speaker names** and **color-coded speakers** (with name text so that color is not the only identifier).
6. **Line length and timing**: roughly 35-42 characters per line (broadcast standard heuristic) and maximum two lines; display long enough to read (reading speeds in subtitling guidance are often around 15-20 characters per second; heuristic) and synchronize with speech.
7. **Placement**: bottom-center near, but not on, the action; avoid overlapping HUD; allow repositioning when possible.
8. **Everything spoken gets subtitles**: including barks, radio chatter, tutorial voice-overs, and cutscenes; with an option to include direction indicators for off-screen speakers.
9. **Menus and tutorial text should be fully subtitled/text-based**, not audio-only.
10. **Localization**: leave room; handle all supported languages; include scripts for languages with different line-breaking.
11. **Test** with deaf and hard-of-hearing players and ensure that speech-critical gameplay information has a visual alternative.

### 11.9 Motor accessibility checklist

- [ ] Full remapping for every device; allow simultaneous multiple input sources.
- [ ] Hold-to-toggle options; no required rapid mashing or long holds without alternatives.
- [ ] One-handed or reduced-button layouts; reduce simultaneous button presses.
- [ ] Adjustable sensitivity, dead zones, aim assist; auto-aim or lock-on options.
- [ ] No time-limited input requirements without option to extend/remove (QTEs skippable or slowed).
- [ ] Pause during real-time events where practical, or provide a slow-motion/game-speed option.
- [ ] Menus navigable using directional inputs only; large touch targets; no precision-drag required.
- [ ] Support for adaptive hardware (Xbox Adaptive Controller, switch inputs) via standard input APIs.
- [ ] Don't require voice, or provide alternatives.
- [ ] Reduce fatigue: allow autosprint/auto-run, auto-interact, autoloot.
- [ ] Avoid requiring precision timing as the only challenge; add assist options (wider windows, slow-down).

### 11.10 Cognitive accessibility checklist

- [ ] Clear, short, plain-language instructions; consistent terminology.
- [ ] Re-readable tutorials, objective reminders, searchable help and codex.
- [ ] Optional hints (progressive), waypoint/path guides, quest tracking.
- [ ] Adjustable or removable timers; pause anywhere.
- [ ] Reduce multitasking demands; offer simplified modes or fewer simultaneous enemies.
- [ ] Avoid flashing/strobing (see photosensitivity); allow reduction of screen shake, camera effects and visual noise.
- [ ] Persistent save/autosave and clear save indicators.
- [ ] Allow skipping and replaying story content; summaries of what happened.
- [ ] Avoid unexplained UI changes; keep layouts stable between sessions.
- [ ] Don't rely on memory: show control reminders.
- [ ] Dyslexia-friendly fonts or font options; line spacing; avoid long text blocks.
- [ ] Offer breaks: session timers/rest reminders if appropriate.
- [ ] Consider neurodiversity needs (sensory overload controls, predictable patterns, audio mixing options).

### 11.11 Vision, hearing and testing

**Vision**
- Text scaling, high-contrast UI, adjustable HUD scale, screen-reader/text-to-speech for menus, audio cues, navigation assistance, simplified visuals, and clear object highlights. Colorblind support (see 11.7). Blind accessibility: sound-based navigation, haptic cues, spatialized audio beacons (*TLOU2*, *Forza* blind driving assist).
- **Photosensitivity**: Avoid flashes more than three times per second and large saturated red flashes. The standard is WCAG 2.x "three flashes or below threshold" and the Harding test for broadcast (ITU-R BT.1702). Provide a warning and a "reduce flashing" option; test with Harding FPA or similar tools.
- **Motion sensitivity**: toggles for head bob, camera shake, motion blur, depth of field, field of view; stable horizon or dot reference; frame rate stability.

**Hearing**
- Separate volume sliders (master, music, SFX, dialogue, voice chat); mono audio; dynamic range (night mode) or compression; visual indicators for important sounds (damage direction, footsteps, alarms); captions; transcripts for voice chat; visual alternatives for audio puzzles.

**Testing**
1. Include accessibility in every milestone, not just pre-launch.
2. Recruit disabled playtesters across categories; compensate them.
3. Use checklists: Game Accessibility Guidelines, XAG, and APX patterns.
4. Observe real use; do not rely on simulation alone.
5. Log which settings players enable (telemetry) to learn what to default.
6. Fix reported barriers rapidly via patches; publish accessibility notes.

---

## 12. Worked Examples and Diagnostics

### 12.1 "Players miss the key pickup"
Symptom: 40% of playtesters pass over a required item.
Diagnosis: signifier failure (perception) or attention (high load area).
Fix ladder: (1) increase contrast/highlight, (2) add sound cue when near, (3) add light/motion, (4) reposition in sightline, (5) add UI prompt on approach. Retest. Track "time-to-pickup" and "pass-by count".

### 12.2 "Players die to an attack and think it's unfair"
Check: Was there a telegraph? Was it visible at the time (camera, VFX noise)? Was damage proportionate? Was the attack distinct from others? Did the player have a counter? Does the death recap say why? Fix telegraph and clarity before changing damage.

### 12.3 "Menu confusion in crafting"
Run a card sort and a first-click test. Likely issues: terminology, hidden requirements, no comparison view. Fix: show required materials with owned/needed counts, highlight craftable items, allow "craft max".

### 12.4 "Is my HUD too busy?"
Count persistent elements and animated elements. Test a "HUD off" run: which info did players ask for? Move those to contextual HUD; hide the rest behind a hold-button or pause.

### 12.5 "Add accessibility late in production"
Prioritize by impact/cost: (1) remapping and hold/toggle, (2) subtitles with sizes and backgrounds, (3) colorblind-safe indicators, (4) separate volume sliders, (5) screen-shake/motion toggles, (6) difficulty/assist options, (7) high-contrast mode, (8) text-to-speech. These typically cover the largest set of barriers.

### 12.6 Motivation audit of a progression system
Ask: if all rewards were removed, would the core action still be enjoyable? Does the system mainly create competence (new skills), autonomy (new choices), or only compulsion (daily streaks)? Replace compulsion loops with choice and mastery content.

### 12.7 UX review template
For each screen/feature: Goal -> Primary action -> Information needed -> Signifiers -> Feedback -> Errors/recovery -> Accessibility notes -> Test result -> Fix.

---

## 13. Common Pitfalls

1. Designing the UI for designers who already know the game; fix with fresh-eye tests.
2. Using color alone to convey status or team.
3. Tutorials that interrupt flow or cannot be reviewed.
4. Gating fairness behind information the player cannot see.
5. Treating accessibility as a single "easy mode" or a final-polish task.
6. Equating minimalism with clarity: removing the HUD can hide needed info.
7. Reward systems that turn play into work (overjustification), especially chores and daily tasks.
8. Heavy diegetic UI without a clear fallback.
9. Menus that require remembering multiple steps; unlabeled icon-only controls.
10. Inconsistent button mappings between contexts.
11. Small default subtitle and HUD text on TV.
12. Long unskippable cutscenes/animations in repeated loops (crafting, loot opening).
13. Ignoring input latency in action games, especially from display pipelines.
14. Hidden difficulty adjustments with no player agency (and no disclosure) - can feel manipulative.
15. Counting on survey opinion over observed behavior.
16. Misusing biases (loss aversion, FOMO) to convert; players notice and churn, regulators too.
17. Citing "7 plus or minus 2" as a design law for UI; prefer chunking and about 4 simultaneous items for working memory demands.
18. Assuming one color-blind filter fixes everything.

---

## 14. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Papers and standards**
- Ryan, R. M., Rigby, C. S., and Przybylski, A. (2006). The Motivational Pull of Video Games: A Self-Determination Theory Approach. *Motivation and Emotion*, 30, 344-360. https://doi.org/10.1007/s11031-006-9051-8
- Ryan, R. M., and Deci, E. L. (2000). Self-determination theory and the facilitation of intrinsic motivation, social development, and well-being. *American Psychologist*, 55(1), 68-78. https://doi.org/10.1037/0003-066X.55.1.68 (Companion to the "What and Why of Goal Pursuits" paper below.)
- Deci, E. L., and Ryan, R. M. (2000). The "What" and "Why" of Goal Pursuits: Human Needs and the Self-Determination of Behavior. *Psychological Inquiry*, 11(4), 227-268. https://doi.org/10.1207/s15327965pli1104_01
- Fitts, P. M. (1954). The information capacity of the human motor system in controlling the amplitude of movement. *Journal of Experimental Psychology*, 47(6), 381-391. https://doi.org/10.1037/h0055392
- Hick, W. E. (1952). On the rate of gain of information. *Quarterly Journal of Experimental Psychology*, 4(1), 11-26. https://doi.org/10.1080/17470215208416600
- Miller, G. A. (1956). The magical number seven, plus or minus two: Some limits on our capacity for processing information. *Psychological Review*, 63(2), 81-97. https://doi.org/10.1037/h0043158
- Cowan, N. (2001). The magical number 4 in short-term memory: A reconsideration of mental storage capacity. *Behavioral and Brain Sciences*, 24(1), 87-114. https://doi.org/10.1017/S0140525X01003922
- Fagerholt, E., and Lorentzon, M. (2009). *Beyond the HUD: User Interfaces for Increased Player Immersion in FPS Games*. Master's thesis, Chalmers University of Technology. https://publications.lib.chalmers.se/records/fulltext/111921.pdf
- Nielsen, J. (1994/2020). 10 Usability Heuristics for User Interface Design. Nielsen Norman Group. https://www.nngroup.com/articles/ten-usability-heuristics/
- Nielsen, J. (1993/2010). Response Times: The 3 Important Limits. Nielsen Norman Group. https://www.nngroup.com/articles/response-times-3-important-limits/
- Pinelle, D., Wong, N., and Stach, T. (2008). Heuristic evaluation for games: usability principles for video game design. *Proc. CHI 2008*, ACM. https://doi.org/10.1145/1357054.1357282
- Deci, E. L., Koestner, R., and Ryan, R. M. (1999). A meta-analytic review of experiments examining the effects of extrinsic rewards on intrinsic motivation. *Psychological Bulletin*, 125(6), 627-668. https://doi.org/10.1037/0033-2909.125.6.627
- Kahneman, D., and Tversky, A. (1979). Prospect Theory: An Analysis of Decision under Risk. *Econometrica*, 47(2), 263-291. https://doi.org/10.2307/1914185
- Simons, D. J., and Chabris, C. F. (1999). Gorillas in our midst: Sustained inattentional blindness for dynamic events. *Perception*, 28(9), 1059-1074. https://doi.org/10.1068/p281059
- W3C (2023). Web Content Accessibility Guidelines (WCAG) 2.2, quick reference. https://www.w3.org/WAI/WCAG22/quickref/

**Books**
- Hodent, C. (2017). *The Gamer's Brain: How Neuroscience and UX Can Impact Video Game Design*. CRC Press / Routledge. ISBN 978-1138089969.
- Norman, D. (2013). *The Design of Everyday Things* (revised and expanded ed.). Basic Books. https://jnd.org/
- Juul, J. (2013). *The Art of Failure: An Essay on the Pain of Playing Video Games*. MIT Press.
- Sweller, J., Ayres, P., and Kalyuga, S. (2011). *Cognitive Load Theory*. Springer.

**Accessibility resources**
- Game Accessibility Guidelines. https://gameaccessibilityguidelines.com/
- Microsoft. Xbox Accessibility Guidelines. https://learn.microsoft.com/en-us/gaming/accessibility/guidelines
- AbleGamers Charity. Accessible Player Experiences (APX). https://accessible.games/accessible-player-experiences/
- FCC. 21st Century Communications and Video Accessibility Act (CVAA) consumer guide. https://www.fcc.gov/consumers/guides/21st-century-communications-and-video-accessibility-act-cvaa
- PlayStation. The Last of Us Part II accessibility. https://www.playstation.com/en-us/games/the-last-of-us-part-ii/accessibility/
- Celeste (Maddy Makes Games). https://www.celestegame.com/

See references/13-bibliography.md for the master list.
