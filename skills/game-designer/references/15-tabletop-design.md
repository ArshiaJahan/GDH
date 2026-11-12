# Tabletop Design: Board, Card and Role-Playing Games

## Table of Contents

1. [How to Use This File](#1-how-to-use-this-file)
2. [What Is Different About Tabletop](#2-what-is-different-about-tabletop)
3. [Components, Table Presence and the Component Economy](#3-components-table-presence-and-the-component-economy)
4. [Turn Structures](#4-turn-structures)
5. [Mechanism Catalog and How to Use It](#5-mechanism-catalog-and-how-to-use-it)
6. [Engine Building, Deck Building and Drafting](#6-engine-building-deck-building-and-drafting)
7. [Area Control, Roll-and-Write and Other Families](#7-area-control-roll-and-write-and-other-families)
8. [Cooperative Design and the Alpha-Player Problem](#8-cooperative-design-and-the-alpha-player-problem)
9. [Hidden Roles, Traitors and Social Deduction](#9-hidden-roles-traitors-and-social-deduction)
10. [Legacy and Campaign Design](#10-legacy-and-campaign-design)
11. [Player Count, Downtime and Analysis Paralysis](#11-player-count-downtime-and-analysis-paralysis)
12. [Kingmaking, Catch-Up and End-Game Triggers](#12-kingmaking-catch-up-and-end-game-triggers)
13. [Game Length, Weight and Audience](#13-game-length-weight-and-audience)
14. [Rulebook Writing](#14-rulebook-writing)
15. [Playtesting Tabletop Games](#15-playtesting-tabletop-games)
16. [Prototyping Tools and Methods](#16-prototyping-tools-and-methods)
17. [Publishing Paths](#17-publishing-paths)
18. [TTRPG Design Basics](#18-ttrpg-design-basics)
19. [Worked Examples](#19-worked-examples)
20. [Checklists](#20-checklists)
21. [References](#21-references)

---

## 1. How to Use This File

This is the in-depth companion to the tabletop section of `11-genre-playbooks.md` (section 25: Euro vs Ameritrash, mechanism families, levers and pitfalls). That section is the summary; this file goes into craft detail. Do not re-read the same tables: when you need the mechanism-family table (worker placement, engine building, deck building, area control, drafting, tile placement, push-your-luck, cooperative, hidden role, legacy) go to `11-genre-playbooks.md`, section 25.2.

Related files:
- `01-design-process.md` for process, pillars and prototyping philosophy.
- `03-core-loops-and-mechanics.md` for resources, feedback loops, risk/reward and input/output randomness (section 9).
- `04-balance-and-economy.md` for cost curves and probability.
- `10-multiplayer-and-social.md` for social dynamics, toxicity and co-op.
- `12-playtesting-and-analytics.md` for general playtest method; section 15 here adapts it to tabletop.
- `14-ai-procedural-and-audio-design.md` section 10 for game theory (dominant strategies, mixed strategies, social dilemmas).

Labeling convention: **[heuristic]** marks a rule of thumb from industry practice, not a measured finding. Game examples are observations of well-known designs; check details against the games or rulebooks before quoting them in a deliverable.

---

## 2. What Is Different About Tabletop

| Aspect | Video game | Tabletop |
|---|---|---|
| **Rules execution** | Computer enforces rules, hides complexity | Players enforce rules; every rule costs memory, teaching time and error risk |
| **Hidden state** | Easy | Needs components (screens, cards, tokens) and trust |
| **Iteration** | Build cost grows with content | Paper prototypes are cheap, but production is fixed once printed |
| **Pacing** | Real time or fast turns | Human turn time; downtime is a first-order design variable |
| **Social layer** | Optional | Intrinsic: negotiation, table talk, mood, who is winning |
| **Content updates** | Patches | Errata, expansions, new editions; shipped components are permanent |
| **Cost structure** | Dev time | Manufacturing, MOQs (minimum order quantities), shipping, inventory |

Design consequences **[heuristic]**:
1. **Every rule must pay rent.** A rule that is hard to remember must produce a decision or an emotion in proportion to its cost.
2. **The player is the processor.** Keep state visible and computation local; avoid requiring players to track many hidden modifiers.
3. **Players are your interface.** Table-talk, reading faces, and the experience of the table are part of the game (a social-deduction game is mostly that).
4. **Production is a design constraint.** Component count, card count, board size, and box size determine price; price determines audience.

---

## 3. Components, Table Presence and the Component Economy

### 3.1 Component types and roles

| Component | Typical roles | Design notes |
|---|---|---|
| **Cards** | Hidden information, randomization, modular content, actions, events | Cheap, flexible, scalable; ideal for variety and scarcity; require shuffling and text clarity |
| **Dice** | Randomization, resource tracking, selection (dice drafting) | Tactile, visible randomness; consider rolling space and rerolls |
| **Tokens and cubes** | Resources, markers, units | Physical manipulation = feeling of ownership and progress |
| **Boards** | Shared space, tracks, action areas | Define layout, geometry and teach structure; modular boards add variability |
| **Player boards (mats)** | Personal state, action areas, engines | Reduce clutter and aid teaching; enable asymmetry |
| **Miniatures** | Presence, identity, tactical positions | Table presence and cost; sculpt quality drives price |
| **Tiles** | Modular map, hidden content | Variability and tactile building |
| **Screens, apps** | Hidden info, automation, soundtrack | An app can remove bookkeeping but adds a dependency |

### 3.2 Table presence

**Table presence** is how the game looks and feels when set up: visual impact, tactile satisfaction, and the sense that something significant is happening. It is a marketing and play asset, not decoration.

Elements:
- Three-dimensional pieces, a growing structure (towers, tableau), movement across a map.
- Readable state: players can see who is ahead and what threatens them.
- Color palette, iconography, and sensory weight (heavy tokens, satisfying card stock).
- A "photograph moment": something that appears in photos from the table.

Pitfalls: table presence that raises cost without affecting play; unreadable art that hides state; excessive footprint that does not fit a normal table (heuristic: check against the table sizes of the target audience and plan for player aids that do not require extra space).

### 3.3 Component economy

The **component economy** is the budget of physical items (cards, tokens, tiles, miniatures) the design justifies. A design review question: what does each component class **do** in play, and could the same decision be produced with fewer?

Heuristics:
- **Reuse components across roles.** One cube type can be resources, units, or markers depending on location. Reuse lowers cost and learning load, but can reduce clarity if overloaded.
- **Count the hidden costs**: sleeves, trays, inserts, translations, art budget per card (hundreds of unique cards means hundreds of illustrations).
- **Use cards when you need variety; use tokens when you need quantity.**
- **Match component quality to price band**: a $20 game cannot bear miniatures; a $100 game must deliver presence.
- **Track information in the right place**: scores on a board edge or tracker (public) vs. hidden scoring cards.
- **Consider supply limits as a mechanism**: a finite token supply can be a design lever (when the bank runs out, something happens). Catan's limited resource card and building piece supplies are an example of physical scarcity shaping play, though in Catan the main scarcity is the resource production tied to dice numbers and hex placement.
- **Plan for lost pieces**: provide spare or ensure rules work with substitutes (coins, dice).

### 3.4 Iconography and information design

- Use consistent **icons** to replace text, with a legend on a player aid.
- Put the **most important information in the top-left** or the visually dominant region of a card (readers scan from there) **[heuristic]**; test with players seated across the table from the card.
- Colorblind accessibility: pair color with shape or pattern; test in grayscale (`08-player-psychology-ux-accessibility.md`).
- Typography: size for readability at arm's length; avoid ornate fonts for rules text.
- **Player aids** summarizing turn structure, scoring and icon meanings reduce rulebook lookups.

---

## 4. Turn Structures

The turn structure sets the rhythm, the downtime, and what kind of decisions players make. Engelstein and Shalev (2019) catalog turn-order and action-selection mechanisms in detail; this section gives the designer's decision frame.

### 4.1 Overview

| Structure | How it works | Strengths | Weaknesses | Example |
|---|---|---|---|---|
| **Fixed sequential (clockwise)** | Players act in a set order | Simple, predictable, easy to teach | Downtime grows with player count; first-player advantage | Many classic games, Catan (turn-based with trading and production on other players' turns) |
| **Variable player order** | Order changes each round by bidding, passing, or position | Balances first-player advantage; adds strategic layer | More rules; can feel like a catch-up or a cost | Auction-based turn order, "pass order" games |
| **Simultaneous / real-time** | All players act at once, or in parallel planning | No downtime; energy | Chaos, alpha-player in co-op, rules enforcement | Roll-and-write, 7 Wonders (simultaneous card selection), real-time co-op |
| **Action points** | Each turn the player has a budget to spend on actions | Meaningful trade-offs inside a turn; scaling difficulty by changing points | AP can induce analysis paralysis | Pandemic (4 actions per turn), many tactics games |
| **Worker placement** | Place workers on spaces; one worker per space (typically); resolution after | Blocking creates tension; good for resource allocation | Blocking can frustrate; kingmaking; downtime | Agricola and others |
| **Action selection / role selection** | Choose one of a set of actions; others may follow | Interaction on others' turns; tempo play | Complexity; imbalance among roles | Puerto Rico style role selection |
| **Card-driven** | Cards in hand determine what you can do | Randomness and hidden info; tension from dual use | Hand luck; deck knowledge needed | Twilight Struggle (cards give operation points, or trigger events) |
| **Programming / planning** | Plan actions in advance, then reveal and resolve | Anticipation, bluffing, funny failures | Long planning; chaotic execution | Robot-programming games |
| **Phases or rounds** | Round divides into phases all players do in sequence | Clarity; parallelism within phases | Rules overhead | Many Euro games |
| **Bidding / auction** | Players bid for turn order, resources or actions | Self-balancing value; interaction | Math-heavy; bid fatigue | Auction games |
| **Real-time with limits** | Timers or stress mechanics | Tension | Excludes some players; accessibility concerns | Real-time dexterity and co-op games |

### 4.2 Choosing a structure

Ask:
1. **What do I want players doing when it is not their turn?** (Watching, planning, interacting, acting simultaneously.) Downtime is the usual weakness.
2. **How many decisions per turn, and how big?** Many small decisions = lively but shallower; one big decision = deliberate and prone to paralysis.
3. **How much interaction on others' turns?** Reactions (blocks, auctions, triggers) keep attention but add rules.
4. **How scalable to player count?** Simultaneous formats scale best; sequential formats suffer at the high end.
5. **Does the structure match the theme?** Programming a robot is simultaneous planning; a negotiation is open-ended.

### 4.3 Worker placement design levers

- Number of workers, number of spaces, whether spaces are exclusive (blocking) or shareable (at a cost).
- Space tiers: early-game spaces vs. late-game spaces, spaces that become available over time.
- Turn order: how the first-player token moves; whether it is a prize.
- Round count and end condition; whether workers are permanent or earned.
- **Pitfall**: a "must-take" space that every player wants every round creates a first-player trap. Mitigate with scaling costs, a take-that-later token, or compensation for later players (extra resource, flexible placements).

### 4.4 Action points and action selection

- AP budgets create a clear "what can I do this turn" menu; decide whether unspent points carry over. If actions can have high variance in cost, players calculate more; consider tiered costs to reduce analysis.
- **Action selection** (select an action card or tile; others may follow) is used to create interaction on all turns; the "follow" mechanism makes passive turns active.
- Add **card or tile rotation** (used actions go to the back) to prevent repeating the same action every turn.

### 4.5 Simultaneous play

Examples in 7 Wonders: each player drafts a card from their hand at the same time, reveals together, then passes the hand. Benefits: zero downtime in the draft phase, scales to 7 players (the title's player count). Pitfalls: hidden information requires honest play; rules for resolving ties and simultaneous effects must be explicit.

---

## 5. Mechanism Catalog and How to Use It

*Building Blocks of Tabletop Game Design* (Engelstein and Shalev 2019) is the field's reference catalog of mechanisms organized by category (e.g., turn order, auctions, set collection, action selection, area movement, cooperative, and so on). Use it as a **vocabulary and idea generator**, not a recipe book.

### 5.1 How to use a catalog

1. **Start from the experience**, not a mechanism. "I want players to feel clever about timing" suggests simultaneous reveal, auctions, push-your-luck.
2. **Look up the mechanism family**, read variations and the games that use them, and note the trade-offs.
3. **Pick one primary mechanism** (the "engine") and at most one or two supporting. Games that combine five major mechanisms usually dilute the core.
4. **Consider the mechanism's costs**: rules overhead, downtime, player count behavior, luck.
5. **Prototype the mechanism in isolation** before attaching theme or content.
6. **Differentiate**: change one variable (when, how many, what cost, who decides) to avoid being a clone.

### 5.2 Quick mapping from experience to mechanism family (heuristic)

| Experience | Candidate mechanisms |
|---|---|
| Resource optimization | Worker placement, action selection, tableau/engine building |
| Tension and bluffing | Hidden role, simultaneous reveal, bidding, push-your-luck |
| Cooperative struggle | Cooperative with escalating threat, timers, hidden traitor option |
| Territorial conflict | Area control, majority, movement and combat |
| Creativity and expression | Drafting, set collection, tile placement, storytelling |
| Learning and mastery | Perfect information abstract play, puzzle-like optimization |
| Social interaction | Negotiation, trading, voting, party games |
| Escalating power | Deck building, engine building, tech trees |

See `11-genre-playbooks.md` section 25.2 for the table of families with core decisions and pitfalls.

### 5.3 Mechanism pitfalls

- **Mechanism soup**: many mechanisms with no unifying decision.
- **Theme pasted on**: mechanisms that do not support the fantasy. Test: can a player explain why a rule exists in the fiction?
- **Unexamined legacy**: copying a mechanism's surface without understanding the balancing rules around it (for example, a worker-placement game without blocking constraints).
- **Optimization puzzle without interaction**: multiplayer solitaire (see section 6).

---

## 6. Engine Building, Deck Building and Drafting

### 6.1 Engine building

An **engine** converts resources/actions into more resources/actions over time. The pleasure is compounding growth and seeing your system hum.

Design levers:
- **Cost curve for engine pieces**: early pieces cost little and return little; later pieces cost more and return more. The curve determines the pace of snowballing.
- **Synergy density**: how many pieces interact; high density = rich combos but heavier analysis and balance risk.
- **Game length as the cap on compounding**: a fixed number of rounds or a race-to-X condition limits how far the engine can run. Short games punish heavy engines; long games punish non-engine strategies.
- **Conversion at the end**: the engine must turn into victory points; the **timing of the switch** (when to stop building and start scoring) is the key decision in many engine games.
- **Interaction**: engine games are prone to "multiplayer solitaire". Add competition for shared resources (cards, spaces), blocking, or events that attack engines.
- **Variance**: random card draws create different engine paths; provide mitigation (tutoring, market display, rerolls).

Examples: Wingspan is widely described as an engine-building game with a tableau where birds' powers chain through a habitat row; its end-of-round goals and limited rounds push a timing decision (see section 19).

### 6.2 Deck building

Players start with identical small decks and add cards from a shared market, trimming over time. Dominion popularized the genre (Donald X. Vaccarino, 2008).

Design levers and checks:
- **Kingdom / market setup**: Dominion uses a random subset of action card piles per game, which forces players to reevaluate strategy each time. A fixed market gives stable strategy but less replayability.
- **Card interaction**: provide ways to gain cards, trash cards, draw more, and play more per turn; these four levers define engine speed.
- **Dominant strategies**: check for "do-nothing" strategies (for example, simply buying treasure, nicknamed "Big Money" in the Dominion community) and ensure that engine strategies can beat them on a typical kingdom, but not always. This is a standard balance test for deckbuilders: **a baseline simple strategy should be a viable but beatable benchmark**.
- **Ending condition**: pile exhaustion (when specific supply piles run out) puts the end under player control and punishes stalling.
- **Interaction**: attacks, shared supply competition, denial.
- **Snowball risk**: the early leader buys better cards; add negative feedback (cost of victory cards clogging the deck is itself a built-in brake in Dominion).
- **Downtime**: complex chains on one player's turn leave others waiting; encourage reactive cards or keep chains bounded.

Pitfalls: card text that requires rulings, strong combos that break the game, a first-player advantage that matters because of the race. Playtest with many random kingdoms/markets.

### 6.3 Drafting

Players choose a card from a hand and pass the remainder.

Variants:
- **Pack drafting** (pass entire hand: 7 Wonders, Sushi Go, Magic draft).
- **Open drafting / market**: take from a shared display (Ticket to Ride face-up cards).
- **Auction draft**.
- **Snake order** for a fair draft.

Levers: hand size, pass direction (left/right alternating), number of rounds, what happens to leftover cards, how much you know about others' needs, **hate-drafting** (denying) versus building.

Pitfalls:
- **Information overload**: reading a 7-card hand and tracking neighbors can cause analysis paralysis. Use icons to reduce reading.
- **Imbalanced options**: one dominant card collapses the draft.
- **Passive feel**: players feel drafted into a strategy they did not choose; give flexibility (alternate uses of cards, wild options).
- **Denial dominance** at two players.

In 7 Wonders, cards can be used in several ways (build a structure, build a wonder stage, or discard for coins), which keeps cards useful across situations; the neighbor-based interaction (only interacting with immediate neighbors for trade and military) keeps it playable at higher counts.

---

## 7. Area Control, Roll-and-Write and Other Families

### 7.1 Area control and majority

Players compete to dominate regions, scored by majorities or by control at set times.

Levers: number of areas, scoring timing (repeated scoring rounds keep tension), combat/resolution (deterministic, dice, cards, bidding), support (alliances, shared control), unit supply (the scarcity that forces choices), and the cost of expansion.

Twilight Struggle is a standout example of card-driven area influence: cards offer operation points to place influence in regions or trigger events (often benefiting the opponent if you play them for operation points), and scoring cards periodically evaluate regional control. The dual-use card (events vs. operations) is the engine of tension. Verify specifics against the rulebook.

Pitfalls: **runaway leader** (more territory yields more resources), **kingmaking** when a losing player's final attack decides the winner, **dogpiling** the leader, **turtling** (defensive stalling), and **dead zones** (areas no one wants). Typical fixes: scoring that rewards second place, hidden scoring objectives, rubber-banding resources, and a hard end trigger (section 12).

### 7.2 Tile placement and set collection

- Tile placement: spatial puzzle, with scoring tied to adjacency, completing features or patterns. Low rules weight, high accessibility (Carcassonne, Azul).
- Set collection: collect combinations for points (Ticket to Ride, Sushi Go). Levers include set sizes, diminishing returns, and denial.

### 7.3 Roll-and-write

Players roll shared dice and each records the result on their own sheet; the sheet is the player's engine and scoreboard.

Design strengths: simultaneous play (little downtime), low component cost, scalable to any player count, solo-friendly, teachable.

Levers: dice pool sharing and selection rules (e.g., active player picks first, then others), constraints on how results are written (adjacency, columns), scoring synergies on the sheet, and end triggers (filling sections, rounds).

Pitfalls: **multiplayer solitaire** (little interaction beyond dice choice), **luck dominance** (fix with choice and mitigation), and **sheet design** (layout must make state and scoring easy to read; test with real pens and pads).

Interaction design: allow players to choose from a shared pool in an order that rewards smart selection, or add "take-that"-lite mechanisms where a choice denies others.

### 7.4 Push-your-luck and dice allocation

See `11-genre-playbooks.md` section 25.2. Design principle: the stop decision must have visible odds, and a bust must be bearable (low sunk cost, short turns).

### 7.5 Negotiation and trading

Catan's trade is a canonical example: players negotiate resource swaps, with the dice distributing resources unpredictably, so trade is where players create value. Levers: who may trade (active player only, or anyone), what can be traded, whether deals are binding, and what happens when the leader refuses to trade with. Pitfalls: trade can dominate the game session, and players who are not good at negotiation get excluded; the "do not trade with the leader" norm emerges naturally.

### 7.6 Dexterity, party and word games

Codenames (Vlaada Chvatil, 2015) is a team word-association game where one clue-giver gives a single word and number to guide teammates to specific words on a grid; its elegance comes from tiny rules, high social interaction, and scalability. Lessons: **low rules weight with high expressive depth**, a clear failure condition (the assassin card), asymmetrical information (the key card), and self-regulating difficulty (players choose how risky their clues are).

---

## 8. Cooperative Design and the Alpha-Player Problem

### 8.1 Designing cooperative games

Cooperative games make players a team against the game. The game is the opponent, so the designer must build an **automated adversary** that creates pressure and surprise.

Core components:
- **Escalating threat**: a clock, a track, or a deck of events that gets worse. In Pandemic, infection cards and outbreaks escalate, and the epidemic cards periodically accelerate the threat; players race against both the deck and the cure requirements. (Matt Leacock designed Pandemic, 2008.)
- **Role asymmetry**: players have distinct abilities so each has something to contribute; Pandemic gives each player a unique role.
- **Shared resources and limited actions**: scarcity forces trade-offs and discussion.
- **Difficulty scaling**: adjustable via the number of threat cards, the starting setup, or modular difficulty levels.
- **Uncertainty**: a mixture of randomness (cards, dice) and hidden info so that planning is not an exercise in solving a known puzzle.
- **Win/lose clarity**: players should know how close they are.

### 8.2 The alpha-player (quarterbacking) problem

In co-op games with perfect information, one experienced player tends to direct everyone else's moves, turning others into pieces. This is the **alpha-player problem**.

Mitigations **[heuristic]**:
| Mitigation | How | Example approach |
|---|---|---|
| **Hidden information** | Each player has a private hand/plan they cannot fully share | Hands that cannot be revealed or discussed in detail |
| **Communication limits** | Limit talk (no showing cards, time limits, restricted vocabulary) | Games with restricted communication |
| **Real-time pressure** | Simultaneous, timed play prevents central direction | Real-time cooperative games |
| **Hidden traitor** | Players cannot fully trust the advice | Traitor variant (section 9) |
| **Individual decisions with team stakes** | Each player controls their own character with meaningful, separable decisions | Role-based games with distinct actions |
| **Complexity of simultaneous demands** | So many things to track that no single person can see all | Large boards with parallel threats |
| **Social design** | Teach the group norms: suggestions, not orders | Rulebook advice on playing together |
| **Solo-friendly design** | Make the game satisfying in solo so that alpha dynamics are optional | Solo modes |

Some of these simply make the problem less visible; accept that the problem cannot be removed entirely for groups that choose to play that way.

### 8.3 Other co-op considerations

- **Difficulty by player count**: co-op scales threats by count; test each count.
- **Randomness and "unwinnable" setups**: ensure randomness does not produce unwinnable games too often (use a floor: guaranteed minimum safe cards at the start).
- **Pacing**: build up, crisis, relief. Pandemic's escalation provides a natural tension curve.
- **Replayability**: modular scenarios, villains, characters.
- **Campaign co-op** (Gloomhaven, Pandemic Legacy; see section 10).
- **Win rate target** **[heuristic]**: set a target win rate for typical groups (many co-op designers aim for a wins-slightly-below-half feel, but decide per audience) and measure it in playtests.

Gloomhaven is a cooperative tactical dungeon crawler with card-driven actions: each character uses a personal hand of ability cards, and the limited card count in hand means exhaustion acts as a clock. The no-dice-for-actions card play with an attack-modifier deck creates a controlled randomness. It also demonstrates the combination of cooperative play with a long campaign structure. Treat this as a description for study and verify rule specifics.

---

## 9. Hidden Roles, Traitors and Social Deduction

### 9.1 Structure

- **Hidden roles** with different goals (town vs. wolves, loyalists vs. traitors).
- **Information asymmetry**: some players know more; the informed minority hides while the majority deduces.
- **Discussion and voting** phases create social dynamics.

### 9.2 Design levers

| Lever | Effect |
|---|---|
| Ratio of traitors to loyalists | Higher traitor ratio = easier traitor wins, less certainty for loyalists |
| Information leakage | Actions, votes or night results reveal evidence; tune how much |
| Elimination | Eliminating players causes boredom; use elimination sparingly, allow eliminated players to participate (ghosts), or keep rounds short |
| Voting structure | Public vs. secret votes, who may propose |
| Role variety | Special roles add depth but need balance |
| Accusation cost | If accusing is free, accusations flood the table |
| Traitor activity | Traitors need things to do besides wait |
| Variance in role distribution | Make sure the game is fun for a player who gets the traitor role early |

Examples: Werewolf-style games (original party game), Avalon/Resistance (mission team voting with no elimination), Secret Hitler (policy cards with hidden roles), Battlestar Galactica style (traitor hidden among a cooperative team).

### 9.3 Pitfalls

- **Early elimination** of a player in a long game.
- **Groupthink**: the loudest player decides; add structures that give quiet players useful information to act on.
- **Lying discomfort**: some players dislike bluffing; provide clear frames ("it's just a game"), optional variants, and non-accusatory modes.
- **The traitor with no plan**: if the traitor's best strategy is to do nothing, the game collapses.
- **Playtest with experienced liars and with novices**.

See `14-ai-procedural-and-audio-design.md`, section 10, on the prisoner's dilemma and trust.

---

## 10. Legacy and Campaign Design

Legacy games permanently alter components (stickers, rewriting cards, destroying cards) as the campaign advances (see `11-genre-playbooks.md` section 25.2 and 25.3 for the pitfalls summary). Risk Legacy (Rob Daviau and Chris Dupuis, 2011) introduced the format; Pandemic Legacy (Daviau and Leacock, 2015) popularized it. The primary study materials are the games themselves; no verified written source is cited here.

### 10.1 Design principles

1. **Plan the arc** across sessions, with a beginning, middle, and finale; a campaign that is a sequence of identical scenarios is just a repeated game.
2. **Permanent change must be meaningful**: new rules, new characters, a changed board, a story consequence. Cosmetic changes do not justify destroying components.
3. **Protect the base game**: after the changes, the game should remain playable and fun; test the "end state" as a standalone game.
4. **Oops protection**: provide spare stickers, errata cards, or a way to recover from mistakes.
5. **Catch-up and comeback**: a bad early result should not lock a group into a lost campaign; adjust via mechanics that give disadvantaged groups new tools (the campaign can also be won by a narrow margin).
6. **Variance control**: randomness can produce wildly different campaign experiences; limit with scripted beats.
7. **Replay value**: decide whether the box is single-use or resettable; if single-use, price and communicate that clearly.
8. **Group commitment**: one group, one campaign; design for gaps between sessions with recap tools.
9. **Pre-playtest the destruction**: test with real destructive steps because players behave differently when changes are permanent.

### 10.2 Campaign without destruction

Gloomhaven and similar campaigns use persistent state (character progression, unlocked scenarios, envelopes and sealed boxes) without destroying components. Advantages: reusable and resettable, more tolerance for errors. The cost is bookkeeping (campaign sheets) and the need for spoiler-protected content (sealed packets).

### 10.3 Pitfalls

- Mistakes on rules that become permanent.
- Content that locks players out by the choices of a single player.
- Overlong campaigns that lose group members.
- Spoilers in the box art or component layout.

---

## 11. Player Count, Downtime and Analysis Paralysis

### 11.1 Player count scaling

Each player count is effectively a different game. Test 2, 3, 4, 5 and so on **separately**. Typical scaling issues:
- **Downtime** grows linearly with players in sequential games.
- **Contention** changes: board spaces, resources, majorities are tuned for a given count.
- **Information load**: tracking opponents' tableaus.
- **Dynamics**: two-player games are head to head; three-player games tend to produce kingmaking; larger counts dilute individual influence.

Scaling techniques **[heuristic]**:
| Problem | Technique |
|---|---|
| Too crowded at high count | Reduce available spaces at low count (cover spaces, use fewer), expand board for more |
| Too empty at low count | Neutral or automa players, dummy workers, "ghost" competitors, variable setup |
| Resource scarcity changes | Scale the supply with count |
| Sequential downtime at high count | Simultaneous phases, interleaved turns, shorter turns |
| Three-player kingmaking | Public scoring, tie-breakers, reduce late-game direct interaction |
| Interaction depth | Neighbor-only interaction (7 Wonders) so that scale does not multiply information |

Be honest on the box: state the recommended player counts and best count.

### 11.2 Downtime

Downtime is the time between a player's turns when they have nothing to do. Reduce it by:
- **Short turns**: fewer, quicker decisions.
- **Simultaneous phases**: planning, selecting, drafting.
- **Interaction on others' turns**: reactions, auctions, triggered abilities, following actions.
- **Parallelizable bookkeeping**: other players handle upkeep (rolling dice, drawing events).
- **Planning in advance**: visible state lets players think while waiting.
- **Time pressure** (sand timers) used sparingly and optionally.

Metric: *turn time x (players - 1)* is the downtime per round. Track total game time and decisions per hour in playtests.

### 11.3 Analysis paralysis (AP)

AP occurs when a player cannot decide because the option space is large and consequences are complex. Causes: too many options, calculable but laborious outcomes, perfect information with long-term consequences, and fear of making a suboptimal move.

Mitigations **[heuristic]**:
- Reduce option sets: show 3 cards instead of 7; make options visually distinct.
- **Increase uncertainty** slightly to reduce the value of exhaustive calculation.
- **Tight turn structure**: bounded decisions each turn.
- **Simple heuristics**: obvious good defaults ("when in doubt, do X") for new players.
- **Make good-enough moves OK**: avoid designs where a single suboptimal move ruins the game.
- **Clear preview of consequences**: visible scoring, icons that show conversions.
- **Timers** as an optional rule.
- **Table culture**: teach groups to plan during others' turns.

Do not mistake AP for depth: depth is the number of **meaningful** decisions, not the time per decision.

---

## 12. Kingmaking, Catch-Up and End-Game Triggers

### 12.1 Kingmaking

**Kingmaking** happens when a player who cannot win decides who does. Causes: end-of-game direct interaction, players choosing a target, negotiation.

Mitigations: reduce late-game direct attacks; make scoring public so the outcome is known; make decisions about resources rather than players (attack the board, not a person); randomize or limit target choices; adjust end conditions to keep everyone in contention longer.

### 12.2 Catch-up mechanisms and runaway leaders

Positive feedback (rich get richer) is needed to end games, but unbounded it creates a decided game with 30 minutes left. Techniques (SKILL.md section 4.5; `03` section 6.1):
| Technique | How |
|---|---|
| **Turn order catch-up** | Last place goes first or picks first (Catan variants, many worker-placement games) |
| **Resource subsidy** | Trailing players get extra resources or cheaper actions |
| **Scoring caps / diminishing returns** | Extra investment in one area yields less |
| **Hidden scoring** | Nobody knows who is ahead; the leader is not targeted |
| **Tax the leader** | Leader pays more, or opponents get bonuses against them |
| **Big late-game swings** | Final scoring bonuses that can overturn position (use carefully) |
| **Soft-limit snowballing** | Cap on engine speed or number of actions |

Warnings: **sandbagging** (deliberately staying behind to exploit catch-up), **punishing skill** (players feel their good play is taxed), and **feeling of futility** when the catch-up is obviously artificial. Heuristic: catch-up should narrow gaps, not erase them.

### 12.3 End-game triggers

How the game ends affects tension and pacing:
| Trigger | Description | Effect |
|---|---|---|
| **Fixed rounds** | A set number of rounds | Predictable, enables long-term planning; may feel mechanical |
| **Score threshold** | First to X points | Race; can create runaway or last-round tension; need equal turns rule |
| **Resource depletion** | A supply runs out (Dominion piles) | Players can accelerate or delay; can cause stalling |
| **Event trigger** | Specific card or milestone | Tension, uncertainty; risk of surprise endings |
| **Player-triggered end** | A player declares, others get a final turn | Strategic timing; risk of an early end by the leader |
| **Time limit** | Real-time cap | Fixed length; stress |
| **Mission/condition** | Complete objectives | Narrative closure; co-op |

Guidelines **[heuristic]**:
- Make the end **visible** (track, counter) so that players can plan; hidden or random end conditions require compensation.
- Ensure **equal turns** or an explicit tiebreaker for fairness.
- Avoid **long tails**: when the winner is clear and the game continues. End when it is at its best.
- Align the trigger with **player agency**: the player in the lead should not be able to end the game unilaterally without a cost.
- **Test with players trying to end early** and trying to stall.

---

## 13. Game Length, Weight and Audience

### 13.1 Weight

BoardGameGeek (BGG) users rate each game's complexity ("weight") on a scale from 1 (light) to 5 (heavy), and the average is shown on the game's page. Treat it as an informal community measure of rules and decision complexity (no verified URL for BGG's own weight definition in this reference set; check the BGG site for the current wording).

Rough audience bands **[heuristic, informal community usage]**:
| Band | Typical features | Audience |
|---|---|---|
| Light | A few rules, teach in a few minutes, short games | Families, casual, gateway |
| Medium | A turn structure with several options, teach in around 15 minutes | Hobbyists |
| Heavy | Many interacting systems, long teach, long play | Dedicated hobbyists |

### 13.2 Matching length to weight

- **Light games** should be short; a light game that outlasts its decisions overstays.
- **Heavy games** can be long, but should have a clear arc and turns that move.
- **Number of decisions per minute** is a better measure of engagement than total length. Playtest to track decision density.
- **Playtime printed on the box** should match first-play time with the rules explained; first plays are usually longer than box time.
- **Teach time** counts: a 90-minute game with a 45-minute teach is a heavy commitment.

### 13.3 Audience and positioning

Define your audience and the **table**: families with kids, couples (2-player), game-night groups of 4, solo gamers. Each demands different component weights, rules, and play lengths. Gateway designs (Catan, Ticket to Ride, Codenames, Carcassonne) win by clarity; hobby designs win by depth and replayability. Decide before designing; changing target audience late is expensive.

---

## 14. Rulebook Writing

The rulebook is part of the game. Most first plays are decided by the rulebook, and the blind playtest tests it (section 15).

### 14.1 Structure

A reliable order **[heuristic]**:
1. **Overview / goal / theme** (one short paragraph): what are we doing and how do we win.
2. **Component list** with images and counts.
3. **Setup** with a diagram.
4. **Turn structure** at a glance (a summary of phases).
5. **Detailed rules** in the order they occur in play, each section short.
6. **Special cases / FAQ / clarifications**.
7. **End of game and scoring**, with an example.
8. **Variants, solo mode, appendix** (icon glossary, card index).
9. **Credits and contact**.

The back page should hold a **quick reference** (turn summary, scoring, icon legend) so that players can find rules in play.

### 14.2 Writing principles

- **Teach in layers**: first the goal and main loop, then details. Avoid front-loading exceptions.
- **One idea per paragraph**; short sentences; active voice; numbered steps for sequences.
- **Use consistent terminology**; define a term once and never replace it with a synonym. (If the rulebook says "worker", do not later say "meeple".)
- **Examples everywhere**: every non-trivial rule needs a worked example with an image of the game state. Examples often teach better than text.
- **Show setup visually** for each player count.
- **Define timing and priority** for conflicts: "if two effects trigger at the same time, the active player decides the order".
- **Rule hierarchy**: card text overrides rulebook only when specified; say it.
- **Highlight edge cases** in a clear, separate place so they do not clutter the main text.
- **Avoid hypothetical language and long conditionals**; use tables for variants.
- **Include a "your first game" suggestion** with simplified setup.
- **Test readability**: reading level, sentence length, and scanning ability.

### 14.3 Reference cards and player aids

- A one-page summary per player or per table: turn order, actions with costs, scoring table, icon glossary.
- Put information where the player needs it: costs on the cards, conversions on the board or player mat.
- Make aids **not necessary**: a game that requires a player aid every turn is a rules burden; iconography should carry most of the load.

### 14.4 Teaching a game

Many players learn from a person, not the book. Prepare a **teach script**: a theme sentence, the goal, the turn in 60 seconds, the first example, then let play begin and teach exceptions as they appear. Measure teach time in playtests.

### 14.5 Rulebook pitfalls

- Ambiguity about timing ("at the start of your turn" vs "before drawing").
- Rules scattered between components and book with no index.
- No examples of endgame scoring.
- A table of contents that does not match the content.
- Translating the rulebook without checking terminology consistency.

---

## 15. Playtesting Tabletop Games

See `12-playtesting-and-analytics.md` for general method. Tabletop-specific approach:

### 15.1 Stages

| Stage | Who | Goal | Notes |
|---|---|---|---|
| **Solo testing** | You | Fix obvious rules problems; check flow and math | Play all seats; try to break the rules; time turns |
| **Friends and family** | Familiar testers | Check fun and basic clarity | Biased by politeness; useful for flow |
| **Local playtest groups** | Hobbyist designers | Feedback on mechanisms and balance | They give design advice; filter it |
| **Blind playtests** | Strangers with only the rulebook and components | Test rules clarity and first-play experience | The gold standard for rulebook |
| **Target audience tests** | Players of the intended type | Test fun in the intended market | Observe real tables |
| **Remote tests** | Online groups | Test at scale and with distant groups | Use digital prototypes (section 16) |
| **Balance / long-run tests** | Experienced testers, bots, spreadsheets | Test strategies, dominant plays, scalability | Simulation helps with randomized elements |

### 15.2 Blind playtesting protocol

1. Give the testers the rulebook and components; **do not be present** or stay silent (a recording or observer notes).
2. Record **questions**, **errors** (rules played wrong), **hesitations**, **time to first turn**, and **end time**.
3. After the game, ask: what was the goal, what were your key decisions, what was confusing, would you play again.
4. Do not defend; do not explain. Every question is a rulebook bug.
5. Fix, then test with fresh testers; testers who have seen a version cannot be blind again.

### 15.3 What to observe

- Are players **leaning in** or checking phones?
- Do players **plan on others' turns**?
- Where do **arguments about rules** arise?
- Do players **understand how they are doing** (score awareness)?
- Which options are **never chosen** or **always chosen**?
- **Decision time** per turn; the longest turns indicate AP sources.
- Does the **end** feel right (did players want to stop or continue)?
- **Emotion** at the end: closeness of scores, "one more game".

### 15.4 Questions to ask

Open questions beat leading ones: "What was your plan?" "What would you change?" "Which turn felt best?" "When did you feel behind?" Collect numbers too: a quick rating, a 1-5 scale of fun and clarity, and compare across versions (with small samples treat as directional, not statistical).

### 15.5 Handling feedback

Players report **symptoms** (it's too long) more reliably than **solutions** (add a timer). Identify the underlying cause. Weigh feedback by target audience. Change one thing at a time; track versions (date every prototype and rule change).

### 15.6 Automated and statistical balancing

If randomness or asymmetric roles are involved, simulate: spreadsheets, scripts or simple bots can play thousands of games to find dominant strategies, win rates by seat (first-player advantage), and scoring spreads. Compare to human tests; bots miss social dynamics but detect math problems.

---

## 16. Prototyping Tools and Methods

### 16.1 Paper prototypes

- Start with **index cards, sleeves over a placeholder card, cut paper, coins, dice, cubes**; use ugly components deliberately so that testers critique mechanics, not art.
- Print with a spreadsheet/mail merge (data-driven cards) so balance changes propagate.
- Use **color-coded sleeves or markers** to distinguish versions.
- Keep a **changelog** and version number on each card/board.
- Write rules in a **living document**; the rulebook is part of the prototype.

### 16.2 Digital prototypes

| Tool | Use | Notes |
|---|---|---|
| **Tabletop Simulator** | 3D physics sandbox for tabletop games; supports custom decks, boards and scripting; widely used for remote playtests | Page confirmed: "Home \| Tabletop Simulator" (https://www.tabletopsimulator.com/). Check platform and price on the store page. |
| **Screentop** | Browser-based platform for playing and prototyping tabletop games with friends | Page confirmed: "Screentop.gg - Play tabletop games with friends" (https://screentop.gg/). |
| **Spreadsheets** | Card databases, probability, scoring tables | Excel/Google Sheets; export to print or to digital tools |
| **Scripts / simulators** | Monte Carlo of dice, deck compositions | Python or similar; see `design_calc.py` for expected value and odds |
| **Card layout tools** | Data-driven card templates | Any layout tool that supports data merge |

Use digital prototypes to test remote groups and to log play, but beware: digital automation hides rules problems (the software enforces rules the rulebook may explain badly), so still run physical or blind rule tests.

### 16.3 Prototype fidelity

Increase fidelity as the design stabilizes: **ugly** (mechanism test), **clean** (usable for blind tests), **polished** (for pitching or crowdfunding photos). Do not invest in art before the core loop works.

### 16.4 Iteration cadence

Playtest early and often; many designers aim for multiple playtests per week during active development (heuristic). Each playtest should have a **question**: "does the draft phase have a dominant card?", not "is it fun?" alone.

---

## 17. Publishing Paths

No path is universally best; each trades control, capital, and reach.

| Path | What you do | Pros | Cons |
|---|---|---|---|
| **Pitch to a publisher** | Prepare a prototype, rules, sell sheet; pitch at conventions or submissions; royalty or flat fee | Publisher handles production, distribution and marketing; you focus on design | Rejections common; loss of control; royalty rates and contract terms vary; slow |
| **Self-publish with crowdfunding** | Design, art, manufacture, fulfillment, marketing; use Kickstarter or similar | Control, direct audience, capital from backers | Heavy non-design work (logistics, shipping, taxes, customer service); financial risk; fulfillment delays |
| **Self-publish via print-on-demand** | Print small runs, sell online | Low barrier, low capital | Per-unit cost higher; limited components; limited distribution |
| **Hybrid / partner** | Publisher partners on manufacturing, you crowdfund | Shares risk | Negotiation; shared revenue |
| **Digital adaptation first** | Release on a platform to build audience | Can validate design | Different skills and costs |
| **Free print-and-play** | Release for free | Audience, feedback, portfolio | No revenue; piracy not a concern but no budget |

Practical steps (heuristic checklist):
1. Validate the design with many blind playtests and an audience test.
2. Prepare a **pitch kit**: one-page sell sheet, short rules summary, video demonstration, prototype ready to ship, estimated component cost, target price and audience.
3. Research potential publishers' catalogs and submission guidelines; read their contract terms carefully; consider legal advice for contracts.
4. For crowdfunding, **cost out manufacturing, shipping and taxes** before setting a goal; get quotes from multiple manufacturers; plan for delays; build an audience before launch.
5. Protect your interests: understand what rights you grant (the game, expansions, digital adaptations, derivative works). Intellectual property in games largely covers expression (names, art, text), not mechanisms; consult a professional for specifics.
6. Plan **post-launch**: errata, FAQ, expansions, translations, reprint cycles.

Books such as the *Kobold Guide to Board Game Design* (Kobold Press, 2011) collect essays from designers on design and business topics (see References).

---

## 18. TTRPG Design Basics

Tabletop role-playing games (TTRPGs) are structured conversation with rules: a shared fiction plus resolution procedures. They differ from board games in having a facilitator role (GM) in most games and open-ended player actions.

### 18.1 The core elements

| Element | Questions to answer |
|---|---|
| **Premise / fantasy** | What do characters do? What is the game about? |
| **Characters** | How are they created, defined, advanced? |
| **Resolution** | How are uncertain actions resolved? |
| **Fiction and rules interface** | When do rules apply and when does the conversation just flow? |
| **GM role** | Who creates situations, plays the world, adjudicates? |
| **Advancement** | What changes over time? How is it rewarded? |
| **Tone and safety** | What tone is expected, and how do players keep it comfortable? |
| **Procedures** | Procedures for exploration, combat, social scenes, downtime |

### 18.2 Resolution mechanics

| Mechanic | How it works | Feel | Example |
|---|---|---|---|
| **d20 + modifier vs target number** | Roll one die, add bonuses, compare to difficulty | Swingy; simple; bonuses matter | D&D 5e: ability checks and attack rolls use a d20 plus modifiers against a DC or AC; advantage/disadvantage (roll two, take the higher/lower) is a core modifier |
| **Dice pool, count successes or take highest** | Roll several dice; count hits or read the highest | More granular probabilities; scale with ability | Blades in the Dark: roll a number of d6 equal to the rating and take the highest die; a 6 is a full success, 4-5 is a partial success, 1-3 is a failure (rules details: check the published rules) |
| **Roll-under** | Roll below a skill number | Intuitive | Several classic and OSR games |
| **Bell-curve (2d6, 3d6)** | Sum of multiple dice | Predictable results with fewer extremes | Some narrative systems |
| **Cards or tokens** | Draw instead of roll | Controlled randomness, tracking | Alternative decks |
| **Diceless / narrative bidding** | Resources or negotiation decide | Player control, less randomness | Some indie systems |
| **Degrees of success (partial success)** | Results with success, success-at-a-cost, failure | Keeps fiction moving; failure advances the story | Blades in the Dark's "success with consequences" |

Design questions:
- **What is the probability curve** of success at typical difficulty? Sketch it with `design_calc.py` or a spreadsheet.
- **What does failure do?** Failure that stops play is boring; "fail forward" results (failure introduces complications) keep momentum.
- **Who narrates results?** Player, GM, or shared.
- **How often do players roll?** Roll when stakes are meaningful and failure is interesting. A common GM maxim is not to call for rolls when there is no uncertainty or consequence.
- **Fortune in the middle or at the beginning**: Blades in the Dark's design has players choose position and effect before rolling, which sets stakes up front (check the rulebook to see how this works).

### 18.3 GM tools and support

A game is only as good as the GM's ability to run it. Provide:
- **Procedures**, not just advice: step-by-step (e.g., how to run a heist, a dungeon turn, a social encounter).
- **Prep tools**: random tables, oracles, encounter builders, quick NPC/location generators (links to PCG, `14-ai-procedural-and-audio-design.md` section 7).
- **Clocks and trackers** for tracking progress of threats and projects (Blades in the Dark uses clocks; the format is widely borrowed).
- **Principles and agendas**: short lists that tell the GM how to behave (be a fan of the characters, make the world feel real, etc.). Many modern games have explicit GM principles.
- **Example play**: a worked scene is the most effective teaching tool.
- **Adventure structure**: scenario format with maps, hooks, secrets, and consequences.
- **Difficulty guidance** and an encounter-balancing method (D&D 5e provides encounter-building guidance in its core books; check the books for the current method).

### 18.4 Player-facing design

- **Character creation** should be fast and produce interesting characters with hooks; consider playbooks/classes with clear identity (Blades in the Dark playbooks).
- **Agency**: players should have verbs and levers to change the fiction.
- **Spotlight sharing**: mechanisms to give each player moments of focus.
- **Advancement** tied to the fantasy (new abilities, new relationships, new resources).

### 18.5 Safety tools

Safety tools help groups talk about content and boundaries so the game can be intense without harm. They are not a substitute for care and communication, and they are not universally liked; offer them as options and use them consistently.

| Tool | What it is | How it is used |
|---|---|---|
| **X-Card** | An index card with an X (by John Stavropoulos) that any player can tap to signal that content should be edited or skipped, without explanation | Introduced at the start; no questions asked; the group adjusts the scene |
| **Lines and Veils** | Lines: content that will not appear. Veils: content that may exist but is not shown on-screen (fade to black, off-screen) | Discussed in session zero; written down |
| **Session zero** | A pre-game discussion on tone, expectations, boundaries, and characters | Held before the first session |
| **Check-ins / debriefs** | Brief conversations after intense scenes or sessions | Maintains trust |
| **Stars and wishes, or similar feedback rituals** | Players note what they liked and what they want | Ongoing improvement |

Design tips: include safety tools in the rulebook; state that they are optional but encouraged; give examples of tone/content calibration; note that the **designer's choices about content** (what the game explicitly asks the players to portray) set expectations and responsibility. Verify the primary source for each tool before citing (the X-Card document is confirmed in References; no verified URL for Lines and Veils in this reference set).

### 18.6 TTRPG pitfalls

- Rules that do not support the stated fantasy (a grim survival game with generous healing).
- Too many subsystems with no integrating procedure.
- Combat that dominates when the game claims to be about something else; the amount of rules text signals what the game is about.
- GM overload: if the GM must remember every rule, prep time explodes.
- Missing guidance for new players.
- Playtest with groups other than your own; groups' habits hide problems.

---

## 19. Worked Examples

These are design-study notes. Verify details against rulebooks before quoting.

### 19.1 Catan: trade and production as the engine

Observations: resource production from dice rolls on hexes gives every player income on others' turns (low downtime), trading is the main interaction, and the robber (rolled seven) adds a negative event that can target the leader. Lessons: **income on every turn keeps everyone engaged**; the randomness of production gives a varied board; trade makes social negotiation the game's heart; dice distribution (6 and 8 being the most frequent sums) shapes where players want to build. Known critiques: runaway-leader dynamics, player elimination from the resource pool via bad placement, and kingmaking in endgames.

### 19.2 Agricola: scarcity and pressure

Observations: players are farmers who place workers on action spaces each round, with a feeding requirement at harvests that is a constant pressure. The cost of the next action competes with the need to feed the family; scarcity of workers and spaces; a huge variety of occupation and improvement cards creates different engines. Lessons: **pressure creates meaning** (feeding), **blocking creates tension**, and **variety through cards** increases replayability; cost is complexity and analysis paralysis.

### 19.3 Pandemic: escalating cooperative threat

Observations: four actions per turn; players draw cards to cure diseases while the infection deck spreads disease; epidemic cards intensify the situation; roles give special abilities. Lessons: an **automated adversary** produces drama; limited actions create tension; role asymmetry combats the alpha-player problem only partly (information is public).

### 19.4 Dominion: asymmetric start, symmetric potential

Observations: players begin with the same small deck and buy from a randomly selected set of ten kingdom card piles; the deck tradeoff (adding good cards slows cycling) is the central tension. Lessons: **randomized supply provides replayability**; the baseline "Big Money" strategy is a benchmark for kingdom balance; end by piles exhausted.

### 19.5 7 Wonders: simultaneous drafting with neighbor interaction

Observations: three ages, each starting with seven cards; draft-and-pass; you interact with neighbors through trade and military; cards have multiple uses. Lessons: simultaneous play scales to seven, neighbor-only interaction caps information load, and **multi-use cards** keep drafted hands valuable. Weakness: players can feel isolated from non-neighbors; scoring variety hides who leads.

### 19.6 Gloomhaven: card-driven tactics and campaign

Observations: tactical combat driven by a limited set of ability cards per character, where resting and exhausted cards form a resource clock; an attack-modifier deck replaces dice; a campaign unlocks content. Lessons: a **resource clock built into the cards** gives scenarios natural length; campaign structure drives long-term investment; the cost is huge component count, setup and teach time.

### 19.7 Wingspan: tableau engine with table presence

Observations: players place birds into habitats; each habitat row activates powers in sequence, creating chain engines; limited rounds with end-of-round goals; high-quality components and art. Lessons: **engine building with visible payoff** (watching a row chain), **table presence** drives appeal, and low conflict suits broader audiences; the weakness is lower interaction.

### 19.8 Twilight Struggle: dual-use cards for tension

Observations: two-player card-driven game; each card has an event and an operations value; playing an opponent's event for operations triggers the event anyway. Lessons: **dual-use cards** create constant dilemma; theme and mechanics align; the steep learning curve and length place it at the heavy end.

### 19.9 Codenames: minimal rules, maximum interaction

See section 7.6. Lessons: tiny rule set, social deduction embedded in clue-giving, scalable team sizes, and variety from the 25-word grid.

### 19.10 Blades in the Dark: fiction-first resolution

Observations: players are criminals in a haunted city; the system uses position and effect to set stakes before rolls, clocks to track progress, and stress to power-up at cost. Lessons: **procedures that keep the fiction moving**, partial successes, and shared GM tools.

### 19.11 D&D 5e: accessibility and legacy

Observations: a d20 core with proficiency bonus scaling and advantage/disadvantage; classes with levels; a large ecosystem. The Systems Reference Document is published online (see References). Lessons: **a simple universal mechanic** (d20 plus modifiers) onboard players quickly; advantage/disadvantage replaces long modifier lists; the ecosystem and accessibility drive adoption.

---

## 20. Checklists

### 20.1 Design review (tabletop)
- [ ] One-sentence pitch and target audience defined.
- [ ] Core decision identified and meaningful at every player count.
- [ ] Turn structure and downtime evaluated; turn length measured.
- [ ] No dominant strategy found in simulation or playtests.
- [ ] Runaway leader and kingmaking handled.
- [ ] End condition visible and tuned; no long tail.
- [ ] Component economy justified; cost estimated.
- [ ] Iconography clear, colorblind-safe.
- [ ] Rulebook passes blind playtest.
- [ ] Player aids exist and are not mandatory.

### 20.2 Rulebook checklist
- [ ] Goal and overview on page one.
- [ ] Setup diagrams for each player count.
- [ ] Terminology consistent.
- [ ] Examples with images for each non-trivial rule.
- [ ] Timing/priority rules for simultaneous effects.
- [ ] Quick reference on the back.
- [ ] Index or glossary.

### 20.3 Co-op checklist
- [ ] Escalating threat with tunable difficulty.
- [ ] Role asymmetry.
- [ ] Alpha-player mitigation chosen.
- [ ] Win rate measured by player count.
- [ ] Unwinnable setups prevented.

### 20.4 Legacy checklist
- [ ] Arc planned; base game works at end state.
- [ ] Oops protection.
- [ ] Destructive steps playtested.
- [ ] Group commitment and recap tools.

### 20.5 TTRPG checklist
- [ ] Premise and fantasy stated; rules support it.
- [ ] Resolution mechanic with probability curve known.
- [ ] Failure moves the fiction.
- [ ] GM procedures, tools and principles included.
- [ ] Quick character creation.
- [ ] Safety tools and session zero guidance.
- [ ] Playtested with groups unfamiliar with the designer.

---

## 21. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Books (ISBNs verified via Open Library)**
- Engelstein, G. and Shalev, I., 2019, *Building Blocks of Tabletop Game Design: An Encyclopedia of Mechanisms*, CRC Press. ISBN 9781138365490.
- Salen, K. and Zimmerman, E., 2003, *Rules of Play: Game Design Fundamentals*, MIT Press. ISBN 9780262240451.
- Selinker, M. (ed.), 2011, *Kobold Guide to Board Game Design*, Open Design / Kobold Press. ISBN 9781936781041.

**Websites (URLs verified, titles confirmed)**
- Blades in the Dark (official site; page title "Greetings, Scoundrel | Blades in the Dark RPG"): https://bladesinthedark.com/
- Stavropoulos, J., "X-Card" (tinyurl link resolves to a Google Docs page titled "X-Card by John Stavropoulos"): http://tinyurl.com/x-card-rpg
- Tabletop Simulator: https://www.tabletopsimulator.com/
- Screentop.gg: https://screentop.gg/
- Wizards of the Coast, System Reference Document (page title "SRD v5.2.1 - System Reference Document - D&D Beyond"): https://dnd.wizards.com/resources/systems-reference-document

**Not verified (do not cite as sources)**: BoardGameGeek weight definition (BGG returned an access error to the automated check), Lines and Veils origin (no verified URL), Engelstein's *Game Production* (ISBN not verified), rulebooks of the games used as examples (Catan, Agricola, Pandemic, Dominion, 7 Wonders, Gloomhaven, Wingspan, Twilight Struggle, Codenames); the example sections are design-study observations and should be checked against the rulebooks.

Notes: statements marked "heuristic" are rules of thumb. Games are recommendations for the reader to play and study, not sources.
