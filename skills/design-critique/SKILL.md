---
name: design-critique
description: >
  Use when a Unity milestone exits, a juice-pass or release needs design review, or a BACKLOG.md story is marked '- Critique: yes'. Reviews fresh play-verify screenshots against the design target, player experience and TASTE.md with three independent reviewers.
---

# design-critique

Judge the completed design against its intended experience with three independent reviewers (L4 of the quality ladder).

## Inputs
- Story/AC IDs and acceptance criteria from `BACKLOG.md`, the design target and GDD pillars, and the scoped diff/stat.
- Project-root `TASTE.md`: three words, ranked heuristics, anti-patterns, references and hard constraints. If absent, draft it from [templates/TASTE.template.md](templates/TASTE.template.md) with game-designer and have the user settle the taste decisions before reviewing.
- Observed L1 compile, L2 behaviour tests and L3 play evidence for these subjects: `VERIFY.md`, logs/metrics and screenshots from `play-verify` under `Logs/harness/verify/<run-id>/shots/`.

## Rules
- **Design target, not delta.** Define done before iterating: write the intended player experience, observable acceptance conditions and numeric passing score before the first review. Judge the whole target, not whether this version is better than the last. If the passing score is unspecified, get the user's decision; this skill supplies no default threshold.
- **Layer, don't replace.** Build the new thing beside the old, verify it against the target, then remove the old only within the authorized scope. Preserve the working path until the replacement is proven; ask before destructive removal.
- **FRESH screenshots are mandatory.** Never critique without screenshots from play-verify newer than the last change to the files in scope. Check capture timestamps against changed-file mtimes, match story/AC IDs, and inspect the actual images. Missing, stale or unbound evidence requires a fresh play-verify run before review. Timeouts and partial runs do not prove a pass.
- Behavioural evidence wins: an L2/L3 FAIL overrides perceptual scores. Missing/skipped evidence cannot support PASS. An agent-written report alone is not observed evidence.

## Procedure
1. **Prepare.** Freeze the target and passing score; identify the story/AC IDs, evidence paths, latest change time and TASTE.md. Check freshness and required L1–L3 results. In Plan mode, describe needed runs without executing gates.
2. **Review.** Use the harness `critique()` tool when available for the stories or milestone. Otherwise read [references/reviewers.md](references/reviewers.md) and spawn three read-only reviewer subagents with its briefs: Spec Auditor, Player Advocate and Art Director. Give each the same target, criteria, TASTE.md, diff/stat and fresh evidence. Have each inspect screenshots independently and return the specified JSON. Do not substitute your own review for an unavailable reviewer; escalate if independent review cannot run.
3. **Aggregate.** Validate all three JSON results. Set `min` to the minimum score, never an average. Any nonempty `blockers` array or `severity: blocker` issue, or any behavioural FAIL, overrides to REFINE regardless of score. Otherwise require the predeclared passing score, target conditions and Three Words test (at least two yes answers per screenshot or feel change). If `max(score) - min(score) > 3`, mark `needs-human` and ESCALATE; retain blockers/behavioural failures in the report. Invalid/missing results cannot PASS.
4. **Refine or escalate.** On a first-round REFINE, address evidenced issues within scope, rerun required behaviour checks and play-verify after edits, then review again. Cap the process at two critique rounds total (initial plus one refinement review); no third automatic round. If round two fails, escalate to the user with screenshots, all reviews, minimum score, remaining issues and choices: Accept as is / Revise with my notes / Park. Only the user can accept an escalation; record that as human acceptance without changing failing evidence.
5. **Report.** Include subject IDs, frozen target/pass bar, evidence timestamps/paths, three JSON reviews, minimum score, round count and decision. End the response with exactly one status line, substituting the decision and minimum integer: `CRITIQUE: PASS|REFINE|ESCALATE min=<n>`. If review cannot run, say why and use ESCALATE with `min=0` as an unscored sentinel, not a reviewer score.

## Verify
- Three valid independent JSON reviews name the required reviewers; each score is an integer 1–10 and each taste word has yes/no plus evidence.
- Every screenshot exists, was inspected, names the subject and was captured after the last scoped change; required behavioural results are observed and current.
- The decision uses the minimum score, predeclared pass bar, blocker/behavioural overrides and disagreement > 3 rule; no more than two rounds ran.
- The report ends with `CRITIQUE: PASS min=<n>`, `CRITIQUE: REFINE min=<n>` or `CRITIQUE: ESCALATE min=<n>`; PASS satisfies the target and has no outstanding blocker or behavioural FAIL.
