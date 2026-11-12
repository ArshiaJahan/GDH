---
name: high-performance-claude-delegation
description: Finish a task as fast and as well as possible by splitting it into independent units and running them all at once on Opus subagents (tier claude.deep, effort high), each code-writing unit in its own git worktree, then an independent Opus reviewer. Use when speed and quality matter more than cost; for cheap runs use the delegation skill instead.
runtime: workspace
---

# High-performance Claude delegation

Goal: the best result in the least wall-clock time. Every unit runs on the strongest
default route, `spawn_subagent` with provider `claude`, tier `claude.deep` (Opus 5.5
unless Settings maps the tier elsewhere) and effort `high`, and all independent units
run at the same time. Cost is secondary but still capped: stay inside the budgets.

## 1. Split
- Break the task into as many **genuinely independent** units as make sense: one per
  module, file group, question, document batch or subtopic. Each unit has one clear
  output and needs nothing from another unit's reasoning.
- Don't split for its own sake: a unit that needs another's result goes in a later
  wave, and work smaller than its brief is done by you directly.
- Add one final **reviewer** unit (also claude.deep, high) that checks the merged result
  against the original request. It never sees the other units' transcripts, only the
  task, the diff or output, and the check commands.

## 2. Plan and budget
- Write the plan as a table: unit, output, tools, worktree (yes/no), depends on,
  estimated cost. Estimate with `get_delegation_stats` for claude.deep @ high when it
  has rows; otherwise assume each Opus-high unit costs several times a standard one.
- Compare the total with the limits in your system prompt (`job_budget_usd`, session
  and daily caps). If it exceeds them, tell the user and shrink the scope (fewer or
  larger units, drop nice-to-haves) before launching. `spawn_subagent` refuses new
  units once the job budget is spent.
- If the estimate exceeds `confirm_over_usd`, show the table first and wait for the
  user's go-ahead. In Plan only mode, show the table and stop.

## 3. Launch everything at once
- In one turn, call `spawn_subagent` for every unit of the wave with
  `provider: "claude"`, `tier: "claude.deep"`, `effort: "high"`,
  `run_in_background: true`, a short `name`, a `job_type`, and a self-contained brief.
- The `claude_codex` pool (`max_parallel`, default 4, changeable in Settings) caps how
  many run at a time; extra units queue automatically and start as others finish.
  Launch them all anyway; don't hold units back to wait for a slot.
- Grant only the tools a unit needs: read-only units get the defaults
  (`read_file`, `list_dir`, `search`), research units add `web_search` and
  `web_fetch`, code units add `write_file`, `edit_file` and `run_command`.
- Every code-writing unit gets `worktree: true` (the session folder must be a git
  repo; if it isn't, run code units one after another instead).
- Never set effort above `high` yourself. If a unit truly needs more, call
  `request_effort_approval` and pass the returned `approval_token`.

## 4. Briefs
Aim under 300 words each: goal, inputs (paths, URLs, item IDs rather than contents),
constraints, done criteria, the check or test command, and the output format. Ask for a
compact, structured result: what changed, check results, open issues. No narration.
Keep shared instructions first and identical across units so caching applies.

## 5. Collect and merge
- While units run, prepare the next wave's briefs and the reviewer's brief.
- Collect with `get_subagent_result` (pass all `ids`; use `all: false` to act on the
  first finishers). Read only the compact results, never full transcripts.
- Merge each finished code unit with `merge_worktree`, one at a time. On a conflict,
  resolve it yourself or with one more claude.deep unit in a worktree.
- If a unit failed, re-brief it once at the same route with what went wrong; after
  that, report it instead of retrying.
- Stop remaining units early (`stop_subagent`) when results already answer the
  question or show the plan was wrong.

## 6. Review
Run the reviewer unit after the merges: it reads the result, runs the checks and
returns issues with severity and file/line references. Fix real issues (yourself or
with a targeted unit), then re-run the failing checks.

## 7. Record and report
- Call `record_unit_outcome` for every unit (success true/false after you checked
  its result), the reviewer included.
- Reply compactly: what was done, check results, the reviewer's verdict, total cost
  and time, and anything left open.
