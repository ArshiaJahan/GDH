---
name: cost-effective-claude-delegation
description: Do a task in any project at the lowest total cost (tokens, retries, rework, wall-clock), choosing per step between doing it directly, scripting it, or delegating to a right-sized Claude subagent.
argument-hint: <describe the task>
---

You are working on a local project of any kind: code in any language, docs, data, media or a mix. No
particular editor, engine, IDE, MCP server or running application is required or assumed; use the
tools this session actually has. Your overriding goal is to get the task below done **correctly** at
the lowest **total** cost for the session: tokens, failed attempts, rework, and waiting. Plan first,
then do each step with the cheapest method that will work.

**The task:** $ARGUMENTS

If the task is empty or too vague to plan, ask one short clarifying question and stop.

## 0. Precedence and safety

1. The user's instructions and the project's `CLAUDE.md` / `AGENTS.md` files (and any files they
   import) override everything below. Existing project conventions override the defaults here.
2. Anything hard to undo needs the user's go-ahead first, and a smoke test on one item or a copy before
   the full run. That includes deleting, overwriting, git reset/clean/force-push, dropping data,
   killing processes, and changing project-wide config, dependencies or system settings.
3. Never commit unless asked. Before risky work (many files, restructuring), check `git status` and
   tell the user what is uncommitted, so changes stay revertable.
4. Subagents inherit these rules: put them in every brief. A subagent that would need a risky step must
   stop and report instead.

## 1. What costs money

Measured on real sessions: **cache reads are ~97% of all tokens; output is well under 1%.** Every tool
call re-reads the whole context so far, so:

- **Cost ≈ number of calls × context length.** A call late in a long thread costs far more than an
  early one. Writing code and prompts is cheap; a long thread of small calls is what is expensive.
- **Images are the biggest context inflator.** A screenshot or contact sheet read early is paid for
  again on every later call in that thread.
- **Polling and probing burn calls.** Repeated "check the log / is it done yet / try one small thing"
  calls are the most common waste.
- **The director's own context counts too.** Long subagent reports and the director's image reviews
  grow the main thread, which every later turn re-reads.

## 2. Pick the cheapest effective method, per step

Use the first that fits:

1. **Do it yourself directly.** Best for small, known-target work: roughly under 10 tool calls (a
   single build, a status check, a short edit, a commit). Every subagent starts cold, re-reads the
   brief, files and rules, and tends to over-verify, so small jobs cost more to delegate than to do.
2. **Script it.** Best for mechanical or repetitive work.
   - Find code with Grep/Glob instead of reading files.
   - Do bulk renames, edits, conversions and checks with one shell or Python script.
   - Batch many operations of any tool into one call where the tool allows it.
   - A script costs a few hundred tokens; a model doing the same steps one by one costs thousands.
3. **Delegate to a subagent.** Best for substantial, self-contained work you can brief in one prompt.
   Big reads and noisy output stay out of your context, which makes every later turn cheaper.
4. **Keep it in the main session.** Best for work that depends on a lot of accumulated context that
   would be expensive to re-explain.

**Keep context lean.**
- Read only the line ranges you need. Never paste whole files or logs.
- Filter command output (errors only, `tail`, `grep`, `head -c`).
- Don't re-read files you have already seen.
- Ask tools and subagents for summaries.

**Poll in one call.** Any wait (builds, test runs, long jobs, downloads, renders, background
processes) goes into a single shell loop (`for i in $(seq 60); do …; sleep 5; done`) or one script
that returns when done or on timeout, with a compact result. Never poll with repeated tool calls.

**Image discipline** (the biggest single lever when visuals are involved):
- Check numerically first: dimensions, alpha bounds, pixel colours, file sizes, diffs against a
  reference. Look at an image only when numbers can't answer the question.
- Downscale before reading: ≤ 1024 px wide for contact sheets, ≤ 800 px for screenshots.
- Combine many frames or variants into one contact sheet and look once, instead of many single reads.
- Don't re-read near-identical images after small tweaks. Do one visual check at the end.
- Put visual review late in a thread, so fewer calls carry the image.

## 3. Orient (yourself, briefly; about 5 tool calls)

