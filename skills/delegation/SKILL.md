---
name: delegation
description: Plan and delegate jobs across Claude and Codex subagents and ElevenLabs tools, choosing model tier and thinking effort per unit, running independent units in parallel and keeping token use low. Use for any task with 2+ independent parts, bulk reading, code changes across files, or audio work; skip for quick single-step answers.
---

# Delegation

Goal: finish the job as fast as possible at the lowest token cost that still meets
the quality bar. Speed comes from running independent units in parallel. Savings come
from routing each unit to the cheapest tier and lowest effort that will get it right
the first time, and from keeping every context small.

## 1. Decide whether to delegate
Do it yourself when the task is one or two steps, needs the full conversation, or the
brief would be longer than the work. Delegate when parts are independent, when there
is much more to read than to return, when code must be written and tested, or when
audio is needed.

## 2. Plan
- Split the job into units, each with one clear output. Map dependencies; every unit
  without one goes in the first wave.
- Size units so each does meaningful work: batch tiny items (e.g. 20–50 records per
  extraction unit) instead of one subagent per item.
- Write the plan as a table: unit, job type, route, effort, inputs, output format,
  depends on, estimated cost. Show it to the user first only if the estimate exceeds
  `confirm_over_usd`, an effort above high is needed, or the session is in Plan mode.

## 3. Route
Use the table below as the default, then prefer what `delegation_stats` shows works
best for that job type (highest success rate at lowest average cost). Cross-model
review is deliberate: when Codex writes code, Claude reviews it, and when Claude
writes code, Codex can write the tests.

| # | Job type | Route | Effort | Parallelize | Brief must include | Returns | Escalate to |
|---|---|---|---|---|---|---|---|
| 1 | Extract, reformat, classify, rename, fill structured fields | claude.fast | low | Yes, batches of 20–50 items | Schema, 1–2 examples | JSON matching schema | claude.standard, low |
| 2 | Summarize or scan many docs/pages (map step) | claude.fast; claude.standard for dense technical text | low | Yes, one unit per doc or chunk group | Paths/IDs, what to look for, length cap | ≤150-word bullets with locations | claude.standard, medium |
| 3 | Search or map a codebase ("where is X", call graphs) | claude.fast, read-only tools | low | Yes, one unit per top-level directory | Question, directories, read-only | Paths + line refs + 1-line notes | claude.standard, low |
| 4 | Web or doc research on one subtopic | claude.standard | low (medium if sources conflict) | Yes, one unit per subtopic | Question, scope, source quality bar | Findings with sources | claude.standard, medium |
| 5 | Small mechanical code edits (renames, lint fixes, types, boilerplate) | codex.fast | low | Yes, one unit per file group, separate worktrees | Exact change, files, check command | Diff summary + check result | codex.standard, low |
| 6 | Implement a well-specified feature or fix with tests | codex.standard (codex.cli for multi-file work) | medium | Yes, one unit per independent module, separate worktrees | Spec, files, acceptance tests, test command | Diff summary + test results | codex.standard, high → claude.deep, medium |
| 7 | Write tests for existing code | codex.standard | low | Yes, one unit per module | Files, framework, coverage target | Test files + pass/fail | codex.standard, medium |
| 8 | Debug a failing test or CI job with a reproducible error | codex.cli | medium | No (one unit), unless several unrelated failures | Repro command, error log, suspected area | Root cause + fix + passing run | codex.cli, high → claude.deep, medium for diagnosis |
| 9 | Large refactor or migration | Plan: claude.deep. Execute: codex.cli. Review: claude.standard | Plan medium, execute medium, review medium | Execute slices in parallel worktrees | Plan with slice boundaries and invariants | Merged diff + review findings | Re-plan with claude.deep, high |
| 10 | Code or security review of a diff | claude.standard | medium | Yes for big diffs, one unit per file group | Diff, what matters (security, perf, style) | Issues list with severity and line refs | claude.deep, medium |
| 11 | Frontend/UI build or polish | claude.standard | medium | Yes, one unit per independent component | Design constraints, components, screenshots | Diff + screenshot | claude.deep, medium |
| 12 | Data analysis with code (pandas, charts) | codex.standard | low (medium for modeling) | Yes, one unit per independent question | Data path, questions, output format | Numbers + chart files + code | claude.standard, medium |
| 13 | Algorithm design, math, proofs | claude.deep (codex.standard high when results can be checked by running code) | medium | Only to try 2 genuinely different approaches | Problem, constraints, how to verify | Solution + verification | high (ask before anything above) |
| 14 | Architecture, ambiguous specs, trade-off decisions | claude.deep | high | No | Goals, constraints, options considered | Recommendation + reasons + risks | Ask the user |
| 15 | Writing: docs, READMEs, explanations, emails | claude.standard | low | Yes, one unit per section with a shared outline | Audience, outline, tone, length | Text per section | claude.standard, medium |
| 16 | Image or screenshot understanding | claude.standard | low | Yes, one unit per image group | Images, what to extract | Structured findings | claude.deep, low |
| 17 | Verification (schemas, tests, fact spot-checks) | No model when a deterministic check exists; else claude.fast | low | Yes | Criteria, item to check | Pass/fail + reason | claude.standard, low |
| 18 | Final synthesis or reconciling conflicting results | Orchestrator itself; claude.deep if conflicts are deep | medium | No | Compact results only | Final answer | Ask the user |
| 19 | Narration, voiceover, read-aloud | Script: claude.standard, low. Audio: ElevenLabs `tts` | n/a | Yes, one call per paragraph or scene | Text, voice, model, format | Audio item IDs | n/a |
| 20 | Transcribe audio or video | ElevenLabs `transcribe`, then claude.fast low to summarize | n/a | Yes, one call per file | File, language, speaker labels | Transcript item ID + summary | claude.standard for summary |
| 21 | Sound effects or music | Prompt: claude.fast, low. Audio: ElevenLabs `sound_effect` / `music` | n/a | Yes, one call per cue | Description, duration | Audio item IDs | n/a |

