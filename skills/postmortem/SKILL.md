---
name: postmortem
description: Use when a gate is exhausted, a campaign parks, the user reverts a change on the Changes card, or the user says 'that broke'. Records an evidenced failure and a scoped prevention rule in POSTMORTEMS.md, links it from PROJECT.md, and proposes enforcement for user approval.
---

# postmortem

Turn a demonstrated failure into a traceable prevention rule. Keep root-cause detail in project-root `POSTMORTEMS.md`; keep only a one-line pointer in `PROJECT.md`.

## Procedure
1. **Gather evidence.** Collect the relevant `gate_runs` (attempts, status, output and exhausted gate), campaign file (target, phase, exit evidence and park reason), scoped `git log` and diff, and Changes card data (reverted change and user feedback). The harness may offer a "Write a postmortem?" chip after `gate.exhausted` or `campaign.parked`. Use read-only sources; record unavailable data explicitly rather than reconstructing a passing run or performing a revert. Link paths/run IDs/commit IDs and separate observed facts from hypotheses.
2. **Identify the failure.** State expected versus actual behaviour, what caught it (`gate|hook|human|nothing`), and measured time/money cost. Mark unknown cost as unknown. Trace the root cause to the mechanism that allowed the failure, not a person's mistake. Derive a concrete prevention rule and the narrow `Applies to` globs it needs.
3. **Write the entry.** Read existing `POSTMORTEMS.md` and allocate the next unused `PM-###`; preserve existing entries. Use [templates/POSTMORTEMS.template.md](templates/POSTMORTEMS.template.md) for a new file and its exact entry format for appends. Update the rule index. Keep evidence citations inside the existing fields; use the actual date. Record current enforcement, or `none` while approval is pending.
4. **Propose enforcement.** Prefer **lint rule > hook > skill text > note**. Explain the strongest practical option, exact scope/change and how to verify it; explain any stronger options skipped. Implement enforcement only with the user's OK. Present a concrete proposal and wait; writing this postmortem does not authorize changing lint, hooks or skill policy. After approval, implement within scope, smoke-test the failure case and a valid case, and update `Enforced by` to `lint:<RULE>`, `hook:<id>`, `skill:<name>` or `none`. Include the `PM-###` reference in the enforcing rule. If implementation is outside available permissions, report the pending work.
5. **Link the gotcha.** Add one line under `PROJECT.md` → `Known gotchas`, creating the section/file only if absent: `- Pooled feedback must reset on disable — [PM-007](POSTMORTEMS.md#pm-007-hit-flash-stayed-on-after-pooling-2026-11-12).` Replace the example with this entry's rule, ID and actual heading anchor. Keep root-cause details solely in POSTMORTEMS.md.
6. **Report.** Return the PM ID, evidence gaps, entry/gotcha links and enforcement proposal or approved implementation/verification. Pending approval must remain explicit.

## Entry contract
Use a `### PM-### <title> (<YYYY-MM-DD>)` heading followed by exactly these fields in order:
- `What broke: … · Caught by: gate|hook|human|nothing · Cost: …`
- `Root cause: …`
- `Rule: …`
- `Enforced by: …` (one of `hook:<id> | lint:<RULE> | skill:<name> | none`)
- `Applies to: …` (comma-separated project-relative globs)

## Verify
- The unique PM entry and rule index exist in root `POSTMORTEMS.md`, follow the exact heading/field format and cite the gathered evidence or explicitly identify missing sources.
- `PROJECT.md` has one concise Known gotchas line linking to that PM heading; detailed facts are not duplicated.
- The rule addresses the evidenced root cause and uses scoped globs; the enforcement proposal follows the preference order.
- Enforcement was implemented only after the user's OK, with failure/valid-case results recorded; otherwise `Enforced by: none` (or the existing mechanism) and pending approval are reported honestly.
