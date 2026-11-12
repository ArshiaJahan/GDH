---
name: campaign
description: How to work inside a Workspace campaign or workflow chain - read the brief, work only on the current phase, log decisions, finish each phase with a HANDOFF block and campaign_phase_done (chain_step_done in a chain), ask through campaign_pause. Pinned in campaign and chain sessions.
runtime: workspace
---

# Working in a campaign or chain

This session belongs to a **campaign** (several sessions, a campaign file in the project) or a **chain** (one session, steps from a workflow template). Workspace runs the phases, checks them and hands the work from session to session. You do the work of the current phase.

## Start of a session
1. Read the first message (the campaign brief) and, for a campaign, the campaign file it names (`.workspace/campaigns/<slug>.md`). Call `campaign_status` whenever you need the phase, its checks or the next action.
2. Read PROJECT.md (conventions, ADRs, gotchas) and BACKLOG.md when they exist and the phase touches them.

## Planning (status planning)
- Fill the campaign file's **Design target** with end states as checkboxes (`- [ ] Death returns to Title in < 3 s`). Never deltas ("improve X", "refactor Y", "make it faster"): those can't be checked and the validator sends them back.
- Fill **Scope** (`Stories:` BACKLOG ids, `Claimed paths:`, `Out of scope (user-acknowledged):`) and **Constraints**.
- If the template's phases don't fit, pass your own to `campaign_submit_plan(phases=[...])`, same fields as a template phase (name, type, skills, done_when). Every phase needs a check the app can run itself.
- Call `campaign_submit_plan`. If it lists gaps, fix them and submit again. When it says the plan went to the user, end your turn.

## Executing a phase
- Work **only on the current phase**. The next phase starts with its own brief.
- Its skills are loaded for you; load others with `read_skill` only when needed.
- The phase's `done_when` conditions are checked by the app from observed results (gates, test runs, screenshots, files, git). Produce that evidence: run the compile gate (`run_gate`), tests, play-verify, the scripts the conditions name. A report that "it works" counts for nothing.
- Record decisions with `campaign_log(kind="decision", ...)`, surprises and facts later phases need with `kind="discovery"`, short context with `kind="note"`.
- Never edit the harness-owned sections of the campaign file by hand (Phases, Coverage, Feature ledger, Continuation state). You may edit Design target, Scope and Constraints while planning.
- Don't revert or reset work yourself; phase checkpoints exist and the user restores them.
- A **fleet-eligible** phase has a Fleet section in its brief: when the work splits into independent units with one folder each, run them as a wave with `run_wave(..., campaign_id=...)`, then `wave_status`, `merge_wave` and `close_wave` before declaring the phase done. The units' discoveries are added to the campaign file for you.
- Some workflows make a gate blocking (`campaign_status` lists them, e.g. `unity.antipatterns` in a performance pass): fix what it reports before you finish.

## Finishing a phase
When the phase's checks should pass, write a HANDOFF block in your reply and pass the same text to `campaign_phase_done` (in a chain: `chain_step_done`):

```
---HANDOFF---
- What: what this phase produced (files, stories, behaviour)
- Decisions: choices made and why (or none)
- Unresolved: what is left or risky (or none)
- Reversibility: how to undo it (e.g. revert commit abc123; delete Assets/Game/BossRush)
---
```

- If a check fails, the reply lists what is missing; fix it and call again. Each failure costs a retry; when they run out the campaign parks and the user decides.
- When the call says the next phase starts in a new session, or that the plan is with the user, end your turn.

## When you're blocked
Call `campaign_pause(reason, question)` and end your turn. The question goes to the user's Review queue. Don't end a turn with a question without pausing: autopilot treats a final question as waiting for the user.
