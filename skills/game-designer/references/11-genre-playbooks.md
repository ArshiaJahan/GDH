# Genre Playbooks

## Table of Contents

1. [How to Use This File](#1-how-to-use-this-file)
2. [Platformer](#2-platformer)
3. [Action and Character Action](#3-action-and-character-action)
4. [Shooter (FPS and TPS)](#4-shooter-fps-and-tps)
5. [RPG (CRPG, JRPG, ARPG)](#5-rpg-crpg-jrpg-arpg)
6. [Roguelike and Roguelite](#6-roguelike-and-roguelite)
7. [Strategy (RTS, 4X, Tactics, Grand Strategy)](#7-strategy-rts-4x-tactics-grand-strategy)
8. [Puzzle](#8-puzzle)
9. [Survival and Crafting](#9-survival-and-crafting)
10. [Horror](#10-horror)
11. [Simulation, Management and City-Builder](#11-simulation-management-and-city-builder)
12. [Sandbox](#12-sandbox)
13. [Deckbuilder and Card Games (CCG, LCG)](#13-deckbuilder-and-card-games-ccg-lcg)
14. [Idle and Incremental](#14-idle-and-incremental)
15. [Fighting](#15-fighting)
16. [Racing](#16-racing)
17. [Sports](#17-sports)
18. [MOBA](#18-moba)
19. [Battle Royale](#19-battle-royale)
20. [MMO](#20-mmo)
21. [Metroidvania and Soulslike](#21-metroidvania-and-soulslike)
22. [Narrative Adventure and Visual Novel](#22-narrative-adventure-and-visual-novel)
23. [Party, Casual and Hyper-Casual](#23-party-casual-and-hyper-casual)
24. [Rhythm](#24-rhythm)
25. [Tabletop Board Games](#25-tabletop-board-games)
26. [Genre Hybrids and Choosing a Genre](#26-genre-hybrids-and-choosing-a-genre)
27. [References](#27-references)

---

## 1. How to Use This File

Each genre uses the same sub-template:

- **Fantasy**: the promise to the player.
- **Core loop**: the repeating cycle (seconds to minutes).
- **Key systems**: what must exist for the genre to work.
- **Design levers**: what you tune to differentiate and balance.
- **Pitfalls**: common failure modes.
- **Study**: exemplar games to play and deconstruct.
- **Key reference**: where to read more.

Genre conventions are **industry practice and descriptive generalizations**, not laws. Genres overlap and drift. Numbers marked "heuristic" are starting points. When designing, use a genre as a **contract of expectations** (what the audience assumes) and decide deliberately which expectations to honor, twist or break. Cross-reference: loops (`03`), balance (`04`), difficulty/onboarding (`05`), levels (`06`), narrative (`07`), monetization (`09`), multiplayer (`10`), playtesting (`12`).

## 2. Platformer

- **Fantasy**: mastery of movement through hostile space; expressive, precise control.
- **Core loop**: observe the obstacle, plan the route, execute jumps and timing, land, repeat; checkpoint; escalate.
- **Key systems**: a movement model (run, jump, variable jump height, air control), collision forgiveness (coyote time, jump buffering, ledge corner correction), hazards, collectibles, checkpoints, camera.
- **Design levers**: gravity and jump arc; acceleration vs instant turn; level metrics (see `06`); hazard density; checkpoint spacing; collectible risk/reward; power-ups; assist options.
- **Pitfalls**:
  - Imprecise or inconsistent jump physics; camera that hides landings.
  - Blind jumps and unfair deaths on first exposure.
  - Long un-checkpointed stretches; slow respawn.
  - Introducing mechanics without safe practice.
  - Difficulty from precision demands only, without variety.
- **Study**: Super Mario Bros. / Super Mario World / Super Mario Odyssey, Celeste, Super Meat Boy, Hollow Knight (movement), Donkey Kong Country: Tropical Freeze, Rayman Legends, Ori and the Blind Forest.
- **Key reference**: Swink 2009 *Game Feel* (responsiveness, forgiveness); Rogers 2014 *Level Up!*; Celeste's assist mode as an accessibility model. Level design: `06-level-design.md`.

## 3. Action and Character Action

- **Fantasy**: stylish, expressive combat; being a powerful, skillful fighter.
- **Core loop**: engage, read enemy tells, attack/dodge/parry, chain combos, finish, collect rewards, upgrade.
- **Key systems**: move set with startup/active/recovery frames, hit-stop and feedback, enemy attack telegraphs, lock-on or targeting, combo system, dodge/parry/guard, stylish ranking or resource economy, upgrade shop.
- **Design levers**: animation timing and cancel windows; enemy aggression tokens (limit simultaneous attackers); input buffering; damage/stagger values; resource gain (ammo/rage/focus); camera.
- **Pitfalls**:
  - Button mashing wins; no reason to use the full move set.
  - Telegraphs too short or ambiguous; attacks that cannot be reacted to.
  - Camera loses the enemy; target switching unreliable.
  - Combat arenas repeated without new questions.
  - Animation lock that feels unresponsive (feel vs realism trade-off).
- **Study**: Devil May Cry 3/5, Bayonetta, God of War (2018), Sekiro (posture), Hades (action roguelite), Metal Gear Rising, Batman: Arkham series (freeflow).
- **Key reference**: Swink 2009 *Game Feel*; frame-data thinking from fighting games (section 15).

## 4. Shooter (FPS and TPS)

- **Fantasy**: power and precision; being a lethal presence in a hostile space; tactical dominance (tac-shooters) or movement-driven mastery (arena shooters).
- **Core loop**: move, acquire target, aim and fire, take cover or dodge, reload or switch, resolve, pick up resources.
- **Key systems**: weapon handling (recoil, spread, ranged falloff, TTK), movement (speed, jump, slide, sprint), enemy AI roles (see `06` section 9), health model (regenerating, medkits, armor), hit feedback (audio, hit markers, flinch), ammo economy, aim assist (console).
- **Design levers**:
  - **Time to kill (TTK)** relative to reaction time and ping; higher TTK favors aim consistency and positioning, lower favors first shot and information.
  - Weapon roles and ranges; hitscan vs projectile; recoil patterns (learnable vs random).
  - Health model: regen encourages cover cycles; medkits encourage attrition; Doom-style kill-for-health encourages aggression.
  - Map sizes and sightlines (`06` section 12).
  - Movement tech and speed.
- **Pitfalls**:
  - Weapons indistinct in role; one hitscan weapon dominates.
  - Feedback gaps (no sense of hitting, damage direction unclear).
  - Randomness (spread) that overrides skill in competitive modes.
  - Enemy AI that is bullet sponge instead of tactical.
  - Spawn problems in multiplayer; lack of onboarding for new players; skill-gap lockout (see `10`).
  - Linear campaigns that are shooting galleries without variety.
- **Study**: Half-Life 2, Doom (1993 and 2016), Halo (combat sandbox: "30 seconds of fun"), Counter-Strike, Call of Duty 4, Quake, Titanfall 2, Apex Legends, Valorant, Overwatch.
- **Key reference**: Bungie's Halo talks (golden triangle: weapons, grenades, melee, plus vehicles) as a model of combat sandbox design; verify specifics in GDC Vault sources. Level design: `06`. Multiplayer: `10`.

## 5. RPG (CRPG, JRPG, ARPG)

- **Fantasy**: growth of a character (or party) in a rich world; build identity; narrative role-play.
- **Core loop**: explore or take quests, fight or talk, gain XP and loot, improve the build, take on harder content.
- **Key systems**: attributes and skills, classes/builds, equipment and itemization, combat (turn-based, real-time with pause, or action), progression curve, quests and dialog, inventory, economy, companions.
- **Subgenres**:
  - **CRPG** (Baldur's Gate, Pillars of Eternity, Disco Elysium): choice, consequence, tactical or turn-based combat, reactivity; high writing cost.
  - **JRPG** (Final Fantasy, Persona, Dragon Quest): linear narrative, party, turn-based/ATB combat, set-piece storytelling, overworld; strong character presentation.
  - **ARPG** (Diablo, Path of Exile, Torchlight): real-time combat, loot treadmill, build crafting, endgame.
- **Design levers**: XP curve and level cap; stat scaling and soft caps; build diversity vs balance; loot drop rates and rarity tiers (see `04`); difficulty scaling (level-scaled vs zone-fixed); respec cost; party composition; encounter frequency.
- **Pitfalls**:
  - Number inflation without meaning; trivial stat upgrades.
  - Fake choice in builds (one optimal build); respec-less lock-in.
  - Level scaling that erases progression feel, or lack of scaling that breaks sequence.
  - Grind walls; repetitive random encounters; bloated quest logs.
  - Loot that is mostly junk, or so much that inventory management dominates.
  - Writing bulk without reactivity.
- **Study**: Baldur's Gate 3, Disco Elysium, Persona 5, Final Fantasy VI/X, Dragon Quest XI, Diablo II / IV, Path of Exile, The Witcher 3, Skyrim, Dark Souls (action RPG), Elden Ring.
- **Key reference**: Adams and Dormans, *Game Mechanics: Advanced Game Design* (progression and economy); Rogers 2014; `04` for loot and XP math; `07` for dialogue and companions.

## 6. Roguelike and Roguelite

- **Fantasy**: a unique run each time; improvisation under uncertainty; risk of loss and the thrill of a lucky build; "one more run".
- **Core loop**: start run, make moves/fights, collect upgrades, adapt to randomized situations, die or win; (roguelite) carry over meta-progression; repeat.
- **Key systems**: procedural generation (levels, items, enemies), permadeath, build synergies, risk/reward choices (shops, elites, events), run-to-run meta-progression, run-end summary/seed.
- **Berlin Interpretation** (International Roguelike Development Conference, 2008): a definition of "roguelike" as a set of factors. **High-value factors**: random environment generation, permadeath, turn-based, grid-based, non-modal, complexity, resource management, hack-and-slash, exploration and discovery. **Low-value factors**: single player character, monsters are trouble, tactical challenge, ASCII display, dungeons, numbers. Use it as a vocabulary: games with some but not all factors are "roguelike-likes" or "roguelites" (see Roguelike, Wikipedia).
- **Roguelike vs roguelite**: traditional roguelikes keep nothing between runs but player knowledge; roguelites add **meta-progression** (unlocks, permanent upgrades, new starting options).
- **Meta-progression design**:
  - **Power meta** (permanent stat boosts): reduces early frustration, risks trivializing the challenge; keep increments modest or capped.
  - **Option meta** (unlock new items, characters, options): widens the build space without raising baseline power; preferable for depth.
  - **Knowledge meta**: the player learns (Spelunky, Slay the Spire).
  - **Narrative meta**: story progresses by runs (Hades).
  - Include a "failure still progresses" guarantee for new players.
- **Design levers**: variance (how much luck vs skill, including mitigation like rerolls, choices, banishes); run length (heuristic: 20-60 minutes for most modern roguelites); synergy density; build-defining items; difficulty scaling and optional difficulty modifiers (Hades' Heat, Slay the Spire's Ascension); item pool management (unlock gating avoids early overload).
- **Pitfalls**:
  - Randomness that decides runs before the player acts (unwinnable seeds, no way to mitigate).
  - Dominant builds that collapse variety; item pool dilution from too many mediocre items.
  - Meta-progression that is an obvious grind, or makes early game boring.
  - Opaque item interactions; illegible rules.
  - Run length that discourages "one more run".
  - Procedural generation producing bland rooms (authored chunks with procedural arrangement often beat pure randomness).
- **Study**: Spelunky, Slay the Spire, Hades, Dead Cells, The Binding of Isaac, Nethack/Brogue (classic), FTL, Rogue Legacy, Risk of Rain 2, Vampire Survivors.
- **Key reference**: Berlin Interpretation (via Roguelike, Wikipedia); Spelunky (Derek Yu, *Spelunky*, Boss Fight Books) for design notes on generation; `03` and `05` for loops and difficulty.

## 7. Strategy (RTS, 4X, Tactics, Grand Strategy)

- **Fantasy**: command, foresight, optimization; being the mastermind; building an empire.
- **Core loop** varies:
  - **RTS**: gather resources, build economy and army, scout, fight, expand, win (real-time, high APM demands).
  - **4X** (explore, expand, exploit, exterminate): take turns managing cities, research, diplomacy, military.
  - **Tactics** (XCOM, Into the Breach, Fire Emblem): small-squad turn-based fights with positioning, cover, unit abilities.
  - **Grand strategy** (Crusader Kings, Europa Universalis, Hearts of Iron): long-horizon simulation of states/dynasties with deep systems and emergent narrative.
- **Key systems**: resource economy, tech/upgrade tree, unit roster with rock-paper-scissors counters, fog of war and scouting, map design, AI opponents, victory conditions, diplomacy.
- **Design levers**:
  - Unit cost curve and counters (`04`); economy snowballing vs rubber-banding; tech pacing.
  - Map control vs turtling incentives; build orders and openings (RTS); end-game victory pace (4X).
  - Information (fog, hidden units); randomness (hit chance in tactics: XCOM famously shows percentages).
  - APM demands vs decision depth.
- **Pitfalls**:
  - Snowballing with no comeback; early game decides the match.
  - Dominant opening/rush; solved metas.
  - 4X "mid-game slog": once victory is determined, the remaining turns are bookkeeping; late-game turn time; AI that is too passive or cheats opaquely.
  - Hidden information that frustrates; hit-chance randomness perceived as unfair (display, bias, or design around it).
  - UI overload; tooltips missing; unclear economy numbers.
  - Weak AI: players detect and exploit it; consider scenario-based puzzles (Into the Breach) to avoid AI weakness.
- **Study**: StarCraft II / Brood War, Age of Empires II, Civilization VI (and Civ IV), Crusader Kings III, XCOM: Enemy Unknown, Into the Breach, Fire Emblem, Total War, Advance Wars, Slay the Spire (tactics-adjacent).
- **Key reference**: Sirlin, *Playing to Win* (competitive games: https://www.sirlin.net/ptw); Sid Meier's "interesting decisions"; Brathwaite and Schreiber, *Challenges for Game Designers* (strategy exercises); `04` for cost curves; `10` for multiplayer balance.

## 8. Puzzle

- **Fantasy**: insight; the "aha" moment; being clever.
- **Core loop**: observe the rules and state, form hypotheses, test, fail cheaply, learn the rule, apply, solve, escalate.
- **Key systems**: a small, consistent rule set; puzzle presentation; undo/reset; hint system; difficulty progression; tutorial through puzzles.
- **Design levers**:
  - **Rule set depth vs. puzzle count**: derive many puzzles from few rules (Baba Is You, The Witness, Portal).
  - Order: introduce a rule in isolation, develop, twist, combine (kishotenketsu pattern, `06` section 10).
  - Solution space (unique vs multiple solutions); red herrings; length to solve.
  - Feedback to avoid brute force and to encourage understanding.
- **Pitfalls**:
  - Guess-and-check or trial-and-error with a punishing reset.
  - Puzzles that rely on obscure knowledge or pixel hunting.
  - Pacing without breathers; difficulty spikes with no hint system.
  - Spoilers via hint system or online walkthroughs; consider optional hints and a "stuck" detector.
  - Reusing the same trick too often.
- **Study**: Portal, The Witness, Baba Is You, Tetris, Return of the Obra Dinn, Monument Valley, Lemmings, Zachtronics games (Opus Magnum), Outer Wilds (knowledge puzzles).
- **Key reference**: Jonathan Blow's and Marc ten Bosch's talks on puzzle design (search GDC Vault; not verified here); Rogers 2014; `05` for onboarding.

## 9. Survival and Crafting

- **Fantasy**: self-reliance; mastering a hostile environment; building something from nothing.
- **Core loop**: gather resources, craft tools and shelter, manage needs (hunger, thirst, temperature, health), explore for rarer resources, survive threats, expand base.
- **Key systems**: needs meters, crafting recipes and tech tiers, inventory with weight/slots, day-night and weather, base building, enemies/predators, resource regeneration, persistence/save.
- **Design levers**: need decay rates (pressure vs nagging), scarcity curve, crafting depth (recipe tree breadth), danger level by time/area, death penalty, base defense, co-op scaling.
- **Pitfalls**:
  - Meter babysitting (hunger/thirst as chores rather than decisions).
  - Grind walls without novelty; repeated gathering with no new verbs.
  - Early game brutal, mid game trivial (once the base is established, no tension); no endgame.
  - Crafting UI/inventory friction.
  - Griefing in multiplayer (offline raiding, base decay); server economy issues.
  - Unclear goals after the first hour (give an arc: tiers of environment, a final goal, or story).
- **Study**: Minecraft, Don't Starve, Subnautica, Valheim, The Long Dark, RimWorld (colony), Rust, Project Zomboid, The Forest, Frostpunk (city-builder with survival).
- **Key reference**: Schell 2019 (resource and economy lenses); `04` for faucets and sinks; `10` for co-op and griefing.

## 10. Horror

- **Fantasy**: confronting fear safely; vulnerability; dread and release.
- **Core loop**: explore cautiously, detect threat, avoid or confront it with limited resources, solve environmental puzzles, reach safe room, escalate.
- **Key systems**: vulnerability (limited ammo, slow or weak combat), information control (darkness, audio, camera), scarcity (resources), threat AI (stalker, director), safe zones/save points, sound design, pacing of tension and release.
- **Design levers**:
  - **Tension curve**: anticipation (dread) > startle (jump scare) > release; overuse of jump scares desensitizes.
  - **Power balance**: how often the player can fight; too strong removes fear, too weak causes frustration.
  - Information: what the player can see/hear; partial information is scarier than full reveal.
  - Threat design: predictable-enough to learn, unpredictable-enough to fear; avoiding "learn the pattern and the fear is gone".
  - Prospect-refuge inversion (`06` section 13).
  - Checkpoint/save spacing (Resident Evil's ink ribbons vs auto-save).
- **Pitfalls**:
  - Fear decay: monsters become familiar; vary and rotate threats, withdraw them.
  - Cheap deaths; trial-and-error stealth with long reload.
  - Over-reliance on jump scares; sound as the only scare.
  - Tank controls vs camera confusion used unintentionally.
  - Resource scarcity becoming trivial after learning the economy (director AI/dynamic resource drops to maintain tension).
  - Accessibility: motion sickness, flashing, loud audio; provide options and warnings (`08`).
- **Study**: Resident Evil 2 (original and remake), Silent Hill 2, Alien: Isolation, Amnesia: The Dark Descent, Dead Space, Outlast, Resident Evil 4 (action-horror), Five Nights at Freddy's, Phasmophobia (co-op), Darkwood.
- **Key reference**: Totten 2014 for spatial design of fear (prospect-refuge); Ernest Adams and others; study Alien: Isolation GDC talks on AI (search GDC Vault).

## 11. Simulation, Management and City-Builder

- **Fantasy**: stewardship; optimization; watching a complex system you shaped come alive.
- **Core loop**: observe the state, identify bottlenecks, allocate resources or build, watch results, adjust, expand.
- **Key systems**: a legible simulation (agents, resources, flows), UI overlays (heat maps, graphs), economy with faucets and sinks, growth and disaster events, time controls (pause, speed), goals/scenarios.
- **Design levers**: simulation depth vs legibility; feedback delay (how long before a decision shows results); emergent crises; scenario goals vs free play; unlocks pacing; difficulty via economy tuning.
- **Pitfalls**:
  - **Opaque simulation**: players cannot see why things fail (give overlays, causality tooltips, event logs).
  - Late-game idleness: everything balanced, nothing to do; add new challenges, scaling or objectives.
  - Death spirals that cannot be recovered; trivial solutions (dominant strategies, exploits).
  - Micromanagement overload; no automation; clunky UI at scale.
  - Performance with scale.
- **Study**: SimCity 2000 / Cities: Skylines, Factorio (logistics), Dwarf Fortress, RimWorld, Two Point Hospital, Planet Coaster, Frostpunk, Football Manager, Anno series, The Sims.
- **Key reference**: Sylvester 2013 *Designing Games* (RimWorld design thinking); Will Wright's "possibility space" talks (search GDC Vault); `03` on emergence; `04` on economy.

## 12. Sandbox

- **Fantasy**: freedom and expression; "make your own fun"; creation and experimentation.
- **Core loop**: set a self-directed goal, use tools and systems, observe results, iterate, share.
- **Key systems**: a rich, consistent toolset; a physics/rules layer that composes (multiplicative interactions); persistence; sharing/mods; optional goals and progression to bootstrap new players.
- **Design levers**: constraint vs freedom (purely open is intimidating; scaffold with soft goals); depth of interactions; tool power; onboarding that teaches possibilities; creative-mode vs survival-mode splits.
- **Pitfalls**:
  - "Blank page" problem: no direction for new players.
  - Tools without compelling output or feedback; creations that are not shareable.
  - Interaction combinatorics creating bugs and balance issues.
  - Content that lacks permanence or meaning; no reason to return.
- **Study**: Minecraft, Garry's Mod, Kerbal Space Program, Teardown, Besiege, Terraria, Dreams, Roblox (platform), Super Mario Maker (constrained creation).
- **Key reference**: Koster, *A Theory of Fun for Game Design* (patterns and learning; 2nd ed., O'Reilly 2013); Jenkins 2004 for emergent narrative (`07` section 3).

## 13. Deckbuilder and Card Games (CCG, LCG)

- **Fantasy**: building an engine from choices; clever combos; outplaying opponents with preparation and adaptation.
- **Core loop**:
  - **Deckbuilder roguelite** (Slay the Spire): fight with a deck, add/remove cards between fights, shape the deck, beat the boss.
  - **CCG** (Magic, Hearthstone, Legends of Runeterra): construct a deck from a collection, play against others, adapt to the meta.
  - **LCG** (Netrunner, Arkham Horror LCG, Marvel Champions): fixed-distribution expansions rather than random packs.
- **Key systems**: resource system (mana, energy, action points), card types and keywords, deck-construction rules, card draw and randomness management, rarity (CCG), meta-game and ban/rotation, collection/acquisition (monetization).
- **Design levers**:
  - **Cost curve and power budget** (`04`); keyword design (a few keywords with consistent meaning); synergy design (archetypes with support); variance control (mulligan, card filtering, draw smoothing).
  - Deck size and copy limits; rotation vs eternal formats.
  - For roguelite deckbuilders: card removal and thinning; scaling vs consistency; enemy intent display (informed decisions).
- **Pitfalls**:
  - Power creep in live CCGs; card-text bloat; unreadable boards.
  - Randomness that decides games (flood/screw without mitigation).
  - Pay-to-win collection perceptions; economy fairness (`09`).
  - Combos that end the game with no interaction; "non-interactive" archetypes.
  - For deckbuilders: always-take-every-card synergy-free decks; no meaningful skip decisions.
- **Study**: Magic: The Gathering (Mark Rosewater's design columns), Slay the Spire, Hearthstone, Legends of Runeterra, Netrunner, Marvel Snap, Balatro, Dominion (deckbuilding board game).
- **Key reference**: Mark Rosewater's "Making Magic" columns and "Lessons Learned" GDC talk (search; not verified here); Garfield's design philosophy; Engelstein and Shalev 2019 *Building Blocks of Tabletop Game Design* for deck-building mechanisms.

## 14. Idle and Incremental

- **Fantasy**: watching numbers grow exponentially; optimizing a machine; steady, low-effort progress and discovery of new layers.
- **Core loop**: spend currency on generators/upgrades, earn faster, hit a plateau, prestige/reset for a permanent multiplier, repeat at a higher scale.
- **Key systems**: exponential cost vs production curves, prestige layers (reset mechanics), offline progress, unlock/reveal pacing, automation, achievements, events.
- **Design levers**: cost growth exponent vs production multiplier (determines pace between purchases); prestige timing (when resetting becomes better than continuing); layer reveal cadence; active vs passive play balance; offline earnings cap.
  - Model it: use `scripts/design_calc.py` for progression curves; simulate time-to-next-purchase.
- **Pitfalls**:
  - Walls where the optimal action is "wait" with nothing new; prestige too early/late.
  - Number blindness (huge numbers without meaningful reveals); lack of decisions beyond "buy the next".
  - Monetization pressure through time-skips and manipulative friction (`09`).
  - Stale content after the first few layers; no meaningful long-term goal.
- **Study**: Cookie Clicker, Universal Paperclips (narrative reveal), Adventure Capitalist, Antimatter Dimensions, Realm Grinder, Clicker Heroes, Egg, Inc., NGU Idle.
- **Key reference**: Community write-ups on incremental game design (search; no single canonical reference); `04` for progression math and pity/prestige modeling.

## 15. Fighting

- **Fantasy**: one-on-one mastery; reading and outwitting a human opponent; execution of precise techniques.
- **Core loop**: neutral (spacing, poking, baiting), land a hit, convert to damage (combo), pressure (offense) or defend, reset to neutral.
- **Key systems**: frame data (startup, active, recovery, advantage on hit/block), hitboxes and hurtboxes, move properties (high/mid/low, throws), defense (block, parry, dodge), meter systems (super, drive), rollback netcode, input system, training mode.
- **Design levers**: character archetypes (rushdown, zoner, grappler, shoto); frame advantage and punish rules; damage/health scaling; comeback mechanics; combo systems (links, cancels, juggles); simplified inputs for accessibility vs execution barrier.
- **Pitfalls**:
  - Inaccessible to new players: unexplained systems, demanding execution, weak tutorial; the beginner-to-intermediate gap.
  - Dominant characters or unblockable/infinite setups.
  - Poor netcode (delay-based) for online play: rollback is now the expected standard.
  - Lack of training tools (frame data display, replays).
  - Excess comeback mechanics that devalue winning; stale meta with long patch cycles.
- **Study**: Street Fighter II / III: Third Strike / 6, Tekken 7/8, Guilty Gear Strive, Super Smash Bros. (platform fighter), Mortal Kombat, Skullgirls, Virtua Fighter.
- **Key reference**: Sirlin, *Playing to Win* (https://www.sirlin.net/ptw) and his writing on Yomi and fighting game design; community frame-data resources for specific games.

## 16. Racing

- **Fantasy**: speed, control at the limit, vehicle mastery or arcade thrill.
- **Core loop**: accelerate, brake, steer, find the line, overtake, finish, upgrade or unlock, next event.
- **Key systems**: vehicle handling model (arcade ... simulation spectrum), track design, AI opponents (including rubber banding), tuning/upgrade, game modes (race, time trial, drift), damage model, career progression, multiplayer.
- **Design levers**: handling model (grip, weight transfer, assists); track layout (corner variety, overtaking zones, risk/reward lines); AI difficulty and rubber banding; power-ups (kart racers); boost/drift reward; progression and unlocks; assist options.
- **Pitfalls**:
  - Handling that feels floaty or inconsistent; mismatch between assists and promised realism.
  - Rubber banding that feels unfair or erases skill; AI that cannot be raced against.
  - Track visibility problems (blind corners from camera, texture noise).
  - Power-up randomness that decides outcomes (mitigate with rank-based items).
  - Repetitive tracks; unrewarding career.
- **Study**: Mario Kart 8, Gran Turismo, Forza Horizon, Burnout 3: Takedown, Forza Motorsport, Need for Speed: Hot Pursuit, Wipeout, Trackmania, Assetto Corsa.
- **Key reference**: Swink 2009 (control and feel); Ian Bell and others on vehicle handling (search GDC Vault).

## 17. Sports

- **Fantasy**: playing as/managing the real sport; mastering team play; authentic competition or exaggerated arcade fun.
- **Core loop**: match play (read, pass, shoot, defend) within season/career/ultimate-team meta-structure.
- **Key systems**: input mapping that abstracts complex actions, animation systems, AI teammates and opponents, rules engine, physics for ball/puck, player ratings, career/franchise mode, online modes, roster updates.
- **Design levers**: sim vs arcade tuning; player ratings affecting outcomes; difficulty levels; skill-gap in controls (timing mechanics); sliders; momentum and comeback mechanisms; mode economy (card packs in ultimate-team modes, see `09`).
- **Pitfalls**:
  - Annual-release stagnation; roster-only updates.
  - Animation-priority systems that hide player control ("canned" outcomes).
  - Exploits against AI (e.g., a repeatable cross or pass that always scores).
  - Monetization pressure in card modes; fairness in online.
  - Complexity for newcomers; depends heavily on licensing.
- **Study**: FIFA / EA Sports FC, Madden NFL, NBA 2K, NHL series, Rocket League (sports reinvented), Tony Hawk's Pro Skater, Mario Tennis, Wii Sports.
- **Key reference**: Rocket League's design as a case of abstracting sports into a simple physical ruleset; `10` for competitive balance and matchmaking.

## 18. MOBA

- **Fantasy**: teamwork, hero mastery, strategic battle with many decisions and comebacks.
- **Core loop**: farm (last-hit minions), gain gold/XP, buy items, level abilities, fight in team skirmishes, take objectives (towers, neutral objectives), push to destroy the base.
- **Key systems**: a hero roster with distinct abilities, three-lane (or other) map with jungle, economy (gold/items), XP and leveling, objectives, vision (wards, fog of war), matchmaking and ranked ladder, draft/ban phase.
- **Design levers**: hero kits and counters; snowball vs comeback tuning (bounty gold, catch-up XP); map objectives and timers; item shops and recommended builds; game length (target typically 25-45 minutes, heuristic); roles (carry, support, jungle, etc.).
- **Pitfalls**:
  - High learning barrier (heroes x items x map); toxic communities (see `10`).
  - Snowballing losses that feel hopeless; no clean surrender or comeback valve.
  - Meta stagnation or hero imbalance; balance patches that upset communities.
  - Team dependency (one bad teammate decides the match).
  - Long match times; lack of onboarding.
- **Study**: League of Legends, Dota 2, Heroes of the Storm (accelerated), Smite, Pokemon UNITE, Wild Rift, Overwatch (hero-shooter adjacent).
- **Key reference**: Riot and Valve design blog posts (search); `10` for matchmaking, toxicity and competitive balance; `04` for hero balance.

## 19. Battle Royale

- **Fantasy**: survival against many; the thrill of being the last one standing; emergent stories from a shared, shrinking arena.
- **Core loop**: drop in, loot, move with the shrinking zone, fight or avoid, adapt to circle and loot, survive to the end.
- **Key systems**: large map with POIs, loot distribution and rarity, shrinking safe zone, matchmaking for large lobbies, movement/traversal, squads, ping and communication, respawn/revive mechanics (some titles), cosmetics monetization.
- **Design levers**: drop distribution and POI risk/reward (high loot = high risk); zone timing and damage; loot density and TTK; match length (heuristic: about 20-30 minutes); mobility tools; squad size; comeback mechanisms (revives, gulag).
- **Pitfalls**:
  - Dead time (looting and running) vs early death; low action density.
  - Camping and zone-based stalemates; third-partying frustration.
  - Hackers and cheating; server load.
  - Loot RNG deciding fights; skill-gap lockout for new players (bot lobbies).
  - Live-ops treadmill, map fatigue, power creep via seasonal weapons.
- **Study**: PUBG, Fortnite (building), Apex Legends (legends, ping system), Warzone (gulag), Call of Duty Blackout, Super Auto Pets-style auto battlers (adjacent), Tetris 99.
- **Key reference**: `10-multiplayer-and-social.md` for matchmaking and cheating; `06` section 12 for map design.

## 20. MMO

- **Fantasy**: living in a persistent world with others; identity, community, long-term growth.
- **Core loop**: quest/grind, level, gear, group content (dungeons, raids), economy participation, social ties, endgame cycles.
- **Key systems**: character progression and classes (tank/healer/damage roles), persistent world, quest content, group finder/raid design, economy and trading, guilds, crafting, PvP, seasons and expansions, live operations.
- **Design levers**: leveling speed and content cadence; gear treadmill and reset cycles; group role design; server vs shard population; economy sinks (repair, auction fees); social tools; subscription vs F2P (`09`).
- **Pitfalls**:
  - Empty world / population imbalance; content consumed faster than produced.
  - Endgame treadmill, power resets that make time feel wasted.
  - Inflation and bots; real-money trading.
  - Solo-vs-group friction; steep onboarding for new players into old games.
  - Toxicity in group content; high costs to run (servers, live team).
- **Study**: World of Warcraft (vanilla through current), Final Fantasy XIV (story-driven), EVE Online (player-driven economy and politics), Guild Wars 2, RuneScape, Lost Ark.
- **Key reference**: Richard Bartle, *Designing Virtual Worlds* (2003, New Riders) for MMO design theory and player types; `09` and `10`.

## 21. Metroidvania and Soulslike

- **Fantasy**: discovery and mastery in an interconnected world; ability growth that unlocks the map (Metroidvania); resilient perseverance against harsh challenge (Soulslike).
- **Core loop**:
  - **Metroidvania**: explore, find blocked paths, acquire abilities, return and unlock, expand the map, fight bosses.
  - **Soulslike**: fight methodically (stamina-based), die, retry, retrieve lost resource, discover shortcuts, beat the boss.
- **Key systems**: interconnected map with ability gates (`06` section 7), map UI with markers, movement abilities, combat (often 2D action for Metroidvania; stamina/commit-based for Soulslike), checkpoint system (bench/bonfire), death penalty (soul/currency recovery), boss design, builds (Soulslike).
- **Design levers**: gate placement and ability order; shortcut frequency; backtracking cost and fast-travel; checkpoint spacing; enemy telegraph readability; death penalty severity; boss attack patterns and phases; optional difficulty and accessibility (assist options, summons).
- **Pitfalls**:
  - Backtracking tedium; unclear where to go next; map without annotations.
  - Sequence breaks that soft-lock or bypass key content unintentionally.
  - Soulslike difficulty as an identity without fairness: unreadable telegraphs, long runbacks to bosses, damage from off-screen.
  - Over-clone of formula without a fresh hook (new traversal verb or setting).
  - Accessibility: "difficulty is the point" vs player inclusion; consider optional tools.
- **Study**: Super Metroid, Symphony of the Night, Hollow Knight, Ori and the Will of the Wisps, Dark Souls 1 (interconnection), Bloodborne, Sekiro, Elden Ring, Blasphemous, Dead Cells (hybrid).
- **Key reference**: `06-level-design.md` sections 7-8; Mark Brown's "Boss Keys" video series (YouTube; not verified here).

## 22. Narrative Adventure and Visual Novel

- **Fantasy**: living inside a story; choices of character and consequence; emotional or intellectual discovery.
- **Core loop**: read/explore, interact (talk, examine, solve), make choices, see consequences, progress the story.
- **Key systems**: dialogue and choice system, state variables, scene/chapter flow, puzzle or investigation mechanics (adventure), art/audio presentation, save/rewind, backlog.
- **Design levers**: branching structure (`07` section 6); frequency and weight of choices; interaction density (reading vs doing); puzzle difficulty and hint tools; length and episodic structure; replay incentives (route unlocks, flowcharts).
- **Pitfalls**:
  - Walking-simulator disengagement: too little interaction; pacing of exposition.
  - Illusory choices that break trust; unmanageable branching scope.
  - Obscure puzzle logic in point-and-click adventures ("moon logic").
  - Text-heavy UIs without accessibility options (font size, skip, log).
  - Shipping without a strong hook or marketing beyond story tagline.
- **Study**: Disco Elysium, Life is Strange, The Walking Dead (Telltale), Steins;Gate, Ace Attorney, Return of the Obra Dinn, Kentucky Route Zero, Firewatch, Danganronpa, 80 Days (inkle, built with Ink).
- **Key reference**: Ashwell 2015 (patterns); Jenkins 2004; `07-narrative-design.md`.

## 23. Party, Casual and Hyper-Casual

- **Fantasy**: instant, social fun with zero learning curve (party); effortless, satisfying micro-interactions (casual/hyper-casual).
- **Core loop**:
  - **Party**: short rounds (30-120 seconds), simple rules, quick scoring, rotating mini-games, laughter.
  - **Casual / match-3 / puzzle-casual**: simple input, levels with escalating goals, boosters, lives/energy.
  - **Hyper-casual**: one-touch mechanic, endless or very short levels, ad-driven monetization.
- **Key systems**: a one-sentence-explainable rule, accessible controls, short sessions, immediate feedback, scoring, variance that keeps outcomes close, local multiplayer support, monetization (ads, IAP; see `09`).
- **Design levers**: round length; skill floor/ceiling; luck vs skill ratio (party games lean toward luck and catch-up mechanics so all can win); difficulty ramp; reward timing; session hooks (daily rewards, events); creative variation across mini-games.
- **Pitfalls**:
  - Rules that need an explanation (kills party flow); player elimination (spectators bored).
  - Hyper-casual: shallow retention; ad overload; clone saturation; reliance on user-acquisition cost.
  - Match-3/casual: difficulty walls designed to sell boosters (ethics; `09`).
  - Accessibility: color-only information; small touch targets; length of tutorial.
- **Study**: Mario Party / WarioWare, Jackbox Party Pack, Overcooked (co-op chaos), Fall Guys, Candy Crush Saga (monetization case; critique), Stardew Valley (cozy), Among Us, Wii Sports (accessibility), Flappy Bird (hyper-casual).
- **Key reference**: `09-monetization-and-live-ops.md` for ethics; `05` for onboarding in seconds.

## 24. Rhythm

- **Fantasy**: playing music; synchronization with sound; flow state through rhythmic precision.
- **Core loop**: read note stream, execute timed inputs, receive accuracy feedback, build combo, finish song, rank, unlock.
- **Key systems**: note charts, timing windows (perfect/great/good/miss), latency calibration (audio/visual/input), scoring and combos, difficulty tiers, song library, peripheral support (controllers, guitars, touch).
- **Design levers**: timing window width; note density; chart design (patterns that match the music vs random); scrolling speed and readability; judgment feedback; calibration tools; unlock cadence; licensed vs original music.
- **Pitfalls**:
  - **Latency** unaccounted for (audio/visual/input offsets): calibration is mandatory.
  - Charts that do not follow the music's phrasing, or have unreadable patterns.
  - Difficulty cliffs between tiers; punishing fail states in early songs.
  - Limited song catalog; licensing cost and expiry.
  - Accessibility: flashing visuals, audio-only reliance; offer visual cues/vibration where possible.
- **Study**: Guitar Hero / Rock Band, Dance Dance Revolution, Beat Saber, Rhythm Heaven, Crypt of the NecroDancer (rhythm roguelike), Hi-Fi Rush, Patapon, osu!, Sayonara Wild Hearts.
- **Key reference**: Swink 2009 (responsiveness and timing); `03` for feedback layering.

## 25. Tabletop Board Games

Different medium, same craft: components and rules replace code; players are the "engine", so rules clarity and downtime are central. Tabletop physicality and social dynamics shape design. See `01` for process and `12` for playtesting (blind playtests are the tabletop standard).

### 25.1 Euro vs Ameritrash (and the modern landscape)
| | Eurogame (Euro) | Ameritrash / thematic | Modern reality |
|---|---|---|---|
| Emphasis | Mechanisms, optimization, resource management | Theme, narrative, conflict, luck | Most modern games blend; "hybrid" or "Eurogame with theme" |
| Player interaction | Indirect (competition for resources, blocking) | Direct (combat, take-that) | Wide spectrum |
| Luck | Low to moderate | Higher (dice, cards) | Tuned per audience |
| Elimination | Rare; everyone plays to the end | Possible | Player elimination widely considered poor design |
| Scoring | Victory points, hidden until the end | Last standing or objectives | Varies |
| Examples | Catan, Agricola, Puerto Rico, Carcassonne | Risk, Talisman, Descent, Cosmic Encounter (take-that) | Terraforming Mars, Gloomhaven |

The labels are informal and somewhat contested; use them as shorthand for design tendencies, not as strict categories.

### 25.2 Core mechanism families (see Engelstein and Shalev 2019)
| Mechanism | Fantasy | Core decision | Design levers | Pitfalls | Study |
|---|---|---|---|---|---|
| **Worker placement** | Allocating scarce labor | Which action space to claim and when | Number of spaces, blocking intensity, action tiers, start-player order, round count | Analysis paralysis; kingmaking; "first player" advantage; spaces that are never worth it | Agricola, Lords of Waterdeep, Viticulture, Everdell |
| **Engine building** | Compounding growth | What to invest in for future returns | Cost curve, synergy density, game length (cap runaway), tempo/race to end | Runaway leader; multiplayer solitaire; non-interactive; "build the engine, then nothing" | Splendor, Wingspan, Terraforming Mars, Race for the Galaxy, Dominion |
| **Deck building** | Crafting a deck from a shared market | What to buy, what to trim | Market refresh, card synergy, ending condition | Snowballing; one-dominant-strategy (Big Money-type) | Dominion, Clank!, Ascension |
| **Area control / majority** | Dominating territory | Where to commit limited units | Scoring timing, combat resolution, alliances | Runaway leader, king-making, dogpiling | Risk, El Grande, Root, Twilight Struggle |
| **Drafting** | Selecting from limited options | Take best vs deny | Hand size, pass direction | Downtime if analyzing; imbalanced cards | 7 Wonders, Sushi Go, Magic draft |
| **Tile placement** | Spatial puzzle | Where to place | Scoring rules, tile distribution | Luck of the draw | Carcassonne, Azul, Patchwork |
| **Dice allocation / push-your-luck** | Risk and tension | When to stop | Probability, safety nets | Frustrating swings | Can't Stop, Yahtzee-likes, Quacks of Quedlinburg |
| **Cooperative** | Shared struggle | Joint planning | Difficulty scaling, hidden info, traitor | Quarterbacking (alpha player dominates) | Pandemic, Spirit Island, Gloomhaven |
| **Hidden role / social deduction** | Bluff and deduce | Whom to trust | Role balance, elimination avoidance | Early elimination; groupthink | Werewolf, Avalon, Secret Hitler |
| **Legacy / campaign** | Evolving game that changes permanently | Choices across sessions | Permanent changes (stickers, tearing cards), story arcs, scenario structure | Locked-in early mistakes, replayability low, group commitment needed | Risk Legacy, Pandemic Legacy, Gloomhaven (campaign) |

### 25.3 Tabletop design levers and pitfalls
- **Rules economy**: fewer rules with deep consequences beat many rules; target a short rulebook and a teach time (heuristic: teach in 5-10 minutes for family games, 20-30 for heavy games).
- **Downtime**: minimize time between a player's turns (simultaneous actions, short turns, interaction on others' turns). Downtime is the top tabletop killer.
- **Player count scaling**: test 2, 3, 4, 5 separately; many games have a "sweet spot" and break at extremes.
- **Endgame and tempo**: games should end when they are at their best; set a clear end trigger and avoid long tails; track "game length vs number of decisions".
- **Catch-up / runaway control** (SKILL.md section 4.5): negative feedback in scoring, hidden information, or turn order balancing.
- **Kingmaking and player elimination**: avoid designs where a losing player decides the winner or sits out.
- **Components and UX**: iconography, player aids, clear board state, color-blind-safe components (`08`).
- **Solo and co-op modes**: automata and scripted opponents add reach.
- **Legacy design**: plan the arc, include "oops" protections (extra stickers), ensure the base game stays fun after changes, and pre-playtest the campaign with real destructive state changes.
- **Playtest**: blind playtests (players learn only from the rulebook) are the gold standard for rules clarity; track where players ask questions.
- **Study resources**: BoardGameGeek design forums and "Board Game Design Lab" style resources (search); Engelstein and Shalev 2019 for mechanism catalog; Engelstein's *Game Production* and *Achievement Relocked* (psychology) for tabletop-adjacent practice.

## 26. Genre Hybrids and Choosing a Genre

### 26.1 Hybridization patterns
| Pattern | Example | Why it works |
|---|---|---|
| Genre + roguelite loop | Hades (action), Slay the Spire (card), Dead Cells (Metroidvania) | Replayability from run structure |
| Genre + deckbuilding | Balatro (poker + roguelite), Monster Train | Familiar rules with build variety |
| Genre + survival/crafting | Subnautica (adventure), Valheim (action), Frostpunk (city-builder) | Persistent pressure and ownership |
| Genre + auto-battler | Vampire Survivors (shmup-lite), TFT | Low input, high strategy |
| Shooter + extraction | Escape from Tarkov, Hunt: Showdown | High-stakes loot risk |
| Cozy + sim | Stardew Valley, Animal Crossing | Low-pressure routine |

### 26.2 How to pick or position a genre
1. Start from the **player fantasy**, then find the genre(s) that deliver it (`01`).
2. Identify the genre's **contract** (expected features and quality bars). Note each as honor, twist or omit.
3. Pick one **innovation axis** (one new thing, not five).
4. Check **market and scope**: genres vary in saturation, audience size, production cost (an MMO is not a solo-dev project).
5. Define what you will **not** do.
6. Prototype the core loop and check for genre-specific failure modes listed above.

### 26.3 Quick genre diagnostics
| Symptom | Genre-aware cause to check |
|---|---|
| Platformer feels bad | Coyote time, jump buffering, variable jump, camera |
| Shooter feels weak | Hit feedback, audio, recoil, enemy flinch |
| Roguelite is stale after 5 runs | Variance too low, few build-defining choices, meta too deterministic |
| Strategy game decided early | Snowball with no comeback; scout/information issues |
| Survival game boring after base | No escalation, no next tier |
| Card game solved | Cost curve outlier; one archetype dominates |
| Idle game stalls | Plateau without a new layer; prestige timing |
| Horror not scary | Too much power, over-familiar monster, too-easy saves |
| Board game drags | Downtime, too many rules, end-condition tail |

## 27. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Books**
- Swink, S., 2009, *Game Feel: A Game Designer's Guide to Virtual Sensation*, Morgan Kaufmann.
- Schell, J., 2019, *The Art of Game Design: A Book of Lenses*, 3rd ed., CRC Press.
- Rogers, S., 2014, *Level Up! The Guide to Great Video Game Design*, 2nd ed., Wiley.
- Adams, E. and Dormans, J., 2012, *Game Mechanics: Advanced Game Design*, New Riders.
- Sylvester, T., 2013, *Designing Games: A Guide to Engineering Experiences*, O'Reilly Media.
- Koster, R., 2013, *A Theory of Fun for Game Design*, 2nd ed., O'Reilly Media.
- Bartle, R., 2003, *Designing Virtual Worlds*, New Riders.
- Engelstein, G. and Shalev, I., 2019, *Building Blocks of Tabletop Game Design: An Encyclopedia of Mechanisms*, CRC Press.
- Brathwaite, B. and Schreiber, I., 2009, *Challenges for Game Designers*, Charles River Media.
- Totten, C. W., 2014, *An Architectural Approach to Level Design*, CRC Press.

**Websites and articles (URLs verified)**
- Sirlin, D., *Playing to Win*: https://www.sirlin.net/ptw
- Roguelike (includes the Berlin Interpretation summary), Wikipedia: https://en.wikipedia.org/wiki/Berlin_Interpretation
- The Level Design Book: https://book.leveldesignbook.com/
- Ashwell, S. K., 2015, "Standard Patterns in Choice-Based Games": https://heterogenoustasks.wordpress.com/2015/01/26/standard-patterns-in-choice-based-games/
- Jenkins, H., 2004, "Game Design as Narrative Architecture": https://www.electronicbookreview.com/essay/game-design-as-narrative-architecture/

Notes: statements marked "heuristic" are rules of thumb. Talks mentioned as "search GDC Vault" were not verified here and should be checked before being cited in a deliverable; the games listed are recommendations for the reader to play, not sources.
