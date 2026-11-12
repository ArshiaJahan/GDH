# Core Loops, Mechanics, Systems and Game Feel

## Table of Contents

1. [How to Use This File](#1-how-to-use-this-file)
2. [Verbs: The Atoms of Player Action](#2-verbs-the-atoms-of-player-action)
3. [Loops: Core, Meta, Long-Term](#3-loops-core-meta-long-term)
4. [Compulsion Loop vs. Engagement Loop](#4-compulsion-loop-vs-engagement-loop)
5. [Mechanics Taxonomy](#5-mechanics-taxonomy)
6. [Systems Design](#6-systems-design)
7. [Machinations-Style Modeling](#7-machinations-style-modeling)
8. [Risk and Reward](#8-risk-and-reward)
9. [Skill vs. Luck: Input and Output Randomness](#9-skill-vs-luck-input-and-output-randomness)
10. [Game Feel](#10-game-feel)
11. [Juice](#11-juice)
12. [Responsiveness Toolkit: Coyote Time, Buffering, Hit-Stop, Camera](#12-responsiveness-toolkit-coyote-time-buffering-hit-stop-camera)
13. [Worked Examples](#13-worked-examples)
14. [Checklists](#14-checklists)
15. [References](#15-references)

---

## 1. How to Use This File

Load for: designing or fixing a core loop, choosing mechanics, building systemic depth, modeling an economy or feedback structure, deciding how much randomness to include, or making controls and combat *feel* good. Related files: `02-design-frameworks.md` (theory), `04-balance-and-economy.md` (numbers), `05-progression-difficulty-onboarding.md` (curves, reward schedules), `11-genre-playbooks.md`.

Labels: **[established]** documented in books/talks; **[practice]** common industry practice; **[heuristic]** tune to context. Numeric values for game feel are starting points to tune, not rules.

---

## 2. Verbs: The Atoms of Player Action

A **verb** is something the player does repeatedly (jump, shoot, trade, bluff, place, connect, hide). The verb set *is* the game's identity.

### 2.1 Principles

1. **Few, deep verbs beat many shallow ones.** Each verb should have variation (context, timing, resources) that produces decisions. Rule of thumb [heuristic]: 3-6 core verbs for most action games; complexity should come from verb combinations and context.
2. **Verbs must be fun alone.** In grey-box, the primary verb should be satisfying with no goal (moving in Mario, grapple in Spider-Man, drawing a card).
3. **Verbs interact with the world** through rules (physics, resources, AI), creating *consequences*, not just animations.
4. **Verbs need counter-verbs** or constraints: attack/defend, build/destroy, hide/seek. Without a counter, verbs become one-note.
5. **Verb economy**: each new verb has a cost (tutorial, UI, QA, balance). Add one only if it opens new decisions.

### 2.2 Verb inventory exercise

Make a table for the game:

| Verb | Input | Cost (resource/time/risk) | Feedback | Counter / constraint | Decisions it opens |
|---|---|---|---|---|---|
| Dash | Button | Stamina + cooldown 1.5 s | Streak VFX, whoosh | Enemy attacks track dash end | When to dash: offense vs defense |
| Parry | Timing | Risk of failing, a small stun | Clang, hit-stop | Unblockable attacks | Commit to read or play safe |

If a verb opens no decisions, cut or merge it. If two verbs are used identically, merge.

### 2.3 Verb families (for brainstorming)

| Family | Verbs |
|---|---|
| Movement | run, jump, climb, swing, teleport, glide, drift |
| Combat | strike, shoot, block, parry, stun, push, throw |
| Manipulation | pick up, carry, place, rotate, combine, craft |
| Information | scan, scout, ping, read, deduce, remember |
| Social | trade, negotiate, bluff, vote, gift, coordinate |
| Economy | harvest, build, upgrade, sell, invest, gamble |
| Stealth | hide, distract, sneak, disguise, listen |
| Expression | paint, decorate, emote, record |

---

## 3. Loops: Core, Meta, Long-Term

### 3.1 Definitions

| Loop | Time scale | Purpose | Player question |
|---|---|---|---|
| **Moment-to-moment loop (micro)** | Seconds | Responsiveness and basic satisfaction | "What do I do right now?" |
| **Core loop** | 30 s - 5 min | The repeated activity that is the game | "Which choice gives me the best result?" |
| **Session / meta loop** | 15 min - 2 h | Progression within a session; goals, upgrades | "What am I building toward this session?" |
| **Long-term / macro loop** | Days to months | Mastery, collections, seasons, story | "Why come back tomorrow?" |

Every layer should: (1) offer meaningful decisions, (2) provide feedback and reward, (3) change the player's capability or situation so the next loop is different.

### 3.2 Generic loop template

```
 GOAL  --> ACTION (verb) --> FEEDBACK --> REWARD / OUTCOME --> NEW CAPABILITY or STATE
   ^                                                                   |
   +-------------------------------------------------------------------+
```

A loop is healthy when each pass offers (a) skill expression, (b) a decision with a trade-off, (c) a change in state that alters the next pass.

### 3.3 Nested loops in practice

**Hades** (action roguelite):

```
Micro:   dash / attack / cast ---> hit feedback, enemy tells
Core:    clear a room --> choose a door (reward preview) --> boon / resource
Session: run through 4 biomes --> boss --> death or escape
Meta:    spend Darkness / Keys / Nectar on mirror upgrades, weapon aspects, relationships
Long:    story progression via repeated escapes; heat difficulty; prophecies
```

Key design insights: **death is a narrative and progression beat**, not just failure; the meta loop makes even a failed run produce value, shortening the "time to feel progress".

**Stardew Valley**:

```
Micro:   water crops / swing tool
Core:    day: plan energy -> farm, mine, fish, socialize -> sleep (save, summary)
Session: season goals (crops, bundles, festivals)
Long:    expand farm, unlock areas, relationships, completion
```

**Civilization-style 4X**:

```
Micro:   move unit, assign tile
Core:    "one more turn": build -> explore -> expand -> end turn
Meta:    era shifts, tech/civic trees, wars
Long:    victory condition race
```

The "one more turn" effect works because each turn **starts several overlapping mini-goals** (almost finished build, tech near completion, unit arriving) so there is always a reason to continue.

**Match-3 + meta (Candy Crush / Homescapes style)**:

```
Core:    match tiles (short, skill+luck)
Meta:    earn stars/moves -> unlock decor / story chapters
Long:    events, collections, social lives
```

### 3.4 Designing a loop: procedure

1. Start with the **verb** and a **goal** (what the verb is for).
2. Identify the **tension** that makes the verb non-trivial (time, scarcity, risk, enemies, information).
3. Define **feedback** at three levels: instant (hit, sound), short (score, resource change), long (progress bar, unlocks).
4. Define the **reward** and *what it changes* (new options, not just bigger numbers).
5. Feed output into input: the loop output must become a new input or a new difficulty.
6. Estimate the **loop length** and the number of decisions per loop (target at least one meaningful decision per core loop pass) [heuristic].
7. Prototype just the core loop in grey-box; if not fun for 10 minutes, don't add meta.
8. Add meta loops only to amplify what is already fun. *Meta cannot fix a broken core.*

### 3.5 Loop failure modes

| Failure | Symptom | Remedy |
|---|---|---|
| **Flat loop** | Every pass is the same | Add variance (enemy types, procedural layout, choices) and escalating mixing of atoms |
| **Reward without agency** | Rewards random and unrelated to skill | Link rewards to decisions or performance |
| **Meta overwhelms core** | Players grind for numbers, ignoring play | Keep progression power gains modest; reward skill expression |
| **Dead meta** | Progress is only numeric | Unlock new verbs, systems, options |
| **Long loop with no short-term hooks** | Players churn at day 3 | Add daily goals, short wins, partial progress |
| **Dominant strategy loop** | One optimal repeated action (e.g., farm one monster) | Diminishing returns, counters, diversified rewards |
| **Friction between loops** | Meta menus interrupt core | Streamline transitions; defer admin to natural pauses |

---

## 4. Compulsion Loop vs. Engagement Loop

### 4.1 Compulsion loop

A **compulsion loop** (Zynga-era term) is a short loop designed around anticipation and reward cycles (often variable-ratio) to drive repeated behavior: *Trigger -> Action -> Variable reward -> Investment -> Trigger*. Think slot machines, loot boxes, daily notifications, gacha pulls, timers.

Characteristics:
- Driven by **anticipation** and **variable reward** (operant conditioning; see `references/05-progression-difficulty-onboarding.md` for reward schedules).
- Often tied to **external triggers** (push notifications, energy refills) and **sunk-cost investment**.
- Minimal skill dependence; the "loop" works without the player learning anything.

### 4.2 Engagement loop (skill/mastery loop)

An **engagement loop** is driven by *competence*: the player does something, learns, gets better, and the game offers a higher challenge. *Challenge -> Action -> Feedback/Learning -> Mastery -> Higher challenge*.

Characteristics:
- Intrinsic motivation (Self-Determination Theory: competence, autonomy, relatedness).
- Rewards are *information and capability* (new tools, new problems).
- Retention tied to depth and meaningful variation.

### 4.3 Comparison

| Aspect | Compulsion loop | Engagement loop |
|---|---|---|
| Primary driver | Anticipation, variable reward, loss aversion | Mastery, curiosity, expression, relatedness |
| Skill dependence | Low | High |
| Content demand | Low per loop; relies on schedule | High; needs variety and depth |
| Failure risk | Burnout, regret, ethics and regulation | Churn if difficulty/novelty fails |
| Player sentiment after | Often "wasted time" | "I learned/accomplished something" |
| Best for | Short, casual sessions with light stakes | Games players want to master or share |

### 4.4 Practical guidance

- Most successful games have **both**: a skill-based core engaging the player, wrapped in reward cadence (loot, XP, unlock rhythms). Diablo's loot is variable reward layered on skill-based combat.
- Design the **engagement loop first**; add reward rhythm to *celebrate* skill, not replace it.
- Treat pure compulsion mechanics (timers, loot boxes, streak punishment) as high-risk: they invite regulatory scrutiny and player backlash. See `09-monetization-and-live-ops.md` for ethics and regulation.
- Test: if the player stopped receiving the variable rewards, would they still play? If no, the core loop is weak.
- Test: "Would I be comfortable showing the player exactly how this loop works?" If not, reconsider.

---

## 5. Mechanics Taxonomy

Categories for generating and auditing mechanics. Adams and Dormans (2012) and Fullerton (2018) provide fuller catalogues; this is a working version.

### 5.1 Resources

Anything with value that is gained, spent, or traded.

| Type | Examples | Design questions |
|---|---|---|
| **Consumable** | Ammo, mana, gold | What are the sources (faucets) and sinks? |
| **Renewable** | Stamina, cooldowns, action points | What is the regeneration rate and cap? |
| **Permanent** | Level, gear, unlocks | Do they power-creep? |
| **Soft vs hard currency** | Gold vs premium gems | Conversion, exploitation |
| **Time / tempo** | Turns, tick time, timers | Who controls tempo? |
| **Information as resource** | Scouting, cards in hand | Can it be bought, stolen, lost? |
| **Space as resource** | Territory, inventory slots, grid cells | Does it compete with other uses? |
| **Health / lives** | HP, lives, sanity | Is damage permanent? What is the failure state? |

Design heuristics:
- Every faucet needs a sink (see `04-balance-and-economy.md`).
- **Scarcity drives decisions**; abundance removes them.
- Convertibility between resources creates interesting exchange decisions (and exploits).

### 5.2 Space

| Mechanic | Effect | Example |
|---|---|---|
| **Grid / tile** | Clear positional reasoning | Into the Breach, XCOM, Fire Emblem |
| **Continuous 2D/3D** | Execution skill, physics | Celeste, Mario |
| **Line of sight / cover** | Tactical positioning | XCOM, Rainbow Six |
| **Verticality** | Third dimension to threats and routes | Dark Souls, Hitman |
| **Chokepoints / lanes** | Control and flow of conflict | MOBA lanes, tower defense |
| **Territory / area control** | Contested regions score or yield | Risk, Go, Splatoon |
| **Distance and range** | Trade-off for weapons | Sniper vs shotgun |
| **Hidden space** | Secrets, fog of war | Metroidvania, Outer Wilds |

### 5.3 Time

| Mechanic | Effect | Example |
|---|---|---|
| **Real-time** | Pressure, execution | Action, RTS |
| **Turn-based** | Contemplation, planning | Chess, Civ |
| **Real-time with pause** | Planning plus flow | Baldur's Gate, Pillars of Eternity |
| **Timers / clocks** | Urgency | Overcooked, Papers Please |
| **Cooldowns / rhythm** | Pacing within action | MMO rotations, Hades cast |
| **Time manipulation** | Puzzle or skill mechanic | Braid, Prince of Persia |
| **Calendar / season** | Long-term rhythm | Stardew, live-ops |
| **Tick / simulation rate** | System responsiveness | Dwarf Fortress |

### 5.4 Information

| Type | Effect | Example |
|---|---|---|
| **Perfect information** | Pure skill, deterministic planning | Chess, Into the Breach (enemy intents) |
| **Imperfect / hidden** | Bluffing, deduction | Poker, Mastermind |
| **Asymmetric** | Different players know different things | Hidden role games, Spy-Party |
| **Telegraphing** | Fair, learnable challenge | Dark Souls tells, boss patterns |
| **Fog of war** | Scouting, tension | StarCraft, Civ |
| **Information cost** | Scouting costs resources | Poker tells, StarCraft scouting |

Rule: **Make hidden information a decision, not a punishment.** Players should be able to choose to gain information at a cost.

### 5.5 Chance

See section 9. Uses: variety, surprise, narrative sparks, equalizing skill. Risks: unfair feelings, reduced mastery.

### 5.6 Actions

| Action design | Effect |
|---|---|
| **Action economy** (AP, one action per turn) | Constrains complexity; trade-offs |
| **Commitment** (animation lock, recovery frames) | Risk and reward for attacks |
| **Combos / chaining** | Execution skill, expression |
| **Contextual actions** | Few buttons, many uses |
| **Reactions / interrupts** | Counterplay, tension (XCOM overwatch, parry) |
| **Queued / programmed actions** | Planning (Frozen Synapse, Into the Breach) |
| **Cost/benefit asymmetry** | Dominant strategies if skewed |

### 5.7 Interaction patterns between mechanics

- **Synergy**: two mechanics multiply value (build crafting).
- **Counter**: a mechanic that answers another (rock-paper-scissors).
- **Gate**: a mechanic that unlocks others (key, ability).
- **Trade**: converts one resource into another (shop, exchange).
- **Feedback**: output feeds input (snowball, catch-up).

A design is a **graph of these interactions**; document it (see section 7 for diagram conventions).

---

## 6. Systems Design

### 6.1 Stocks, flows and feedback loops

A system is **stocks** (quantities that accumulate: gold, health, population), **flows** (rates in/out), and **feedback** relationships among them (Adams and Dormans 2012; Meadows 2008 for systems thinking).

```
            +------------+                +-----------+
 income --> |   GOLD     | --- spend ---> |  UNITS    |
 (flow)     |  (stock)   |                | (stock)   |
            +------------+                +-----------+
                  ^                             |
                  |   (positive loop)           | units capture
                  +----- more income <----------+ resources
```

| Feedback type | Effect | Use | Danger |
|---|---|---|---|
| **Positive (reinforcing)** | Amplifies deviations; snowball | Ensures decisive endings, momentum, fantasy of growth | Runaway leader; decided games feel pointless |
| **Negative (balancing)** | Dampens deviations; stabilization | Close games, comebacks, safety nets | Rubber-banding frustrates skilled players; stalemate |

Examples:
- **Positive**: Monopoly (rent buys more property), RTS economy snowball, roguelike power build.
- **Negative**: Mario Kart blue shell and item balance, XCOM panic, Catan robber, Rubber-band AI in racing.
- **Mixed**: Civilization's empire-size unhappiness (negative) against expansion benefits (positive).

Design rules [practice]:
1. Decide what you want: *decisive* (positive dominates late) or *tense* (negative dominates).
2. **Visible feedback** is more acceptable than hidden: the comeback mechanic that players can see and plan around feels fair; hidden rubber-banding feels cheaty.
3. Add **stabilizers** to positive loops (caps, upkeep, diminishing returns, counters).
4. Look for **delays** in feedback: long delays cause oscillation or players not understanding cause and effect.

### 6.2 Emergence

**Emergence**: complex, unscripted behaviors arise from simple rules interacting. Juul distinguishes **games of emergence** (small rule sets, huge outcome space, e.g., chess, Go) from **games of progression** (scripted content sequences) (Juul 2002).

Techniques for building emergence:
- Few rules, **high connectivity**: each rule can interact with many others.
- **Consistent rules** with few exceptions: players can predict and exploit.
- **Shared state** across entities: fire spreads from enemy to grass to oil, etc.
- **Simulation** over scripting where practical: AI uses same rules as the player.

Costs: harder to test, balance, and keep on-rails for story; exploits; performance. Mitigation: automated testing, design rules (clear tags), and curated sandboxes.

### 6.3 Orthogonal unit differentiation and systemic interaction (immersive sim approach)

**Orthogonal unit differentiation** (Harvey Smith's term, associated with Looking Glass/Ion Storm/Arkane design culture [practice]): units/objects differ along *different dimensions* rather than just stats, so each has a unique role and they combine in novel ways.

- Non-orthogonal: Sword A (10 dmg), Sword B (12 dmg), Sword C (14 dmg), a linear power ladder.
- Orthogonal: Bow (silent, ranged, limited ammo), Grenade (area, loud, destroys cover), Sleep dart (non-lethal), Rope arrow (changes space).

Each tool should answer a different question; none should be strictly better.

**Systemic interaction (immersive sim, 'chemistry engine')**: entities have **properties/tags** (flammable, conductive, loud, heavy, wet) and the world has **rules** between properties (fire + flammable -> burns; water + electricity -> shock). Players discover solutions that designers didn't script.

Examples:
- **Deus Ex / Dishonored / Prey**: multiple solutions (stealth, combat, hacking, environment) using the same toolset.
- **Breath of the Wild / Tears of the Kingdom**: physics and chemistry (fire, wind, metal conducts lightning, Ultrahand building) allow improvisation.
- **Hitman**: NPC routines + props + disguises = sandboxes with emergent kills.
- **Noita**: every pixel simulated; unique chemistry.

Design checklist for systemic games:
1. **Tags/properties list** (finite, orthogonal).
2. **Interaction matrix** (property x property -> outcome); design the table intentionally, mark uninteresting or dangerous cells.
3. **Consistency rule**: if it works for the player, it works for NPCs (and vice versa).
4. **Readability**: players must predict outcomes (visual/audio cues for properties).
5. **Guardrails**: rate limits, caps, and failsafes for infinite loops and softlocks.
6. **Design for intentional abuse**: playtest with testers trying to break it; decide which exploits to embrace.
7. **Multiple solutions at the encounter level**: define the problem, not the solution (goal + obstacles + tools).

### 6.4 Counter-systems and rock-paper-scissors

- **Intransitive relationships** (A beats B beats C beats A) avoid a single best option and create meta-game cycles (fighting games' strike/throw/block; RTS counters).
- Use soft counters (modifiers) rather than hard (instant lose) so skill can overcome unfavorable matchups.
- Ensure players can **see and adapt** (scouting, flexible build) so counters become decisions, not coin flips.

### 6.5 Depth vs complexity

- **Depth** = number of meaningful strategic options and the skill space.
- **Complexity** = number of rules/elements to learn.
- Aim for **high depth, low complexity** (elegance): Go, Tetris, Into the Breach. Complexity without depth is bureaucracy.
- Test: does adding this rule open new decisions, or add bookkeeping?

### 6.6 Systems audit checklist

- [ ] Every stock has at least one source and one sink; caps defined.
- [ ] Positive loops have stabilizers; negative loops don't punish skill excessively.
- [ ] No strictly dominant option (simulate or test).
- [ ] Rules combine (at least a few interactions are non-obvious but explicable).
- [ ] Failure states are clear, recoverable, and instructive.
- [ ] Edge cases: min/max values, zero, negative, overflow, simultaneous events.
- [ ] Feedback visible for every important variable.

---

## 7. Machinations-Style Modeling

### 7.1 Summary

Adams and Dormans (2012) present a method of modeling game economies and mechanics as **diagrams** (the Machinations framework), enabling designers to simulate feedback structures before building. The tool (Machinations.io) implements it, though the principles can be applied with a spreadsheet or small script.

Core element types (conceptual):

| Element | Meaning | Symbol (ASCII) |
|---|---|---|
| **Source** | Generates resources (faucet) | `(S)` / triangle |
| **Pool** | Stores resources (stock) | `[P]` |
| **Drain** | Removes resources (sink) | `(D)` |
| **Converter** | Transforms one resource into another (e.g., wood -> planks) | `<C>` |
| **Gate** | Randomly or conditionally routes resources | `{G}` |
| **Resource connection** | Moves resources at a rate | `--n-->` |
| **State connection** | Modifies other elements (rates, triggers) | `- - - >` |
| **Trader** | Exchanges resources between pools | `<T>` |
| **Register** | Computes values from state | `[R]` |

(Naming and notation follow the book in spirit; check the book and the tool for exact syntax.)

### 7.2 Building a model: process

1. **List resources** and who owns them.
2. **Draw sources, pools, drains**. Check every pool has in and out.
3. **Add converters** for crafting/upgrade steps.
4. **Add feedback**: state connections where a pool's level changes a rate elsewhere.
5. **Add player decisions** as user-triggered actions (spend gold on A or B).
6. **Simulate** (run 1000 times, vary strategies); chart pool levels over time; look for runaway, deadlock, or dominant strategy.
7. **Tune** parameters; document ranges.
8. **Validate** with real play: models are only as good as their assumptions.

### 7.3 Example: simplified RTS economy

```
 (Mine S) --2/s--> [Gold] --50g--> <Barracks C> --1 unit--> [Army]
                      |                                        |
                      | 20g  (positive: more workers -> more   |
                      v       mining rate)                     |
                  <Worker C> --- state: +1 mining rate         |
                                                               v
                                                      (Upkeep D: -1 gold / 10 units / s)  <-- negative stabilizer
```

Insights modeled: workers produce a positive feedback loop (snowball); upkeep provides negative feedback so armies cannot grow indefinitely; testing shows the optimal strategy ("all workers first") is dominant unless early aggression exists (counter pressure). Solutions: increase early raiding opportunities; cap worker returns (diminishing returns per mine).

### 7.4 Using spreadsheets or code

Machinations.io is optional. A spreadsheet or 30-line script can simulate pools and flows. See `scripts/design_calc.py` for related calculators (progression curves, drop odds, pity timers).

### 7.5 Limitations

- Models simplify away skill and perception; good for economy, poor for feel.
- Garbage in, garbage out: wrong constants produce confident wrong answers; calibrate with playtests.
- Players behave unexpectedly; model multiple player strategies.

---

## 8. Risk and Reward

**Principle**: Risk should be proportional to reward, and players should be able to *choose* their risk. The decision "do I gamble?" is one of the most reliable sources of interesting choices.

### 8.1 Dimensions of risk

| Dimension | Example |
|---|---|
| Resource loss | Lose items on death (Escape from Tarkov), spend currency on a gamble |
| Time loss | Lose progress since last checkpoint |
| Positional | Move into the open to reach the reward |
| Information | Reveal your position to attack |
| Social | Betray an ally |
| Opportunity | Choosing A forecloses B |

### 8.2 Design heuristics

1. **Choice of risk**: offer safe and risky paths with different reward magnitudes (Hades door previews; Slay the Spire elites; Spelunky's altar and shopkeeper).
2. **Clear stakes**: show what is at risk and the approximate odds.
3. **Expected value check**: risky option's expected reward should exceed the safe path for *skilled* players, otherwise nobody takes it (EV calculations in `04-balance-and-economy.md`).
4. **Loss aversion**: losses feel ~2x as strong as equivalent gains (Kahneman and Tversky, prospect theory; the exact ratio is debated) so make punishments proportionate and recoverable.
5. **Push-your-luck mechanics** (Can't Stop, Blackjack, extraction modes): reward the greedy until a threshold; ensure a satisfying "bank it" decision.
6. **Risk should scale** with player power to retain tension.
7. **Fail-forward**: let failures change the situation rather than reset (XCOM wounded soldiers).

### 8.3 Pitfalls

- High risk with no ability to mitigate = frustration; mitigate through skill, preparation or information.
- Reward without risk = boredom.
- Hidden risk (unknown or arbitrary) feels unfair; telegraph it.
- Excess punishment pushes players to the lowest-risk repetition (safe farming).

---

## 9. Skill vs. Luck: Input and Output Randomness

### 9.1 Definitions

- **Input randomness**: random elements are revealed *before* the player decides, so the player reacts skillfully (a random map, the cards in hand, the dice shown before choosing, procedural level, a Tetris next-piece).
- **Output randomness**: random elements occur *after* the decision, determining the result (hit chance rolled after you attack, a loot roll, critical hit).

This distinction is commonly credited in modern design discourse and is discussed in *Characteristics of Games* (Elias, Garfield and Gutschera 2012), where Garfield also discusses luck/skill balance across games; the specific "input/output" terminology is popularized by designers such as Geoffrey Engelstein [practice; verify attribution before citing formally].

### 9.2 Effects

| Aspect | Input randomness | Output randomness |
|---|---|---|
| Skill expression | High: adapt to what appears | Lower: skill is in setup and odds |
| Feeling after a loss | "I made a bad decision" or "I was unlucky but I could cope" | "The dice cheated me" |
| Variety | High (new situation each time) | Moderate |
| Tension | Moderate | High (suspense during the roll) |
| Best for | Strategy, puzzle, roguelike, deckbuilder | Party games, gambling feel, narrative moments |

### 9.3 Practical guidelines [heuristic]

1. **Prefer input randomness for competitive or mastery-focused games**; use output randomness where tension and "stories" matter more than fairness.
2. **Give mitigation tools** for output randomness: rerolls, hedging, probability-shifting skills, multiple attempts so the law of large numbers smooths variance.
3. **Show the odds** honestly. Display percentages; note that humans misread them (players perceive 90% as near-certain; a 10% miss feels like a bug). Some games (e.g., XCOM) are widely reported to be perceived as unfair at 90%+ hit chances; designers sometimes bias outcomes in the player's favor in ways that are explicitly disclosed. Disclose if you do.
4. **Streak protection / pseudo-random distribution** (PRD): avoid long bad streaks by increasing chance after each failure (used in some MOBAs for crit/proc). Tune with `scripts/design_calc.py`.
5. **Increase the number of independent rolls** (more attacks with smaller effect) to reduce variance; fewer, bigger rolls increase swings.
6. **Luck at the start, skill at the end**: let randomness shape the situation, let skill decide the outcome.
7. **Randomness as equalizer**: in games with mixed skill players, more luck helps beginners compete (Mario Kart items). Give experts ways to manage it.
8. **Narrative and surprise**: randomness is often what generates stories (Spelunky, FTL, Dwarf Fortress). It doesn't have to be balanced to be valuable.

### 9.4 Skill-luck spectrum (typical)

```
Pure skill <--------------------------------------------> Pure luck
Chess   Go   Fighting   Poker   Backgammon   Hearthstone   Candy Crush   Roulette
```

Position depends on audience. Placement should be a decision made explicitly early in design, since changing it later changes the game's character.

---

## 10. Game Feel

### 10.1 Swink's definition

Swink (2009) defines **game feel** as *real-time control of virtual objects in a simulated space, with interactions emphasized by polish*. The framework has three building blocks:

| Building block | Meaning | Key concept |
|---|---|---|
| **Real-time control** | Input -> response with low latency; the avatar feels like an extension of the player | Responsiveness, sensitivity, acceleration/deceleration, "feeling of control" |
| **Simulated space** | The world the avatar moves in; collisions, physics, environment | Consistency and legibility of space |
| **Polish** | Effects that emphasize and communicate interactions without changing the simulation | Juice, animation, sound, camera |

Swink also identifies metrics: **input** (sensitivity, accuracy, latency), **response** (acceleration curves, max velocity), **context** (obstacles, targets, spaces), **polish** (effects), **metaphor** (the fiction creating expectations), **rules** (the larger game that gives movement purpose).

### 10.2 Feel parameters to tune

| Parameter | Typical effect | Notes |
|---|---|---|
| **Input latency** | Total delay input -> visible result | Aim for as low as possible; many designers aim for under ~100 ms total [heuristic], and action games often target far less (one to three frames at 60 fps) |
| **Acceleration time** | Time to reach top speed | Short = snappy (Celeste, Meat Boy); long = weighty (Dark Souls) |
| **Deceleration / friction** | Stop distance | Controls precision vs sliding |
| **Top speed** | Overall pace | Match to level metrics |
| **Jump arc** | Gravity, jump velocity, variable height (release to cut), fall multiplier | Fall faster than rising feels better [practice] |
| **Air control** | Steering in air | More = forgiving |
| **Turn speed / turn radius** | Responsiveness vs weight | |
| **Hit stun / recovery** | Commitment | Fairness vs punishment |
| **Aim assist** | Gamepad accuracy | See genre notes |
| **Camera lag / lead** | Look-ahead, smoothing | See 12.5 |

Procedure:
1. Build a **tuning panel** exposing each parameter live.
2. Start from a reference game with the feel you want; match its numbers (measure by recording frames).
3. Tune **one parameter at a time**, test with fresh hands.
4. Fix **control readability** before polish.
5. Test across frame rates and input devices (keyboard vs pad vs touch).
6. Lock the movement metrics before level design begins (level design depends on jump distance, speed, etc.).

### 10.3 Weight vs responsiveness

A fundamental trade-off: realism/weight (animation anticipation, momentum) vs immediacy. Typical solutions:
- Start motion immediately, ease into weight (cancel windows, animation-cancel into dodge).
- Hide latency with anticipation visuals that start on frame 1.
- Prioritize the player's input over animation completion (allow interrupts).

---

## 11. Juice

### 11.1 Concept

**Juice** = "constant and bountiful user feedback", additional layered feedback that makes actions feel impactful without changing the core rules. The classic talk is Jonasson and Purho's "Juice it or lose it" (GDC Europe 2012), which takes a plain breakout clone and adds layers: easing, squash and stretch, particles, screen shake, sound, trails, and camera motion. The message: *you can transform feel with feedback alone*, but juice should amplify a good core, not replace one.

Vlambeer's Jan Willem Nijman's "The Art of Screenshake" (2013) similarly shows a basic shooter transforming through ~dozens of small feedback additions (recoil, muzzle flash, bullet casings, screen shake, enemy knockback, hit flash, sound layering, camera kick).

### 11.2 Juice toolbox

| Tool | Use | Typical starting values [heuristic] |
|---|---|---|
| **Squash and stretch** | Convey mass/elasticity | 10-30% scale change over 2-6 frames |
| **Anticipation / follow-through** | Telegraph, then settle | 2-6 frames anticipation for light actions |
| **Easing** | Natural motion for UI and objects | Ease-out for arrivals, ease-in for departures; back/overshoot for pop |
| **Screen shake** | Impact | Scale by event importance; 0.1-0.3 s; decay exponentially; provide an option to reduce/disable |
| **Hit flash** | Confirm damage | 1-3 frames of white |
| **Hit-stop (freeze frames)** | Weight on impact | 2-6 frames light, 6-12 frames heavy (see 12.3) |
| **Particles** | Impact, dust, trails | Short life, high count with randomness |
| **Knockback / recoil** | Physicality | Proportional to damage |
| **Camera effects** | Zoom, kick, FOV change | Subtle; return to baseline |
| **Audio layering** | Impact = transient + body + tail; pitch randomization | Pitch +/- 5-10%; vary variants to prevent repetition |
| **Color and flash** | Emphasis | Reserve for key events |
| **Rumble / haptics** | Feel through hands | Short, shaped, with off-switch |
| **UI juice** | Rolling counters, pop-ups, button feedback | Keep fast; do not delay input |
| **Time dilation** | Slow-mo on critical events | Short, rare |

### 11.3 Principles

1. **Scale with importance**: small action, small feedback; big action, big feedback. If everything shakes, nothing matters.
2. **Feedback within one frame** of the cause (visual at least), audio in sync.
3. **Layer multiple senses**: visual, audio, haptic. Audio often carries the most weight per effort.
4. **Variation**: randomize slightly (pitch, particles) to avoid fatigue.
5. **Clarity first**: effects must not obscure gameplay. Readability beats spectacle.
6. **Never slow the player's control**: juice must not add input latency or lock control unnecessarily.
7. **Accessibility**: offer toggles for screen shake, flashes, camera motion, rumble (photosensitivity and motion sickness). See `08-player-psychology-ux-accessibility.md`.
8. **Juice is not a fix for missing depth**; it amplifies.

### 11.4 Juice pass checklist for an attack

- [ ] Anticipation frames (wind-up) visible but short
- [ ] Contact: hit-stop, hit flash, particle burst, camera kick scaled to damage
- [ ] Sound: swing whoosh, impact (varied), enemy reaction vocal
- [ ] Enemy: knockback / stagger animation, damage number if appropriate
- [ ] Player: recovery frames and optional cancel window
- [ ] Feedback on kill is larger than on hit
- [ ] Option to reduce shake/flash

---

## 12. Responsiveness Toolkit: Coyote Time, Buffering, Hit-Stop, Camera

Techniques that bend strict rules in the player's favor so the game feels like it follows *intent* rather than raw timing. They are mostly invisible by design.

### 12.1 Coyote time

Allow the player to jump for a short grace period after leaving a platform edge (named after the cartoon character who runs off a cliff before falling).

- Typical window: about 3-8 frames at 60 fps (roughly 50-130 ms) [heuristic]; Celeste is commonly cited as using a few frames (6 frames per community analysis; verify against the source if quoting).
- Implementation: when grounded, set `coyoteTimer = COYOTE`; each frame decrement when not grounded; allow jump if `coyoteTimer > 0`; zero it after a jump to prevent double-jumps.
- Effect: removes "I pressed jump and it didn't work" complaints without visibly changing rules.

### 12.2 Input buffering

Store a button press for a short window and execute when legal.

- **Jump buffer**: press jump slightly before landing; jump executes on landing. Typical 4-8 frames [heuristic].
- **Combat buffer**: queue the next attack during the previous animation's recovery; execute at the first cancel frame (fighting games, Devil May Cry, Hades).
- **Action queue** in turn-based/real-time games (RTS command queues).
- Implementation: store `lastPressedTime`; accept if `now - lastPressedTime <= BUFFER` and action becomes available; consume to avoid duplicates.
- Pitfall: too large a buffer causes unintended actions executing late. Test with fast and slow players.

### 12.3 Hit-stop (hit freeze, hit pause)

Briefly freeze (or slow) the game or the participants on impact to convey weight.

- Typical: 2-4 frames light hit; 6-10 frames heavy hit; longer for finishing blows [heuristic].
- Options: global time-scale to 0, local freeze to attacker and victim only (preserves ambient motion), or time-scale to 5-20% for a short duration.
- Combine with screen shake, particles, and sound; keep input buffered during the freeze so the player does not lose control.
- Pitfall: stacking hit-stops in multi-hit combos feels laggy; shorten the stop per hit within combos or cap total freeze per second.
- Examples: fighting games, Dead Cells, Hades, Monster Hunter.

### 12.4 Other forgiveness techniques

| Technique | Description | Example |
|---|---|---|
| **Variable jump height** | Releasing early cuts the ascent | Mario, Celeste |
| **Corner correction (ledge nudging)** | Slide the player around a corner when a jump barely clips it | Celeste, Hollow Knight |
| **Hitbox forgiveness** | Hurtboxes smaller than sprite; hitboxes larger than visuals for player attacks | Most shmups and action games |
| **Edge grab / ledge assist** | Snap to ledge when close | Platformers, Uncharted |
| **Aim assist** | Soft magnetism, friction, bullet bending | Console shooters |
| **Auto-target / lock-on** | Reduces precision demands | Zelda, Souls |
| **Dodge i-frames** | Brief invulnerability during evade | Souls-likes, Hades |
| **Lenient timing windows** | Wider parry/QTE windows in early game | Sekiro, rhythm games |
| **Generous checkpoint and quick respawn** | Reduce cost of failure | Super Meat Boy, Celeste |
| **Last-hit health** | Surviving at 1 HP rather than dying on tiny overkill | Many action games |

Rule: forgiveness should favor the **player's intent**; avoid forgiveness that harms fairness in PvP (apply symmetrically).

### 12.5 Camera

The camera is part of the game feel (Swink's "simulated space" and "polish").

| Feature | Guideline |
|---|---|
| **Follow smoothing** | Light smoothing (lerp or spring) avoids jitter; heavy smoothing causes disorientation and seems to lag |
| **Look-ahead** | Offset camera in the direction of movement so the player sees more of what they approach |
| **Dead zone** | Region where the player moves without the camera moving; reduces motion for precise tasks |
| **Vertical handling** | Platformers lock vertical axis when grounded to avoid bobbing, and look down on fall |
| **Screen shake** | Trauma-based: add trauma value on events, shake amplitude = trauma^2, decays linearly (a common implementation attributed to Squirrel Eiserloh's GDC talk "Math for Game Programmers: Juicing Your Cameras With Math"; verify before citing) |
| **Zoom / FOV** | Brief FOV widening at speed or zoom-in on impact adds sensation |
| **Rooms vs scroll** | Fixed-screen rooms (Celeste, Zelda) make level design legible; scrolling suits flow |
| **Third-person camera** | Avoid obstruction; allow recentering; collision handling; support left/right shoulder |
| **Player control** | Camera control must not fight player input; offer invert, sensitivity, motion-sickness options (FOV slider, head bob off) |

Tip: Design camera behavior *before* level design: it affects visible information and difficulty.

---

## 13. Worked Examples

### 13.1 Super Mario Bros / Mario movement

- Verbs: run, jump (variable height), stomp.
- Feel: acceleration and deceleration tuned for momentum; running changes jump distance; the player quickly learns to read the mass of Mario. Level 1-1 teaches via safe spaces.
- Loop: platforms -> enemy -> reward (coin) -> new platform; the sawtooth through worlds.
- Lesson: the verb is fun in empty space; levels add questions.

### 13.2 Celeste (precision platformer)

- Verbs: jump, dash (8-direction, limited charges), wall climb (stamina).
- Forgiveness: coyote time, jump buffering, corner correction, variable jump, assist mode (game speed, invincibility, dash options) maintaining player agency.
- Quick retry: death respawn in under a second; per-room checkpointing.
- Atoms (see 02): jump, dash, climb are introduced one at a time, then chained.
- Lesson: a punishing game feels fair when forgiveness is invisible and retry is instantaneous.

### 13.3 Dark Souls / Souls-likes combat

- Verbs: attack (light/heavy), roll with i-frames, block, parry, backstab, estus.
- Commitment: attack animations lock; stamina limits spam; positioning decisions.
- Information: enemy tells (wind-ups) are readable; fairness through telegraphing; bonfires as risk-reward pacing (rest respawns enemies).
- Loop: explore -> fight -> collect souls -> decide whether to level up now (safe) or push on (risk losing them).
- Lesson: risk of loss (souls) paired with clear tells creates tension without unfairness.

### 13.4 Slay the Spire (deckbuilder roguelike)

- Verbs: play card, draft, upgrade, choose path.
- Information: enemy intents are shown; hand and draw pile known.
- Input randomness: card draw order; output randomness largely absent. Skill in sequencing and deck construction.
- Loops: fight (energy, hand) -> reward (pick 1 of 3 cards) -> map choice -> rest/upgrade/shop. Meta: unlocks new cards/relics but not power (mostly breadth).
- Systemic: synergies (Strength scaling, poison, exhaust engines); orthogonal characters.
- Lesson: transparent information plus draft-based variety yields strategic depth with simple rules.

### 13.5 Hades (core combat and feel)

- Responsiveness: dash and attack are canceled into one another; input buffering; fast dash with i-frames.
- Juice: hit-stop on strikes, screen shake on heavy attacks, crisp audio, damage numbers, boon VFX identity.
- Orthogonal: six weapons with aspect variants, and boons by god (Zeus: chain lightning, Poseidon: knockback and wall slams, Athena: deflect...), each giving different strategies.
- Loop: reward preview on doors is risk-choice; death returns to hub with narrative.

### 13.6 Breath of the Wild (systemic)

- Properties: fire, wind, electricity, metal, ice, physics; consistent for Link, enemies, environment.
- Players solve shrines and combat with unscripted combos (burning grass for updrafts, metal weapons attract lightning).
- Orthogonal rune tools (Magnesis, Stasis, Cryonis, Bombs).
- Lesson: consistent rules plus a toolbox yield emergent play; design puzzles as goals, accept alternative solutions.

### 13.7 Into the Breach (perfect information)

- Verbs: move, attack (push/pull), sacrifice.
- All enemy intents shown: the game becomes a puzzle each turn with limited actions; no output randomness for the player's moves (building resist rolls are mitigated).
- Feedback: damage previews, reversible moves (undo move, not attack), turn reset in case of mistakes.
- Lesson: remove luck where you want pure planning; make consequences predictable and visible.

### 13.8 Vampire Survivors (reduced verbs, escalating power)

- One verb: move. Weapons fire automatically; player chooses upgrades on level-up.
- Loop: survive -> collect gems -> choose upgrade -> screen fills with effects -> final chaos. Meta: gold unlocks characters and passives.
- Lesson: reduce the active verb set to maximize focus on build decisions and positioning; satisfaction from escalating spectacle (juice and power curve).

### 13.9 Mario Kart (rubber-banding as negative feedback)

- Item distribution weighted toward trailing players (visible via item boxes) and unavoidable hits to leaders (blue shell).
- Positive/negative balance keeps races close, enabling mixed-skill families to play together.
- Critique: experts feel punished. Mitigation: skill-based defenses, item management.

---

## 14. Checklists

### 14.1 Core loop review (10 questions)

1. Can I state the verb, the goal, the tension, and the reward in one line each?
2. Is the verb fun with no goal (grey-box test)?
3. How many meaningful decisions per pass? Are there trade-offs?
4. Is feedback immediate, clear, and proportional?
5. Does the loop output change the next input (new state, new challenge)?
6. Does repetition create mastery or boredom? What new patterns appear at hour 2, 5, 10?
7. What is the failure state, and how fast is retry?
8. Is there variance (content, randomness, opponents) to prevent staleness?
9. Does the meta loop amplify rather than replace the core?
10. Would the loop still work if all explicit rewards were removed? (Intrinsic check.)

### 14.2 Game feel review

- [ ] Input latency measured on target platforms.
- [ ] Movement metrics (speed, jump height/distance, turn time) documented and locked.
- [ ] Forgiveness: coyote time, buffer, corner correction, hitbox bias as needed.
- [ ] Every player action has instant visual and audio feedback.
- [ ] Impact hierarchy: light, medium, heavy have distinct feedback levels.
- [ ] Camera does not obscure, lag, or disorient; accessibility toggles present.
- [ ] Juice does not obscure readability or block input.
- [ ] Fast restart after failure.

### 14.3 Systems design review

- [ ] Resource flows balanced (faucets/sinks), with caps.
- [ ] Positive feedback loops stabilized; negative loops not hidden.
- [ ] No dominant strategy; counters and trade-offs documented.
- [ ] Interaction matrix reviewed for unintended combos.
- [ ] Randomness type chosen (input/output) and justified.
- [ ] Information visible for decisions.
- [ ] Model or simulation run, assumptions listed.

---

## 15. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Books**
- Swink, S., 2009, *Game Feel: A Game Designer's Guide to Virtual Sensation*, Morgan Kaufmann / CRC Press. https://www.routledge.com/Game-Feel-A-Game-Designers-Guide-to-Virtual-Sensation/Swink/p/book/9780123743282
- Adams, E., and Dormans, J., 2012, *Game Mechanics: Advanced Game Design*, New Riders. (Machinations framework; tool at https://machinations.io/)
- Fullerton, T., 2018, *Game Design Workshop*, 4th ed., CRC Press (ISBN 978-1138098770).
- Schell, J., 2019, *The Art of Game Design: A Book of Lenses*, 3rd ed., CRC Press / Routledge. https://www.routledge.com/The-Art-of-Game-Design-A-Book-of-Lenses-Third-Edition/Schell/p/book/9781138632097
- Elias, G. S., Garfield, R., and Gutschera, K. R., 2012, *Characteristics of Games*, MIT Press.
- Meadows, D., 2008, *Thinking in Systems: A Primer*, Chelsea Green Publishing.
- Juul, J., 2002, "The Open and the Closed: Games of Emergence and Games of Progression", Computer Games and Digital Cultures Conference Proceedings, Tampere University Press. https://doi.org/10.26503/dl.v2002i1.9
- Koster, R., 2013, *A Theory of Fun for Game Design*, 2nd ed., O'Reilly. https://www.theoryoffun.com/

**Talks and essays**
- Jonasson, M., and Purho, P., 2012, "Juice it or lose it", 2012 conference talk (video upload by grapefrukt). https://www.youtube.com/watch?v=Fy0aCDmgnxg
- Nijman, J. W. (Vlambeer), 2013, "The Art of Screenshake", INDIGO Classes 2013 (video upload by Dutch Game Garden). https://www.youtube.com/watch?v=AJdEqssNZ-U
- Meier, S., 2012, "Interesting Decisions", GDC 2012. https://www.gdcvault.com/play/1015756/Interesting
- Cook, D., 2007, "The Chemistry of Game Design", Gamasutra / Game Developer. https://www.gamedeveloper.com/design/the-chemistry-of-game-design
- Smith, H., "Orthogonal Unit Differentiation" GDC 2003 (talk on immersive sim design). https://www.youtube.com/watch?v=6zTQL-T2nkc (third-party upload).
- Eiserloh, S., 2016, "Math for Game Programmers: Juicing Your Cameras With Math", GDC 2016. https://www.youtube.com/watch?v=tu-Qe66AvtY (official GDC channel upload).
- Thorson, M., "Celeste and TowerFall Physics" (developer blog post on coyote time, jump buffering and related techniques; no verified URL at time of writing).

**Notes on sourcing**
- Frame counts, timing windows, and effect magnitudes are starting points ([heuristic]); tune with players on target hardware.
- Descriptions of specific game implementations (Celeste coyote frames, Hades cancels, XCOM odds perception) reflect widely discussed community and developer commentary; verify the primary source before citing as fact.
- The input/output randomness terminology is used in design discourse; attribution here is hedged on purpose.
