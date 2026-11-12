# Playtesting and Analytics

How to find out whether a design works: qualitative playtests, structured methods (think-aloud, RITE, heuristics, surveys), quantitative telemetry, A/B tests, and how to turn all of it into a prioritized backlog. Numbers marked **(heuristic)** are rules of thumb from practice, not universal findings.

## Table of Contents

1. [Principles](#1-principles)
2. [Playtest Types and When to Use Each](#2-playtest-types-and-when-to-use-each)
   - [2.1 Stage-by-stage matrix](#21-stage-by-stage-matrix)
   - [2.2 What to test at each stage](#22-what-to-test-at-each-stage)
3. [Recruiting and Sampling](#3-recruiting-and-sampling)
4. [Running a Session](#4-running-a-session)
   - [4.1 Before the session](#41-before-the-session)
   - [4.2 Think-aloud protocol](#42-think-aloud-protocol)
   - [4.3 Observation: what to watch](#43-observation-what-to-watch)
   - [4.4 Facilitator rules](#44-facilitator-rules)
   - [4.5 Remote and unmoderated tests](#45-remote-and-unmoderated-tests)
5. [RITE: Rapid Iterative Testing and Evaluation](#5-rite-rapid-iterative-testing-and-evaluation)
6. [Surveys and Questionnaires](#6-surveys-and-questionnaires)
7. [Interviews and Debriefs](#7-interviews-and-debriefs)
8. [Heuristic Evaluation](#8-heuristic-evaluation)
9. [Usability vs Playability, and Biometrics](#9-usability-vs-playability-and-biometrics)
10. [Telemetry Design](#10-telemetry-design)
    - [10.1 Event design](#101-event-design)
    - [10.2 Funnels](#102-funnels)
    - [10.3 Heatmaps and spatial analysis](#103-heatmaps-and-spatial-analysis)
    - [10.4 Retention cohorts and session metrics](#104-retention-cohorts-and-session-metrics)
    - [10.5 Privacy and data hygiene](#105-privacy-and-data-hygiene)
11. [A/B Testing Basics](#11-ab-testing-basics)
12. [Interpreting Feedback](#12-interpreting-feedback)
13. [Triage: From Findings to a Prioritized Backlog](#13-triage-from-findings-to-a-prioritized-backlog)
14. [Diagnosing Fun Problems from Data](#14-diagnosing-fun-problems-from-data)
15. [Playtest Report Structure](#15-playtest-report-structure)
16. [Common Pitfalls](#16-common-pitfalls)
17. [References](#17-references)

---

## 1. Principles

1. **Test to answer a question, not to "see what happens".** Every session needs 1-3 written research questions ("Do players discover the dash within 2 minutes?"). No question, no test.
2. **Observe behavior; treat opinions as secondary.** What players do is evidence. What they say is a clue that needs interpretation.
3. **Test early with ugly builds.** A grey-box that exposes a broken core loop is cheaper to fix than a polished level. Rough prototypes also invite honest criticism.
4. **You are too close to your own game.** Designers cannot un-know their rules. Fresh eyes are a consumable resource; spend them deliberately.
5. **Players are good at identifying problems and bad at prescribing solutions.** Collect symptoms from players; design the cure yourself (see Section 12).
6. **Qualitative tells you why; quantitative tells you how many.** Use small observed tests to find causes and telemetry or large surveys to size them.
7. **Iterate: test, fix, retest.** A finding is only closed when a later test shows the fix worked.
8. **Make findings actionable.** Each finding: what happened, how often, how severe, probable cause, suggested experiment.

## 2. Playtest Types and When to Use Each

| Type | Who | Typical goal | Strengths | Weaknesses |
|---|---|---|---|---|
| **Internal / dev playtest** | Your team, other departments | Smoke test, find bugs, check build stability | Fast, free, frequent | Biased: knows the rules, wants it to succeed |
| **Friends and family** | People you know | Early "does it make sense at all" | Cheap, forgiving, easy to schedule | Polite; sample is not your audience; low signal on appeal |
| **Kleenex (fresh) testers** | Players who have never seen the game ("use once, then discard") | First-time user experience, onboarding, clarity | Only source of true first-impression data | Each tester can be used once; recruiting cost |
| **Targeted / lab test** | Recruited members of the target audience, observed live | Usability, comprehension, difficulty, emotional response | Rich qualitative data; you can ask why | Small samples; artificial setting |
| **Focus test** | Groups of target players; discussion plus play | Concept appeal, art direction, messaging, naming | Surfaces vocabulary and expectations | Group-think; dominant voices; people say what is socially easy |
| **Closed beta** | Invited, often NDA'd players | Stability, balance, retention, server load, mid/late-game | Real play at scale with telemetry | Needs finished-enough content; feedback volume |
| **Open beta** | Anyone who signs up | Scale testing, marketing, community building | Large samples, stress test | Public perception risk; less control |
| **Soft launch** | Real release in limited markets (common on mobile) | Retention, monetization, KPIs vs benchmarks | Real behavior with real money and no safety net | Expensive to iterate; markets differ from the global audience |

Related terms: **alpha** (feature-complete-ish, internal or small external), **beta** (content-complete, polishing), **vertical-slice test** (one polished slice used to validate the whole).

### 2.1 Stage-by-stage matrix

| Stage | Primary methods | Sample (heuristic) | Cadence |
|---|---|---|---|
| Concept | Paper prototype, focus test, one-pager feedback | 5-10 per round | As needed |
| Prototype (core verb/loop) | Observed sessions with grey-box, think-aloud | 5-8 per round | Weekly or per build |
| Pre-production / vertical slice | Kleenex tests, RITE, heuristic review | 5-8 per round, several rounds | Per milestone or weekly |
| Production | Targeted lab tests per feature/level, internal telemetry | 5-10 per feature | Continuous |
| Alpha/Beta | Closed beta, surveys, telemetry funnels, A/B | Hundreds to thousands | Continuous |
| Soft launch | KPI tracking, cohort retention, A/B | Thousands per cohort | 2-8 weeks per cycle |
| Live | Telemetry, A/B, community and support signals | All players | Continuous |

On sample size: the often-cited "5 users find most usability problems" comes from Nielsen and Landauer's model (found problems = 1 - (1 - L)^n, with L around 0.31 on average in their data). It applies to **qualitative problem discovery of a fairly homogeneous group**, assumes you fix and retest, and says nothing about measuring rates or comparing audiences (Nielsen 2000). Use several rounds of ~5, not one round of 30.

### 2.2 What to test at each stage

- **Feel and comprehension (earliest):** Can players do the core verb? Do they understand what they are looking at and what to do next?
- **Learnability:** Time to first successful use of each mechanic; where they ask "what does this do?".
- **Difficulty and pacing:** Fail counts, retries, perceived fairness, boredom troughs.
- **Appeal:** Would they play again? What would they tell a friend? (Ask last; weak signal until the loop is solid.)
- **Retention and economy:** Only after the loop is validated; needs larger samples and telemetry.
- **Last:** balance at the meta level, monetization, long-term retention.

Testing order mirrors prototype order: **core verb feel -> core loop -> first-time experience -> mid-game -> long-term** (see `references/01-design-process.md`).

## 3. Recruiting and Sampling

**Screen for the target audience, not for convenience.**

1. Define 1-3 player profiles in behavioral terms (games played recently, genre familiarity, platform, hours per week), not demographics alone.
2. Write a short screener with **non-leading** questions: "Which of these games have you played in the last 3 months?" with decoys, not "Do you like roguelikes?".
3. Mix experience levels when the design must serve them: novice, intermediate, expert. Novices expose onboarding failures; experts expose depth and dominant strategies.
4. Exclude industry insiders and anyone who has seen the game (except in retest cohorts you label as such).
5. Over-recruit by 20-30% for no-shows **(heuristic)**.
6. Compensate fairly; obtain consent (recording, data use, minors need guardian consent and local-law checks).

| Source | Good for | Watch out for |
|---|---|---|
| Recruiting agency / panel | Controlled targeting | Cost; professional testers |
| Community (Discord, subreddit, mailing list) | Engaged fans, cheap | Self-selected enthusiasts, not newcomers |
| Local meetups, schools, game stores | Casual players, cheap | Skews local/young |
| Playtest platforms (Steam playtest, itch.io, TestFlight) | Scale, remote builds | Little observation; self-reported |
| Colleagues' friends | Quick | Politeness bias |

Keep a **tester ledger**: who played which build, so nobody is accidentally reused as a "fresh" tester.

## 4. Running a Session

### 4.1 Before the session

1. Fix the **build** (known-good, restart-able, with a debug path to skip broken areas).
2. Write the **research questions**, tasks, and the script (use `templates/playtest-plan.md`).
3. **Pilot** the session with one colleague to catch broken setup and awkward wording.
4. Prepare recording: screen + audio, ideally face/controller camera; get consent.
5. Define the **stop criteria** for each task (e.g., "if stuck for 3 minutes, note it and hint").
6. Observers sit out of the player's sightline. Observers write timestamps, not conclusions.

Session skeleton (45-90 minutes **(heuristic)**): welcome and consent (5) -> background questions (5) -> free play with think-aloud (20-40) -> guided tasks (10-20) -> survey (5-10) -> debrief interview (10-15).

### 4.2 Think-aloud protocol

Ask players to verbalize thoughts while playing (Nielsen 2012; Ericsson and Simon's protocol-analysis work is the academic root).

Briefing script (adapt):
> "We're testing the game, not you. You can't do anything wrong. Please say out loud what you're looking at, what you're trying to do, and what you expect to happen. I may not answer questions right away; I'll note them and come back at the end."

Facilitator prompts, used only when the player goes silent for ~10-15 s **(heuristic)**:
- "What are you thinking right now?"
- "What are you looking at?"
- "What do you expect will happen?"

Cautions: think-aloud slows play and can change behavior (reflecting aloud can make players more careful), so it distorts **speed and timing** data. For pacing and difficulty, run silent sessions and use **retrospective think-aloud** (watch the recording together afterwards and ask "what were you thinking here?"). Games with fast action or immersion goals often work better with retrospective review.

### 4.3 Observation: what to watch

Behavioral signals matter more than statements.

| Signal | What it usually means |
|---|---|
| **Hesitation / long pause** at a decision point | Unclear options, unclear goal, or too many choices |
| **Repeated failed attempts** at the same thing | Unclear telegraph, unfair challenge, or missing tool knowledge |
| **Wandering / backtracking** | Weak wayfinding, unclear objective |
| **Ignoring an item/UI element** | Not noticed (salience) or not valued |
| **Misusing a mechanic** | Affordance mismatch; the intended use is not suggested |
| **Reading nothing** (skipping text) | Tutorial text will not work; show, don't tell |
| **Asking the facilitator** | A teaching failure; log the exact question |
| **Sighing, leaning back, looking at phone** | Boredom or disengagement; mark the timestamp |
| **Leaning forward, smiling, swearing happily, "one more try"** | Engagement; log what caused it |
| **Quits / wants to stop** | Record the last 60 seconds before it |
| **Workarounds and exploits** | Emergent play (good) or degenerate strategy (check) |
| **Mismatch between words and actions** ("it's easy" while dying five times) | Rely on actions; probe politely later |

Log with **timestamp, observation, and tag** (e.g., `12:40 | stuck at locked door, tried lever 3x | WAYFINDING`). Separate **observations** (facts) from **interpretations** (hypotheses). Use a consistent tag set across sessions so patterns can be counted.

### 4.4 Facilitator rules

1. **Do not help.** If the player is stuck, the game is stuck. Silence is data. Intervene only after a pre-agreed time limit, then log it as an assist.
2. **Do not lead.** Never say "try the red button", and avoid "Did you notice the...?" before the player has had the chance.
3. **Do not defend the design.** If you explain or apologize, you teach the tester and bias the rest of the session.
4. **Keep neutral tone and face.** Do not react to successes or failures; do not nod at "correct" actions.
5. **Ask open, non-leading questions.** "What do you think that does?" not "Wasn't that a cool feature?".
6. **Don't ask players to design.** "What would you add?" yields wish lists; ask what they were trying to do and what got in the way.
7. **One facilitator speaks.** Observers stay quiet and do not coach.
8. **Avoid the 'mirror' effect:** do not sit looking over the player's shoulder at the screen; it adds social pressure.
9. **Log assists and hints** so aggregate success rates stay honest ("completed with 1 hint" is not "completed").

### 4.5 Remote and unmoderated tests

- Moderated remote (video call + screen share): good substitute for lab sessions; verify audio and controller setup first.
- Unmoderated (build + survey + telemetry): scales cheaply but you lose the "why". Combine with in-game prompts and short surveys at key moments.
- Always include a **build-version tag** in telemetry and survey so feedback can be tied to the build.
- For online multiplayer, test at the scale and latency that matches real play.

## 5. RITE: Rapid Iterative Testing and Evaluation

RITE was developed at Microsoft (Medlock, Wixon, Terrano, Romero, Fulton, 2002) and used by Microsoft Games User Research. It differs from a classic test-then-report cycle:

- Test with **a very small number of participants** (often 1-3 at a time).
- **Fix problems as soon as they are clearly identified** and verify the fix with the next participant(s), *within the same study*, rather than collecting everything for a final report.
- The team (designers, engineers, artists) **watches live** and agrees on the diagnosis immediately.

### How to run RITE

1. **Pre-conditions.** Team commitment to attend; builds that can be changed within hours; authority to make decisions in the room (a designer and an engineer present).
2. **Define tasks and success criteria** beforehand (e.g., "player finds the exit within 3 minutes").
3. **Run a participant.** Everyone observes; log problems with severity.
4. **Triage immediately after the session:** for each problem, decide *fix now / fix later / not a problem / need more data*.
5. **Fix** the "fix now" items, produce a new build (same day or overnight).
6. **Run the next participant on the new build** and check whether the issue is gone and no new ones appeared.
7. Continue until problems stop appearing or time is out. Record what was changed and the evidence it worked.

### When RITE fits and when it does not

| Good fit | Poor fit |
|---|---|
| Onboarding, tutorials, UI flows, level comprehension | Statistical comparisons or preference measurement |
| Clear, fixable usability/comprehension problems | Problems with unclear causes that need many observations |
| Teams that can ship a patch build in hours | Content-locked builds or long build pipelines |
| Early and mid development | Balance of mature meta-systems (need volume) |

Pitfall: fixing after a **single** observation can overfit to an unusual player. Mitigation: fix obvious errors (a button players cannot find) immediately; for ambiguous ones wait for a second observation.

## 6. Surveys and Questionnaires

Use surveys to quantify what you saw. They do not replace observation.

### 6.1 Design rules

1. **Short and focused.** Every question maps to a research question; delete the rest. Survey fatigue ruins late answers.
2. **Ask immediately after play**, while memory is fresh; for long play, ask at milestones.
3. **Neutral wording.** Avoid leading ("How much did you enjoy the amazing combat?") and loaded terms; avoid **double-barreled** items ("Was the game fun and easy?").
4. **Use balanced scales.** Likert items: 5 or 7 points, labeled endpoints, a neutral midpoint, consistent direction. Mix positively and negatively worded items sparingly to detect straight-lining.
5. **Concrete before abstract.** "I always knew what to do next" (1-5) beats "Was the game clear?".
6. **Open text last**, 2-3 prompts maximum: "What was most frustrating?" "What was the most memorable moment?" "In your own words, what is this game about?"
7. **Randomize** item order when comparing builds or conditions.
8. **Don't ask players to predict their own behavior** ("Would you buy this?"); stated intent poorly predicts actions (heuristic; use pre-orders, wishlists, and retention as behavior proxies).
9. Pair with **behavior**: compare self-reports to telemetry and observation.

### 6.2 Useful question patterns

| Goal | Example item (5-point agree/disagree unless noted) |
|---|---|
| Clarity of goals | "I always knew what my current goal was." |
| Control and feedback | "I could tell whether my actions succeeded." |
| Fairness | "When I failed, I understood why." |
| Difficulty | "The difficulty was: much too easy / too easy / about right / too hard / much too hard" |
| Pacing | "There were moments when I was bored." / "There were moments when I felt overwhelmed." |
| Comprehension | "In your own words, explain how [system] works." (open) |
| Intent to continue | "I want to keep playing." |
| Net promoter-style | "How likely are you to recommend this game? (0-10)" (use as a trend, not a single verdict) |

### 6.3 Validated instruments

| Instrument | What it measures | Notes |
|---|---|---|
| **Game Experience Questionnaire (GEQ)** (IJsselsteijn, de Kort, Poels 2013) | Core module: Competence, Sensory and Imaginative Immersion, Flow, Tension, Challenge, Negative Affect, Positive Affect. Also in-game and post-game modules | Free for research use; 33-item core; scoring guide in the manual |
| **PENS (Player Experience of Need Satisfaction)** (Ryan, Rigby, Przybylski 2006) | Self-Determination Theory needs: Competence, Autonomy, Relatedness; also Presence/Immersion and Intuitive Controls | Based on SDT; useful for motivation analysis |
| **Intrinsic Motivation Inventory (IMI)** | Interest/enjoyment, effort, pressure/tension, perceived competence | General-purpose research instrument |
| **SUS (System Usability Scale)** | General usability of interfaces/menus | Quick, 10 items; designed for software, not play |
| **NASA-TLX** | Perceived workload | Use for complex UIs or accessibility reviews |

Treat scores as **relative** (compare builds, segments, or genre norms), not as absolute grades. Cite the instrument's manual before use, and don't alter items if you want to claim validity.

## 7. Interviews and Debriefs

1. **Open with the player's own words**: "Tell me about what you just played, as if I'd never seen it."
2. **Go chronologically** through memorable moments using the recording as a prompt.
3. **Use the five whys softly**: "What made that frustrating?" -> "What did you expect to happen?".
4. **Probe actions, not hypotheticals**: "I saw you go left twice. What were you looking for?".
5. **Ask for the best and worst moment**, the elevator pitch in their words, and who they would recommend it to.
6. **Comprehension checks**: ask players to explain rules, goals, and their strategy; mismatches reveal teaching failures.
7. **Last, ask comparisons** with other games they play; this reveals expectations and positioning.
8. **Close with an exit question**: "Is there anything I haven't asked that you want to tell me?".

Interview pitfalls: leading questions; accepting solutions at face value; interviewing in groups (conformity); asking about things the player never saw.

## 8. Heuristic Evaluation

Expert review without players. Cheap and fast; finds many issues before testing, so player time is spent on deeper problems. It does **not** replace playtests: heuristics generate false positives and miss emergent problems.

Method (after Nielsen): 2-4 evaluators work **independently** against a heuristic list, log problems with location, heuristic violated, and severity; then merge, deduplicate, and rate (Nielsen NN/g heuristic evaluation guidance).

### 8.1 Playability heuristics (PLAY, Desurvire et al.)

Desurvire, Caplan and Toth (2004) proposed **Heuristic Evaluation of Playability (HEP)**, later refined by Desurvire and Wiberg as **Game Approachability Principles (GAP)** and PLAY. The categories (paraphrased; consult the original papers for exact wording):

| Category | Questions |
|---|---|
| **Gameplay** | Is there a clear goal? Is challenge balanced and does it scale? Can players pace themselves? Are strategies varied? |
| **Game story** | Is the story involving without blocking play? Is the player's role clear? |
| **Game mechanics** | Are controls consistent, predictable, and customizable? Is the AI believable? Are rules consistent? |
| **Game usability** | Is the interface consistent? Can players tell state and progress? Is feedback immediate and informative? |

### 8.2 Established usability heuristics to apply to games

Nielsen's 10 heuristics (visibility of system status, match to real world, user control and freedom, consistency, error prevention, recognition over recall, flexibility, minimalist design, error recovery, help) apply to menus, HUD, inventory, and tutorials. Remember games *want* some difficulty: the goal is to remove **accidental** friction, not the **intended** challenge.

### 8.3 A quick game-specific checklist (practitioner heuristics)

- Can a new player state their goal within 60 seconds?
- Is the next action always discoverable (affordance, signposting)?
- Does every important input produce feedback in a perceivable window (about 100 ms for responsiveness)?
- Can the player always tell what caused a failure?
- Are failure costs proportional (retry time, lost progress)?
- Are there at least two viable approaches to key challenges?
- Is the UI readable at target distance/resolution; are colors not the sole information carrier?
- Can any required action be done with reduced ability (see `references/08-player-psychology-ux-accessibility.md`)?

### 8.4 Severity scale (use consistently)

| Level | Name | Definition |
|---|---|---|
| 0 | Not a problem | Disagreement among evaluators |
| 1 | Cosmetic | Fix if time permits |
| 2 | Minor | Low priority; small annoyance |
| 3 | Major | Important to fix; hurts experience or progress |
| 4 | Catastrophic | Blocks progress or causes quit; must fix before release |

## 9. Usability vs Playability, and Biometrics

**Usability**: can players operate the interface and understand the system with minimal effort? Friction is always bad.
**Playability**: is the experience engaging, challenging, and satisfying? Friction may be *intended* (challenge, uncertainty).

| Question | Usability problem | Playability (design) problem |
|---|---|---|
| Player fails | Didn't know how to do it / UI hid the info | Knew how, but challenge is unbalanced or dull |
| Player confused | Poor labeling, inconsistent controls | Rules too complex for target audience |
| Player stops | Couldn't progress | Chose to stop: bored, stuck on a fair challenge, no motivation |

Rule of thumb: **fix usability problems first**; they mask playability signals. A player who can't find the jump button tells you nothing about your platforming.

### 9.1 Biometrics (brief)

Physiological sensors add objective signals alongside observation:

| Signal | Typical use | Caveat |
|---|---|---|
| **Eye tracking** | Where players look, what they miss in HUD/levels | Needs calibration; shows attention, not understanding |
| **Heart rate / HRV, galvanic skin response (GSR)** | Arousal peaks in horror/tension design | Arousal does not say whether valence is positive or negative |
| **Facial EMG** | Positive/negative affect | Intrusive; lab only |
| **EEG** | Cognitive load, engagement research | Noisy, expensive; hard to interpret for design decisions |

Use biometrics to **corroborate** observations (e.g., a flat arousal curve during a "tense" sequence), never as sole evidence. A cheap alternative: a **mood marker** (player rates 1-5 each few minutes) or a post-hoc arousal chart on video. For methods and cautions see Drachen, Mirza-Babaei and Nacke (2018).

## 10. Telemetry Design

Telemetry = automatically logging what players do. Used in playtests, betas, and live games. Foundational reading: Seif El-Nasr, Drachen and Canossa (2013), *Game Analytics: Maximizing the Value of Player Data*.

### 10.1 Event design

**Start from questions, then define events.** Logging everything creates cost and noise; logging too little leaves questions unanswerable.

Process:
1. List **design questions** ("Where do players die? Which weapon is used most? Where do they stop playing?").
2. List the **metrics** that answer them (death count per location, pick rate, last event before churn).
3. Define the **events** and **properties** that compute them.
4. Document in a **tracking plan** (name, trigger, properties, owner, version).
5. QA the events in the build (no event = silent bug).

Event schema (every event):

| Field | Purpose |
|---|---|
| `event_name` | `snake_case`, past-tense verb noun: `level_completed` |
| `timestamp` (UTC) | Order and session length |
| `player_id` (pseudonymous) | Joins events per player |
| `session_id` | Group events in one play session |
| `build_version`, `platform`, `locale` | Segmenting; ties data to builds |
| Event-specific properties | `level_id`, `attempt_number`, `position (x,y,z)`, `cause_of_death`, `loadout`, `time_in_level_s` |

Core event categories:

| Category | Examples |
|---|---|
| **Session** | `session_start`, `session_end`, `app_background` |
| **Progression** | `tutorial_step_completed`, `level_started`, `level_completed`, `level_failed` |
| **Challenge** | `player_died` (with position and cause), `checkpoint_reached`, `retry` |
| **Economy** | `currency_earned` (source), `currency_spent` (sink, item), `item_acquired` |
| **Social** | `match_found`, `match_ended`, `party_joined` |
| **UI/Funnel** | `menu_opened`, `store_viewed`, `purchase_started` |
| **Technical** | `crash`, `load_time_ms`, `fps_bucket` |

Rules:
- Log **sources and sinks** with a reason code so economy flows can be reconstructed.
- Log **context with failure** (position, cause, loadout, time since last checkpoint) so deaths are diagnosable.
- Prefer **raw events** over pre-aggregated metrics; aggregations can be rebuilt, raw data cannot.
- **Version your schema**; do not silently change meaning.
- Watch volume: sampling for high-frequency data (positions every N seconds, not per frame).

### 10.2 Funnels

A funnel counts how many players reach each sequential step.

Example: `install -> first_launch -> tutorial_started -> tutorial_step_3 -> tutorial_completed -> level_1_completed -> day_1_return`.

How to use:
1. Define steps as distinct events, in order.
2. Compute **step conversion** (step n / step n-1) and **cumulative conversion**.
3. Find the **largest drop** (absolute and relative).
4. Segment the drop (platform, device, source, skill, build) to find who drops.
5. Pair with qualitative evidence (watch recordings or run a test at that step).
6. Fix, re-measure with the same funnel definition.

Heuristic reading: a sharp drop at a single step usually indicates a specific blocker (UI, difficulty, loading, bug). A gradual decay suggests weak motivation or pacing.

### 10.3 Heatmaps and spatial analysis

Plot events on the level map: deaths, kills, time spent, positions, item pickups, use of cover or routes.

**Example (Halo, Bungie/Microsoft):** Microsoft Games User Research (Randy Pagulayan's group) overlaid playtester locations on level maps. In one Wired account of *Halo 3* testing, an early map of the *Jungle* level showed about 30 testers' positions after half an hour scattered across the terrain; the diagnosis was that players were wandering instead of progressing. The designers changed the geography (steep ledges that can only be dropped down so players can't backtrack), and a later round showed testers clustered along the intended route (Thompson 2007). Takeaway: a heatmap turns "players seem lost" into a visible, testable fact, and the fix is an environment change, not a tutorial popup.

Spatial analysis checklist:
- **Death heatmap**: clusters = hard spots or unfair spots; one cluster across all players is a design signal.
- **Position/time heatmap**: dead zones (no one goes there: wasted content), hot zones (choke points, camping).
- **Path analysis**: do players follow the critical path; where do they leave it?
- **Kill/damage maps (multiplayer)**: map balance, spawn issues, sniper lanes.
- **Normalize by time/visits**: otherwise popular areas always look "hot".
- Always overlay on geometry and view in context of what the player could see and do there.

### 10.4 Retention cohorts and session metrics

**Cohort**: players grouped by install (or first-play) date. **Retention Dn** = % of the cohort active on day n after install.

Retention table (example layout):

| Cohort | Size | D1 | D3 | D7 | D14 | D30 |
|---|---|---|---|---|---|---|
| Week 1 | 5,000 | 38% | 22% | 14% | 9% | 5% |
| Week 2 (new tutorial) | 5,200 | 43% | 26% | 16% | 10% | 6% |

(Illustrative numbers only; do not use as benchmarks.)

Reading retention:
- **D1** reflects first-session quality and onboarding.
- **D7** reflects early hooks and goals; **D30** reflects long-term loop and content.
- Compare **cohorts**, not totals, to see whether changes help. Use the same definition ("active" = any session vs meaningful action).
- A flat tail on the retention curve means a stable core; a curve that keeps falling means no lasting hook.
- Benchmarks vary widely by genre, platform, and market and change over time; use industry reports for the **current** range, treat them as rough guides, and prefer your own trend line.

Session metrics:

| Metric | Definition | Use |
|---|---|---|
| **Session length** | Time from start to last event/idle timeout | Pacing, fit to platform (mobile sessions tend to be short; heuristic) |
| **Sessions per day/week** | Frequency | Habit formation |
| **Time to first X** | Seconds to first kill, first level-up, first purchase | Onboarding and pacing |
| **Playtime to churn** | Total play before the last session | Where the experience runs out |
| **DAU / MAU, stickiness (DAU/MAU)** | Active users per day / month | Live-game health |
| **Completion rate** | % finishing a level/campaign | Difficulty, content value |
| **Failure rate and retries** | Failures per attempt per level | Difficulty spikes |
| **Last-event-before-churn** | The final event of lapsing players | Pinpoints quit reasons |

Monetization metrics (ARPU, ARPPU, conversion, LTV) are covered in `references/09-monetization-and-live-ops.md`.

### 10.5 Privacy and data hygiene

- Collect the minimum data needed; document purpose and retention.
- Pseudonymize player IDs; get consent where required (GDPR, CCPA/CPRA, COPPA for children); honor deletion requests.
- Be careful with position and chat data; never log passwords, payment details, or free text without a clear need.
- Exclude testers, bots, and internal accounts from analysis (tag them).
- Separate **dev builds** from **live data**.

## 11. A/B Testing Basics

An A/B test randomly assigns players to variant A (control) or B (change) and compares a pre-chosen metric.

### 11.1 Procedure

1. **Hypothesis**: "Reducing tutorial text by half will raise tutorial completion."
2. **One primary metric** (plus guardrail metrics that must not get worse: retention, crashes, revenue).
3. **Minimum detectable effect (MDE)**: the smallest improvement worth caring about.
4. **Sample size and duration** fixed *before* starting.
5. **Random assignment** at the player level, persistent across sessions.
6. **Run full weeks** (to cover weekday/weekend cycles).
7. **Analyze once**, at the planned end. Report effect size with confidence interval, not just p-value.
8. **Decide and document**: ship, iterate, or drop.

### 11.2 Sample size (heuristic)

For a conversion-type metric at 5% significance and 80% power, Lehr's rule of thumb gives about **n per group = 16 x p(1-p) / delta^2**, where p is the baseline rate and delta the absolute difference to detect. Example: baseline D1 retention 40%, detect +2 percentage points: n = 16 x 0.24 / 0.0004 = **about 9,600 players per variant**. Detecting +1 point needs roughly four times as many. Use a calculator for exact numbers (Miller's sample-size calculator) and treat the rule as an estimate.

Implications: small games rarely have the traffic to detect small effects. Use A/B tests for **big levers** (onboarding flow, first-session length, store layouts), and use qualitative methods for subtle feel changes.

### 11.3 Pitfalls

| Pitfall | Why it hurts | Fix |
|---|---|---|
| **Peeking / early stopping** | Repeatedly checking p-values inflates false positives (Miller 2010) | Fix duration and sample in advance, or use sequential methods designed for it |
| **Multiple metrics/variants** | More comparisons -> more chance of false wins | One primary metric; correct for multiple comparisons |
| **Underpowered tests** | "No significant difference" does not mean "no effect" | Compute sample size first |
| **Novelty effect** | Players react to anything new; the lift decays | Run longer; check effect over time on returning players |
| **Sample ratio mismatch** | Assignment bugs (e.g., 52/48 when 50/50 was planned) invalidate results | Check the split before analysis |
| **Interference** | In multiplayer, variants affect each other (matchmaking, economy, social) | Randomize by group/server/region |
| **Segment fishing** | Slicing until something is "significant" | Pre-register segments of interest |
| **Optimizing a proxy** | Higher short-term engagement may harm trust and long-term retention | Add long-horizon guardrails; apply the ethics checks in `references/09-monetization-and-live-ops.md` |
| **Local maxima** | A/B testing refines, it doesn't invent | Use qualitative work and design vision for new directions |

A/B tests tell you **which** variant performs better on a metric, not **why**, and they only evaluate options you thought of.

## 12. Interpreting Feedback

**Core rule: players are good at identifying problems and bad at identifying solutions.** Treat feedback as a symptom report from an expert on *their own experience*.

Translate each comment through four steps:

1. **Record verbatim** (quote, timestamp, player profile).
2. **Identify the underlying problem** ("add a map" -> "I get lost").
3. **Locate the cause in the design** (wayfinding? goals? level geometry? UI?).
4. **Choose your own fix** and test it.

| Player says | Possible real issue | Question to ask |
|---|---|---|
| "Make it harder / easier" | Wrong challenge curve, or unclear feedback on failure | "When did you feel bored/stuck, specifically?" |
| "Add more weapons" | Combat lacks variety or choice | "What did you want to do that you couldn't?" |
| "This is unfair" | Unclear telegraph, hidden rule, input latency | "What did you expect to happen?" |
| "I'm bored" | No tension, no new info, repetitive loop | "What was the last moment you were interested?" |
| "It's confusing" | Overloaded onboarding, poor information hierarchy | "What did you think you were supposed to do?" |
| "Needs a tutorial" | Mechanics not self-evident | Prefer redesigning for discoverability first |

Weigh feedback by:
- **Source relevance** (is the player in your target?).
- **Frequency** (how many independent players?).
- **Behavioral corroboration** (did they also *act* that way?).
- **Strength of emotion** (rage-quit vs mild preference).
- **Fit with pillars**: not every valid complaint should be fixed; some conflict with the pillars. Decide consciously.

Biases to watch: **politeness** (friends/family), **confirmation** (you remember what supports your view), **vocal minority** (forum and Discord skew toward hardcore), **survivorship** (you only hear from those who stayed), **recency** (latest session overweighted), **expert blindness** (the team's tolerance has shifted).

## 13. Triage: From Findings to a Prioritized Backlog

### 13.1 Steps

1. **Collect** all findings from sessions, surveys, telemetry, and bug reports into one list.
2. **Normalize** each as: *Observation -> Impact -> Location -> Evidence*.
3. **Deduplicate** and cluster by root cause (twelve "I died there" comments may be one wayfinding problem).
4. **Rate severity** (impact on the player) and **frequency** (share of players affected).
5. **Score priority** = severity x frequency, adjust for fix cost and risk.
6. **Assign** an owner and a next action: fix, experiment, retest, monitor, or consciously ignore (with reason).
7. **Verify** in the next round.

### 13.2 Severity x frequency matrix

Severity: 1 cosmetic, 2 minor, 3 major, 4 blocker (see 8.4). Frequency: 1 (<10% of testers), 2 (10-30%), 3 (30-60%), 4 (>60%) **(heuristic bands)**.

| | Freq 1 | Freq 2 | Freq 3 | Freq 4 |
|---|---|---|---|---|
| **Sev 4** | P1 | P1 | P1 | P1 |
| **Sev 3** | P2 | P1 | P1 | P1 |
| **Sev 2** | P3 | P2 | P2 | P1 |
| **Sev 1** | P4 | P3 | P3 | P2 |

P1 = fix before next test; P2 = fix this milestone; P3 = backlog; P4 = note/won't fix unless cheap.

Adjustments:
- Raise priority for problems in the **first 10 minutes** (they lose players before anything else matters) and on the **critical path**.
- Raise for issues affecting accessibility, safety, or legal compliance.
- Lower for issues with low user value that cost a lot to fix, but record the decision.
- Split big findings into a quick mitigation and a proper fix.

### 13.3 Backlog entry format

```
ID: PT-014
Finding: 6 of 8 testers did not notice the dash prompt in Level 2.
Severity/Frequency: 3 / 4 -> P1
Evidence: observation logs S1-S8; funnel step "dash_used" 31%
Hypothesis: prompt appears during combat when attention is elsewhere
Proposed experiment: move prompt to calm pre-combat moment; add required gap to cross
Owner / due: [name] / [date]
Retest plan: next build, 5 fresh testers; success = dash used by 5 of 5 in 2 minutes
Status: Open
```

## 14. Diagnosing Fun Problems from Data

Combine telemetry with observation. Form a hypothesis, check a second source, run an experiment.

| Symptom (data) | Likely cause | Verify with | First fix to try |
|---|---|---|---|
| Large drop in the tutorial funnel at step N | Confusing step, text wall, forced wait, bug | Watch recordings at step N; time per step | Cut text, show-don't-tell, shorten the wait |
| D1 retention low, tutorial completion high | No hook after tutorial; first goal unclear | Interviews with D1 churners; "last event before churn" | Give a clear short-term goal and early reward |
| D1 fine, D7 collapse | Progression plateau, no mid-term goals | Funnel across levels; playtime-to-churn | New goals, variety, social or meta hooks |
| Spike in failures/retries at one level | Difficulty spike, unfair mechanic | Death heatmap, cause-of-death split | Telegraph, checkpoint, resource gift, tune enemy |
| Deaths cluster at a spot, but players pass on retry | Surprise (learn-by-dying) | Failure count distribution | Add foreshadowing or accept as a designed "gotcha" |
| Quit right after death | Retry cost too high | Time-to-retry; session end events | Faster restarts, fewer lost items |
| Wide spread in completion time | Players take different routes, or some are lost | Path analysis | Landmark, sightline, gating |
| Low use of a feature | Not discovered, not needed, not rewarding | Observation; unlock timing; funnel to feature | Surface in critical path once; make it solve a felt need |
| One item/class/strategy dominates (pick rate x win rate) | Cost-curve outlier | Matchup tables, cost curve | Nerf outlier, buff underused, one variable at a time |
| Currency balances only rise | Faucets > sinks | Source/sink flow chart | Add sinks, cap, rebalance (see `references/04-balance-and-economy.md`) |
| Session length short with many sessions | Fits "snack" play but no deeper hook | Cohort comparison | Consider session-spanning goals |
| High engagement, low satisfaction scores | Compulsion loops without payoff | GEQ/PENS, sentiment | Reduce friction-to-reward manipulation; revisit pillars |

Process for any data-driven investigation:
1. State the question and what result would change your mind.
2. Segment (new vs returning, platform, skill, source, build).
3. Look for the **outlier** location, step, or segment.
4. Triangulate with observation or interview.
5. Run the smallest experiment that could falsify your explanation.
6. Re-measure with the same definition.

Caveat: correlation is not causation. Players who use feature X may retain better simply because they were more engaged to begin with.

## 15. Playtest Report Structure

Aim for a report a busy producer can act on in 5 minutes. Full template in `templates/playtest-plan.md`.

1. **Summary (top of page)**: build, dates, number and profile of participants, 3-5 headline findings, top recommended actions.
2. **Research questions and answers**: each question with a short verdict (answered / partially / inconclusive).
3. **Method**: tasks, tools, instruments (survey, telemetry), deviations from plan.
4. **Participants**: table of profiles (no personal data).
5. **Findings by priority**: for each: description, evidence (quotes, timestamps, counts), severity, frequency, probable cause, recommendation. Include clips/screenshots.
6. **What worked**: protect strengths (no one tests only to find faults).
7. **Quantitative results**: survey scores, completion rates, time on task; with sample size and caveats.
8. **Recommendations and next experiments**.
9. **Open questions and next test plan.**
10. **Appendix**: raw observations, questionnaires, data tables.

Reporting rules: lead with the finding, not the narrative; separate fact from interpretation; use counts ("5 of 8") not adverbs ("many"); never present survey means from tiny samples as precise.

## 16. Common Pitfalls

- Testing without a question; "let's see what they think".
- Helping the player in the session, or explaining the game beforehand.
- Using only friends and family, or only the hardcore community.
- Treating one tester's strong opinion as a trend; or ignoring a clear pattern because it hurts.
- Implementing player-suggested solutions without understanding the problem.
- Asking leading questions in surveys, or too many questions.
- Reading telemetry without definitions (what counts as a session? active player?).
- Instrumenting too late; no baseline to compare with.
- A/B testing without sample-size planning; peeking; shipping noise.
- Overfitting to the current cohort and losing the design vision (pillars exist to resolve this).
- Not retesting fixes.
- Testing too late, when the cost of change is high.
- Reporting problems only; teams stop attending when sessions are only bad news.

Quick start (small team, no budget): five fresh testers per build, silent play with screen recording, 6-question survey, 1 tag-based observation log, 30-minute team debrief, one prioritized list of at most 5 fixes, retest next week.

## 17. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Books**
- Seif El-Nasr, M., Drachen, A., Canossa, A. (eds.), 2013, *Game Analytics: Maximizing the Value of Player Data*, Springer. ISBN 978-1-4471-4768-8. https://doi.org/10.1007/978-1-4471-4769-5
- Drachen, A., Mirza-Babaei, P., Nacke, L. (eds.), 2018, *Games User Research*, Oxford University Press. ISBN 978-0-19-879484-4. https://global.oup.com/academic/product/games-user-research-9780198794844
- Nielsen, J., 1993, *Usability Engineering*, Academic Press (heuristic evaluation, severity ratings).
- Krug, S., 2010, *Rocket Surgery Made Easy*, New Riders (lightweight usability testing). ISBN 978-0-321-65729-9.
- Schell, J., 2019 (3rd ed.), *The Art of Game Design: A Book of Lenses*, CRC Press (playtesting lenses). ISBN 978-1-138-63205-9.
- Fullerton, T., 2018 (4th ed.), *Game Design Workshop*, CRC Press (playtesting chapters). ISBN 978-1-138-09877-0.

**Papers and articles**
- Medlock, M. C., Wixon, D., Terrano, M., Romero, R., Fulton, B., 2002, "Using the RITE Method to Improve Products: A Definition and a Case Study", Usability Professionals Association Annual Conference (Microsoft). No stable URL verified; the method is also described in Medlock, M. C., 2018, "The Rapid Iterative Test and Evaluation Method (RITE)", in *Games User Research*, OUP, https://doi.org/10.1093/oso/9780198794844.003.0013
- Desurvire, H., Caplan, M., Toth, J. A., 2004, "Using Heuristics to Evaluate the Playability of Games", CHI '04 Extended Abstracts, ACM. https://doi.org/10.1145/985921.986102
- IJsselsteijn, W. A., de Kort, Y. A. W., Poels, K., 2013, *The Game Experience Questionnaire*, Eindhoven University of Technology. https://pure.tue.nl/ws/files/21666907/Game_Experience_Questionnaire_English.pdf
- Ryan, R. M., Rigby, C. S., Przybylski, A., 2006, "The Motivational Pull of Video Games: A Self-Determination Theory Approach", *Motivation and Emotion* 30, 344-360. https://doi.org/10.1007/s11031-006-9051-8
- Nielsen, J., 2000, "Why You Only Need to Test with 5 Users", Nielsen Norman Group. https://www.nngroup.com/articles/why-you-only-need-to-test-with-5-users/
- Nielsen, J., 2012, "Thinking Aloud: The #1 Usability Tool", Nielsen Norman Group. https://www.nngroup.com/articles/thinking-aloud-the-1-usability-tool/
- Nielsen, J., 1994, "10 Usability Heuristics for User Interface Design", Nielsen Norman Group. https://www.nngroup.com/articles/ten-usability-heuristics/
- Nielsen Norman Group, "How to Conduct a Heuristic Evaluation". https://www.nngroup.com/articles/how-to-conduct-a-heuristic-evaluation/
- Miller, E., 2010, "How Not To Run an A/B Test". https://www.evanmiller.org/how-not-to-run-an-ab-test.html
- Miller, E., "Sample Size Calculator (A/B tests)". https://www.evanmiller.org/ab-testing/sample-size.html
- Thompson, C., 2007, "Halo 3: How Microsoft Labs Invented a New Science of Play", *Wired*. https://www.wired.com/2007/08/ff-halo-2/

**GDC talks**
- Zoeller, G., 2010, "Development Telemetry in Video Games Projects", GDC (BioWare Austin/EA). https://www.gdcvault.com/play/1012434

**Related skill files**: `references/01-design-process.md`, `references/05-progression-difficulty-onboarding.md`, `references/08-player-psychology-ux-accessibility.md`, `references/09-monetization-and-live-ops.md`, `templates/playtest-plan.md`.

See references/13-bibliography.md for the master list.