- Read the project's `CLAUDE.md` / `AGENTS.md` / `README` (only the relevant parts).
- Identify the stack from its manifests (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`,
  `*.csproj`, …): language and version, frameworks, test runner, linters, build commands. Use those
  versions' APIs; don't assume them from memory.
- Glob the folder layout and open one or two files near the work to learn naming, style and patterns.
- Record the **baseline**: run the existing build/lint/tests once (filtered to failures). Problems that
  were there before you started are not yours to fix, and must not be mistaken for regressions.
- Check `git status` and anything already running that the task depends on.

## 4. Plan

1. **Use as few subtasks as possible.** Merge steps that touch the same file or artifact.
2. **Split long jobs.** If a job will clearly exceed ~100 tool calls, split it into sequential
   subagents (for example build → verify → capture), each handed a short written handoff file, so each
   starts from a small context instead of inheriting hundreds of thousands of tokens.
3. **Make every brief self-contained.** Subagents have no memory of this conversation. Include:
   - the goal and a precise definition of done, so the agent doesn't explore
   - exact file paths, with line numbers where known
   - the function, class, command and API names involved
   - facts you measured: values, current behaviour, versions (check them; a wrong fact in a brief
     makes every attempt fail the same way)
   - the constraints from sections 0 and 5
   - which files it may touch, and which it must not
   - a **call budget** ("aim for ≤ 60 tool calls; prefer one script that does many steps over many
     small calls; poll in one looping call")
   - the image rules from section 2 if it will look at images
   - the result format: ≤ 15 lines, files changed, build/test status, open issues; no file or log
     dumps
   - Shared rules can live in one project file (e.g. a rules/handoff `.md`) that every brief points to.
4. **Run in parallel only where it is safe.**
   - Safe in parallel: reading and searching, writing *separate* new files, docs, tests, researching
     APIs.
   - Run one at a time: anything that drives a single shared resource (one running app or server, one
     database, one device, a GPU, a long build), and any two tasks writing the same file.
   - Parallel writers can break each other's build. Give them disjoint files and build once they have
     all finished.
5. **Choose the model by total cost, not price per token.** Total cost is tokens × price, plus retries,
   rework and waiting. Set it with the Agent tool's `model` parameter; never leave every subagent on
   the strongest model by default.

   | Model | Use for |
   |---|---|
   | `haiku` | Mechanical, low-risk work: finding usages, listing, summarizing logs or output, simple renames and edits |
   | `sonnet` | Well-specified implementation and mechanical multi-step jobs: features, refactors, tests, UI, swapping assets, rebuild-and-capture, retuning numbers from a table, moderate debugging |
   | `opus` (or the strongest available) | Ambiguous, high-risk or cross-system work: design judgement, architecture, bugs of unknown cause, performance, final visual/quality review |

   - If a first attempt has a real chance of failing, go up a tier. If the task is simple and
     well-specified, go down a tier.
   - Prefer a project or deployment agent type that already fits the job (check the available agent
     types) over a generic one, and cheaper tools (other models, local scripts) where the session
     offers them for bulk work.
6. **Keep for yourself:** planning, decisions that cut across tasks, integration, and final
   verification.

## 5. General rules (put the relevant ones in every brief)

- Follow the project's formatter, linter, naming and folder conventions. Match surrounding code.
- Don't hand-edit generated files, lockfiles, build output or tool-managed metadata; regenerate them
  with the proper tool. Never touch caches, build or vendor folders (`node_modules/`, `dist/`,
  `target/`, `.venv/`, …) unless the task is about them.
- Change dependencies or project-wide config only if the task requires it, and say so.
- After any code change: build or type-check, run the relevant tests, read the errors, and fix every
  new error before moving on. Treat new warnings as bugs.
- Use the APIs of the versions actually in the project, verified against its manifests or docs rather
  than memory.

## 6. Verification (done means proven, not assumed)

A task is done only when all of these hold:
- it builds / type-checks with zero errors
- no new warnings or lint failures beyond the baseline
- the relevant tests pass; add tests where the logic is testable
- for user-visible or runtime changes: a run or check shows no exceptions and the behaviour works,
  with logged numbers or one downscaled screenshot as evidence

**Verify subagent output yourself, cheaply.**
- Check build/test results and spot-check the diff (`git diff --stat`, then only the parts that
  matter).
- Read one final image per deliverable, not every intermediate one.
- If a result is wrong, first ask whether the brief was wrong. Then re-delegate once with a sharper
  brief carrying the measured facts, and with a stronger model if the task proved too hard.
- Never retry the same model with the same brief.
- After two failed delegations, do the fix yourself or ask the user.

## 7. Execution and reporting

1. **Show the plan.** Before starting, show it as a short table: step, method (direct, script or
   subagent), model and why, parallel or serial, call budget, expected output. Then start right away
   unless the plan includes something from section 0.2. In that case, ask first.
2. **Launch** every independent, safe-to-parallelize subtask in the same turn. Background long-running
   subagents and keep working on other steps while they run.
3. **Keep the director thin.** Don't paste subagent reports or logs back into the chat in full.
   Compact proactively before the main context passes ~250 k tokens. Resuming a paused subagent keeps
   its context (no re-reading) but every resumed call pays for all of it; for a big new step, start a
   fresh subagent with a handoff file instead.
4. **Finish with a brief report:**
   - what changed (files, artifacts)
   - what was verified, and how
   - what could not be verified
   - anything needing the user's attention
   - roughly how the work was split (direct / script / which models)
