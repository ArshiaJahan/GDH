# Narrative Design

## Table of Contents

1. [What Narrative Design Is](#1-what-narrative-design-is)
2. [Story Structures](#2-story-structures)
3. [Embedded vs Emergent Narrative](#3-embedded-vs-emergent-narrative)
4. [Environmental Storytelling](#4-environmental-storytelling)
5. [Ludonarrative Harmony and Dissonance](#5-ludonarrative-harmony-and-dissonance)
6. [Branching Structures (Ashwell's Patterns)](#6-branching-structures-ashwells-patterns)
7. [Choice Design and Consequences](#7-choice-design-and-consequences)
8. [Quality-Based Narrative and Storylets](#8-quality-based-narrative-and-storylets)
9. [Character Design and Companions](#9-character-design-and-companions)
10. [Dialogue Systems and Tools](#10-dialogue-systems-and-tools)
11. [Barks and Reactive Lines](#11-barks-and-reactive-lines)
12. [Lore Delivery](#12-lore-delivery)
13. [Player Agency vs Authored Story](#13-player-agency-vs-authored-story)
14. [Writing for Games](#14-writing-for-games)
15. [Narrative in Systemic Games: Case Studies](#15-narrative-in-systemic-games-case-studies)
16. [Process, Documents and Scoping](#16-process-documents-and-scoping)
17. [Checklists and Common Pitfalls](#17-checklists-and-common-pitfalls)
18. [References](#18-references)

---

## 1. What Narrative Design Is

**Narrative design** is the discipline of making story and game systems work as one experience. It decides *how* story is delivered through play: structure, pacing, choices, reactivity, tools, and the dependencies between narrative and every other discipline.

### 1.1 Narrative designer vs writer
| | Narrative designer | Writer |
|---|---|---|
| Primary output | Story structure, delivery systems, quest/mission narrative flow, dialogue logic, reactivity specs, content pipelines | Prose, dialogue, characters' voices, lore text, scripts |
| Works with | Game designers, level designers, UI, audio, engineers, localization | Narrative designer, voice director, editors, localization |
| Core question | "How does the player experience and affect the story through play?" | "What does this character say and how does it sound?" |
| Failure mode | Beautiful story the mechanics ignore | Great lines in a structure that can't deliver them |

In small teams one person does both. Roles overlap, titles vary by studio (industry practice). Responsibilities to name explicitly on any project:
- Who owns **story structure and pacing**?
- Who owns **the voice** of each character and the style guide?
- Who owns **narrative tooling** and implementation (dialogue scripting, state variables)?
- Who owns **cross-discipline requests** (a level needs a reveal beat; a system needs a bark set)?
- Who owns **localization and VO constraints**?

### 1.2 Principles
1. **Story serves the play experience, and play serves the story's emotional goal.** Decide which leads (story-first, systems-first, or hybrid) and be consistent.
2. **The player is a protagonist, not an audience.** Maximize moments where the player's actions carry narrative weight.
3. **Use the cheapest delivery that works.** A prop in a room beats a cutscene; a cutscene beats a text log, if the beat matters.
4. **Interactivity is the medium's strength.** Prefer to have the player do the story event (open the door, hold the hand, make the call) rather than watch it.
5. **Scope is the enemy of branching.** Content cost grows combinatorially; design for reactivity that is cheap (flags, reuse, callbacks) over bespoke branches.
6. **Narrative is a dependency chain.** Locks, quests, levels, VO, animation and localization all depend on the script; freeze early, iterate late (see section 16).

## 2. Story Structures

### 2.1 Three-act structure
The Western baseline: **Act I** setup (status quo, inciting incident, commitment), **Act II** confrontation (rising complications, midpoint reversal, low point), **Act III** resolution (climax, denouement). Useful as a pacing scaffold for campaigns: first ~25% setup, ~50% complications, ~25% climax and resolution (heuristic proportions, borrowed from screenwriting).

Applying it to games:
- Map act breaks to **gameplay escalations** (new verbs, new world, new power level), not only plot events.
- The **midpoint** should change the game's question (new ability, a reveal, a shift of goal).
- The **climax** should test the verbs the player has been practicing.

### 2.2 The Hero's Journey (monomyth) and critique
Campbell's monomyth (*The Hero with a Thousand Faces*, 1949), adapted by Vogler (*The Writer's Journey*) for screenwriters: ordinary world, call to adventure, refusal, mentor, threshold crossing, tests/allies/enemies, ordeal, reward, road back, resurrection, return with the elixir.

Strengths: matches how many games pace growth (power curve, mentor, trials, boss, return).

Critique and cautions:
- It is a **descriptive pattern, not a recipe**; following it step by step produces predictable stories.
- It assumes a **single, mostly male-coded, chosen-one protagonist** and a linear arc, which fits poorly with ensemble casts, systemic games, or non-heroic themes.
- The "Chosen One" trope can **clash with player agency** (why was I special?) and with multiplayer/persistent worlds.
- Treat it as one lens among others; combine with character-driven structure (want vs need, flaw, arc), or non-conflict structures like kishotenketsu.

### 2.3 Kishotenketsu
Four beats: **ki** (introduction), **sho** (development), **ten** (twist), **ketsu** (reconciliation), with a twist rather than a conflict as the engine (Kishotenketsu, Wikipedia). In games, useful for:
- Puzzle and level sequences (see `references/06-level-design.md` section 10).
- Short quests, vignettes and character moments where the twist recontextualizes earlier information.
- Games where conflict is not the core fantasy (cozy games, exploration games).

### 2.4 Other useful structures
| Structure | Idea | Game fit |
|---|---|---|
| **Five-act (Freytag)** | Exposition, rising action, climax, falling action, resolution | Tragedies, linear action |
| **Save the Cat beats** (Snyder) | Screenwriting beat sheet | Pacing aid for linear campaigns; formulaic if overused |
| **Episodic / seasonal** | Self-contained episodes with a thin arc | Telltale-style, live-service stories |
| **Mystery / investigation** | Reveal order is the structure; player assembles truth | Return of the Obra Dinn, Disco Elysium, Her Story |
| **Anthology / vignette** | Many short stories in one framework | Roguelikes, sandbox, Hades-style repeatable runs |
| **Ensemble / party** | Multiple arcs with shared events | RPGs with companions |
| **Frame story** | Narrator/memory structure | Bastion, Pyre-style narration |

### 2.5 Structural questions to answer for any game
1. What is the **central dramatic question**? ("Can I save X?")
2. What does the **player want** (goal) vs the **character want** and **need**?
3. What are the **stakes** and what is the **cost** of failure?
4. Where do the **reveals** land relative to gameplay peaks?
5. What is the **ending's relationship to the player's choices**: fixed, tiered, or branching?

## 3. Embedded vs Emergent Narrative

Henry Jenkins, in "Game Design as Narrative Architecture" (2004), reframes games as **spaces for storytelling** rather than stories themselves: designers build narrative architecture rather than tell stories directly. He identifies four modes in which games can relate to narrative: **evoked narratives** (the game evokes prior stories, such as film or myth), **enacted narratives** (the player acts out a story structure through movement in space), **embedded narratives** (information placed in the environment for the player to piece together), and **emergent narratives** (stories that arise from the game's rules and the player's interaction). Treat the specific category names as Jenkins's framework; check the essay for exact wording.

### 3.1 Embedded (authored) narrative
- Story content is **prewritten** and unlocked by progress: cutscenes, scripted events, audio logs, set dressing.
- Strengths: control over pacing, quality, theme, emotional beats; production predictability.
- Risks: passive consumption, ludonarrative dissonance, repetition when the player replays, linear feel.

### 3.2 Emergent narrative
- Story arises from **systems and player behavior**: The Sims, Dwarf Fortress, RimWorld, XCOM (named soldiers), Crusader Kings, multiplayer sandbox.
- Strengths: personal stories, replayability, player authorship, scale per content dollar.
- Risks: story is unreliable, pacing uncontrolled, themes diffuse; players must do interpretive work.
- Enablers: **attachable entities** (named, customized characters), **persistent consequences**, **legible simulation** (the player can read why things happened), **narrative framing** (events described in story terms), and **a storyteller/director system** that paces events.

### 3.3 Hybrid designs
Most great games are hybrid: an authored frame with systemic generation inside, or systemic play with authored beats injected (see section 15).

| Approach | Authored | Systemic |
|---|---|---|
| Hades | Cast, voice, plot, relationship arcs | Run structure, boons, reactive dialog selection |
| RimWorld | Setting, events, difficulty storytellers | Colonist behavior, injuries, relationships |
| Disco Elysium | Case, cast, text | Skill checks, internal voices, thought states |
| Skyrim-type RPG | Main quest, faction stories | Radiant quests, NPC schedules |

### 3.4 Design guidance
1. Decide which stories the **designers must tell** and which stories **players should tell**. Don't try to do both everywhere.
2. For emergent play, supply **story fuel**: strong character traits, relationships, grudges, injuries, memories, names and an event log.
3. For authored play, supply **player expression**: ways to react, to bring their own meaning (dialogue stance, build, loadout, small choices with echoes).
4. Use **systems to retell**: a recap screen, a "chronicle", photo mode, or a log, so the player can narrate what happened.

## 4. Environmental Storytelling

Telling story through **space, props and the arrangement of things**, so the player infers what happened. Jenkins calls this embedded narrative (section 3); see also level hand-off in `references/06-level-design.md` section 14.

### 4.1 Techniques
| Technique | Example idea |
|---|---|
| **Aftermath scenes** | A barricaded door, scratch marks inside, a note |
| **Contrasts** | A child's drawing in a bunker |
| **Trails** | Items that imply a journey (bags, bandages, a path of blood) |
| **Juxtaposition** | Luxury beside decay |
| **Absence** | Missing portraits, empty beds |
| **Repetition across the level** | A symbol or slogan whose meaning the player decodes |
| **Cause and effect chains** | Props that imply sequence (an overturned table, then an open window, then a rope) |
| **Audio logs / documents** | Text delivering what a prop can't; keep short |

### 4.2 Rules
1. **Readable in a glance** (1-5 elements per scene).
2. **Consistent with the world's logic** (who lived here, when, what happened).
3. **Ask a question and give a clue** rather than state the answer.
4. **Reinforce the theme** and the mechanics (a stealth game's props tell about surveillance).
5. **Support multiple readings** where possible; resolve key facts in at least two redundant places because players miss things.
6. **Don't hide critical plot in optional props**; use them for depth.
7. **Reward lingering without punishing rushing.**

## 5. Ludonarrative Harmony and Dissonance

**Ludonarrative dissonance** is a term coined by Clint Hocking (2007) in discussing BioShock: the conflict between what the game's **mechanics** tell the player to do (self-interested play maximizes power) and what the **narrative** tells the player to value (selflessness, cooperation). Players noticing the contradiction feel the game is at odds with itself (Hocking 2007).

**Ludonarrative harmony** is the reverse: mechanics and story say the same thing.

### 5.1 Types of mismatch
| Mismatch | Example pattern |
|---|---|
| **Verbs vs themes** | A story about pacifism in a game rewarding killing |
| **Character vs player behavior** | A "reluctant hero" who massacres hundreds in play |
| **Stakes vs systems** | "Urgent" quest with no time pressure; infinite resurrection |
| **Tone vs feedback** | A tragic moment with comedic physics or UI pops |
| **Agency vs plot** | Plot requires a capture the player's skills could prevent |

### 5.2 Fixes
1. **Align verbs with theme.** Choose mechanics that physically express the story's idea (e.g., a game about fragility has fragile resources; a game about guilt makes repeated actions costly).
2. **Narrate the mechanics.** Explain mechanical behavior in-fiction (respawns, saving, power levels) or lean into the fourth wall.
3. **Make dissonance meaningful.** Sometimes dissonance is the point (Spec Ops: The Line is often cited as using it to provoke reflection). Do it deliberately and signal intent.
4. **Constrain player power to match story.** If the hero is vulnerable, the player should be.
5. **React to what players actually do.** Acknowledge in dialogue and world state the kills, deaths, failures, or skips.
6. **Choose combat pacing and fiction together** (a stealth protagonist should have non-lethal options valued by the systems).

### 5.3 Test
For each major story claim ("the hero is a pacifist", "time is short", "this place is dangerous"), ask: **what in the mechanics proves it?** If nothing does, either change the mechanic, the claim, or the framing.

## 6. Branching Structures (Ashwell's Patterns)

Sam Kabo Ashwell's "Standard Patterns in Choice-Based Games" (2015) catalogs structural patterns for choice-based narratives, each with different content-cost, agency, and authorial-control tradeoffs. The list below covers the main patterns named in that essay (confirm details and additional patterns, such as hub-and-spoke variants, in the source).

| Pattern | Structure | Pros | Cons | When to use |
|---|---|---|---|---|
| **Time cave** | Every choice branches and never rejoins | Strong consequences, feels like real divergence | Exponential content cost; most paths unseen | Very short pieces, gamebook-like experiments |
| **Gauntlet** | A linear spine with side-branches that mostly lead to failure/early ends; success continues | Cheap, tense; clear stakes | Little real choice; can feel punishing | Survival/peril sequences, horror |
| **Branch and bottleneck** | Branches diverge then reconverge at fixed points | Manageable cost; keeps authorial control; allows variation within each chapter | Choices can feel cosmetic; reconvergence may be obvious | Most narrative adventures and CRPG quests |
| **Quest** | Player must complete a set of sub-goals in any order, then proceeds | Flexible ordering; replay variety | Requires state tracking; some combos untested | Fetch-a-set, mystery-clue structures |
| **Open map** | Player moves among locations with free choice of order | Freedom, exploration, player pacing | Hard to control narrative tension; content must be modular | Investigation, open-world quests |
| **Sorting hat** | An early series of choices assigns the player to a path (class, faction, personality) | Replay value, identity, affordable "branches" | Path may feel locked; choices that feel like a quiz | Origin stories, faction games |
| **Loop and grow** | Repeating a structure where options or text change on each loop based on state | Strong sense of progression and mastery; cheap | Needs good state design; repetition risk | Time loops, daily-cycle games, roguelikes with story |
| **Floating modules** | Self-contained story pieces served in an order determined by state and conditions | Highly scalable; content can be added; storylet-compatible | Weak overall arc without scaffolding | Live games, episodic reactive worlds, quality-based narrative |

Practical use:
1. **Choose the pattern per section, not per game.** A game may be a branch-and-bottleneck overall, with a gauntlet in the horror chapter and an open map hub.
2. **Budget content per branch.** Count the lines/scenes/VO per path; time cave budgets explode.
3. **Prefer reconvergence with residue**: paths rejoin, but the state (flags, relationships, items, memories) alters later dialogue, scenes and options.
4. **Make variation visible**: show the player evidence that their choice mattered (a different NPC reaction, a scar, a changed location).
5. **Plan for the 80% player**: the average player experiences only one path; ensure the main path is strong and the branches reward replay with different perspective rather than just more content.

## 7. Choice Design and Consequences

### 7.1 Types of choices
| Type | Description | Cost | Effect |
|---|---|---|---|
| **Expression** | Tone/flavor; same outcome | Low | Roleplay, voice |
| **Cosmetic reactivity** | Minor different reaction later | Low | Acknowledgment |
| **Tactical/resource** | Changes options or resources | Medium | Gameplay consequences |
| **Relationship** | Changes NPC stance | Medium | Emotional stakes |
| **Structural/world state** | Changes available content or the world | High | Major divergence |
| **Dilemma** | No right answer; values in conflict | Medium | Thought and discussion |
| **Illusory** | Appears impactful, but outcome is fixed | Low | Risk: reveals fakery |

### 7.2 What makes a choice interesting
Apply the general decision checklist (SKILL.md section 4.4) to narrative: options must be **distinct**, **comprehensible**, with **foreseeable-in-kind** (not exact) consequences, and each should **reflect values** the player cares about. Weak choices: "obviously good vs obviously evil", "which dialogue gets the same result", choices with unreadable button text.

### 7.3 Principles
1. **Telegraph the stakes.** The player should know a choice matters (a UI cue, an NPC emphasis) if you want them to deliberate. The opposite, unannounced consequence, supports a "life is like that" tone but risks feeling punitive.
2. **Options must be written in the player's voice, and predictable.** The paraphrased dialogue wheel problem: the player expects to say X and the character says something harsher. Give a short preview or the exact line.
3. **Avoid false binaries**: add a refusal, a delay, a "ask more" option when natural.
4. **Moral dilemmas need competing goods** (loyalty vs justice), not good vs evil.
5. **Delay and echo.** A consequence that arrives later, referencing the earlier choice, creates the strongest sense of agency. Keep a ledger of "callbacks".
6. **Make consequences proportional and persistent**: small choices produce small echoes; big ones reshape.
7. **Failure is content.** Failing a check or losing a fight should open a different story, not a game-over (Disco Elysium and Fallen London use this "fail forward" approach).
8. **Don't punish the choice, punish the commitment**: let players change course at costs rather than permanent lock-outs unless intended.
9. **Support multiple playstyles** (talk, sneak, fight) for key moments, if scope allows.
10. **Track state simply.** Use a small set of well-named variables (flags, counters, relationship scores). Document each variable: who sets it, who reads it.

### 7.4 Consequence ledger (practical tool)
A table in the narrative doc:

| Choice ID | Where | Options | State set | Immediate reaction | Later callbacks | Cost |
|---|---|---|---|---|---|---|

Review it to ensure each important choice has at least one callback and that no variable is set but never read.

## 8. Quality-Based Narrative and Storylets

**Quality-based narrative (QBN)** is a structure, developed by Failbetter Games for *Fallen London*, in which content is organized as small units gated by **qualities** (named state variables: stats, items, relationships, progress). Content appears when the player's qualities satisfy its conditions. Emily Short has written extensively on it as "storylets" (Short 2019).

### 8.1 Core elements
| Element | Meaning |
|---|---|
| **Quality** | A named variable (e.g., Suspicion 3, Nightmares 5, "Knows the Secret"). Can be a stat, item, progress track, or boolean |
| **Storylet** | A self-contained chunk of narrative with **preconditions** (qualities required), content, choices, and **effects** (quality changes) |
| **Deck / pool** | A set of storylets from which the game draws eligible ones (random or prioritized) |
| **Salience / priority** | A rule determining which eligible storylets are offered |
| **Challenge** | A check against a quality with probabilistic or deterministic result |

### 8.2 Why designers use it
- **Scalable and modular** (floating modules, section 6): authors add content without rebuilding a tree.
- **Reactive**: content responds to many state variables, giving reactivity at low per-branch cost.
- **Supports long-running live narrative** where the story grows in installments.
- **Good for emergent combos** of themes: the combination of qualities makes the narrative feel personal.

### 8.3 Pitfalls and mitigations
| Pitfall | Mitigation |
|---|---|
| **No overall arc** (a grind through disconnected content) | Add scaffolding: story "spines" via gating qualities, milestone storylets, deliberate escalation |
| **Opaque conditions**; players don't know why content is missing | Show locked options or hints; make qualities visible |
| **Qualities explode** | Naming conventions, ownership, deprecation |
| **Repetition** | Large pools, cooldowns, "seen" flags, weighted selection |
| **Tone inconsistency from independent authors** | Style guide, editorial pass, shared voice samples |
| **Hard to test** | Tooling to simulate states, coverage reports, "what can fire now?" views |

### 8.4 Variants
- **Salience-based dialogue selection**: pick the most specific matching line (Left 4 Dead's response rules and many bark systems work like this; the Valve talk "Dynamic Dialog" by Elan Ruskin describes it; I have not verified a URL for it here, so find it via the GDC Vault).
- **Priority queues** (Hades-style): each line has requirements and a priority; the game plays the highest-priority eligible line (see section 15).
- **Tools**: Ink (inkle), Yarn Spinner, ChoiceScript, Twine, Articy:draft, Fungus; custom data-driven systems.

## 9. Character Design and Companions

### 9.1 Character fundamentals
- **Want / Need / Flaw / Fear / Contradiction**: the want drives action; the need (often unknown) drives growth; the flaw blocks; the contradiction makes them human.
- **Distinct voice**: vocabulary, rhythm, humor, topics. Test: cover the speaker name; can you tell who speaks?
- **Silhouette and role in the cast**: each character should create a different reaction in the protagonist (foil, mirror, antagonist, mentor).
- **Verbs**: what can this character *do* in the game? A companion who is only talk is cheaper but less embodied.

### 9.2 Player-character types
| Type | Description | Pros | Cons |
|---|---|---|---|
| **Blank slate** | Unvoiced, undefined | Projection, flexibility | Weak emotional beats |
| **Defined protagonist** | Strong personality (Geralt, Kratos) | Strong writing, voice, arcs | Player may disagree with choices |
| **Defined with player stance** | Fixed identity, variable attitude (Mass Effect's Shepard, Hades' Zagreus) | Balance | Needs reactive writing |
| **Created by the player** | Backstory, origin, class | Ownership | Requires many variants |

### 9.3 Companions
Companions deliver emotion, exposition, tactics and reactivity. Design them across **three layers**:
1. **Gameplay role**: what they add (tank, healer, hacker, scout), how controllable, how smart.
2. **Personality and arc**: want/need, their relationship to the protagonist, personal quest.
3. **Reactivity**: comments on locations, events, choices; banter between companions; approval/loyalty states.

Checklist:
- [ ] AI does not steal, block, or ruin player agency (positioning, aggro, stealth).
- [ ] Banter is context-aware and has cooldowns.
- [ ] Companions disagree with each other and with the player at times.
- [ ] Personal quests connect to the main theme.
- [ ] A relationship system with legible effects (not only hidden approval numbers) and fail states that are story, not punishment.
- [ ] Their absence is handled (dead, dismissed) without breaking content.
- [ ] Writing budget accounts for N companions x M locations x K reactions: make reactions systemic (tags) instead of bespoke where possible.

### 9.4 Antagonists
- A strong antagonist **opposes the protagonist's theme** and has a coherent logic.
- In games, the antagonist also appears as **mechanics** (their systems restrain or hunt the player); allow the player to feel their presence before the confrontation.

## 10. Dialogue Systems and Tools

### 10.1 Dialogue interface patterns
| Pattern | Notes |
|---|---|
| **Dialogue tree (choose lines)** | Clear, writer-controlled; heavy to author |
| **Dialogue wheel / paraphrase** | Fast, cinematic; risk of mismatch between summary and spoken line |
| **Keyword / topic list** | Exploration-friendly (Morrowind, Disco Elysium's topics); lots of authoring |
| **Skill-gated options** | Options appear only if skill/quality is high; make locked options visible when useful |
| **Timed choices** | Add pressure; consider accessibility (pauses, longer timers options) |
| **Silent / non-verbal choices** | Actions as dialogue (hold hand, leave) |
| **Free text / LLM-driven** | Experimental; requires strong guardrails for canon, tone, safety, and testing |

### 10.2 Tooling
| Tool | Strength |
|---|---|
| **Ink** (inkle) | Narrative scripting language with weave syntax, variables, conditional logic; embeds in Unity/Unreal/web (Ink) |
| **Yarn Spinner** | Node-based dialogue with easy integration, popular with Unity/Godot, used in many indie games (Yarn Spinner) |
| **Twine** | Hypertext prototyping; good for quick branching drafts |
| **ChoiceScript** | Choice-of-Games style variable-heavy fiction |
| **Articy:draft** | Commercial narrative database / flow editor |
| **Custom** | Often needed for AAA integration, VO pipelines, localization |

Selection criteria: writer-friendly syntax, **version control friendliness** (text-based), variable/state support, debugging/testing tools, VO and localization export, runtime footprint, engine integration.

### 10.3 Authoring practices
- **Write in a testable format** and playtest dialogue as text early (Twine/Ink/Yarn) before voice.
- **Keep nodes short** (a few lines) and **return control to the player often** (heuristic: do not make the player passively read/listen for long stretches without interaction).
- **IDs and naming**: stable line IDs for VO and loc; avoid renumbering.
- **Variables**: document set/read locations; automatic dead-variable checks if possible.
- **Writing for localization**: avoid puns that cannot translate, gendered text where unnecessary, concatenated sentences; provide context notes and character limits.
- **Skippable/rewindable dialogue** and a **log** are accessibility and quality-of-life features (see `references/08-player-psychology-ux-accessibility.md`).

## 11. Barks and Reactive Lines

**Barks** are short, context-triggered lines (combat shouts, idle remarks, reaction to events) that make a world feel reactive.

### 11.1 Design
- **Trigger taxonomy**: combat start/end, kill, damage, reload, low ammo, spot player, lost player, ally down, location entered, item found, idle, weather/time change.
- **Conditions**: speaker, listener, state (hurt, afraid), location, recent events, relationships.
- **Priority and cooldowns**: avoid repetition and overlap; global cooldown per speaker, per trigger and per line.
- **Variety budget**: the more frequent the trigger, the more variants (heuristic: frequent triggers need many variants; rare triggers need few but high quality).
- **Informational barks** do double duty as gameplay feedback (flank called out, grenade warning). Keep them clear and consistent.
- **Specificity wins**: choose the most specific eligible line; fall back to generic ones.
- **Silence is a tool.** Not every event needs a line.

### 11.2 Process
1. List triggers with frequency estimates.
2. Write pass 1: functional lines; pass 2: character flavor; pass 3: callbacks and rare gems.
3. Test in the game for repetition: log which lines fire; look for the top 5 most repeated lines.
4. VO budgeting: barks are expensive in aggregate; prioritize common triggers and unique characters.

## 12. Lore Delivery

Lore is background world knowledge. Players generally **do not read** large amounts of it; some love it deeply. Design layers.

| Layer | Delivery | Audience |
|---|---|---|
| **Layer 0: felt** | Look, sound, behavior of the world | Everyone |
| **Layer 1: seen** | Props, environmental storytelling, signage | Most |
| **Layer 2: heard** | Short barks, overheard conversation, ambient VO | Many |
| **Layer 3: asked** | Optional dialogue, codex entries | Curious |
| **Layer 4: found** | Documents, audio logs, item descriptions | Enthusiasts |
| **Layer 5: studied** | Out-of-game wikis, community theory | Lore hunters |

Heuristics:
1. **The critical path needs only layers 0-2.** Deeper layers add richness, never gating.
2. **Item descriptions are a high-leverage channel** (Dark Souls-style): short, evocative, fragmentary text that invites interpretation.
3. **Keep documents short**, one idea each, in a character's voice, and not in the critical moment of gameplay.
4. **Delay and withhold**: mystery drives engagement; doling out in small pieces gives a reason to keep going.
5. **Avoid exposition dumps**: use conflict, subtext, interruption, and visual demonstration.
6. **Consistency bible**: maintain a canon document to keep facts straight across writers.
7. **Let lore matter mechanically** where possible (enemy factions, item effects, region rules).

## 13. Player Agency vs Authored Story

The central tension: authored stories need control; interactivity yields freedom.

### 13.1 Spectrum
| Level | Description | Example pattern |
|---|---|---|
| **Pure authored** | Story proceeds regardless; player controls the pace | Linear action-adventure |
| **Authored with expression** | Fixed plot, player chooses tone, approach, details | Many RPG and narrative adventures |
| **Branching** | Player choices change events and endings | Branch-and-bottleneck, CRPGs |
| **Systemic** | Plot emerges from rules and simulation | Sims, strategy, sandbox |
| **Player-authored** | The player builds narrative with tools | Roleplay MMOs, mod and sandbox spaces |

### 13.2 Techniques to reconcile
1. **Illusion of agency (carefully):** implement choices whose outcomes converge but whose acknowledgments differ. Use sparingly and never break the player's trust with obvious fakery (e.g., a choice that gets the same line after).
2. **Agency in the how, not the what:** the player decides how to approach a fixed event.
3. **Player-triggered reveals:** the story advances when the player acts (opens a door, interacts), so pace follows their curiosity.
4. **Soft constraints:** nudge via NPCs and the world rather than invisible walls.
5. **Diegetic failure states:** let capture, injury or loss move the story forward.
6. **Plan for sequence breaking:** if the player can visit locations in any order, write content to be order-independent or to adapt (dialogue variants keyed to what the player knows).
7. **Respect the player's mental model:** if the player knows X, the characters shouldn't pretend otherwise; if the character knows more than the player, show why.
8. **Time and urgency:** if the fiction says "hurry", systems or UI must support (timers, consequences) or the story should avoid claiming urgency (ludonarrative; section 5).

### 13.3 Telling vs interactive moments
- Prefer **short, interruptible cutscenes**, skippable on replay.
- **Return control quickly**; use in-engine conversations while walking where feasible.
- **Make the player complicit** in key events (press to act) when emotional.

## 14. Writing for Games

### 14.1 Principles
1. **Brevity.** Players want to play. Say it in fewer words, split long lines, cut greetings. Tools: cut the first and last sentence of a line and see if it still works.
2. **Voice over exposition.** Characters speak from their perspective with attitude, not as information dispensers.
3. **Subtext and conflict.** Every exchange should have someone wanting something.
4. **Function first:** each line should do at least one of: advance, inform, characterize, set tone, give feedback.
5. **Contextual clarity.** Players may return after weeks; reminders (journal, quest log, recaps) are part of writing.
6. **Repetition-aware.** Anything the player will see 50 times (barks, item names, UI text) must be short and good or have variants.
7. **Write for the voice actor and the engine.** Directions, emotional state, lengths; test lines spoken aloud.
8. **Consistency:** style guide with tone rules, vocabulary, forbidden words, formatting for UI strings.
9. **Inclusive and accessible writing:** plain language options, avoid reliance on color words or sound-only cues in puzzle text, content warnings where appropriate.
10. **Localization-friendly.**

### 14.2 UI and system text
Quest titles, objectives, tooltips and tutorials are narrative surfaces too. Use consistent terminology across UI, dialogue and codex; objective text should say **what, where, and why** in one line.

### 14.3 Style guide contents
Tone and genre; character voice sheets (3 sample lines each, 3 things they'd never say); world terminology glossary; formatting rules; profanity/violence guidelines; localization notes.

## 15. Narrative in Systemic Games: Case Studies

Descriptions are summaries of well-known public features of the games; verify details by playing and by reading developer talks.

### 15.1 Hades (Supergiant Games)
- **Structure:** a roguelike with a repeating loop; each death returns the protagonist to the House, where the story advances. The narrative **uses the loop** (death is part of the fiction), so repetition becomes character development rather than a break.
- **Delivery:** a large body of conversation content is triggered by conditions and **priority rules** (who you've met, what happened in the last run, which boons or weapons you used, relationship states), so players generally see fresh dialogue as they progress and get responses to their own actions.
- **Ludonarrative harmony:** the mechanical premise (try again) is the story premise (escape the underworld and fail often).
- **Lessons:** let the core loop be the narrative engine; build a conditional-line system with priority and "seen" tracking; write many short exchanges rather than long scenes; reward failure with story.

### 15.2 RimWorld (Ludeon Studios)
- **Structure:** a colony sim presented explicitly as a **story generator**; AI "storytellers" (such as Cassandra, Phoebe, Randy) control the pacing of random events. Tynan Sylvester's *Designing Games* discusses emergent narrative design (Sylvester 2013).
- **Story fuel:** colonists with traits, backstories, needs, moods and relationships; injuries and permanent scars; mental breaks; an event log.
- **Lessons:** emergent stories need characters the player cares about, consequences that persist, a pacing director, and legible causality. Authorship is shared: the system supplies events, the player supplies meaning.

### 15.3 Disco Elysium (ZA/UM)
- **Structure:** a CRPG whose primary interface is **text and internal voices**: skills are characters that interject, argue and mislead. The Thought Cabinet turns ideas into slow-burn state changes.
- **Choice design:** failure is content (fail-forward checks); stats shape not only success but perspective on the world.
- **Lessons:** a systemic skill/quality model can generate voice-rich, reactive narrative; make skills characters; make failing interesting; the interface (long text, passive checks) is the game.

### 15.4 Other patterns worth studying
| Game | Narrative design lesson |
|---|---|
| **Return of the Obra Dinn** | Mystery structure where the player's deduction is the narrative; clear verb = story reconstruction |
| **Outer Wilds** | Knowledge as progression (knowledge gates); a time loop as story engine |
| **Dark Souls / Elden Ring** | Fragmentary lore in item text and environment; minimal cutscenes |
| **The Last of Us / God of War** | Companion-driven embedded narrative with mechanics supporting the relationship |
| **Disco-like QBN: Fallen London** | Storylets / qualities for ongoing narrative |
| **Papers, Please** | Mechanics create moral dilemmas; ludonarrative alignment |
| **Mass Effect / Baldur's Gate 3** | Branching companion-driven RPG narrative at large scale; track state meticulously |
| **Her Story / Telltale-style** | Interface as narrative device; episodic structure |

## 16. Process, Documents and Scoping

### 16.1 Pipeline
1. **Narrative pillars** (3-5 statements: theme, tone, what the player does emotionally). Tie to game pillars (see `references/01-design-process.md`).
2. **Premise and structure**: logline, central question, act/beat outline, ending model.
3. **World and cast bible**: setting rules, factions, characters, glossary.
4. **Delivery plan**: which beats are cutscene, in-world, dialogue, environmental, systemic; map beats to levels/missions with the level designer.
5. **State and reactivity design**: variables, choice ledger, callbacks.
6. **Prototype in text** (Twine/Ink/Yarn) and playtest the pacing.
7. **Production scripting**: lines, IDs, VO direction, implementation, localization hand-off.
8. **Iteration and lock**: define a "narrative lock" date after which changes are costly (VO, animation, cinematics).
9. **QA**: dead ends, unreachable lines, variable bugs, continuity.

### 16.2 Scoping rules (heuristics)
- **Count lines early** and budget VO; cut by the cost-benefit of each scene.
- **Reuse** assets, scenes and dialogue structures with variable fill-ins.
- **Reactivity budget:** decide which 5-10 choices get big consequences and make the rest light-touch.
- **Write the ending first** (or at least pick its shape) in branching narratives.
- **Telegraph** to the team which narrative content is mandatory vs optional.
- **Design for the cut:** build optional layers that can be dropped without breaking the main story.

### 16.3 Testing narrative
- Read-throughs and table reads (hear the lines).
- **Comprehension test**: after play, can the player explain the plot and character motives? Which beats were missed?
- **Emotional beat test**: ask where they felt something.
- **Pacing test**: where did they skip or check out?
- **Choice awareness test**: did the player realize the choice was impactful? Did they notice consequences?
- See `references/12-playtesting-and-analytics.md`.

## 17. Checklists and Common Pitfalls

### 17.1 Narrative design review
- [ ] Narrative pillars exist and agree with game pillars.
- [ ] Every major story claim is supported by a mechanic (section 5.3).
- [ ] The critical path story is understandable with no optional content.
- [ ] Choices have clear stakes, distinct options, and recorded callbacks.
- [ ] Branching structure is chosen per section with a content budget.
- [ ] State variables are documented, with no orphaned variables.
- [ ] Barks have variety, cooldowns, and fallbacks.
- [ ] Lore layers exist; deep lore is optional.
- [ ] Cutscenes are skippable, short, and return control fast.
- [ ] Dialogue is brief, voiced distinctively, localization-ready.
- [ ] Replays/NG+ handle repeated content.
- [ ] Narrative lock date and dependency map are agreed with production.

### 17.2 Pitfalls
| Pitfall | Fix |
|---|---|
| **Story and mechanics disagree** | Align verbs and themes; adjust claims |
| **Exposition dumps** | Show, spread out, use conflict |
| **Choice theater** (choices that don't matter) | Fewer, better; acknowledge differences; be honest about stakes |
| **Time-cave scope** | Branch-and-bottleneck with residue |
| **Unread lore walls** | Layered delivery, brevity, in-world cues |
| **Chosen-one clichés** | Rethink the hero's role; subvert or ground |
| **Cutscene-heavy, play-light** | Make events playable; trim |
| **Bark repetition** | Variants, cooldowns, priority |
| **Characters as quest dispensers** | Wants, flaws, reactivity |
| **Inconsistent tone across writers** | Style guide, editor, shared sample lines |
| **Agency promised, not delivered** | Marketing and in-game claims should match what you build |
| **Narrative late in production** | Involve narrative from pre-production; lock early |
| **Ignoring accessibility** | Subtitles, readable text, pausable timers, content notes |

### 17.3 How to apply: requests for help
1. Clarify what the story is *for* (theme, emotion) and the genre's constraints.
2. Pick the structure and delivery model (embedded, emergent, or hybrid).
3. Choose a branching pattern per section and set a content budget.
4. Draft a beat outline mapped to gameplay beats and levels.
5. Design the state model and choice ledger.
6. Define voice, style guide and dialogue tooling.
7. Provide a prototype and playtest plan.

## 18. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Essays and articles (URLs verified)**
- Jenkins, H., 2004, "Game Design as Narrative Architecture", in *First Person: New Media as Story, Performance, and Game* (Wardrip-Fruin and Harrigan eds., MIT Press); online version at Electronic Book Review: https://www.electronicbookreview.com/essay/game-design-as-narrative-architecture/
- Hocking, C., 2007, "Ludonarrative Dissonance in Bioshock", Click Nothing: https://clicknothing.com/2007/10/07/ludonarrative-d/
- Ashwell, S. K., 2015, "Standard Patterns in Choice-Based Games", Heterogenous Tasks: https://heterogenoustasks.wordpress.com/2015/01/26/standard-patterns-in-choice-based-games/
- Short, E., 2019, "Storylets: You Want Them", Emily Short's Interactive Storytelling: https://emshort.blog/2019/11/29/storylets-you-want-them/
- Kishotenketsu, Wikipedia: https://en.wikipedia.org/wiki/Kish%C5%8Dtenketsu

**Tools and studios (URLs verified)**
- Ink, inkle: https://www.inklestudios.com/ink/
- Yarn Spinner: https://www.yarnspinner.dev/
- Failbetter Games (Fallen London, Sunless Sea): https://www.failbettergames.com/

**Books**
- Campbell, J., 1949, *The Hero with a Thousand Faces*, Pantheon Books.
- Vogler, C., *The Writer's Journey: Mythic Structure for Writers*, Michael Wiese Productions.
- Sylvester, T., 2013, *Designing Games: A Guide to Engineering Experiences*, O'Reilly Media.
- Schell, J., 2019, *The Art of Game Design: A Book of Lenses*, 3rd ed., CRC Press.
- Wardrip-Fruin, N. and Harrigan, P. (eds.), 2004, *First Person: New Media as Story, Performance, and Game*, MIT Press.
- Totten, C. W., 2014, *An Architectural Approach to Level Design*, CRC Press.

**Games discussed (play to verify)**: Hades, RimWorld, Disco Elysium, Fallen London, Return of the Obra Dinn, Outer Wilds, Papers Please, BioShock, Spec Ops: The Line, Dark Souls, Mass Effect, Baldur's Gate 3, Left 4 Dead.

Note: proportions, budgets and counts in this file are heuristics, and the game case studies summarize publicly known design features; they are not quotations from developers.
