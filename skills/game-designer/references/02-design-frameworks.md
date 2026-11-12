# Design Frameworks and Theory

## Table of Contents

1. [How to Use Frameworks](#1-how-to-use-frameworks)
2. [MDA: Mechanics, Dynamics, Aesthetics](#2-mda-mechanics-dynamics-aesthetics)
3. [LeBlanc's 8 Kinds of Fun](#3-leblancs-8-kinds-of-fun)
4. [DDE: Design, Dynamics, Experience](#4-dde-design-dynamics-experience)
5. [Schell's Elemental Tetrad and Lenses](#5-schells-elemental-tetrad-and-lenses)
6. [Fullerton: Formal and Dramatic Elements](#6-fullerton-formal-and-dramatic-elements)
7. [Koster: Theory of Fun](#7-koster-theory-of-fun)
8. [Csikszentmihalyi: Flow](#8-csikszentmihalyi-flow)
9. [Caillois: Agon, Alea, Mimicry, Ilinx; Paidia and Ludus](#9-caillois-agon-alea-mimicry-ilinx-paidia-and-ludus)
10. [Player Typologies: Bartle and Quantic Foundry](#10-player-typologies-bartle-and-quantic-foundry)
11. [Lazzaro's 4 Keys to Fun](#11-lazzaros-4-keys-to-fun)
12. [Salen and Zimmerman: Meaningful Play and the Magic Circle](#12-salen-and-zimmerman-meaningful-play-and-the-magic-circle)
13. [Sid Meier: Interesting Decisions](#13-sid-meier-interesting-decisions)
14. [Dan Cook: Skill Atoms and the Chemistry of Game Design](#14-dan-cook-skill-atoms-and-the-chemistry-of-game-design)
15. [Keith Burgun: Form Taxonomy](#15-keith-burgun-form-taxonomy)
16. [Choosing and Combining Frameworks](#16-choosing-and-combining-frameworks)
17. [References](#17-references)

---

## 1. How to Use Frameworks

Frameworks are **lenses, not laws**. They give vocabulary, expose blind spots, and structure critique. None predicts whether a game will be fun; playtesting does. Use them to:

1. Generate hypotheses ("this mechanic should produce Challenge; does it?").
2. Diagnose ("players are bored; which kind of fun is missing; which dynamic should produce it?").
3. Communicate with the team (shared words reduce argument).
4. Check coverage (is any critical dimension ignored?).

Each section: **Summary -> How to apply -> Limitations**. Items labeled [heuristic] are practical rules of thumb, not research results.

Quick chooser:

| Question | Start with |
|---|---|
| What should players feel, and how do rules create it? | MDA (2), 8 Kinds of Fun (3) |
| Is my design missing a dimension (story, tech, aesthetics)? | Tetrad (5), Fullerton (6) |
| Why is this level/skill ramp boring or frustrating? | Flow (8), Skill atoms (14), Koster (7) |
| Who is this for? | Bartle / Quantic Foundry (10), Caillois (9) |
| Emotion without story? | Lazzaro (11) |
| Are my choices good? | Meier (13), Salen and Zimmerman (12) |
| What kind of thing am I even making? | Burgun (15), Caillois (9) |

---

## 2. MDA: Mechanics, Dynamics, Aesthetics

### 2.1 Summary

Hunicke, LeBlanc and Zubek (2004) formalize a game as three layers:

| Layer | Definition | Example (Poker) |
|---|---|---|
| **Mechanics** | Rules, algorithms, data structures: the components of the game at the code/rules level | Deck, betting rounds, hand rankings |
| **Dynamics** | Run-time behavior arising from mechanics acting on player input over time | Bluffing, reading opponents, bankroll management |
| **Aesthetics** | The emotional responses evoked in the player | Challenge, Fellowship, Submission (ritual) |

**Two perspectives**: the designer sees M -> D -> A (builds rules, hopes for feelings); the player experiences A -> D -> M (feels first, gradually perceives the rules). Therefore design **from the intended aesthetic backward**, and remember that you only control mechanics directly.

### 2.2 How to apply

1. Choose 1-3 target aesthetics (use the 8 kinds of fun, section 3). Rank them.
2. For each, ask what **dynamics** would produce it (e.g., Challenge -> mastering patterns, resource tension; Fellowship -> shared goals plus dependency).
3. Choose the **mechanics** that give rise to those dynamics; prototype the smallest set.
4. Test: observe the dynamics players actually produce (not what you intended); adjust mechanics.
5. When diagnosing, move *up* the chain: symptom (aesthetic) -> behavior (dynamic) -> rule (mechanic) to change.

Worked example, **Left 4 Dead** [practice]: Target aesthetics: Fellowship, Sensation (fear), Challenge. Dynamics: players stay grouped and cover each other; the unpredictable pacing director creates peaks and lulls. Mechanics: AI Director that spawns based on player stress, special infected that punish stragglers (Smoker, Hunter), friendly-fire and incapacitation rules, shared resources. Remove any mechanic and the dynamic that creates the aesthetic collapses.

Worked example, **Into the Breach**: Aesthetic: Challenge (as puzzle), Discovery. Dynamics: planning around forced enemy moves; sacrificing buildings for tempo. Mechanics: visible enemy intents, push/displacement-based weapons, small 8x8 grids, grid-power health.

Diagnostic table:

| Aesthetic complaint | Look for dynamic | Likely mechanic change |
|---|---|---|
| "No tension" | Players accumulate safe surplus | Add upkeep/decay, scarcity |
| "Nothing to decide" | Dominant strategy | Costs/trade-offs, situational counters |
| "Too random" | Outcomes ignore skill | Reduce output randomness; add mitigation |
| "Feels lonely" | Little interdependence | Shared goals, asymmetric roles |

### 2.3 Limitations and critiques

- Designed to bridge design, development and research, not to be a complete theory. The authors present it as a *lightweight* tool.
- **Aesthetics** is an overloaded word (in MDA = emotional responses, not graphics). Players' emotions vary; one ruleset yields different aesthetics for different people.
- Treats the designer-to-player pipeline linearly; ignores context (social setting, platform, culture) and the player's contribution, which DDE (section 4) tries to remedy.
- Does not cover narrative, art, tech and production directly (the tetrad does, section 5).
- Dynamics are observed, not specified; designers still need testing to learn them.

---

## 3. LeBlanc's 8 Kinds of Fun

### 3.1 Summary

A taxonomy of aesthetics from the MDA work; the kinds are **not exhaustive or exclusive**, and a game combines several (Hunicke et al. 2004).

| Kind | Meaning | Typical mechanics and dynamics | Examples |
|---|---|---|---|
| **1. Sensation** | Game as sense-pleasure | Juice, audio, visuals, haptics, rhythm | Rez, Journey, Tetris Effect |
| **2. Fantasy** | Game as make-believe | Roles, fictions, avatars, world consistency | Skyrim, The Sims |
| **3. Narrative** | Game as drama | Authored arcs, branching, characters | Disco Elysium, The Last of Us |
| **4. Challenge** | Game as obstacle course | Skill tests, mastery, scores, difficulty | Celeste, Dark Souls, chess |
| **5. Fellowship** | Game as social framework | Co-op, guilds, shared goals, chat | Deep Rock Galactic, MMOs, Among Us |
| **6. Discovery** | Game as uncharted territory | Exploration, secrets, hidden rules | Outer Wilds, Breath of the Wild |
| **7. Expression** | Game as self-discovery | Customization, creation, building | Minecraft, Dreams, Animal Crossing |
| **8. Submission** | Game as pastime | Low-stakes repetition, meditative loops | Idle games, Stardew farming, Solitaire |

### 3.2 How to apply

- Rate your design 0-5 on each kind for the *intended* experience, then rate what playtesters report. Mismatches are design bugs.
- Pick **two or three** dominant kinds; a game aiming at all eight is generic.
- Use as a cross-check on features: a feature that serves none of your chosen kinds is suspicious.
- Use for comparables: map two reference games to see why they feel different.

### 3.3 Limitations

- Subjective; sorting is arguable ("Is Tetris sensation or challenge?").
- Not backed by empirical factor analysis; compare with Quantic Foundry (section 10) for data-derived motivations.
- Gives no guidance on *how* to build each (that is what dynamics and mechanics are for).

---

## 4. DDE: Design, Dynamics, Experience

### 4.1 Summary

Walk, Görlich and Barrett (2017) propose DDE as an advancement of MDA, addressing some limitations:

| Layer | Meaning (paraphrase) |
|---|---|
| **Design** | The designer's intentions, expressed through rules, content, narrative, aesthetics: the whole *authored* package, not just rules |
| **Dynamics** | The run-time behavior and system response emerging from design and player interaction |
| **Experience** | The player's subjective response, including emotions, cognition and context |

Key moves relative to MDA: broadens the designer's layer beyond mechanics (including narrative, art, audio), and stresses that the player's experience has a **feedback relationship** with the design (iterating, playtesting, data), not just a one-way pipeline.

Note: I describe the framework from memory of its stated goals; check the chapter (DOI in References) for details before quoting or relying on the specific sub-elements.

### 4.2 How to apply

1. Define Design as including non-mechanical content (narrative beats, art direction, UI) so teams do not treat "design" as rules only.
2. Treat each playtest as an **observation of Dynamics and Experience**, feeding back into Design (a loop, not a line).
3. Record context (device, session length, social setting) with experience feedback.

### 4.3 Limitations

- Less widely adopted than MDA; fewer worked examples and less shared vocabulary in industry.
- Still conceptual; offers little concrete guidance for choosing between alternatives.

---

## 5. Schell's Elemental Tetrad and Lenses

### 5.1 The Elemental Tetrad

Four categories, all equally important, arranged as a diamond (Schell 2019):

| Element | Covers | Visible to player? |
|---|---|---|
| **Mechanics** | Rules, procedures, goals, what players can do | In between (inferred through play) |
| **Story** | Sequence of events, theme, world; can be emergent | In between (fairly visible) |
| **Aesthetics** | Look, sound, feel, smell/touch for physical games | Most visible to players |
| **Technology** | Any medium (paper, engine, hardware) enabling the game | Least visible, but enabling or limiting |

Principle: the game is the experience, but these four are what you control. A **theme** should bind all four (e.g., Journey: mechanics of silent cooperation, story of pilgrimage, aesthetics of sand and cloth, tech of seamless matchmaking).

How to apply: for each design decision, ask which element it touches and whether the other three support it. A mechanic that fights the story (ludonarrative dissonance), or tech that cannot deliver the aesthetic (animation budget), is a tetrad mismatch.

### 5.2 The Lenses (24 of the most useful)

Schell's book contains over 100 lenses, each a question to view the design from a different perspective. These twenty-four are the highest-value, paraphrased (see Schell 2019 for exact names and numbering).

| # | Lens | Key question |
|---|---|---|
| 1 | **Essential Experience** | What experience do I want the player to have, and what is essential to it? |
| 2 | **Surprise** | What will surprise players (in story, rules, art, tech)? Does it surprise *me*? |
| 3 | **Fun** | What parts are fun? What could make them more fun? |
| 4 | **Curiosity** | What questions does my game put in the players' minds? What do I do to make them care? |
| 5 | **Endogenous Value** | What is valued inside the game? How does it connect to the player's feelings? |
| 6 | **Problem Solving** | What problems does my game ask players to solve? Are there hidden ones that arise? |
| 7 | **The Elemental Tetrad** | Are all four elements balanced and reinforcing a theme? |
| 8 | **Holographic Design** | What is the interplay, from what I see in the whole game, of the four elements? |
| 9 | **Resonance** | What about my game is resonant with the player? Why does it feel special beyond rules? |
| 10 | **Infinite Inversion** | What happens if I invert an assumption (e.g., you are the bad guy)? |
| 11 | **Player** | Who are my players? What do they like? What do they expect? What would I like in their place? |
| 12 | **Judgment / Meaningful Choices** | Do players have meaningful choices? What makes them meaningful? |
| 13 | **Goals** | Is the goal clear? Is it achievable, rewarding, and a mix of short and long term? |
| 14 | **Skill** | What skills does my game require? Is each of them fun and in balance? |
| 15 | **Chance** | Does randomness serve the experience, and do players understand how to play with it? |
| 16 | **Balance / Fairness** | Is my game fair? Is it symmetrical or deliberately asymmetrical? |
| 17 | **Flow** | Are goals clear, feedback immediate, and challenge matched to skill? Are there distractions? |
| 18 | **Needs / Motivation** | Which of the player's needs does my game fulfil (e.g., Maslow-style needs)? |
| 19 | **Emergence** | Do simple rules combine into complex situations? |
| 20 | **Risk vs. Reward** | Are the risks and rewards balanced so players take interesting gambles? |
| 21 | **Time / Interest Curve** | Does the experience have rises, falls, and a climax? Is it paced? |
| 22 | **The Toy / Playfulness** | If my game were a toy, would it be fun to play with with no goals? |
| 23 | **Character / Story / Obstacle** | What makes the protagonist's goals and obstacles compelling? |
| 24 | **The Eight Filters** | Does the design pass the Eight Filters: Artistic Desire, Demographics, Experience Design, Innovation, Business and Marketing, Engineering, Social/Community, and Playtesting? |

(The list is numbered for convenience; the numbering is not Schell's. Lens names are condensed/paraphrased; the book is the authority.)

### 5.3 How to apply lenses

1. Don't use all of them at once. Pick 3-5 relevant to the current question; run them in a review.
2. Write answers; "I don't know" is a finding (playtest it).
3. Use **Essential Experience + Problem Solving + Flow + Meaningful Choices** as the default quartet for core-loop review.
4. Pair lenses with prototypes: each lens question should become a test question.

Quick lens review of a mechanic (template):
- What experience does it serve? (Essential Experience)
- What problem does it ask the player to solve? (Problem Solving)
- Which choices does it create, and are they meaningful? (Judgment)
- Is the feedback immediate, and challenge matched? (Flow)
- What is the failure mode? (Surprise, Balance)

### 5.4 Limitations

- Lens-based advice is qualitative; there is no scoring.
- Large catalogue can induce analysis paralysis; mastering a handful is better.
- Written primarily from a video-game-centric perspective with an emphasis on entertainment; applicability to serious games varies.

---

## 6. Fullerton: Formal and Dramatic Elements

### 6.1 Summary

Fullerton (2018) structures game design as a *playcentric* process and describes the **formal elements**, the structure of a game (present in all games), and the **dramatic elements**, which give emotional context.

**Formal elements**

| Element | Description | Design questions |
|---|---|---|
| **Players** | Who plays; how many; their roles and interaction patterns (single, co-op, team, multilateral, etc.) | What role does the player take; how do they interact? |
| **Objectives** | What the player is trying to accomplish (capture, chase, race, alignment, rescue, forbidden act, construct, solve, outwit) | Are objectives clear and varied at short and long scales? |
| **Procedures** | Actions players can take, methods of play | Are the verbs interesting? Do they combine? |
| **Rules** | Define objects/actions and constraints | Are rules minimal, consistent, and comprehensible? |
| **Resources** | Assets with value (lives, units, currency, time, health, inventory, special abilities) | Where is scarcity? How are they gained and spent? |
| **Conflict** | Obstacles, opponents, dilemmas that stand in the player's way | Is there productive conflict at all scales? |
| **Boundaries** | Separate the game from the rest of the world (the magic circle) | Where are physical/conceptual limits? |
| **Outcome** | Uncertain result; the system's end state | Is the outcome uncertain until late? Is the ending satisfying? |

**Dramatic elements**

| Element | Description |
|---|---|
| **Challenge** | Tasks that stretch the player |
| **Play** | Free, exploratory interaction |
| **Premise** | Setting and set-up that provide context |
| **Character** | Protagonists, antagonists, and agency in the fiction |
| **Story** | Authored or emergent narrative arc |
| **World building** | Details and internal consistency of the world |
| **Dramatic arc** | Pacing of tension: setup, rising action, climax, resolution |

### 6.2 How to apply

- Use the formal elements as a **completeness checklist** for any game description or prototype (a missing element is a gap: "What is the conflict?").
- Use the dramatic elements to ensure the structure is *wrapped* in emotional context.
- Use the **playcentric process**: prototype, playtest, evaluate, revise, with the player as the centre.

Worked example, **Hades** against formal elements: Players (single, role of Zagreus); Objective (escape the Underworld; secondary: relationships, upgrades); Procedures (dash, attack, cast, choose boon); Rules (damage/armor/boon interactions); Resources (health, gold/obols, darkness, keys); Conflict (Underworld denizens, bosses, family); Boundaries (run-based structure and rooms); Outcome (death sends you back, not failure). Dramatic: death as narrative engine; Zagreus's family as character; each run advances story.

### 6.3 Limitations

- A descriptive framework, not generative; lists parts without explaining which combinations produce fun.
- Textbook-style: good for teaching and review, less so for creative breakthrough.

---

## 7. Koster: Theory of Fun

### 7.1 Summary

Koster (2013) argues that **fun is the feedback the brain gives when it learns** a pattern in a safe environment. Games are "exercises for the brain": a game becomes boring when the patterns are mastered (nothing left to learn) or overwhelming when they are too complex to grok.

Key points:
- Games teach by presenting **patterns** (spatial, logical, social, kinesthetic) to be recognized and chunked.
- **Mastery -> boredom**: once a pattern is automated, the game ceases to be interesting unless it supplies new patterns. This is why games die and why variation and depth matter.
- Fun from mastery is "grokking"; fun from other sources (social, sensory) is not the same.
- Games that contain *meaningful* patterns (relevant to survival/social skills) last; "chocolate-coated broccoli" educational games fail by separating learning from play.
- Distinguishes games from stories and puzzles in terms of their patterns (stories are linear; games are about mastering systems).

### 7.2 How to apply

1. **Identify the patterns** a player learns in your game (what does mastery look like?). If you cannot name them, the game may have little depth.
2. Plan a **pattern curriculum**: introduce, combine, twist (see 05 progression). When the pattern is mastered, provide a new one (new enemy type, new rule, new context).
3. Check **depth**: after 10 hours, what new patterns exist? If none, expect churn.
4. Use *chunking*: make complex games learnable by letting players master sub-patterns first (skill atoms, section 14).
5. Check that the patterns matter: if the learned skill has no consequence, grokking feels empty.

### 7.3 Limitations and critiques

- Reductive: learning is only one source of fun (see Caillois, Lazzaro, LeBlanc for sensory, social and fantasy).
- Little empirical support for a single-cause theory; compare with flow and motivation research.
- Provides no direct design method; the value is in framing.

---

## 8. Csikszentmihalyi: Flow

### 8.1 Summary

Csikszentmihalyi (1990) describes **flow** as an optimal experience: deep absorption in an activity where challenge matches skill. Typical conditions:

1. Clear goals.
2. Immediate feedback.
3. Balance between challenge and skill.
4. Merging of action and awareness; concentration.
5. Sense of control.
6. Loss of self-consciousness; altered sense of time (autotelic experience).

Classic diagram (channel model):

```
Challenge
  ^
  |   Anxiety       /
  |               /   <- Flow channel
  |             /
  |           /   Boredom
  +--------------------------> Skill
```

Players drift out of the channel as their skill grows, so the game must raise challenge (or the player must).

### 8.2 How to apply to games

| Condition | Design implementation |
|---|---|
| Clear goals | Short-term objective always visible; long-term goal legible |
| Immediate feedback | Hit confirmation, score changes, audio, animation; short retry loops |
| Challenge-skill balance | Difficulty curves with options (difficulty settings, adaptive systems, player-chosen risk), sawtooth pacing |
| Control | Responsive inputs; predictable physics; no unfair deaths |
| Concentration | Remove interruptions (menus, popups, unskippable text) during action |

Practical heuristics [heuristic]:
- Offer several channels: multiple difficulty options, optional challenges, assist modes.
- Use **rest points** after intense peaks; a permanent flow channel is exhausting.
- Short loops: restart in under 5 seconds on failure-heavy games (Super Meat Boy, Celeste).
- Diagnose by telemetry: high-quit points = anxiety; idle/skip behaviors = boredom.

### 8.3 Limitations and critiques

- Flow was derived from studies of activities in general (rock climbing, chess, surgery), not games; mapping onto game design is by analogy (see Chen 2007 for a game-oriented application).
- The balance is subjective and varies per player and moment; a single "difficulty line" cannot satisfy all.
- Flow is not the only valuable state; tension, play, and relaxed "flow-less" modes also matter.
- Can be misused to justify invisible dynamic difficulty that undermines trust or agency (see 05).

---

## 9. Caillois: Agon, Alea, Mimicry, Ilinx; Paidia and Ludus

### 9.1 Summary

Caillois (1961/2001) classifies play in two dimensions.

**Four categories of play**

| Category | Meaning | Digital examples |
|---|---|---|
| **Agon** | Competition; skill and effort in a controlled contest | Fighting games, RTS ladders, chess |
| **Alea** | Chance; surrender to fate | Gacha, loot rolls, card draws, slot machines |
| **Mimicry** | Simulation; role-play, make-believe | RPGs, The Sims, cosplay, immersive sims |
| **Ilinx** | Vertigo; disorientation, speed, thrill | Roller coaster VR, racing, Katamari-like momentum, Tetris Effect rush |

**Two poles**

| Pole | Meaning |
|---|---|
| **Paidia** | Free play: improvisation, exuberance, no fixed rules (a sandbox, toys) |
| **Ludus** | Rule-bound play: structure, goals, difficulty (puzzles, competitive games) |

Games combine categories (e.g., poker = agon + alea; MMORPG = agon + mimicry; Mario Kart = agon + alea + ilinx). 

### 9.2 How to apply

- Describe your game as a mix: "60% agon, 30% mimicry, 10% alea". Is the mix coherent with the target audience?
- Check **paidia vs ludus**: toy-like games (Minecraft creative, Townscaper) lean paidia; they need minimal goals; ludus-heavy games need clear rules/goals.
- Use categories for feature coherence: adding Alea (random drops) into a pure Agon game (esports) reduces competitive legitimacy.
- Use paidia -> ludus progression in onboarding: let players play freely before adding goals.

### 9.3 Limitations

- Anthropological and descriptive (1958 French original), not designed for digital games; categories overlap.
- Does not address cooperation, narrative or creativity cleanly.
- Use as a vocabulary, not a rigorous classification.

---

## 10. Player Typologies: Bartle and Quantic Foundry

### 10.1 Bartle's player types

Bartle (1996), from MUD observation: two axes (acting vs interacting; players vs world).

| Type | Axis | Wants | Design needs |
|---|---|---|---|
| **Achievers** | Acting on the world | Points, levels, status, completion | Clear goals, progression, leaderboards, collectibles |
| **Explorers** | Interacting with the world | Discovery, systems understanding | Hidden content, deep systems, secrets, lore |
| **Socializers** | Interacting with players | Relationships, chat, community | Chat, guilds, co-op, emotes |
| **Killers** (Griefers) | Acting on players | Dominance over others, impact | PvP, rankings, meaningful consequences for opponents (and moderation) |

Bartle's population-balance observation: types influence each other's presence (too many killers drive away socializers).

Applying: use as a **checklist of motivations your game supports**; make sure the core loop gives each target type something. Don't claim you can sort individuals into one type; most people shift by context.

Limitations: derived from text MUDs (not general video games), based on observation not statistics; subsequent questionnaire work (Bartle test) is unvalidated; Killers type is commonly misread as "toxic" rather than "competitive".

### 10.2 Quantic Foundry gamer motivation model

Based on survey data from large samples of gamers (Yee and colleagues; see Yee 2006 for the earlier online-games factor analysis). 12 motivations in 6 clusters:

| Cluster | Motivations |
|---|---|
| **Action** | Destruction, Excitement |
| **Social** | Competition, Community |
| **Mastery** | Challenge, Strategy |
| **Achievement** | Completion, Power |
| **Immersion** | Fantasy, Story |
| **Creativity** | Design, Discovery |

Findings reported by Quantic Foundry (verify current numbers on their site before quoting): motivation profiles correlate with genre preferences and with demographics like age and gender, but with substantial overlap; the model is empirical and based on surveys of self-selected respondents.

Applying:
- Map your game to the 12 motivations; target 3-4 strongly.
- Use for marketing and audience definition (which genres/players overlap).
- Check retention features against motivations (e.g., Completion -> collections; Community -> guild systems).

Limitations: self-reported survey data; self-selected respondents; correlation with demographics must not be used for stereotyping individuals; predicted preferences do not guarantee design quality.

---

## 11. Lazzaro's 4 Keys to Fun

### 11.1 Summary

Lazzaro (2004) analyzed player behavior and facial expressions to identify four sources of emotion-driven play ("keys"):

| Key | Emotion source | Typical emotions | Design tools |
|---|---|---|---|
| **Hard Fun** | Challenge, strategy, mastery | Frustration to fiero (triumph) | Clear goals, escalating difficulty, mastery loops, boss fights |
| **Easy Fun** | Curiosity, exploration, role-play, no pressure | Curiosity, wonder, awe | Ambiguity, details, toys, discovery, intrigue |
| **Serious Fun** | Changing internal state via play (relaxation, purpose, improving the real world) | Relief, excitement, purpose | Rhythm, collection, repetition, real-world meaning |
| **People Fun** | Social interaction | Amusement, schadenfreude, naches (pride in others), social bonding | Competition, cooperation, communication, spectating |

Lazzaro's central claim: successful games usually mix **several keys** and often *switch* keys during a session to maintain emotional variety.

### 11.2 How to apply

- Chart the emotional keys across the session timeline. Flat (all Hard Fun) leads to fatigue; mix.
- Use *fiero*: the biggest Hard Fun payoff comes after a real struggle; do not diminish struggle with excessive hand-holding.
- Design "Easy Fun" zones as breathing space between difficulty peaks (hubs, exploration, toys).
- For social games, add People Fun options even to single-player designs (leaderboards, sharing, spectatorship).

### 11.3 Limitations

- Based on one consultancy's observational studies (Xeodesign); sample sizes and methods are not as accessible as academic work.
- Keys are broad; "serious fun" is least intuitive.
- Overlaps heavily with LeBlanc's kinds of fun.

---

## 12. Salen and Zimmerman: Meaningful Play and the Magic Circle

### 12.1 Meaningful play

Salen and Zimmerman (2004) define **meaningful play** as the relationship between player action and system outcome, in the larger context of the game. It emerges when:
- **Discernable**: the game communicates the result of an action clearly (feedback on the immediate outcome).
- **Integrated**: the action and its result are woven into the larger game structure, affecting later play.

Both are needed: an action that has an obscure result, or a visible one that doesn't matter later, is not meaningful.

### 12.2 The magic circle

Borrowing from Huizinga, the **magic circle** is the temporary, bounded space in which game rules apply and actions get special meaning (the board, the pitch, the screen, the agreement). Entering is voluntary (**lusory attitude**, Suits): players accept inefficient means for the sake of the game.

### 12.3 How to apply

- **Discernability audit**: for each player action, list what feedback shows the outcome. If none, add one (visual, audio, UI, log).
- **Integration audit**: for each choice, state how it affects later states. If it doesn't, it is cosmetic, which can be fine for expression but not for strategy.
- Use the magic circle for social design: where its boundary is porous (in-game chat toxicity, real-money trading, streaming spoilers), the experience degrades; make boundaries clear (codes of conduct, safe rooms, session start/end rituals).
- Be careful when monetization breaks the circle (pay-to-win undermines the fairness assumed within it).

### 12.4 Limitations

- Magic circle is contested: many scholars argue real-world context always leaks in (esports, gambling, social media); treat it as a useful boundary metaphor, not a literal wall.
- Meaningful play is a necessary-sufficient-sounding label but gives little guidance on degree; use with the interesting-decisions checklist (section 13).

---

## 13. Sid Meier: Interesting Decisions

### 13.1 Summary

Meier's definition: a game is "a series of interesting decisions." The idea predates his GDC 2012 talk "Interesting Decisions" and is commonly traced to his talks from about 1989 onward. The five-element list below is a commonly cited secondary synthesis (assembled by later designers and writers), not Meier's own enumeration:
- **Trade-offs**: no option is best in all circumstances.
- **Situational**: the best choice changes with context.
- **Persistent**: consequences carry forward.
- **Informed**: the player has enough information to reason.
- **Personal**: reflects play style / risk appetite.

Meier also describes the pitfalls of the **player vs designer vs AI** "who has the fun?" balance and warns against *dominant strategies* (where one option is always best), *no-brainer* options, and *too many* decisions without information. The talk also covers the "Double it or halve it" rule of thumb for iteration of numbers. [Please verify details against the GDC Vault talk before quoting specifics.]

### 13.2 How to apply: decision audit

For each recurring decision in the core loop:

| Check | Fail sign | Fix |
|---|---|---|
| Distinct options? | Choices produce the same result | Differentiate by risk/range/timing/resource |
| Trade-off? | One option strictly dominates | Add cost or opportunity cost |
| Informed? | Player guesses blind | Show odds, intents, previews |
| Consequential? | Results don't persist | Tie to state, resources, positioning |
| Varying? | Same answer every time | Add variance in context and counterplay |
| Frequency | Too many trivial decisions | Automate the obvious; focus on key choices |

Also run a **dominant strategy hunt**: simulate or test; if one option is picked >~60% of the time without situational reason [heuristic], investigate.

Example: **Slay the Spire** map choice - elite fights give relics but cost HP; shops need gold; rest sites heal or upgrade. The state (HP, deck, gold) changes the right answer each time.

### 13.3 Limitations

- Doesn't cover non-decision-focused play (reflex, sensory, expressive); a rhythm game is not primarily about decisions.
- "Interesting" is subjective; judge with playtests.
- Decision-density has an upper limit: analysis paralysis is a failure mode, especially in real-time.

---

## 14. Dan Cook: Skill Atoms and the Chemistry of Game Design

### 14.1 Summary

Cook (2007), "The Chemistry of Game Design", proposes that games are built from **skill atoms**, the smallest repeatable units of learning, modeled as a feedback loop:

```
 Player ACTION --> SIMULATION (game rules) --> FEEDBACK
      ^                                            |
      |                                            v
      +------- MODEL (player's mental model) <-----+
```

Each atom: the player takes an action; the simulation computes a result; feedback shows it; the player updates their mental model (learning). Mastering the atom produces **fun** (in line with Koster) and then the atom becomes boring.

**Molecules / chemistry**: atoms combine into **skill chains** and larger structures; the output of one atom can be the input to another. Games are **graphs of atoms** with sequencing:
- **Skill chains**: one atom's output feeds the next (shoot -> reload -> take cover).
- **Burnout**: atoms are consumed (mastered) and the game must add new ones; this is the game's **lifespan** problem.
- Atoms may be **fed by resources** and gated by other atoms; the player's choice of atoms creates a "meta-game."

Cook's related essay "Loops and Arcs" (2012) distinguishes repeating **loops** (mastery, skill atoms) from **arcs** (linear, one-shot content such as story or level progression), arguing that arcs are expensive and loops are cheap.

### 14.2 How to apply

1. **Atom inventory**: list every atom in the game as `verb -> immediate feedback -> new knowledge`.
2. For each atom, check **feedback clarity** and **time to mastery**. Atoms mastered in 30 seconds with no variation are fillers.
3. Chain atoms: design **skill chains** where the output state of one atom changes how the next should be played (aim -> shoot -> cover -> flank).
4. Plan **atom introduction schedule** (tutorial/pacing, see 05): one new atom at a time, practice, combine.
5. Estimate **lifespan**: sum time-to-mastery over all atoms plus recombination depth; if less than your target playtime, add atoms, increase depth, or add social/competitive replay value.
6. For F2P/live: new atoms (not just new numbers) are what refresh the game.

Example, **Celeste**: atoms: jump, dash, wall-climb/cling, wall-jump. Early rooms isolate atoms; later rooms chain them (dash -> wall-jump -> dash), then add twist atoms (springs, moving platforms, feathers, wind).

### 14.3 Limitations

- Reductive: not all enjoyment is skill-learning.
- Hard to define the "smallest" atom boundary; no standard granularity.
- Chain modelling is conceptual rather than quantitative; use it for structure, not prediction.

---

## 15. Keith Burgun: Form Taxonomy

### 15.1 Summary

Burgun (2012) argues that "game" is too broad and proposes classifying interactive systems by **form** (by what they aim for). His four forms are toy, puzzle, contest and game (narrative-driven works fall outside this taxonomy):

| Form | Definition (paraphrase) | Examples |
|---|---|---|
| **Game** | A system of rules with a goal, defined by *interesting decisions* and an ambiguity that depends on player *decisions* ("contests of decision-making" with a score/goal) | Chess, Go, poker, Into the Breach |
| **Puzzle** | A system with a fixed solution to find | Sudoku, Portal-like puzzles |
| **Contest** | A measure of ability/performance (physical or timing) | Races, speedruns, many arcade scores |
| **Toy** | Interactive object with no goals | Sandbox, Townscaper |

Burgun's thesis: games are most powerful when they focus on **interesting decisions** using "clarity" (visible state) and "depth," and he is critical of random outcomes, ornamentation, and unclear systems. He encourages designers to choose a form deliberately rather than mixing forms accidentally.

### 15.2 How to apply

- Ask "What form is this?" A product that is half-toy, half-game, half-puzzle may frustrate players who want the other half. Make forms legible in the pitch.
- Use the form to choose success metrics: a puzzle is finished by solution; a game replays by decision depth; a toy by expression.

### 15.3 Limitations and critiques

- Highly opinionated and prescriptive; many designers and scholars disagree with narrow definitions (e.g., treating narrative or sensation-driven games as lesser).
- Definition of "game" excludes much of mainstream play; use the taxonomy as a design aid, not as a verdict on value.

---

## 16. Choosing and Combining Frameworks

### 16.1 A practical stack

| Stage | Use | Output |
|---|---|---|
| Concept | LeBlanc 8 kinds of fun + Quantic Foundry + Caillois | Target aesthetics/motivations |
| Core loop design | MDA (backward), Cook's atoms, Meier checklist | Dynamics and decisions |
| Review | Schell lenses (3-5), Fullerton formal elements | Gap list |
| Pacing/difficulty | Flow, Koster, Lazzaro keys | Sawtooth curve plan |
| Social/multiplayer | Bartle, Salen and Zimmerman circle | Role design |
| Evaluation | Playtest against the aesthetics you named | Evidence |

### 16.2 Worked mini-analysis: Stardew Valley

- **Kinds of fun** (LeBlanc): Submission, Expression, Fantasy, Discovery; low Challenge.
- **Caillois**: mostly paidia with light ludus (goals like community center); mimicry.
- **Lazzaro**: Easy Fun (exploring, relationships), Serious Fun (relaxation, routine), minimal Hard Fun.
- **Skill atoms** (Cook): few mechanical atoms; depth is in scheduling and optimizing, plus relationship loops (arcs and loops).
- **Meier**: the daily choice "what do I spend today's energy on?" is the interesting decision.
- **Flow**: player-controlled difficulty; the game does not push.

Result: an assessment that tells a designer what *not* to add (twitch combat in the farm loop would conflict with Submission/Easy Fun) and what supports the target.

### 16.3 Cross-framework pitfalls

- **Framework worship**: citing a model instead of testing.
- **Confusing description with prescription**: Bartle types describe; they don't tell you whom to cater to.
- **One-size mapping**: apply to features/moments, not only to the whole game.
- **Ignoring context**: audiences, platforms, cultures change which frameworks apply.

---

## 17. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Papers and online essays**
- Hunicke, R., LeBlanc, M., and Zubek, R., 2004, "MDA: A Formal Approach to Game Design and Game Research", Proc. AAAI Workshop on Challenges in Game AI. https://users.cs.northwestern.edu/~hunicke/MDA.pdf
- Walk, W., Görlich, D., and Barrett, M., 2017, "Design, Dynamics, Experience (DDE): An Advancement of the MDA Framework for Game Design", in Korn, O., and Lee, N. (eds.), *Game Dynamics*, Springer. https://doi.org/10.1007/978-3-319-53088-8_3
- Bartle, R., 1996, "Hearts, Clubs, Diamonds, Spades: Players Who Suit MUDs", Journal of MUD Research. https://mud.co.uk/richard/hcds.htm
- Lazzaro, N., 2004, "Why We Play Games: Four Keys to More Emotion Without Story", Xeodesign. http://www.xeodesign.com/xeodesign_whyweplaygames.pdf
- Cook, D., 2007, "The Chemistry of Game Design", Gamasutra / Game Developer. https://www.gamedeveloper.com/design/the-chemistry-of-game-design
- Yee, N., 2006, "Motivations for Play in Online Games", CyberPsychology and Behavior 9(6). https://doi.org/10.1089/cpb.2006.9.772 (publisher blocks automated checks; resolves in a browser)
- Quantic Foundry, gamer motivation model and research articles. https://quanticfoundry.com/ (site blocks automated checks; resolves in a browser)

**Books**
- Schell, J., 2019, *The Art of Game Design: A Book of Lenses*, 3rd ed., CRC Press / Routledge. https://www.routledge.com/The-Art-of-Game-Design-A-Book-of-Lenses-Third-Edition/Schell/p/book/9781138632097
- Fullerton, T., 2018, *Game Design Workshop*, 4th ed., CRC Press (ISBN 978-1138098770).
- Koster, R., 2013, *A Theory of Fun for Game Design*, 2nd ed., O'Reilly. https://www.theoryoffun.com/
- Csikszentmihalyi, M., 1990, *Flow: The Psychology of Optimal Experience*, Harper and Row (ISBN 0-06-016253-8).
- Caillois, R., 1961 (2001 reprint), *Man, Play and Games* (trans. M. Barash), University of Illinois Press.
- Salen, K., and Zimmerman, E., 2004, *Rules of Play: Game Design Fundamentals*, MIT Press (ISBN 0-262-24045-9).
- Burgun, K., 2012, *Game Design Theory: A New Philosophy for Understanding Games*, CRC Press.
- Chen, J., 2007, "Flow in Games (and Everything Else)", Communications of the ACM 50(4), 31-34. https://doi.org/10.1145/1232743.1232769 (cited for the application of flow to games).
- Suits, B., 1978, *The Grasshopper: Games, Life and Utopia*, University of Toronto Press (lusory attitude).

**Talks**
- Meier, S., 2012, "Interesting Decisions", GDC 2012. https://www.gdcvault.com/play/1015756/Interesting

**Notes on sourcing**
- Descriptions of DDE, Lazzaro, Meier, Burgun, and Quantic Foundry are summaries from memory of the primary sources; check the originals before quoting exact terms or figures.
- Lens names and numbering follow the spirit of Schell (2019) but are paraphrased; the numbering in section 5.2 is not Schell's.
