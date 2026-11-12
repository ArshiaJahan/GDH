# Progression, Difficulty and Onboarding

How players grow, how challenge keeps pace with that growth, and how a new player is taught. Load this for difficulty curves, DDA, tutorials, reward schedules, pacing and retry loops. Number-heavy tuning (XP formulas, drop odds) lives in `references/04-balance-and-economy.md`.

## Table of Contents

1. [One System, Three Jobs](#1-one-system-three-jobs)
2. [Progression Types](#2-progression-types)
3. [Reward Schedules](#3-reward-schedules)
4. [Extrinsic vs Intrinsic Rewards](#4-extrinsic-vs-intrinsic-rewards)
5. [Difficulty Curves](#5-difficulty-curves)
   - [5.1 Flow channel](#51-flow-channel)
   - [5.2 Sawtooth and other shapes](#52-sawtooth-and-other-shapes)
   - [5.3 What actually makes something hard](#53-what-actually-makes-something-hard)
6. [Difficulty Modes and Assist Modes](#6-difficulty-modes-and-assist-modes)
7. [Dynamic Difficulty Adjustment](#7-dynamic-difficulty-adjustment)
   - [7.1 Examples](#71-examples)
   - [7.2 Rubber-banding](#72-rubber-banding)
   - [7.3 Pitfalls and rules](#73-pitfalls-and-rules)
8. [Failure Design and Retry Loops](#8-failure-design-and-retry-loops)
9. [Checkpoints and Saves](#9-checkpoints-and-saves)
10. [Onboarding and Tutorial Design](#10-onboarding-and-tutorial-design)
    - [10.1 Principles](#101-principles)
    - [10.2 Case studies](#102-case-studies)
    - [10.3 Kishotenketsu](#103-kishotenketsu)
    - [10.4 Skill atoms](#104-skill-atoms)
    - [10.5 FTUE](#105-ftue-first-time-user-experience)
    - [10.6 Tutorial anti-patterns](#106-tutorial-anti-patterns)
11. [Pacing Across a Session and a Campaign](#11-pacing-across-a-session-and-a-campaign)
12. [Mastery, Skill Ceilings and Floors](#12-mastery-skill-ceilings-and-floors)
13. [Power Fantasy vs Challenge](#13-power-fantasy-vs-challenge)
14. [Worked Example: Platformer First Hour](#14-worked-example-platformer-first-hour)
15. [Checklists and Pitfalls](#15-checklists-and-pitfalls)
16. [References](#16-references)

---

## 1. One System, Three Jobs

Progression (what the player gains), difficulty (what the game asks) and onboarding (how the player learns to meet the ask) are one control loop:

```
player skill + player power  --meets-->  challenge
        ^                                    |
        |   learning, unlocks                |  success / failure + feedback
        +------------------------------------+
```

Design questions that tie them together:
1. What does the player **learn** (skill) and **gain** (power, options, content) at each stage?
2. What does the game **ask** at that stage, and is it answerable with what they have?
3. How does the player **find out** they are improving (feedback, visible mastery)?
4. What happens when they **fail** (cost, time to retry, information gained)?

If one of the four is missing, expect a standard complaint: "I don't know what to do" (no teaching), "it's too easy/hard" (mismatch), "I'm not getting anywhere" (no visible growth), "it's unfair" (failure without information).

## 2. Progression Types

Most games blend several. Name which ones you use and which carries the main motivation.

| Type | What grows | Examples | Strengths | Risks |
|---|---|---|---|---|
| **Power** (character) | Stats, damage, HP, gear | RPG levels, loot | Obvious reward, easy to pace | Treadmill; trivializes content; number inflation |
| **Skill** (player) | The player's own ability | Celeste, Dark Souls, fighting games | Durable, intrinsic, no content cost | Invisible unless you show it; walls for those who can't |
| **Content / access** | New areas, modes, mechanics | Metroidvania abilities, level unlocks | Novelty, curiosity | Pace is bounded by content production |
| **Options / breadth** | Number of viable choices | Skill trees, deck-building, unlocked verbs | Expression, replay | Choice overload; hidden dominant options |
| **Narrative** | Story reveals, relationships | Story games, visual novels | Emotional payoff | Pacing depends on writing |
| **Cosmetic / expression** | Looks, titles, emotes | Fortnite skins, card backs | Low gameplay impact; identity | Monetization pressure; no gameplay payoff |
| **Social / status** | Rank, reputation, guild standing | Ladders, leaderboards, titles | Strong long-term motive | Toxicity, exclusion |
| **Collection / completion** | Items, achievements | Pokedex, 100% completion | Clear goals | Checklist fatigue |
| **Account / meta** | Persistent unlocks across runs/seasons | Hades mirror upgrades, roguelite meta trees, battle pass tiers | Failure still produces gain | Can undermine challenge; can become a grind |

Guidance:
- **Skill progression is the most durable** (it cannot be bought, patched away, or exhausted) but has to be *surfaced*: replays, ghost races, ranks, personal-best markers, "you do this now without thinking" moments.
- **Power progression without skill growth** feels hollow; players quickly see through "numbers go up". Combine: power changes **what is possible** (new verb, new route) rather than only **how much** (+5% damage).
- **Make progression legible.** Show the next milestone, the distance to it, and what it unlocks. Unknown or opaque requirements remove motivation.
- **Meta-progression for failure-heavy games** (roguelikes) reduces the sting of loss: each run advances something permanent. In Hades the player's "God Mode" option, which makes the character stronger after each failed run, is an explicit form of this (Wikipedia, Hades); it sits next to ordinary meta upgrades.
- **Plateaus** are normal in skill learning; schedule new tools, goals, or content right before a typical plateau (see sawtooth, section 5).
- **Account/meta layer risks**: if a persistent power unlock makes early content trivial, you have changed the difficulty curve; re-scale or provide optional challenge modifiers (heat/ascension style).

## 3. Reward Schedules

Operant conditioning (Ferster and Skinner 1957) describes how the *timing* of reinforcement shapes behavior. Game designers use these patterns constantly, often unknowingly.

| Schedule | Rule | Behavior pattern (lab findings) | Game examples |
|---|---|---|---|
| **Fixed ratio (FR)** | Reward after every N-th response | High rate, brief pause after reward | "Collect 10 coins for a life"; "kill 20 enemies for a chest"; quest counters |
| **Variable ratio (VR)** | Reward after an unpredictable number of responses (average N) | Highest, steadiest rate; most resistant to extinction | Loot drops, crit procs, gacha pulls, slot machines, card packs |
| **Fixed interval (FI)** | First response after a fixed time yields reward | Rate rises as the time nears ("scallop"), pause after reward | Daily login bonus, energy refill, timed chests, fixed respawn timers |
| **Variable interval (VI)** | First response after an unpredictable time | Steady, moderate rate | Random world events, fishing bites |
| **Continuous** | Every response rewarded | Fast learning, fast extinction when removed | Tutorials, early levels, coin per hit |

(Summary of well-established laboratory findings; see Wikipedia, "Schedule of reinforcement", and the original Ferster and Skinner work. Human behaviour in games is much more complex than pigeon behaviour, so use this as a lens, not a prediction.)

How to apply:
1. **Teach with continuous reinforcement, then thin it out.** First kill gives a clear reward; later rewards come on a ratio. Removing rewards abruptly feels like a bug.
2. **Mix schedules in layers**: FR for short-term goals (a bar that fills), VR for surprise (a rare drop), FI for return habits (daily), plus long, deterministic goals (a milestone). The *predictable* layer provides trust; the *variable* layer provides excitement.
3. **Near-misses and visible odds**: displaying "almost won" outcomes is a known way to increase engagement in gambling; in games it is a design pattern with ethical consequences.
4. **Pair VR with a floor.** Variable rewards + a guaranteed minimum (pity, bad-luck protection) keep surprise without the worst-case frustration (see 04, section 6).
5. **Avoid reward inflation**: if everything rewards constantly, nothing registers. Scale reward size to effort and rarity, and reserve the biggest celebration for rare/meaningful achievement.

Ethical notes (practice and widely discussed concerns, not a legal opinion):
- Variable-ratio schedules tied to real-money spending (loot boxes, gacha) are **the** pattern regulators and researchers criticize; several jurisdictions now require probability disclosure or restrict them. See `references/09-monetization-and-live-ops.md`.
- Fixed-interval **daily** rewards with streak loss create compulsion-by-obligation ("fear of missing out"). Prefer catch-up/grace days, banked rewards, and no punishment for absence.
- Do not exploit vulnerable players (children, people with gambling problems): offer spending limits, transparent odds, cool-down prompts.
- A good test: **would the player endorse this loop if they understood exactly how it works?** If not, redesign.
- Rewards should **reinforce what the game wants players to enjoy** (skill, exploration, cooperation), not just consume time.

## 4. Extrinsic vs Intrinsic Rewards

- **Intrinsic motivation**: doing the activity for its own sake (the joy of a perfect jump). **Extrinsic**: doing it for a separate outcome (points, loot, badges).
- **Overjustification effect**: giving an *expected, tangible* reward for an already enjoyable activity can reduce later interest in it. Classic findings (Lepper, Greene and Nisbett 1973 with children's drawing; meta-analysis Deci, Koestner and Ryan 1999) show the effect is strongest for tangible, expected, contingent rewards, and weaker for unexpected rewards and for verbal feedback that is informational. (See Wikipedia, "Overjustification effect", and Deci et al. 1999.)
- **Self-determination theory** (Ryan and Deci): needs for **competence**, **autonomy** and **relatedness** drive sustained intrinsic motivation. Rewards that **inform** competence ("you executed a 5-chain") support it; rewards that **control** behavior ("do this to earn X") can undermine it.

Design guidance (applied; the research is mostly on non-game contexts, so treat transfer to games as a hypothesis):
1. **Make the core verb rewarding by itself** (game feel, mastery) before adding external rewards. If players need a bribe to do the core loop, fix the loop.
2. **Prefer informational rewards**: ranks showing skill, replays, personal bests, "you beat your last time" over generic points.
3. **Use unexpected rewards** (surprise discoveries) and **competence-supporting rewards** more than expected, contingent ones for activities that are intrinsically fun.
4. **Offer autonomy**: let players choose goals and order, not follow a single checklist.
5. **Be careful with achievements and daily quests** that turn exploration into a to-do list. Optional is better than mandatory; make them *describe* play rather than *prescribe* it.
6. **Rewards should scale with challenge**, not time spent.
7. **Playtest question**: "Would you still do this if the reward were removed?" If no, the reward is carrying the loop.

## 5. Difficulty Curves

### 5.1 Flow channel

Csikszentmihalyi's flow model (1990): an optimal experience occurs when **challenge matches skill**, with clear goals and immediate feedback. Challenge much above skill produces anxiety; much below produces boredom. Chen (2007) applied this to games and argued for letting players find their own channel through choices of path and risk, rather than a single forced difficulty.

Practical use:
- The channel is a **moving band**: as skill grows, the same challenge becomes boring, so challenge must rise. Skill also *drops* after a break (returning players), so rising challenge must be reversible (checkpoints, assist options, review levels).
- The channel is **individual**. A single curve cannot fit everyone; offer difficulty choice (section 6) and adaptive tools (section 7).
- Flow also needs **clear goals, feedback and sense of control** (Csikszentmihalyi's conditions). A perfectly matched challenge still fails if the player does not know what to do, or why they died.

### 5.2 Sawtooth and other shapes

A **sawtooth** curve rises into a peak (boss, set-piece, gauntlet), drops into a release (reward, rest, safe hub, new power), then rises again from a **slightly higher baseline**.

```
difficulty
   ^                      /|              /|
   |            /|       / |      /|     / |
   |    /|     / |      /  |     / |    /  |
   |   / |    /  |     /   |    /  |   /   |
   |  /  |   /   |    /    |   /   |  /    |
   | /   |  /    |   /     |  /    | /     |
   +------------------------------------------> time / levels
        peak/release     peak/release
```

Why it works: tension needs release to remain perceivable; releases let players consolidate learning; peaks give a feeling of accomplishment.

Variants and when to use them:
| Shape | Description | Use |
|---|---|---|
| Linear ramp | Steady increase | Short games, arcade; becomes monotonous in long games |
| Sawtooth | Rise, test, relief | Most campaigns |
| Stepped / plateaus | Long stable stretches, then jumps | Skill-learning games with clear tiers |
| "Roller-coaster" with a few spikes | Sharp peaks (set-pieces) in a lower baseline | Narrative action games |
| Flat-then-hard | Easy early, hard end | Risk: players leave before the good part; avoid unless the audience is selected |
| Front-loaded | Hard early, easier later | Roguelikes (early rooms are easiest, so it rises), puzzle games where learned tools simplify later puzzles |
| Player-driven | Difficulty depends on chosen risk | Open worlds, Metroidvanias (go elsewhere if stuck) |

Heuristics:
- **Each peak should test what was just taught** (skill atoms, section 10.4) and not something new.
- Ratio of **peak to release** time varies by genre; a rough heuristic is 1:2 to 1:3 (heuristic, test in your game).
- Add **optional spikes** (secret bosses, challenge rooms) rather than forcing every player to the top of the difficulty range.
- **Difficulty vs. resource curve**: if the player stockpiles consumables or power faster than the enemy scaling, the curve flattens; plan the resource economy against the difficulty curve (see 04).
- **Do not rely on stats alone** for difficulty (more HP, more damage); change the *demands* (new patterns, positioning, decision pressure).

### 5.3 What actually makes something hard

Difficulty is multi-dimensional. List what each encounter demands:
| Dimension | Example | Tuning knob |
|---|---|---|
| Execution | Precise inputs, timing | Window size, speed |
| Perception | Reading a crowded screen, sound cues | Telegraph clarity, clutter |
| Knowledge | Pattern memory, rules | Information shown, tutorials |
| Decision | Resource allocation, risk | Number of options, time pressure |
| Endurance | Long stretches without a checkpoint | Checkpoint spacing |
| Planning | Multi-step puzzle | Steps, branching |
| Stress | Time or threat pressure | Timers, enemy density |
| Randomness | Variance of outcomes | Probability, variance control |

Changing one dimension usually suffices; stacking all at once is how "unfair" difficulty is created. In accessibility terms, offering separate sliders for these dimensions (section 6) lets players tune the dimension they struggle with.

**Fair vs cheap difficulty** (heuristic checklist): the player could **perceive** the threat (telegraph), **understand** the rule, **respond** with available skill, and **learn** from failure. If any of the four is missing, failure feels cheap.

## 6. Difficulty Modes and Assist Modes

Options, from least to most intrusive:
| Approach | Description | Pros | Cons |
|---|---|---|---|
| Single authored difficulty | One experience | Cohesive vision | Excludes many players |
| Named presets (Easy/Normal/Hard) | Scalars on HP/damage/etc. | Simple, familiar | Often just number scaling; names can shame ("baby mode") |
| Modifier presets with different behaviour | Enemies act differently, not just stronger | Meaningful modes | More work to test |
| Granular assists | Sliders/toggles for specific dimensions | Maximum accessibility | Test matrix; some designers worry about vision dilution |
| Unlockable/harder modes after completion | Hard mode, new game plus | Replay | Gate behind a first playthrough |
| Self-selected challenge | Optional objectives, risk-reward modifiers | Autonomy | Needs good communication |
| Adaptive (DDA) | Game adjusts silently or visibly | Invisible help | Trust issues (section 7) |

**Celeste** (2018) is the standard case. Its Assist Mode lets players change game speed (50-100%), enable infinite stamina, set air dashes (default, two, or infinite), turn on dash assist and invincibility, and skip a chapter (via chapter select); it is framed as a way to make the game accessible; designer Maddy Thorson described it as a counterbalance to the optional hard content (strawberries, B-sides) which lets players customize difficulty (Wikipedia, Celeste, citing developer statements). Craft points worth stealing:
- The assists are **granular** (separate toggles), so players pick what they need.
- The game states the assists are for **play on your own terms** without shaming or locking features (tone and framing matter; avoid labels that insult).
- The core design supports it: **screen-sized rooms as natural checkpoints**, near-instant respawn, readable hazards. Low retry cost makes a "hard" game humane even without assists.

**Hades God Mode**: after each failed run, the player takes less damage (the exact scaling is a game detail; see the game's help text). It is an accessible, visibly-opt-in, and failure-driven assist (Wikipedia, Hades).

Rules for mode design:
1. **Don't just scale HP and damage**. Add or remove *mechanics* (more telegraphs on easy, fewer resources and extra threats on hard).
2. **Allow changing difficulty mid-game** where possible. Lock-in at the start punishes players who guessed wrong.
3. **Avoid shaming language** and avoid blocking story or achievements on lower modes unless truly necessary (competitive modes may require fairness: leaderboards can use per-difficulty boards).
4. **Test each mode**, not just Normal; Easy is often under-tested and becomes boring or broken.
5. **Describe modes by experience**, not by adjectives ("Story: focus on exploration, combat is forgiving").
6. **Provide hints and skips** (puzzle skip after N failures) as opt-in. Players choose to accept a spoiler.
7. **Intentional high difficulty is a legitimate design choice** (Dark Souls built its identity on high difficulty, per Wikipedia); the question is whether the difficulty supports the experience, and whether alternatives (summons, builds, shortcuts, difficulty-adjusting items) provide in-fiction ways to adjust. See `references/08-player-psychology-ux-accessibility.md` for accessibility guidelines.

## 7. Dynamic Difficulty Adjustment

DDA adjusts challenge in response to player performance (Hunicke 2005 discusses the case for DDA, with a research system named Hamlet built on Half-Life; see also Wikipedia, "Dynamic game difficulty balancing").

### 7.1 Examples

| Game | What it does | Notes |
|---|---|---|
| **Resident Evil 4** (2005) | An undocumented "Difficulty Scale" adjusts enemy aggression/health and drop behavior based on player performance (it was mentioned in the official strategy guide) | Wikipedia, DDA article. Invisible; players discuss it widely |
| **Left 4 Dead** (2008) | The **AI Director** controls pacing, enemy spawns and item placement by modeling each survivor's "emotional intensity", creating build-up, peak and relax phases | Wikipedia, Left 4 Dead; Booth 2009 for the design talk |
| **God Hand** (2006) | A visible meter regulates enemy intelligence and strength | Wikipedia, DDA article. Player can see the level |
| **Mario Kart** | Item distribution depends on position (trailing racers get stronger items) | Wikipedia, Mario Kart; a form of rubber-banding by items |
| **Hades God Mode** | Player-chosen, failure-driven damage reduction | See section 6 |
| **Rubber-band AI** in racing games | Computer cars speed up when behind and slow when ahead | Wikipedia, Rubber band AI |

**Left 4 Dead's Director** is an example of DDA aimed at **pacing and drama**, not only difficulty. It tracks recent stress (damage taken, incapacitations, proximity of enemies) and cycles through phases that guarantee peaks and relaxation. Takeaways (from Booth's design talk and general practice): (a) pace and variety make a short level replayable; (b) the same level plays differently each time; (c) adaptation is applied to **spawns and pacing**, which players read as drama rather than as rubber-banding.

### 7.2 Rubber-banding

Rubber-banding is a **negative feedback** loop applied to competitors: the leader is slowed or the trailing player is boosted, so races/matches stay close. See `references/04` and the SKILL core toolkit on feedback loops.
- **Good rubber-banding** is invisible, mild, and applies to resources (items, spawn quality) more than physics.
- **Bad rubber-banding** is obvious ("the AI cheats", "my lead means nothing") and **punishes skilled play**. Also called "catch-up" when applied to the human (acceptable) versus "cheating AI" when applied to the opponent's physics (resented).
- In competitive multiplayer prefer **catch-up mechanics** with a ceiling (comeback XP, rubber-band items) but never to the extent that leading is irrelevant.

### 7.3 Pitfalls and rules

1. **Exploitation**: players figure out DDA and game it (die on purpose to get easier enemies; play badly then ace the final). Use smoothing windows, don't trigger on a single failure, and never let the "underperform" path be optimal.
2. **Perceived unfairness**: if players learn the game was secretly helping or hindering them, trust and achievement feel suffer ("I only won because it went easy on me"). Hidden *helping* is more accepted than hidden *punishing*; be transparent where possible or keep adjustments in a tolerated range.
3. **Inconsistent skill measurement**: a performance proxy such as deaths-per-minute may measure frustration or exploration rather than skill. Use multiple signals (accuracy, damage taken, time-to-clear) and a long enough window.
4. **Dilutes mastery**: if the game always meets the player at their current level, skill growth never feels like it opens new possibilities. Keep fixed, authored challenges (bosses) so progress can be measured against something constant.
5. **Testing complexity**: DDA multiplies test cases. Log the DDA state in playtests and bug reports.
6. **Leaderboards/competitive modes**: DDA breaks comparability; disable it there.
7. **Prefer adjusting resources, not rules**: more ammo, fewer enemies in a spawn wave, faster checkpoint healing is less noticeable and less distorting than changing enemy accuracy or damage.
8. **Soft rails**: limit adjustment range (e.g. ±15% around the baseline - heuristic) so authored difficulty remains the experience.
9. **Make the help optional and visible when possible** (God Hand's meter, Hades's God Mode, "Do you want to lower the difficulty?" prompts after repeated deaths). Players accept help they chose.

## 8. Failure Design and Retry Loops

Failure is the engine of learning; the design problem is **cost** and **information**.

Components of failure cost:
| Cost | Meaning | Tuning |
|---|---|---|
| Time lost | Replaying already-mastered content | Checkpoint spacing, skip options |
| Resource lost | Items, currency, progress | Death penalties |
| Emotional load | Humiliation, tension | Tone, UI messaging |
| Cognitive load | Having to re-learn context | Retry briefings, visible goals |
| Opportunity | Losing an irreplaceable chance (permadeath) | Meta-progression |

Principles:
1. **Time to retry** should be shorter than the player's frustration decay. Instant restart (Celeste and Super Meat Boy are well known for it) makes thousands of attempts tolerable; a 3-minute reload makes three attempts intolerable. Heuristic targets: precision platformers under 2 seconds, action games under 10-15 seconds to be back in control, strategy/roguelike runs can be minutes if a run itself is meaningful.
2. **Failure should teach.** Show **why** the player died (kill cam, damage log, highlighted hazard), and make the cause attributable to the player's decisions rather than randomness.
3. **Fail forward**: let failure advance something (progress in the story, meta currency, knowledge), as in roguelites and many narrative games where defeat leads to a new scene.
4. **Reduce re-do of trivial parts.** If the player must replay a 90-second easy section before the 10-second hard one, either move the checkpoint or compress the easy section (see section 9).
5. **Rewind and forgiveness mechanics** reduce the sting while preserving challenge: Prince of Persia: The Sands of Time lets the player rewind up to ten seconds after a mistake (Wikipedia), turning failure into a mechanic; coyote time and input buffering forgive micro-errors (see `references/03-core-loops-and-mechanics.md`).
6. **Escalate help on repeated failure**: after N failures offer a hint, an assist, more resources, or a skip (opt-in). It addresses the frustration spike without reducing the default challenge.
7. **Permanent loss (permadeath)** works if runs are short, outcomes are mostly attributable to decisions, and meta-progression exists.
8. **Fair feedback on death**: the death must be explainable in one sentence ("I was hit by the third projectile because I jumped too early").
9. **Track "fail streak" telemetry** per encounter (attempts to clear, quit-after-fail rate); a spike marks a difficulty or teaching problem (see `references/12-playtesting-and-analytics.md`).

## 9. Checkpoints and Saves

| Type | Description | Best for | Risk |
|---|---|---|---|
| Per-screen/room | Respawn at start of current screen | Precision platformers | Needs short screens |
| Fixed checkpoints | Flags/bonfires/save points | Action-adventure | Too sparse -> long replays; too dense -> tension drops |
| Auto-checkpoint on progress | Saves after encounters | Narrative shooters | Players lose track of the state |
| Manual save anywhere | Player chooses | PC RPG/strategy | Save-scumming trivializes risk |
| Quick save/load | Fast manual | Immersive sims | Same |
| Limited saves | Save tokens/places | Survival horror (Resident Evil typewriter ribbons) | Anxiety; frustration if misjudged |
| Bonfire-style (resets enemies) | Rest to heal; world resets | Souls-like | Players stuck in loops of old content |

Rules:
- **Place checkpoints before challenges, not after**, and make sure the player is in a **viable state** (health, ammo, position) when they respawn. A checkpoint with 5% health and no ammo is a soft-lock.
- **Keep checkpoint distance proportional to challenge**: the harder the encounter, the closer the checkpoint (heuristic: re-run time under ~60 seconds for general action, under 10 seconds for precision challenges).
- **Never allow soft-locks** (a state where the player cannot progress). Always test saves taken at the worst moment (just before a death, in the middle of a transition).
- **Preserve rewards earned between checkpoints** where possible, or visibly bank them, to avoid anti-fun "lost progress" moments.
- **Show the save state** with clear, unobtrusive feedback (icon on saving).
- **Consider the platform**: mobile and handheld players are interrupted often; allow suspend/resume anywhere.

## 10. Onboarding and Tutorial Design

### 10.1 Principles

1. **Teach by doing, not telling.** The best tutorial is a situation where the only sensible action is the one you want to teach. Minimize text, especially before the first interaction.
2. **One new concept at a time, in a safe space.** Introduce -> practice with no/low risk -> test under light pressure -> combine with known skills -> twist (SKILL.md section 4.7).
3. **Let failure be cheap and instructive** during learning: no punishing death or resource loss before the player knows the rule.
4. **Context-sensitive teaching**: show the prompt when the action is needed, and remove it as soon as the player has done it ("just in time", not "just in case").
5. **Reach the core verb in under ~60 seconds** (heuristic; mobile and F2P often aim even lower).
6. **Show, then ask the player to do.** Demonstrate with an enemy/NPC, an environment tableau, or a brief animation; then give control.
7. **Visual language**: use consistent color/shape/sound for hazards, pickups, interactables. A good language reduces the need for text.
8. **Don't teach everything at once.** Advanced systems (crafting, economy, meta) should unlock when relevant, preferably through a first successful use.
9. **Respect experience**: allow skipping or fast-forwarding for veterans, and an easy way to **re-read** tutorials later (a help codex).
10. **Test with players who have never seen the game** and count: where do they hesitate, ask a question, press the wrong button? Each is a fixable teaching gap. Never rely on the designer's own sense (curse of knowledge).

### 10.2 Case studies

**Super Mario Bros. World 1-1 (1985).** Designed by Shigeru Miyamoto as a tutorial for platform gameplay (Wikipedia, "World 1-1"), at a time when tutorials were rare (Wikipedia, "Super Mario Bros."). Commonly cited analyses (design practice, widely discussed rather than a single documented source) note:
- The player starts at the left with open space and nothing lethal: they learn that moving right is the direction of progress.
- The first enemy (a Goomba) approaches slowly and can be avoided or stomped; death costs little. The player discovers both options by trying.
- Question blocks sit at jump height above the start; the first power-up (a mushroom) is positioned so that it is hard to avoid when released, teaching that it is beneficial rather than dangerous (Wikipedia, "Super Mario Bros.", on the design focus of mushrooms versus Goombas).
- Gaps and pipes introduce vertical jumping and obstacles with increasing demand, in an area with a visible safe return.
- No text is required: the teaching is the level.
Principle: **the level itself is the tutorial; each element is introduced in a safe context, then reused with higher stakes.**

**Portal (2007).** Its test chambers introduce one idea at a time: first moving through a placed portal, then placing portals with the gun, then momentum, then combining them with other elements, with minimal text and an environment that visually signals the intended solution. Chamber sequence is a ladder of skill atoms (section 10.4). The narrative frame (GLaDOS) explains why the player is being tested, which gives a reason for the tutorial structure (Wikipedia, Portal, for the core description of the test-chamber structure). Principle: **teach a tool in isolation, let the player play with it, then combine it.**

**Half-Life 2 (2004).** A commonly cited example of teaching through **scripted, in-fiction scenarios**: the gravity gun is introduced in a safe space with objects you can play with, followed by a situation that requires using it, then by combat uses. The player is never taken out of the first-person view for instruction. (Design-practice summary; I am not citing a specific source here, so verify specific claims before quoting.) Principle: **introduce a new verb in a playground, require it in a puzzle, then make it matter in combat.**

**Celeste (2018).** Teaches dash, climb and jump chapter by chapter with new mechanics (dashing crystals, moving platforms) introduced in one-screen rooms with cheap restarts. Each chapter's rhythm: introduce, vary, combine, twist, test.

### 10.3 Kishotenketsu

Kishotenketsu (ki-sho-ten-ketsu) is a four-part East Asian narrative structure: **ki** (introduction), **sho** (development), **ten** (twist), **ketsu** (conclusion/reconciliation). It has been applied to Nintendo's level design: Koichi Hayashida discussed the structure in connection with the level design of Super Mario 3D Land and Super Mario 3D World (Wikipedia, Kishotenketsu). In level terms:

| Phase | Level design meaning | Example (a "moving platforms" level) |
|---|---|---|
| Ki - introduce | Show the mechanic in safety | A platform moves over a harmless gap; player rides it |
| Sho - develop | Repeat with variations; simple challenges | Two platforms in sequence; one over a small hazard |
| Ten - twist | Use the mechanic in an unexpected way, or combine with another | The platform path crosses an enemy; or platforms disappear when stepped on |
| Ketsu - conclude | A final, satisfying use that ties it together | A gauntlet using both versions, ending in a reward |

Why it works for onboarding: it **builds a mental model, then challenges it with a twist, without needing a boss or conflict**. Compare to a western three-act structure: conflict-based (setup, confrontation, resolution). Kishotenketsu fits **puzzles and platformers** well because the challenge is derived from the mechanic itself.

Use as a checklist for every mechanic: **Where is the safe introduction? Where is the development? Where is the twist? Where is the conclusion?** A mechanic that appears with no twist feels like filler; a twist without an introduction feels unfair.

### 10.4 Skill atoms

Daniel Cook's "skill atom" model (Lost Garden) models a small unit of learning as a loop: the player performs an **action**, the game **simulates**, the player receives **feedback**, and updates a **mental model** (synthesis); and a "skill chain" links atoms where mastering one prepares the next. Applied to onboarding:
1. **Decompose each skill** you require into atoms (e.g. jump -> variable-height jump -> jump onto moving platform -> chain of timed jumps).
2. **Order atoms** so each prerequisite is learned before it is needed (dependency graph).
3. **Make sure each atom has clear feedback**; unclear feedback = atom not learned.
4. **Teach, then test, then combine**: a skill is tested alone before being combined (jump + enemy), because failures in a combined test are hard to diagnose.
5. **Spot missing atoms**: if players fail a challenge in playtests, ask which atom was never taught or never confirmed.
6. **Chain length** (how many atoms in a sequence) rises over time; mastery means chunking a chain into a single action.

Template (skill dependency table):

| Skill atom | Prerequisite | Taught by | Tested by | Combined with |
|---|---|---|---|---|
| Move | none | Open room | Reach goal | Jump |
| Jump | Move | Small gap | Wider gap | Enemy |
| Stomp | Jump | Slow enemy on flat | Two enemies | Gap |
| Wall-jump | Jump | Two close walls, no hazard | Wall shaft with spikes at the bottom | Moving platforms |

### 10.5 FTUE (first-time user experience)

The first minutes decide whether a player continues. FTUE is a designed sequence, not a single tutorial.

Structure (guideline):
| Minute | Goal |
|---|---|
| 0-1 | Fantasy and core verb: the player does the key action and gets a satisfying result |
| 1-5 | Core loop once, end-to-end (act, get reward, spend/upgrade, act again) |
| 5-15 | Second layer introduced (e.g. the first choice or upgrade), the first meaningful decision |
| 15-30 | Hook: a goal that lasts beyond the session, a reason to return |
| Session end | A natural stopping point with a "next time" goal visible |

Checklist:
- [ ] Is there a playable moment before any menus, long cutscenes, sign-ins or permission dialogs?
- [ ] Does the player see the fantasy/hook within the first minute?
- [ ] Is the first success guaranteed (cannot fail before learning)?
- [ ] Is each instruction shown at the moment of need, and dismissed by doing?
- [ ] Is text under ~15 words per prompt (heuristic) and readable on the target screen?
- [ ] Is there something to look forward to (visible unlock, next goal)?
- [ ] Are optional or advanced systems deferred?
- [ ] Is the tutorial skippable / replayable?
- [ ] Did we measure funnel drop-off per step (see 12-playtesting)? Typical analysis: step completion rate, time per step, retry counts, drop points.
- [ ] Is the tutorial's difficulty equal to or below the first real level?
- [ ] Did we test on accessibility settings (screen reader, one-handed, colorblind)?

F2P/mobile note: monetization prompts, notification permission requests and forced social sign-ins in the first session are common retention killers; delay them until after a success moment.

### 10.6 Tutorial anti-patterns

| Anti-pattern | Why it fails | Fix |
|---|---|---|
| Wall of text | Not read; no practice | Break into prompts at the moment of use |
| "Press X" for everything | Unlinked from context, boring | Use level geometry and goals to teach |
| Long unskippable intro | Veterans leave | Skip option; start playing |
| Forced tutorial for the same mechanic every game | Wasted time | Skip based on detected experience |
| Hand-holding after mastery | Insulting | Fade assist prompts once the action has been done N times |
| Teaching late | Players die to unknown rules | Introduce before first required use |
| Teaching via death with no feedback | Frustration | Show why failure happened |
| Overloading with all verbs | Cognitive overload | Gate behind skill atoms |
| Tutorial different from real game | Misleading | Use the real systems in a sandbox |
| No re-access | Players forget | Codex, tooltips, practice room |
| Fake tutorial difficulty | Players think the game is easy, then hit a wall | Honest difficulty ramp; show a taste of real challenge |

## 11. Pacing Across a Session and a Campaign

**Session level (5-60 minutes).** Design a rhythm in each session:
1. **Entry** (low friction, returns to the state they left; a reminder of the goal).
2. **Build** (a rising series of decisions/challenges).
3. **Peak** (a boss, an objective, a tense decision).
4. **Payoff** (reward, progress).
5. **Exit hook** (the next goal, or a natural save point). Mobile sessions are often 2-5 minutes; console 30-120; make sure the session has a natural end.

**Campaign level (10-100 hours).** Think in acts and chapters:
- **Introduction** (verbs, fantasy), **expansion** (more tools, wider world), **complication** (twists on tools, tougher challenges), **climax** (mastery test), **resolution/epilogue**.
- Introduce **new mechanics at a steady cadence** (e.g. every 1-2 hours, heuristic) and retire or combine them before they overstay; mid-game content should not simply repeat early content with larger numbers.
- Alternate **intensity types**: combat, exploration, puzzle, story, rest. Variety within the same verbs keeps long games from feeling repetitive.
- Plan **pacing graphs**: intensity per hour of the intended path; check against playtest data (see 12). Look for valleys of 30+ minutes with no new stimulus.
- **Mid-game slump** is the most common campaign problem. Fixes: a new mechanic, a changed context (new biome with new rules), a narrative turn, or a shortened path.
- **End-game**: either a strong finale or a sustainable loop (endless modes, challenge content). Don't let "the end" be the first time the game is hard.
- **Rest points**: villages, safe rooms, slow walks, quiet scenes. Silence is part of pacing (L4D's "relax" phase is an example of programmed rest; Booth 2009).
- **Backtracking and re-use**: Metroidvanias reuse space with new abilities; this is cheap content and strong progression feedback ("I can finally reach that").

**Live/service games** add a time dimension: daily, weekly, seasonal loops. See `references/09-monetization-and-live-ops.md`. Pace *meaningful* content so long-term goals exist without making each day a chore.

## 12. Mastery, Skill Ceilings and Floors

- **Skill floor**: how easy it is to play competently. **Skill ceiling**: how much room there is to keep improving. Good games often have a low floor and high ceiling (Chess/Tetris are examples often cited; more a common saying than a measured result).
- **Mastery loop**: attempt -> feedback -> insight -> improvement -> harder attempt. The game must offer **visible gradients**: score, rank, time, combos, styles, replays.
- **Depth sources**: interactions between simple rules (emergence), execution depth (precision), knowledge depth (matchups, builds), decision depth (resource tradeoffs), and mind games (prediction).
- **Skill expression**: more than one way to succeed, with clear outcomes. If everyone converges on a single optimal sequence, ceiling is shallow.
- **Raising the floor**: clear UI, forgiving inputs, good default builds, safe practice. **Raising the ceiling**: advanced techniques, risk/reward options, optional mastery content (hard modes, speedrun routes).
- **Don't confuse complexity with depth**: many systems with shallow interaction create overhead without ceiling; fewer systems with rich interaction create more.
- **Expert tech**: speedrunners and competitive players find tricks (wavedash, animation canceling). Decide which are intended (keep, teach in advanced tutorials) and which are bugs (patch). Hidden but consistent techniques extend the ceiling.
- **Visible mastery for casuals**: relative progress (your last 10 runs), personal bests, cosmetic proof, replays. Not only ladders, which show only relative rank.
- **Matchmaking and skill ceilings**: see `references/10-multiplayer-and-social.md`.

## 13. Power Fantasy vs Challenge

Two legitimate and different experiences:
| | Power fantasy | Challenge fantasy |
|---|---|---|
| Player feeling | "I am overwhelming" | "I overcame something hard" |
| Examples | Musou/warriors games, some action RPG endgames, Vampire Survivors-style mowing | Souls-likes, roguelikes, speedruns, precision platformers |
| Difficulty approach | Enemies are fodder; the thrill is the scale of effect | Enemies are threats; the thrill is survival and mastery |
| Progression | Rapid power growth, big visible effects | Slower power growth, skill carries |
| Failure | Rare, minor | Frequent, instructive |

Rules:
1. **Choose per moment, not per game.** Many good games alternate: a power fantasy after a hard section (reward), then a challenge (new threat).
2. **Power must be earned or at least contextualized**: gaining overwhelming power without any struggle feels hollow; gaining it after struggle feels triumphant.
3. **Provide scale**: a power fantasy needs foes that give the player a meaningful sense of the delta (waves of enemies, the previously feared enemy now trivial).
4. **Keep some threat**: even in power fantasies, an occasional boss or hazard preserves tension. Otherwise players disengage.
5. **Let players choose**: difficulty modifiers, optional "elite" content.
6. **Align with the audience and the business model**: F2P power progression sold for money (pay-to-win) breaks challenge fantasy for others. See 09.
7. **Avoid trivializing your own content**: if players can buy or earn a power that skips the main tension, move the tension elsewhere or tune the content upward.

## 14. Worked Example: Platformer First Hour

Goal: a precision-lite platformer, session 30-60 min, audience casual-to-mid core.

Pillars: *clear*, *fair*, *quick to retry*.

**Skill atoms and levels**

| Level | New atom | Safe intro | Test | Twist | Est. time |
|---|---|---|---|---|---|
| 1-1 | Move, jump | Empty flat start, wide gaps with floor below (no death) | Gap with spikes below | Single enemy on a platform | 2-3 min |
| 1-2 | Variable jump height | Low ceilings that require short hops | Ceiling+gap | Hop over enemy under a ceiling | 3 min |
| 1-3 | Wall slide / wall jump | Shaft with no hazard | Shaft with spikes at the bottom | Shaft with moving enemy | 3 min |
| 1-4 (boss) | Combination | Telegraphed attacks | 3 phases | Phase 3 combines wall jumps and enemy dodges | 4 min |
| 2-1 | Dash | Open space | Gap that requires dash | Dash through enemy | 3 min |
| 2-2 | Review + mix | | | | 4 min |

**Difficulty curve:** sawtooth; each world has a peak at the boss and a release in the next world's intro. Target clear rates (heuristic, adjust with playtests): 1-1: 98% first-session clear; 1-4 boss: 70% within 5 attempts; 2-1: 90%.

**Failure design:** per-screen checkpoint, respawn under 1 s, death counter hidden unless the player opens stats; after 10 deaths on a screen, Assist Mode prompt (opt-in: slow-mo, extra air jump, invincibility).

**Reward schedule:** continuous in 1-1 (collectibles every few jumps), then FR (collect 100 for a life), VI for secrets, deterministic star ratings per level. No daily rewards.

**Telemetry to track** (see 12-playtesting-and-analytics): per-level completion rate, attempts per death location (heat map), time to complete, quit-after-fail rate, tutorial prompt dismissal time.

**Playtest questions:** "What did you think you were supposed to do here?" (clarity), "What killed you?" (feedback), "What was the hardest part and why?" (difficulty dimension), "When did you feel you got better?" (visible mastery).

## 15. Checklists and Pitfalls

**Progression checklist**
- [ ] Which progression types are present, and which one is primary?
- [ ] Does each unlock change what the player can do, not only the numbers?
- [ ] Is the next goal always visible?
- [ ] Is there a plan for the plateau (new tool, goal, content)?
- [ ] Do reward schedules mix predictable and variable layers?
- [ ] Is the core verb fun without rewards?

**Difficulty checklist**
- [ ] Is the curve sawtooth (or an intentional alternative) with releases after peaks?
- [ ] Does each encounter specify which difficulty dimension it tests?
- [ ] Are there difficulty options that change meaningful dimensions, not just HP/damage?
- [ ] Is failure fair (perceivable, understandable, answerable, learnable)?
- [ ] Is time-to-retry short enough for the genre?
- [ ] Are checkpoints placed before challenges with a viable state?
- [ ] If DDA exists, is it bounded, hard to exploit, and disabled in competitive modes?

**Onboarding checklist**
- [ ] Core verb in under a minute?
- [ ] One new concept at a time; introduce, practice, test, combine, twist?
- [ ] Level or situation teaches, text minimal?
- [ ] Skippable for veterans; re-accessible?
- [ ] Skill atom graph complete (no missing prerequisites)?
- [ ] Tested with naive players; drop-off per step measured?

**Common pitfalls**
| Pitfall | Symptom | Fix |
|---|---|---|
| Difficulty by stats only | Spongy enemies, boredom | Change demands, not numbers |
| Cliff difficulty | Quit spike at one encounter | Add teaching, a ramp or an assist option |
| Late teaching | Deaths to unknown rules | Move introduction earlier |
| Tutorial overload | Players skip or forget | Teach just in time; chunk |
| Hidden DDA backlash | "The game cheats" | Bound it, show it, or make it optional |
| Grind disguised as progression | Players stop at plateaus | Add new tools, variety |
| Reward saturation | Rewards ignored | Rarity, scaling, meaning |
| Manipulative schedules | Short-term engagement, long-term resentment | Ethical review, transparency, limits |
| Designer's blind spot | "It's easy" (to the designer) | Naive playtesters, telemetry |
| One-size difficulty | Both bored and frustrated players | Modes, assists, optional challenge |

## 16. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Books**
- Csikszentmihalyi, M., 1990, *Flow: The Psychology of Optimal Experience*, Harper & Row.
- Ferster, C. B. and Skinner, B. F., 1957, *Schedules of Reinforcement*, Appleton-Century-Crofts.
- Koster, R., 2004, *A Theory of Fun for Game Design*, Paraglyph Press.
- Schell, J., 2019, *The Art of Game Design: A Book of Lenses*, 3rd ed., CRC Press.
- Schreiber, I. and Romero, B., 2021, *Game Balance*, CRC Press.

**Papers**
- Deci, E. L., Koestner, R. and Ryan, R. M., 1999, "A meta-analytic review of experiments examining the effects of extrinsic rewards on intrinsic motivation", *Psychological Bulletin* 125(6), 627-668. DOI: https://doi.org/10.1037/0033-2909.125.6.627
- Lepper, M. R., Greene, D. and Nisbett, R. E., 1973, "Undermining children's intrinsic interest with extrinsic reward: A test of the overjustification hypothesis", *Journal of Personality and Social Psychology* 28(1), 129-137 (cited from the Wikipedia article on the overjustification effect; no direct link verified).
- Chen, J., 2007, "Flow in Games (and Everything Else)", *Communications of the ACM* 50(4), 31-34. DOI: https://doi.org/10.1145/1232743.1232769
- Chen, J., "Flow in Games" (thesis on player-centric dynamic difficulty adjustment; the longer work behind the CACM article). Author's copy: https://www.jenovachen.com/flowingames/Flow_in_games_final.pdf
- Hunicke, R., 2005, "The Case for Dynamic Difficulty Adjustment in Games", *Proceedings of ACE 2005*, ACM. DOI: https://doi.org/10.1145/1178477.1178573 (ACM blocks automated access; DOI verified through Crossref)
- Hunicke, R., LeBlanc, M. and Zubek, R., 2004, "MDA: A Formal Approach to Game Design and Game Research": https://users.cs.northwestern.edu/~hunicke/MDA.pdf

**Talks**
- Booth, M., 2009, "The AI Systems of Left 4 Dead" (Valve, slides): https://steamcdn-a.akamaihd.net/apps/valve/2009/ai_systems_of_l4d_mike_booth.pdf

**Websites**
- Cook, D., Lost Garden, "Game Design Skill Atoms" and related essays (the specific essay URL could not be verified; site: https://www.lostgarden.com/).
- Wikipedia, "Schedule of reinforcement": https://en.wikipedia.org/wiki/Schedule_of_reinforcement
- Wikipedia, "Operant conditioning": https://en.wikipedia.org/wiki/Operant_conditioning
- Wikipedia, "Overjustification effect": https://en.wikipedia.org/wiki/Overjustification_effect
- Wikipedia, "Self-determination theory": https://en.wikipedia.org/wiki/Self-determination_theory
- Wikipedia, "Flow (psychology)": https://en.wikipedia.org/wiki/Flow_%28psychology%29
- Wikipedia, "Dynamic game difficulty balancing": https://en.wikipedia.org/wiki/Dynamic_game_difficulty_balancing
- Wikipedia, "Rubber band AI": https://en.wikipedia.org/wiki/Rubber_band_AI
- Wikipedia, "Left 4 Dead": https://en.wikipedia.org/wiki/Left_4_Dead
- Wikipedia, "Resident Evil 4": https://en.wikipedia.org/wiki/Resident_Evil_4
- Wikipedia, "Celeste (video game)": https://en.wikipedia.org/wiki/Celeste_%28video_game%29
- Wikipedia, "Hades (video game)": https://en.wikipedia.org/wiki/Hades_%28video_game%29
- Wikipedia, "Super Mario Bros.": https://en.wikipedia.org/wiki/Super_Mario_Bros.
- Wikipedia, "World 1-1": https://en.wikipedia.org/wiki/World_1-1
- Wikipedia, "Kishotenketsu": https://en.wikipedia.org/wiki/Kish%C5%8Dtenketsu
- Wikipedia, "Portal (video game)": https://en.wikipedia.org/wiki/Portal_%28video_game%29
- Wikipedia, "Prince of Persia: The Sands of Time": https://en.wikipedia.org/wiki/Prince_of_Persia:_The_Sands_of_Time
- Wikipedia, "Mario Kart": https://en.wikipedia.org/wiki/Mario_Kart
- Wikipedia, "Dark Souls": https://en.wikipedia.org/wiki/Dark_Souls
