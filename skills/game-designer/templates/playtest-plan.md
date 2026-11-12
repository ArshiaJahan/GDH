# Playtest Plan: [Game / Build / Round]

> A complete kit: plan, session script, survey, observation sheet, and report. Copy the parts you need. One plan per round of testing. Delete guidance lines (starting with `>`) when filling in. Method background: `references/12-playtesting-and-analytics.md`.

| Field | Value |
|---|---|
| Game / build version | [Title, build 0.4.2, commit/hash] |
| Round ID / date(s) | [PT-05, YYYY-MM-DD to YYYY-MM-DD] |
| Test lead / facilitator(s) / note-takers | [names] |
| Location / format | [lab / remote moderated / unmoderated / event] |
| Status | [Planned / Running / Reported] |

## Table of Contents

1. [Plan](#1-plan)
2. [Session Script](#2-session-script)
3. [Survey Template](#3-survey-template)
4. [Observation Sheet](#4-observation-sheet)
5. [Interview Guide](#5-interview-guide)
6. [Analysis and Triage](#6-analysis-and-triage)
7. [Report Template](#7-report-template)
8. [Logistics Checklist](#8-logistics-checklist)
9. [Further Reading](#9-further-reading)

---

## 1. Plan

### 1.1 Objectives and research questions

> 1-3 questions the test must answer. Each should be answerable from observation, survey, or telemetry, and should lead to a decision.

| # | Research question | Decision it informs | Evidence source (observe / survey / telemetry) | Success criterion |
|---|---|---|---|---|
| RQ1 | [Can first-time players complete the tutorial without help?] | [Keep or rewrite tutorial] | [Observation + telemetry] | [>= 5 of 6 finish within 8 min, 0-1 assists] |
| RQ2 | [Do players understand the goal of Level 1?] | [Add objective marker?] | [Think-aloud + comprehension question] | [>= 5 of 6 state the goal correctly] |
| RQ3 | [Do they want to play again?] | [Pillar validation] | [Survey + interview] | [Mean "want to continue" >= 4.0/5] |

### 1.2 Hypotheses and risks being tested

> Write what you expect and what would surprise you. It guards against confirmation bias.

- **Expect:** [ ]
- **Would change our mind:** [ ]
- **Riskiest assumption under test:** [ ]

### 1.3 Build and scope

- **Build contents (what is in/out):** [ ]
- **Known bugs and workarounds (do not test these):** [ ]
- **Debug aids (skip level, reset):** [ ]
- **Test type:** [internal / friends / kleenex fresh testers / targeted lab / focus / closed beta / open beta / soft launch]
- **Method(s):** [observed think-aloud / silent play + retrospective / RITE / survey / telemetry / A/B]

### 1.4 Participants

> Define profile, count, screener, and incentives. Use fresh testers for first-time experience.

| Segment | Definition (behavioral) | Count | Fresh (never seen game)? | Recruited via |
|---|---|---|---|---|
| Novice | [Plays <= 2 hrs/week; no genre experience] | [3] | Yes | [ ] |
| Core | [Plays genre weekly] | [3] | Yes | [ ] |

- **Screener questions (non-leading):** [e.g., "Which of these games have you played in the last 3 months?" (include decoys)]
- **Exclusions:** [industry insiders, team friends, previous testers]
- **Over-recruit:** [+20-30% for no-shows (heuristic)]
- **Incentive:** [ ]
- **Consent and legal:** [recording consent, NDA, minors, data privacy, right to stop at any time]

### 1.5 Tasks and scenarios

> Tasks that elicit behavior, phrased as goals not instructions. Include free-play time.

| # | Task (as read to the player) | Expected path | Success criterion | Time cap | Hint policy |
|---|---|---|---|---|---|
| T0 | "Play the game however you like for 15 minutes." | Free play | n/a | 15 min | None |
| T1 | "Get to the end of the first area." | [Tutorial route] | Reaches exit | 8 min | Hint after 3 min stuck; log as assist |
| T2 | "Defeat the first boss." | [ ] | Boss dead | 10 min | After 5 deaths ask what they think they should try |

### 1.6 Data to collect

| Data | Method | Tool | Owner |
|---|---|---|---|
| Behavior notes with timestamps | Observation sheet (Section 4) | [spreadsheet] | Note-taker |
| Screen + audio (+ face/controller) | Recording | [OBS] | Facilitator |
| Telemetry events | In-game logging | [analytics tool] | Engineer |
| Survey scores | Questionnaire (Section 3) | [form tool] | Test lead |
| Interview notes | Guide (Section 5) | Audio recording | Facilitator |

**Telemetry events required for this round:** [`tutorial_step_completed`, `player_died` (position, cause), `hint_shown`, `session_end`]. Verify they fire before the first session.

### 1.7 Schedule and roles

| Time | Activity | Who |
|---|---|---|
| [T-1 week] | Recruit, build lock | [ ] |
| [T-1 day] | Pilot session with colleague; fix script/setup | [ ] |
| [Day 1-2] | Sessions (slots: 90 min incl. buffer) | [ ] |
| [Day 3] | Debrief + triage meeting | [ ] |
| [Day 5] | Report circulated | [ ] |

- **Stop rules:** [halt the round if a blocker bug prevents all play; for RITE, fix and continue]
- **Analysis plan:** [how data will be coded; who reviews; how disagreements are resolved]

## 2. Session Script

> Read verbatim where possible, so every participant gets the same experience. Keep neutral tone. Adjust brackets. Typical length 60-90 minutes (heuristic).

### 2.1 Setup (before participant arrives)

- [ ] Build loaded from clean state; profile reset; correct version verified
- [ ] Recording running; audio levels checked; backup recorder
- [ ] Controller/mouse paired and charged; seat and display comfortable
- [ ] Observers in position out of the player's sightline
- [ ] Consent forms, survey link, and incentive ready
- [ ] Phones silenced; water available

### 2.2 Welcome and consent (5 min)

> "Thanks for coming. We're testing a game in development, and we're testing the game, not you. You can't do anything wrong, and your honest reactions, good or bad, help us most. You can stop at any time. We'll record the screen and your voice so we can review later; the recording is only used by the team. Is that OK? [Collect signed consent.]"

### 2.3 Background questions (5 min)

1. "What games do you play regularly? On which devices?"
2. "How many hours per week do you play?"
3. "What was the last game you enjoyed, and what did you like about it?"
4. "Have you seen or heard anything about this game?" (note; exclude if familiar)

### 2.4 Think-aloud briefing (2 min)

> "While you play, please say out loud what you're looking at, what you're trying to do, and what you expect to happen. If you go quiet, I may ask what you're thinking. I might not answer questions during play, because I want to see how the game works on its own; I'll note your questions and come back to them at the end. Let's try with a quick warm-up: think aloud while you describe how you'd make a cup of tea." [Optional practice]

### 2.5 Free play (15-30 min)

> "Please start playing however you like. Play as you would at home." [Do not explain the game. Start observation sheet timer.]

Allowed prompts when silent 10-15 s (heuristic): "What are you thinking?" / "What are you looking at?" / "What do you expect to happen?"
Forbidden: hints, confirmations ("good"), explanations, defending the design, "Did you notice...?"

### 2.6 Guided tasks (10-20 min)

> Read each task from Section 1.5. After each task: "On a scale from 1 (very hard) to 7 (very easy), how easy was that?" and "Why that number?" (Single Ease Question variation.)

Intervention protocol: if stuck beyond the time cap: (1) say "What would you try next?" (2) after 1 more minute, give a graded hint ("Look at the objects on the left"); (3) then show the solution and move on. Log every step as an assist with timestamp.

### 2.7 Survey (5-10 min)

> "Now I'd like you to fill out a short questionnaire. Please answer honestly. There are no right answers." [Facilitator leaves the room or stays quiet.]

### 2.8 Debrief interview (10-15 min)

> Use the guide in Section 5.

### 2.9 Close (2 min)

> "Thank you. Please don't share details of what you've seen until [date]. [Hand incentive.] Is there anything else you'd like to tell us that we haven't asked?"

### 2.10 After the session (immediately)

- [ ] Save recordings and files with ID (P03_build042)
- [ ] Facilitator and note-taker write top-5 observations within 15 minutes
- [ ] Mark severe issues for RITE-style fix, if applicable
- [ ] Reset build and workstation

## 3. Survey Template

> Keep it under 10 minutes. Randomize item order when comparing builds. Use neutral language and one idea per question. Scale: 1 = Strongly disagree ... 5 = Strongly agree unless noted. Wording can be adapted; for validated instruments (GEQ, PENS) use the original items and scoring from the authors.

### 3.1 Participant ID and context

- Participant ID: [P__]  Build: [ ]  Date: [ ]
- Age range: [ ]  Gender (optional): [ ]  Primary platform: [ ]
- Hours per week playing games: [ ]  Favorite genres: [ ]

### 3.2 Overall experience

| # | Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| S1 | I enjoyed playing this game. | o | o | o | o | o |
| S2 | I want to keep playing. | o | o | o | o | o |
| S3 | I lost track of time while playing. | o | o | o | o | o |
| S4 | There were moments when I was bored. | o | o | o | o | o |
| S5 | There were moments when I was frustrated. | o | o | o | o | o |

### 3.3 Clarity and control

| # | Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| C1 | I always knew what my goal was. | o | o | o | o | o |
| C2 | I knew what to do next. | o | o | o | o | o |
| C3 | The controls felt responsive. | o | o | o | o | o |
| C4 | I could tell whether my actions worked. | o | o | o | o | o |
| C5 | When I failed, I understood why. | o | o | o | o | o |
| C6 | The information on screen was easy to read. | o | o | o | o | o |

### 3.4 Challenge and pacing

| # | Question | Response |
|---|---|---|
| D1 | The difficulty was... | much too easy / too easy / about right / too hard / much too hard |
| D2 | The game's pace was... | much too slow / slow / about right / fast / much too fast |
| D3 | The game felt fair. (1-5) | o o o o o |
| D4 | I felt I was getting better as I played. (1-5) | o o o o o |

### 3.5 Feature-specific (replace per round)

| # | Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| F1 | [I understood how the dash works.] | o | o | o | o | o |
| F2 | [Using the dash felt satisfying.] | o | o | o | o | o |
| F3 | [I had different options for dealing with enemies.] | o | o | o | o | o |

### 3.6 Open questions (answer in your own words)

1. In your own words, what is this game about?
2. What was the most memorable moment?
3. What was the most frustrating or confusing moment?
4. Was there something you wanted to do but couldn't?
5. What, if anything, would you tell a friend about this game?

### 3.7 Optional standardized instruments

| Instrument | Use when | Note |
|---|---|---|
| Game Experience Questionnaire (GEQ, core module) | Comparing builds on competence, flow, tension, challenge, affect | Use original items and scoring |
| PENS | Evaluating motivation (competence, autonomy, relatedness) | Original items |
| SUS | Menus / UI usability | 10 items |
| Single Ease Question (SEQ) | Per-task difficulty | 1-7 scale after each task |

### 3.8 Survey design checklist

- [ ] Every question maps to a research question
- [ ] No leading, loaded, or double-barreled wording
- [ ] Scales labeled and consistent; neutral midpoint included
- [ ] Concrete questions before abstract; open text last
- [ ] No questions about purchase intent unless you have a plan to interpret them (stated intent predicts behavior poorly)
- [ ] Piloted for length and clarity

## 4. Observation Sheet

> One sheet per participant. Log facts with timestamps, tag them, and keep interpretation in the right-hand column. Use the same tag set across participants so counts can be aggregated.

**Tags:** `CONFUSION` `WAYFINDING` `CONTROLS` `UI` `DIFFICULTY` `FAIRNESS` `BORED` `DELIGHT` `BUG` `ASSIST` `EXPLOIT` `QUIT-RISK` `COMMENT`

| Participant | Build | Date | Observer |
|---|---|---|---|
| [P__] | [ ] | [ ] | [ ] |

### 4.1 Timeline log

| Time | Where / task | Observation (fact) | Quote (verbatim) | Tag | Severity (0-4) | Hypothesis (interpretation) |
|---|---|---|---|---|---|---|
| 00:03:10 | Tutorial step 2 | Presses jump 4x at ledge, no movement | "Why isn't it working?" | CONTROLS | 3 | Ledge grab not signaled |
| 00:07:45 | Hub | Smiles, says "oh nice" after upgrade | "Oh, that feels better" | DELIGHT | - | Upgrade feedback strong |
| | | | | | | |

### 4.2 Task outcomes

| Task | Completed (Y/N/Assisted) | Time (mm:ss) | Errors / deaths | Assists (count, timestamps) | Ease rating (1-7) | Notes |
|---|---|---|---|---|---|---|
| T1 | | | | | | |
| T2 | | | | | | |

### 4.3 Behavior checklist (tick when seen, add timestamps)

- [ ] Hesitated more than 5 s at a decision point: ______
- [ ] Repeated the same failed action 3+ times: ______
- [ ] Wandered or backtracked: ______
- [ ] Ignored a key item/UI element: ______
- [ ] Skipped or did not read tutorial text: ______
- [ ] Asked the facilitator a question: ______ (exact question)
- [ ] Used a mechanic in an unintended way: ______
- [ ] Expressed delight (smile, laugh, "one more try"): ______
- [ ] Expressed boredom (sigh, phone, slumped): ______
- [ ] Expressed frustration (swearing, throwing controller, long silence): ______
- [ ] Wanted to quit or asked how long left: ______

### 4.4 Emotional curve (optional)

Every 5 minutes, circle the visible state: `Bored (1) - Neutral (2) - Engaged (3) - Excited (4) - Frustrated (X)`

| Minute | 5 | 10 | 15 | 20 | 25 | 30 |
|---|---|---|---|---|---|---|
| State | | | | | | |

### 4.5 Top 5 takeaways (written within 15 minutes of the session)

1. 
2. 
3. 
4. 
5. 

## 5. Interview Guide

> Open, non-leading, chronological. Use the recording as a memory prompt. Do not defend the design.

1. "Tell me about the game as if I'd never seen it." (listen for comprehension)
2. "What were you trying to do?" (goal clarity)
3. "What was your favorite moment? What made it so?"
4. "What was the most frustrating or confusing moment? What did you expect to happen?"
5. "I noticed that at [time] you [behavior]. What were you thinking?" (probe 3-5 observed moments)
6. "How did the difficulty feel at the start / middle / end?"
7. "Explain how [mechanic] works." (comprehension check)
8. "What would you do next if you continued playing?" (motivation/goals)
9. "What games does this remind you of? Better or worse than them in what way?"
10. "Who would you recommend this to?" 
11. "Is there anything we haven't asked that you'd like to tell us?"

**Do not ask:** "Did you like the [feature]?" (leading); "Would you buy it?" (unreliable); "What should we add?" (solutions; ask about unmet goals instead).

## 6. Analysis and Triage

1. **Collate:** merge observation logs, survey data, telemetry, and interview notes by research question.
2. **Count:** how many of N participants showed each issue (use counts, not adverbs).
3. **Cluster by root cause:** merge duplicates (several "I died here" notes may be one wayfinding problem).
4. **Rate severity (0-4) and frequency (1-4):**
   - Severity: 0 not a problem, 1 cosmetic, 2 minor, 3 major, 4 blocker.
   - Frequency: 1 (<10% of testers), 2 (10-30%), 3 (30-60%), 4 (>60%) (heuristic bands).
5. **Prioritize** with the matrix (P1 fix before next test; P2 this milestone; P3 backlog; P4 note):

| | Freq 1 | Freq 2 | Freq 3 | Freq 4 |
|---|---|---|---|---|
| Sev 4 | P1 | P1 | P1 | P1 |
| Sev 3 | P2 | P1 | P1 | P1 |
| Sev 2 | P3 | P2 | P2 | P1 |
| Sev 1 | P4 | P3 | P3 | P2 |

6. **Translate feedback to problems, not solutions** (players are good at finding problems and poor at prescribing fixes): record the underlying need, then propose your own fix.
7. **Protect what works:** list strengths so they are not "fixed" by accident.
8. **Plan the retest:** every P1/P2 fix gets a verification step in the next round.

**Findings log:**

| ID | Finding (observation) | Evidence (n of N, clips) | Severity | Frequency | Priority | Probable cause | Proposed fix / experiment | Owner | Retest |
|---|---|---|---|---|---|---|---|---|---|
| PT05-01 | [ ] | [ ] | | | | | | | |

## 7. Report Template

> Executive summary first; the reader should be able to stop after page one. Facts and counts, then interpretation. Include clips and screenshots.

### Playtest Report: [Game], Round [ID], Build [version]

**Date(s):** [ ] **Participants:** [N, profile summary] **Author:** [ ]

#### 7.1 Executive summary

- **Overall verdict:** [One or two sentences.]
- **Top findings (3-5):**
  1. [Finding - evidence count - severity]
  2. [ ]
  3. [ ]
- **What worked well:** [ ]
- **Recommended actions (P1 first):** [ ]
- **Decision requested:** [e.g., approve tutorial rewrite]

#### 7.2 Research questions and answers

| RQ | Answer | Confidence (high / medium / low) | Evidence |
|---|---|---|---|
| RQ1 | [ ] | [ ] | [ ] |
| RQ2 | [ ] | [ ] | [ ] |

#### 7.3 Method

- Test type, location, duration, tasks, instruments, build version.
- Deviations from plan and their effect.
- Limitations (sample size, build bugs, facilitator assists).

#### 7.4 Participants

| ID | Segment | Age range | Experience (genre) | Fresh? | Platform habits |
|---|---|---|---|---|---|
| P01 | Novice | [ ] | [ ] | Yes | [ ] |

#### 7.5 Findings (priority order)

> One block per finding.

**PT05-01: [Short title]** - Priority [P1] (Severity [3] x Frequency [4])
- **What happened:** [facts, with counts: "6 of 8 testers..."]
- **Evidence:** [quotes, timestamps, clip links, telemetry]
- **Why (probable cause):** [hypothesis]
- **Recommendation:** [fix or experiment, with expected effect]
- **Retest criterion:** [what success looks like]

#### 7.6 Quantitative results

| Measure | Result | n | Note / caveat |
|---|---|---|---|
| Tutorial completion | [ ] | [ ] | [ ] |
| Median time to complete Level 1 | [ ] | [ ] | [ ] |
| Mean "want to keep playing" (1-5) | [ ] | [ ] | [Small sample: indicative only] |
| Deaths per encounter (median) | [ ] | [ ] | [ ] |

> Show distributions or individual points for small n; avoid reporting means with false precision.

#### 7.7 Telemetry highlights

- Funnel: [step -> step conversion]; largest drop at [step].
- Heatmaps: [deaths, positions] with annotated images.
- Cohort/retention (if available): [D1/D7].

#### 7.8 Next steps

| Action | Owner | Due | Verification (next test) |
|---|---|---|---|
| [ ] | [ ] | [ ] | [ ] |

- **Open questions for the next round:** [ ]
- **Proposed next test:** [type, sample, focus, date]

#### 7.9 Appendix

Raw observation logs, survey data, interview notes, recordings index, tracking plan version.

## 8. Logistics Checklist

- [ ] Research questions written and agreed
- [ ] Build locked; tester accounts/devices prepared
- [ ] Telemetry verified in test build
- [ ] Screener written; participants recruited and scheduled; reminders sent
- [ ] Consent/NDA forms prepared; data handling plan agreed
- [ ] Pilot session completed and script revised
- [ ] Facilitator briefed on rules: do not help, do not lead, do not defend
- [ ] Recording and backups tested
- [ ] Observation sheets and tag set shared
- [ ] Debrief meeting booked within 48 hours
- [ ] Report template ready; retest planned

## 9. Further Reading

- `references/12-playtesting-and-analytics.md` (methods, RITE, surveys, telemetry, A/B tests, triage)
- `references/05-progression-difficulty-onboarding.md` (what to look for in onboarding and difficulty)
- `references/08-player-psychology-ux-accessibility.md` (accessibility testing)
- `templates/feature-spec.md` (acceptance criteria and test plan), `templates/level-design-doc.md` (playtest goals)