## 4. Choose thinking effort
- Allowed without asking: the provider's lowest/no-thinking setting (only for
  trivial mechanical work), low, medium, high.
- Start from the table. Use low when the spec is exact and the output is checkable;
  medium for multi-step code or judgment; high for hard reasoning, unclear bugs, or
  design decisions.
- Never use a level above high (e.g. "xhigh", "max") on your own. Call
  `request_effort_approval` only when high has already failed on this unit, or the
  task is clearly beyond high and the result matters. Explain why and give the
  estimated extra cost and time, then wait for the answer. If declined, run at high
  or re-scope.
- On failure: if the attempt was on the right track but shallow, raise effort one
  level on the same tier. If it lacked capability or knowledge, move one tier up at
  the same effort. At most two escalation steps per unit, then report to the user.

## 5. Parallelize
- Launch every unit in a wave at once, in the background, up to `max_parallel` per
  provider. Back off and queue on rate-limit errors instead of retrying in a loop.
- One writer per file. Parallel code units always get their own git worktree; merge
  after the wave, and resolve conflicts with codex.fast (low) or yourself.
- Don't parallelize steps that depend on each other's reasoning. Run 2 competing
  attempts only for high-stakes units where the approach is genuinely uncertain.
- While a wave runs, do independent work yourself (prepare the next wave's briefs,
  merge finished results).
- Stop remaining units early when results already answer the question or show the
  plan was wrong.

## 6. Keep tokens low
- Briefs are self-contained and short (aim under 300 words): goal, inputs, constraints,
  done criteria, output format. No conversation history.
- Pass paths, URLs or item IDs instead of contents when the subagent can read them.
- Put shared instructions first and keep them identical across units so prompt
  caching applies.
- Require structured, length-capped output with no narration or restating of the task.
- Grant only the tools each unit needs; read-only where possible.
- Never pull full subagent transcripts into your context; read only the final result.
- Before launching, check `items` and earlier results for work already done; skip
  duplicate units.
- Prefer deterministic checks (tests, schema validation) over a model call.

## 7. Record
After the job, write one row per unit to `delegation_stats`: job type, provider, tier,
model, effort, input/output/reasoning tokens, characters (ElevenLabs), cost, wall
time, success, escalation steps, approval requested. Step 3 reads these, so routing
improves over time.

## Budget
Stay within session and job caps. If a plan would exceed `job_budget_usd`, shrink the
scope or ask the user.
