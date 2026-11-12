# Design Process: From Spark to Shipped Game

## Table of Contents

1. [How to Use This File](#1-how-to-use-this-file)
2. [Ideation Techniques](#2-ideation-techniques)
3. [Constraints as a Creative Engine](#3-constraints-as-a-creative-engine)
4. [Hooks and Player Fantasy](#4-hooks-and-player-fantasy)
5. [Design Pillars](#5-design-pillars)
6. [Pitching](#6-pitching)
7. [Prototyping](#7-prototyping)
8. [Vertical Slice and Pre-Production Exit](#8-vertical-slice-and-pre-production-exit)
9. [Iteration Cycles](#9-iteration-cycles)
10. [Scoping and Cutting](#10-scoping-and-cutting)
11. [Production Phases](#11-production-phases)
12. [Design Documentation as Living Docs](#12-design-documentation-as-living-docs)
13. [Working With Other Disciplines](#13-working-with-other-disciplines)
14. [Common Process Pitfalls](#14-common-process-pitfalls)
15. [References](#15-references)

---

## 1. How to Use This File

Load this when the user is starting something (idea, pitch, jam, new feature), is stuck mid-project (scope, direction, "what do we build first?"), or needs a process or documentation structure. Pair it with `references/02-design-frameworks.md` (theory used to evaluate ideas) and `references/12-playtesting-and-analytics.md` (how to test what you prototype).

The process in one line: **find the experience -> prove the riskiest assumption cheaply -> commit to a slice -> scale content -> keep the game alive.** Everything below elaborates one step.

Labeling convention used in this skill: **[established]** = widely documented in books/talks; **[practice]** = common industry practice; **[heuristic]** = rule of thumb, tune to your context.

---

## 2. Ideation Techniques

Ideas are cheap; the skill is generating many, filtering fast, and keeping the ones that carry a *player experience*. Separate **diverge** (quantity, no judgment) from **converge** (filter against criteria).

### 2.1 Divergent techniques

| Technique | How | Best for |
|---|---|---|
| **Verb-first** | List 10 verbs (grab, swap, bluff, carve, stack, fling). Pick one and ask "what is the most interesting thing to do with this verb, over and over?" | Mechanic-led games, jams |
| **Fantasy-first** | Write the sentence "You are a ___ who ___". Ask what moment-to-moment actions make a player *feel* that. | Narrative, immersive, simulation games |
| **Genre + twist** | Take a well-understood genre and change one axis (time, space, perspective, win condition, who the protagonist is). | Commercially safer pitches |
| **Mashup (A meets B)** | Combine two games or a game and a non-game domain. Keep only combos where the *mechanics* interlock, not just the themes. | Hooks, pitches |
| **"What if the rule were inverted?"** | Take a convention (you avoid damage, you kill enemies, you gain resources) and flip it. | Fresh dynamics |
| **Constraint-first** | Impose a hard limit (one button, 60-second sessions, no text, a single screen). See section 3. | Jams, mobile, small teams |
| **Real-world systems** | Mine jobs, hobbies, sports, sciences, rituals for existing verbs and tension (air traffic control, cooking in a rush, bureaucracy). | Simulation, management, puzzle |
| **Lens interrogation** | Run an idea through Schell's lenses (see 02-design-frameworks) to expose holes. | Convergence phase |
| **Brainwriting / 6-3-5** | 6 people write 3 ideas in 5 minutes, pass the sheet, build on others'. Silent writing avoids loud-voice bias. | Teams |
| **Worst idea first** | Deliberately list terrible ideas, then invert or fix them. Lowers the barrier for shy participants. | Stuck sessions |
| **Playing & dissecting** | Play 3 games in the target space; write down for each: the verb, the loop, the hook, one thing you would change. | Market-aware ideation |

### 2.2 Convergence filters

Score each surviving idea 1-5 on:

1. **Experience clarity**: Can you describe the feeling in one sentence?
2. **Verb strength**: Is the core action fun for 30 minutes in grey-box? (Hypothesis; not testable until prototyped.)
3. **Hook / differentiation**: Would a player repeat it to a friend? Does it have a screenshot- or clip-able moment?
4. **Feasibility**: Can this team ship it in the time and budget? (Be pessimistic; multiply estimates, see 10.1.)
5. **Audience fit**: Is there an identifiable audience that already buys this kind of game?
6. **Personal energy**: Will the team still care in month 18? [practice]

Do not average blindly: a zero on feasibility or experience clarity should veto, regardless of the total.

### 2.3 Idea-capture discipline

- Keep an "idea log": one line per idea, date, trigger. Review monthly; most ideas improve after sleeping on them.
- Write ideas as **player experiences**, not feature lists. "You feel hunted while looting" is an idea; "add a stealth system" is a feature.
- Prefer a *small* idea executed with depth over a big idea executed thinly (see "depth vs. breadth" in 10.4).

---

## 3. Constraints as a Creative Engine

Constraints reduce the search space and force novel solutions. Constraints are also a *scoping* tool, so they serve ideation and production at once.

### 3.1 Types of constraints

| Axis | Examples | What it forces |
|---|---|---|
| **Input** | One button; touch only; no camera control; shared keyboard | Depth from timing, context, and state rather than buttons |
| **Space** | One screen; a single room; 1D track; grid | Dense interactions; readability |
| **Time** | 60-second runs; real-time clocks; turn limit | Pacing, tension, decision pressure |
| **Information** | Fog of war; hidden roles; asymmetrical info | Deduction, bluffing, memory |
| **Resource** | Single currency; scarce ammo; permadeath | Trade-offs, risk assessment |
| **Content** | 10 enemy types total; procedural only; no text | Systemic depth from recombination |
| **Production** | 1 artist, 2 months, 3 colors | Style, feasibility |

### 3.2 Worked examples

- **Super Hexagon / Flappy Bird / Canabalt**: one-input games where all depth comes from timing and pattern reading; extremely short retry loops.
- **Return of the Obra Dinn**: constraint = 1-bit visuals and a single deduction verb; the whole game is observation plus a ledger. Constraint drove both art and design.
- **Papers, Please**: constraint = a single desk and a document inspection verb; tension came from time pressure plus moral cost, not content volume.
- **Spelunky**: constraint = small tile grid, systemic rules; emergent stories came from a few interacting objects (bombs, ropes, shopkeepers, arrows).

### 3.3 Applying constraints

1. Pick 1-3 constraints (more than 3 and you lose coherence).
2. Write what the constraint *forbids* and what it *enables*.
3. Ask: "What is the most interesting decision inside this box?"
4. Hold the constraint through at least one prototype before relaxing it. Relax only when it blocks the experience, not because it is hard.

---

## 4. Hooks and Player Fantasy

### 4.1 Player fantasy

The **player fantasy** is the role/power/experience the player imagines themselves having; it is the emotional promise. It differs from theme (setting) and story (plot).

| Game | Fantasy (promise) | What delivers it |
|---|---|---|
| Hades | Defiantly fighting out of hell, getting stronger through each failed attempt | Fast combat, death as narrative progress, boons |
| Stardew Valley | A gentle escape: build a life at your own pace | Open schedule, small daily loops, relationships |
| Dark Souls | Overcome a cruel world through patience and learning | Readable enemy tells, high stakes, bonfires |
| Hitman (WoLP) | The patient, clever assassin with a sandbox of options | Systemic NPC routines, disguises, environmental kills |
| Slay the Spire | The deck-building genius whose build comes together | Drafting, synergy, readable enemy intents |
| Tetris | Bringing order from chaos with growing mastery | Pattern fitting under rising speed |

Test: if the player were to describe the fantasy in their own words, would it match? Every mechanic should either *deliver* the fantasy or *get out of its way*. Mechanics that contradict it (e.g., tedious inventory management in a power fantasy) are suspects.

### 4.2 The hook

A **hook** is the compact reason someone would try and talk about the game. Good hooks combine something familiar (so people understand) with something different (so people care).

Characteristics of a strong hook [practice]:
- **Stateable in one sentence** with no jargon.
- **Visible in a trailer or screenshot** (marketing needs it to be seen).
- **Mechanically real**, not just a theme skin: the hook should be present in the core loop.
- **Surprising but legible**.

Example hook statements:
- "Portal": "Solve puzzles by placing two linked portals on walls." (Verb is the hook.)
- "Into the Breach": "Chess-like tactics where you see every enemy attack in advance and prevent damage." (Rule twist on a known form.)
- "Papers, Please": "Be a border inspector in a dystopia; your paycheck decides whether your family eats." (Fantasy plus tension.)
- "Vampire Survivors": "Survive 30 minutes while your weapons fire automatically and grow absurdly powerful." (Reduced input, escalating power.)

Hook failure modes: "It's like X and Y but better" (no distinctive idea); feature lists ("open world, crafting, co-op") without a reason; hooks that exist only in marketing copy.

### 4.3 Experience statement exercise

Write all four, in this order, before designing systems:
1. **Feeling**: "The player feels ___ (pressure / mastery / cozy discovery)".
2. **Behavior**: "To feel that, the player repeatedly ___".
3. **Tension**: "The thing that stops them from doing it trivially is ___".
4. **Payoff**: "The moment they remember afterward is ___".

If you cannot fill in the tension, there is no game yet, only an activity.

---

## 5. Design Pillars

**Pillars** are 3-5 short statements of what the experience must be; they are used to say yes or no to features. They are decision tools, not marketing slogans.

### 5.1 Qualities of a good pillar [practice]

1. **Falsifiable / decision-making**: you can name a feature that violates it.
2. **Experience-oriented**, not feature-oriented ("Every fight is a puzzle", not "Has a combat system").
3. **Specific to this game**: if it fits any game, it is useless ("Fun", "Polished", "Engaging").
4. **Short**: 2-6 words plus one clarifying sentence.
5. **Few**: 3-5. More than five means none are prioritized.
6. **Ordered or weighted** when they conflict (state which wins).

### 5.2 Good vs bad

| Bad (and why) | Better (and why) |
|---|---|
| "Great graphics" (quality target, applies to every game) | "Readable chaos: the player can always tell what is dangerous in under 0.5 s" (testable, constrains VFX) |
| "Deep combat" (vague) | "Every fight is won by preparation and positioning, not reflexes" (tells you what to cut: twitch-heavy enemies) |
| "Open world with crafting" (features) | "Make do with what you scavenge" (experience; crafting becomes a means) |
| "Fun for everyone" | "Short, calm sessions that can be paused anytime" (excludes forced timers, long unskippable sequences) |
| "Immersive" | "Never break the fourth wall: all information is diegetic" (HUD decisions follow) |
| "Emotional story" | "The player's choices cost something they care about" (constrains branching design) |

### 5.3 Worked example: pillars used to resolve an argument

Game: a roguelike deckbuilder. Pillars: (1) **Readable decisions**: every enemy intent is visible. (2) **Builds that snap together**: synergy must be discoverable within a run. (3) **Short runs**: a run is 30-45 minutes.

Proposal: add enemies with hidden random attacks to "increase tension". Verdict: violates pillar 1. Alternative accepted: telegraphed multi-turn attacks that increase tension *without* hiding information. Proposal: a 3-hour "campaign mode". Verdict: violates pillar 3; offered a meta-progression layer instead.

### 5.4 Process to derive pillars

1. Collect the experience statement (4.3), the competitive references, and the team's "must not happen" list.
2. Brainstorm 10-15 candidate pillars as sentences.
3. Cluster; merge; discard those that apply to every game.
4. For each candidate, write a feature it would **kill** and a feature it would **demand**. Drop pillars that do neither.
5. Reduce to 3-5; order them for conflicts.
6. Revisit at each milestone; pillars may be revised but not casually. Changing a pillar = a conscious pivot.

### 5.5 Using pillars day-to-day

- Put them at the top of the GDD and in the sprint review template.
- Every feature spec has a line: "Which pillar does this serve? Does it risk another?"
- During playtests, add one question per pillar ("Did you feel ___?").
- Use them in cuts (see 10): the first features cut are those serving no pillar.

---

## 6. Pitching

A pitch is a *decision request*: it asks someone (publisher, boss, team, funder) to invest time or money. Design the pitch around what that person needs to decide.

### 6.1 Audiences

| Audience | Cares about | Lead with |
|---|---|---|
| Publisher / investor | Market, differentiation, team credibility, risk, ask | Hook, comparable titles, plan, budget |
| Internal greenlight committee | Strategic fit, cost, risk | Pillars, vertical-slice plan |
| Team | Direction, role, why it matters | Fantasy, pillars, what they will build |
| Press / players | Excitement | Hook, a clip, a unique moment |

### 6.2 Elevator pitch (20-30 seconds)

Template: **"[Game] is a [genre] where you [core verb] as a [player role] to [goal], while [tension]. Unlike [reference], [differentiator]."**

Example: "Into the Breach is a turn-based tactics game where you defend cities from giant monsters by pushing and redirecting them, with every enemy move shown in advance, so the challenge is pure puzzle-like planning."

Checklist: no more than 3 sentences; contains verb, tension, and differentiator; no adjectives like "innovative"; a stranger can repeat it back.

### 6.3 One-page pitch / concept sheet

Sections, in order (a template exists in `templates/one-page-concept.md`):

1. **Title and one-line hook**
2. **Genre, platform, target audience, session length**
3. **Player fantasy** (2 sentences)
4. **Pillars** (3-5)
5. **Core loop** (diagram or 3-step list) and the 30-second moment
6. **What makes it different** (vs 2-3 comparables, and "why now")
7. **Content and progression overview** (what the player does at hour 1, hour 10)
8. **Business model and monetization stance** (see 09)
9. **Scope and team**: size, timeline, budget range
10. **Risks and mitigation**: top 3 risks and the prototype that addresses each
11. **Visuals**: one mood image or screenshot-quality mockup; one gameplay mockup

### 6.4 Longer pitch deck (publisher) [practice]

~10-15 slides: hook; gameplay video or animatic; pillars; core loop; progression; market and comparables with *sales or engagement evidence you can verify*; audience; team; schedule with milestones; budget and ask; risks. Publishers weigh **team track record, prototype quality, and clarity of scope** heavily; a playable build beats slides.

### 6.5 Comparables ("comps")

- Choose 2-3 recent, relevant titles whose audience overlaps. Explain what you take from each and how you differ.
- Avoid the "AAA-hit comp" (the next Minecraft) unless justified; it signals poor market awareness.
- Do not cite sales or revenue figures unless you have a verifiable source. Mark estimates clearly.

### 6.6 Pitching mistakes

- Telling the story before the gameplay.
- Presenting a feature list instead of an experience.
- No answer to "why will this team finish it?"
- Hiding risks (reviewers will find them and distrust the rest).
- Pitching what you would do with unlimited budget.

---

## 7. Prototyping

A **prototype** is a question-answering tool: build the least that answers a specific design question. If you cannot state the question, you are building a game, not a prototype.

### 7.1 What to prototype (risk-first)

List your assumptions and rank by **(impact if wrong) x (uncertainty)**. Prototype the top one first.

| Risk category | Example question | Prototype type |
|---|---|---|
| **Core verb feel** | Is moving/aiming/swinging fun for 5 minutes? | Digital grey-box with temp art; tune feel parameters |
| **Core loop** | Does repeating the 30-s loop produce interesting decisions? | Paper or digital loop with placeholder content |
| **Systems/balance** | Do the numbers produce multiple viable strategies? | Spreadsheet/simulation; paper (see 04) |
| **Content generation** | Do procedural levels feel varied and fair? | Generator + 20 samples reviewed |
| **Pacing/progression** | Does mid-game stay interesting? | Compressed playthrough with accelerated progression |
| **UX / readability** | Can players parse the screen at speed? | Mock HUD with real enemies; screenshot tests |
| **Technology** | Can the engine do N units / netcode at latency L? | Tech spike, not a design prototype |
| **Market** | Will anyone want this? | Trailer, store page test, demo; see 12 |

### 7.2 Fidelity ladder

Use the lowest fidelity that answers the question.

| Fidelity | Tools | Time per iteration | Good for | Poor for |
|---|---|---|---|---|
| **Thought/whiteboard** | Diagrams, spreadsheets | Minutes | Structure, economy first pass | Anything involving feel |
| **Paper / cards / dice** | Index cards, tokens, grid paper | Hours | Turn-based systems, economy, puzzles, social/negotiation, board games | Real-time reflex, physics, spatial navigation |
| **Role-play / Wizard-of-Oz** | A human simulates the system (AI, DM) | Hours | Social, narrative, AI behavior | Scaling |
| **Digital grey-box** | Engine primitives, no art, debug UI | Days | Game feel, real-time loops, level metrics | Final readability, art-dependent mood |
| **Playable vertical slice** | Real art/audio for a sample | Weeks to months | Final feel, pitch, production plan | Quick idea testing (too expensive) |

### 7.3 Paper prototyping rules [practice]

1. Prototype the *rules and decisions*, not the presentation. Use index cards, coins, dice.
2. Write rules on one page; if it takes more, simplify.
3. Play within an hour of the idea. First play will fail; that is the point.
4. Change **one variable** per round (card cost, board size, scoring rule) and record the result.
5. Turn real-time into turn-based by "slowing down time" only if the decisions survive; reflex games rarely translate.
6. Playtest with someone who did not design it, and say nothing while they play (observe confusion).
7. Count: how many meaningful decisions per minute? Which choices were never picked? Where did players stall or check phones?

### 7.4 Digital prototyping rules

1. **Grey-box first**: primitives, no art. If it is not fun with cubes, art will not fix it.
2. **Expose tuning variables** (speed, jump height, cooldowns, acceleration) in a debug panel or config file; tune live.
3. **Build one verb to feel good** before adding a second. See `03-core-loops-and-mechanics.md` section on game feel for what to tune.
4. **Hard-code and hack freely**; prototype code is disposable. Decide in advance that it will be thrown away (many teams keep it by accident).
5. **Instrument early**: log deaths, time-in-state, choice frequencies; even simple CSV logs reveal dominant strategies.
6. Always provide a **fast restart**; reset time under 3 seconds so testers iterate.

### 7.5 Timeboxes [heuristic]

| Prototype goal | Suggested timebox | Exit criteria |
|---|---|---|
| Verb feel | 1-3 days | Testers want to keep doing it without goals |
| Core loop | 1-2 weeks | Players make non-obvious choices; sessions extend beyond what was asked |
| Single system (economy, crafting) | 3-7 days | Multiple viable strategies emerge in simulation |
| Procedural content sample | 1-2 weeks | 80% of samples pass a human review |
| Slice of the full experience | 6-12 weeks | See section 8 |

Timebox hard. When the box ends, make an explicit decision: **kill, pivot, or proceed**. "Another week" needs a new, specific hypothesis.

### 7.6 How to read a prototype result

- **Proceed** if: unprompted replay, emergent tactics, players invent strategies you did not plan, the room laughs or leans in.
- **Pivot** if: the fun lives in a side effect (the physics, the bug, the speed run).
- **Kill** if: players need constant explanation, find no choices, or play out of politeness. A killed prototype is a successful risk reduction.
- Beware **"the designer is the only one who gets it"**: your own skill hides problems. Test with fresh players early.

### 7.7 Examples

- **Portal** grew from the student project *Narbacular Drop*; a small prototype proved the portal verb before commercial development [practice; widely reported].
- **Slay the Spire** was iterated in public via Early Access, using player data to tune cards.
- **Hades** and **Dead Cells** used long Early Access periods to iterate core combat and balance before 1.0 (Supergiant and Motion Twin respectively; widely reported).

---

## 8. Vertical Slice and Pre-Production Exit

### 8.1 What a vertical slice is

A **vertical slice** is a small portion of the game at *shippable quality* across all disciplines (design, art, audio, UI, tech, narrative) that demonstrates the intended experience, the pipeline, and a believable cost to produce the rest. It is not a prototype (disposable and low-fidelity) and not a demo for press only.

A **horizontal slice** is a thin layer across all features at low quality (every system exists but crudely). Use the horizontal slice to test integration; use the vertical slice to prove quality and cost.

### 8.2 Contents of a good vertical slice

- 5-20 minutes of play (heuristic) including the first-time experience and the core loop repeated at least 2-3 times.
- At least one example of each *content type* (enemy, level, item, quest) built through the **real pipeline**.
- Final-ish UI, audio, VFX at the quality bar.
- Technology on target hardware at target performance (or a credible path).
- The "fun spike": the moment that sells the game.

### 8.3 Exit criteria for pre-production [practice]

Checklist before committing to full production:

- [ ] Core loop is fun in grey-box and in the slice (blind-tested with players outside the team).
- [ ] Pillars are written, and the slice demonstrably embodies them.
- [ ] Content pipeline works: measured time to create one level/enemy/quest at quality.
- [ ] **Cost model**: estimated hours per content unit x number of units fits the budget with a buffer.
- [ ] Top technical risks retired or have a mitigation.
- [ ] Scope defined as MoSCoW (section 10), with a cut list.
- [ ] Schedule with milestones; a realistic velocity from pre-production, not hope.
- [ ] Agreed definition of done and quality bar.

If any of these fails, pre-production is not finished. The most expensive mistake in games is entering production with an unproven core.

### 8.4 Slice pitfalls

- **Slice-itis**: polishing a gorgeous slice that cannot be replicated at scale (hand-made one-off assets).
- **Slice hides the second hour**: the slice proves the first 15 minutes; a mid-game plan is still needed (progression outline, content variety plan).
- **Faked tech**: pre-rendered or hard-coded sequences that the real engine cannot do.

---

## 9. Iteration Cycles

### 9.1 The core cycle

```
  Design hypothesis ("players will feel X when Y")
          |
          v
   Build the smallest test --> Playtest (observe, measure)
          ^                             |
          |                             v
   Decide: change / keep / cut <-- Analyze (why, not only what)
```

Schell calls this the "loop" of design: do not stop at the first idea; run it through the cycle repeatedly (Schell 2019). Fullerton's *playcentric* process puts the player in the loop from the first prototype (Fullerton 2018).

### 9.2 Cadence [heuristic]

| Stage | Iteration length | Playtests |
|---|---|---|
| Concept / paper | Hours to days | Daily, 2-5 people |
| Prototype | 1-3 days | Every build, internal + friends |
| Pre-production | 1-2 weeks | Weekly, fresh players regularly |
| Production | Sprint (1-3 weeks) | Per milestone + external every 4-6 weeks |
| Alpha/Beta | Daily builds | Large-scale tests, telemetry |

### 9.3 Making iteration effective

1. **State the hypothesis and the test question** before each test.
2. **Fix the biggest problem first**; do not tweak numbers while the core is broken.
3. **Change one thing at a time** when diagnosing balance or feel; otherwise you cannot attribute the effect.
4. **Observe, do not explain**: watch silently; note where players hesitate, repeat, or laugh.
5. **Distinguish symptoms from causes**: players report solutions ("add a map"); find the underlying problem (lost) and consider multiple fixes.
6. **Keep a decision log** (what we changed, why, evidence). Prevents re-litigating and informs future projects.
7. **Know when a feature is done**: it meets its pillar goal at the quality bar. Further tuning is polish with diminishing returns.

### 9.4 Iterating after launch

Live games iterate with data: A/B tests, cohorts, content cadence (see `09-monetization-and-live-ops.md`, `12-playtesting-and-analytics.md`). Keep a **design health dashboard**: retention curve, funnel drops, pick/win rates, economy balances.

---

## 10. Scoping and Cutting

### 10.1 Estimating

- Estimates are consistently optimistic. Heuristic: multiply by 1.5-2x for unfamiliar work and add explicit time for bug fixing, integration, polish, and iteration (often as large as initial implementation).
- Estimate **content** as units x cost-per-unit measured from the vertical slice, not guessed.
- Track velocity (completed work per sprint) rather than trusting initial estimates.
- Reserve a buffer (10-20% heuristic) for unknowns.

### 10.2 MoSCoW prioritization

| Category | Meaning | Rule |
|---|---|---|
| **Must have** | The game does not work or fails a pillar without it | Core verb, loop, essential content |
| **Should have** | Important, painful to omit, but game ships | Secondary mechanics, extra modes |
| **Could have** | Nice if time remains | Cosmetics, extra content, QoL extras |
| **Won't have (this time)** | Explicitly out of scope | Documented to prevent scope creep |

Rules: Musts should not exceed about 60% of capacity (heuristic) so there is slack; review the list at each milestone; "Won't" is a real list written down.

### 10.3 Risk-first sequencing

Order work by risk, not by game chronology:
1. Design risks (is it fun?)
2. Technical risks (can we build it?)
3. Content/production risks (can we afford scale?)
4. Market risks (will they buy it?)

Build the scariest parts first. Leaving risky systems for the end is the classic cause of crunch and cancellation.

### 10.4 Cutting heuristics

When forced to cut, evaluate each feature on:

| Question | Cut if |
|---|---|
| Does it serve a pillar? | No |
| Is it on the critical path of the core loop? | No |
| Cost vs. player-perceived value | Cost high, value diffuse |
| Does it interact with many other systems (bug surface)? | Yes, and value is low |
| Can it be replaced by a cheaper approximation? | Yes (scripted instead of systemic, 3 instead of 12) |
| Was it requested by playtesters repeatedly as a *problem solution* or as a *feature wish*? | Wish only |
| Can it be added post-launch? | Yes (and the game is not incomplete without it) |

Principles:
- **Cut breadth before depth**: ship fewer systems that interact richly rather than many thin ones. Systemic depth multiplies content.
- **Cut late-binding content first, systems that other systems depend on last.**
- **Cut early** rather than at the end: a feature cut in month 3 saves its full cost; cut in month 18 loses sunk cost and creates holes.
- **Replace, don't remove** when a cut leaves a hole (e.g., reduce open world to a hub).
- Write the **cut list in advance** with triggers ("If at milestone X feature Y is not at quality Z, cut it").

### 10.5 Scope creep control

- A change request process: "What does it replace?" (Zero-sum scope: adding means removing.)
- Ideas parking lot with a monthly review.
- Distinguish **core scope** (pillars) from **optional scope** (extras).
- The producer and design lead jointly own scope; neither alone.

---

## 11. Production Phases

Terms vary by studio. This table is a common (not universal) model [practice].

| Phase | Goal | Design focus | Key deliverables | Exit gate |
|---|---|---|---|---|
| **Concept** | Decide if the idea is worth pre-production | Hook, fantasy, pillars | One-pager, mood board, rough comps, small team | Greenlight to prototype |
| **Pre-production** | Prove the game and the plan | Prototypes, core loop, vertical slice, pipeline | Prototypes, slice, GDD v1, scope plan, risk list | Greenlight to production (8.3) |
| **Production** | Build all content and features | Feature specs, content design, balancing passes, level design, tuning | Playable builds each sprint, content milestones | "First playable" -> "Content complete" (feature complete) |
| **Alpha** | Feature complete | Stop adding features; fix, tune, test progression end-to-end | Complete game, rough polish, known bugs | Feature complete + all content in |
| **Beta** | Content complete, stabilize | Balance, difficulty, onboarding, QA, accessibility; no new design | Release candidate, store assets, certification builds | Content complete / code release candidate |
| **Launch (Gold)** | Ship | Day-one patch scope, community prep | Master build, launch plan | Release |
| **Live / post-launch** | Maintain, grow, learn | Data-driven tuning, updates, seasons, community | Patches, content roadmap, telemetry reviews | Sunset or continued ops |

Design responsibilities across phases:
- **Concept/Pre-pro**: highest design churn; explore widely, then converge.
- **Production**: design shifts to *specification and tuning*; avoid reopening core decisions (pillar changes need explicit review).
- **Alpha/Beta**: design is mostly *balancing, polish, and removing friction*; changes are risk-weighted ("Does this risk a regression?").
- **Live**: design is a continuous service; tools for rapid tuning (remote config) are valuable.

Notes:
- Agile/Scrum fits production but is poor at pre-production's uncertainty; many teams use a looser, milestone-driven process there [practice].
- "First playable" (sometimes "FPS": first playable state) = early build where the core loop can be played end to end.
- Crunch correlates with late discovery of problems; the whole process above is partly a defense against it.

---

## 12. Design Documentation as Living Docs

### 12.1 Purpose

Documentation exists to **communicate decisions and enable implementation**, not to prove thoroughness. Docs are for: shared understanding, onboarding, outsourcing, certification, and memory. A document nobody reads is waste.

### 12.2 Document hierarchy

| Doc | Audience | Length | Changes |
|---|---|---|---|
| **One-pager** | Everyone, stakeholders | 1 page | Rarely; changes mean pivot |
| **Pillars and vision** | Team | 1 page | Rarely |
| **GDD (overview)** | Team | 10-30 pages, hyperlinked [heuristic] | Per milestone |
| **Feature specs** | Designers, engineers, QA | 1-5 pages each | Often; owned by one designer |
| **Content tables / spreadsheets** | Designers, tools | Data | Constantly |
| **Level docs** | Level designers, artists | 2-6 pages + diagrams | During level production |
| **Decision log / changelog** | Team | Append-only | Constantly |
| **Test plans and reports** | Design, QA | Short | Per test |

Templates: `templates/gdd-template.md`, `templates/feature-spec.md`, `templates/level-design-doc.md`, `templates/playtest-plan.md`.

### 12.3 Principles for living docs

1. **Single source of truth**; link instead of duplicating. Duplicated facts drift.
2. **Wiki or version-controlled docs** (Confluence, Notion, Google Docs, markdown in repo) with change history. Avoid monolithic Word files emailed around.
3. **Short and scannable**: tables, diagrams, bullet points; lead with the *why* (pillar) and the *what*; the *how* only as needed.
4. **Data in tables or spreadsheets**, prose for intent. Numbers in prose rot.
5. **One owner per doc**, with date and status (Draft, Approved, Implemented, Deprecated).
6. **Mark open questions** and assumptions explicitly.
7. **Write testable statements**: "Player can dodge-roll for 0.4 s with i-frames from 0.05-0.30 s" beats "dodge feels responsive".
8. **Document intent and rationale**, so implementers can make good calls on unspecified cases.
9. **Archive, don't delete**; mark old decisions deprecated with reason.
10. **Review docs with engineers early**; they will find ambiguities in minutes.

### 12.4 Feature spec checklist

- Purpose and pillar link; player-facing goal.
- User stories ("As a player I want ___ so that ___").
- Rules, formulas, and ranges (with tuning tables).
- States and transitions (flow chart / state machine).
- Edge cases: death, disconnect, interrupt, save/load, pause, controller swap, localization, accessibility.
- UI/UX and feedback (visual, audio, haptic), including error states.
- Dependencies, risks, analytics events to log.
- Acceptance criteria (how QA verifies it) and playtest questions.

### 12.5 When docs are harmful

- Long GDDs written before prototyping describe an imaginary game. Write less early, more as decisions solidify.
- Over-specification of the unknown; leave tuning values as ranges and mark them "to be tuned".
- Docs as a substitute for talking. A 10-minute conversation plus a 1-page summary often wins.

---

## 13. Working With Other Disciplines

The designer's job is to **make others effective** at realizing the experience. Influence by clarity, not authority.

| Discipline | What they need from design | What design needs from them | Friction points and fixes |
|---|---|---|---|
| **Engineering** | Unambiguous specs, priorities, edge cases, tuning hooks | Cost estimates, feasibility, tools, performance limits | "Just make it work" requests. Fix: write acceptance criteria; discuss risky features early; provide data-driven configs |
| **Art / animation** | Intent (mood, readability, silhouette), gameplay constraints (hit frames, timing), references | Readability feedback, style constraints, asset cost | Anticipation frames vs responsiveness. Fix: agree on frame data early; prototype with placeholder animations |
| **Audio** | Feedback hierarchy, event lists, emotional beats | Prototypes of sound feedback early; mix constraints | Late audio makes games feel flat. Fix: temp sounds in the grey-box |
| **UI/UX** | Information needs per state, priority order, flows | Usability expertise, platform conventions | Designers ask for too much HUD. Fix: list "what decision does this info support?" |
| **QA** | Test plans, expected behaviors, risk areas | Bug reports, repro, perceived balance issues | Specs unclear. Fix: acceptance criteria; early QA involvement |
| **Production** | Scope clarity, dependencies, risk | Schedule, budget, resource constraints | Hidden scope. Fix: shared scope board; MoSCoW |
| **Narrative** | Mechanical constraints, verbs, pacing | Story beats, tone, dialogue systems | Ludonarrative dissonance. Fix: co-design early; see 07 |
| **Analytics/data** | Questions to answer, events to log | Dashboards, A/B test setups | Analysis without questions. Fix: define hypotheses before instrumentation |
| **Marketing / community** | Hook, key moments, roadmap | Player sentiment, market intel | Promises features not planned. Fix: shared messaging doc |
| **Leadership** | Honest status, risks, options | Decisions, priorities | Designers surprising leadership. Fix: regular demos, risk reports |

### 13.1 Collaboration practices

- **Show, don't tell**: playable builds and short videos over decks.
- **Co-ownership of pillars**: workshop the pillars with the whole team; shared ownership increases adherence.
- **Design reviews** with explicit rubrics (pillar fit, clarity, risk, cost).
- **Give problems, not just solutions**, to specialists ("Players must read enemy attacks at 20 m; what do you propose?").
- **Respect expertise**: ask the engineer what the cheap version is; ask the artist what reads at distance.
- **Feedback etiquette**: critique the work against the pillars, not the person; offer one fix suggestion per issue.
- **Decision rights**: clarify who decides (design lead, director, vote). Ambiguity breeds design by committee.

### 13.2 Design roles (typical) [practice]

| Role | Focus |
|---|---|
| Game/Creative Director | Vision, pillars, final decisions |
| Lead Designer | Design consistency, team coordination |
| Systems Designer | Rules, economy, balance |
| Combat / Gameplay Designer | Moment-to-moment mechanics, feel |
| Level / Encounter Designer | Spaces, pacing, difficulty |
| Narrative Designer | Story delivery, dialogue systems |
| UX Designer | Flows, HUD, onboarding |
| Technical Designer | Scripting, prototyping, tools |
| Monetization / Live-ops Designer | Economy, events, retention |

Small teams: one person wears many hats. Name the hat you are wearing in discussions.

---

## 14. Common Process Pitfalls

| Pitfall | Symptom | Remedy |
|---|---|---|
| **Feature-first design** | Long feature list, no experience statement | Write the experience statement and pillars; cut features without a pillar |
| **Documentation before prototype** | 80-page GDD for an unplayed game | Prototype the riskiest assumption first; write a one-pager |
| **Prototype becomes production** | Technical debt, slow iteration | Declare prototype code disposable; rebuild with architecture |
| **Playtesting only with friends/team** | Everyone loves it; strangers bounce | Test with unbiased players from the target audience early |
| **Skipping the second hour** | Great first 15 minutes, nothing after | Plan mid-game progression and variety in pre-production |
| **Design by committee** | Bland compromises | Define decision rights; use pillars as tie-breakers |
| **Scope by addition** | Schedule slips, features half-finished | Zero-sum scope; MoSCoW; cut list with triggers |
| **Over-balancing too early** | Tuning numbers for a non-fun core | Fix structure first; tune after the core works |
| **Ignoring cost of content** | Content debt, crunch | Measure cost per unit in the slice |
| **Copying surface, not principle** | "Souls-like" with floaty combat | Extract why it works (telegraphs, commitment, risk) and adapt |
| **Attachment to ideas** | Defending failed features | Kill rules decided in advance; hypotheses, not beliefs |
| **No decision log** | Re-arguing old choices | Maintain a lightweight log |
| **Pitching hype without proof** | Investor skepticism | Show a playable build and a cost plan |

---

## 15. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Books**
- Schell, J., 2019, *The Art of Game Design: A Book of Lenses*, 3rd ed., CRC Press / Routledge. https://www.routledge.com/The-Art-of-Game-Design-A-Book-of-Lenses-Third-Edition/Schell/p/book/9781138632097
- Fullerton, T., 2018, *Game Design Workshop: A Playcentric Approach to Creating Innovative Games*, 4th ed., CRC Press (ISBN 978-1138098770). Playcentric process, paper prototyping, formal/dramatic elements.
- Adams, E., and Dormans, J., 2012, *Game Mechanics: Advanced Game Design*, New Riders.
- Sirlin, D., *Playing to Win* (online essays, including on scouting and designing for competition). https://www.sirlin.net/ptw
- Koster, R., 2004 (2nd ed. 2013), *A Theory of Fun for Game Design*, Paraglyph / O'Reilly. https://www.theoryoffun.com/

**Talks**
- Meier, S., 2012, "Interesting Decisions", GDC 2012. https://www.gdcvault.com/play/1015756/Interesting

**Notes on sourcing**
- Statements marked [practice] or [heuristic] reflect common industry practice and the author's judgment, not formal research findings. Timeboxes, percentages, and slice lengths are starting points to adapt.
- The Narbacular Drop / Portal, Early Access, and other production anecdotes are widely reported publicly; verify specifics before citing them formally.
