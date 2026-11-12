# PERF.md template

Copy to `<project>/PERF.md` (versioned). One section per perf pass; append, never rewrite history.

```markdown
# Performance log

## Targets
Platform: macOS (Apple Silicon) / Windows / Web · Target: 60 fps · Unity 6000.3.21f1 · URP 17.3 2D

| Key | Budget | Source |
|---|---|---|
| cpu_main_ms_p95 | <= 16.6 | 60 fps |
| gc_alloc_avg | <= 0 B (steady state, Development player) | harness default |
| batches_avg | <= 100 | harness default / art budget |
| setpass_avg | <= 30 | harness default |
| p2d_ms_p95 | <= 2.0 | physics slice |
| frame_ms_max (room transition) | <= 50 | spike budget (optional) |

Budgets file for perf_report: `--budgets perf-budgets.json` → `{"batches_avg": "<= 80"}`

## Scenario
Scene: Assets/Scenes/Arena.unity · Seed: 1234 · Setup: 300 enemies, 6 projectiles/frame, hit sparks, 64x64 tilemap room
How to run: PerfScenarioTests.Scenario_Arena (headless, no -nographics) | MCP: PerfProbe.Begin("<label>", 20, 3) after `DebugSpawn.Wave(300)`

## Runs
| Date | Commit | Path | Label | cpu_main p95 | frame p95 | GC B/frame | batches | setpass | p2d p95 | Result | CSV |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-06 | abc1234 | editor-test | baseline | 9.8 | 10.4 | 2304 (floor 410) | n/a | n/a | 1.1 | FAIL gc | Logs/harness/perf/test-baseline.csv |
| 2026-11-06 | def5678 | editor-test | after-pool-shots | 8.9 | 9.6 | 0 (floor 410) | n/a | n/a | 1.0 | OK | Logs/harness/perf/test-after-pool-shots.csv |

## Changes
- def5678 Pool projectiles (ObjectPool, maxSize 512): gc_alloc_avg 2304 → 0 B, cpu_main p95 -0.9 ms.
- (reverted) Tilemap SRPBatch mode: no change in batches, +0.2 ms; kept Chunk.

## Accepted exceptions
| Key | Value | Budget | Accepted by | Date | Reason | Revisit |
|---|---|---|---|---|---|---|
| batches_avg | 140 | 100 | <user> | 2026-11-06 | boss room particles, 30 s only | M5 |

## Open items
- Memory: textures grow 12 MB per room after room 10 (snapshot compare) → check Addressables release.
```

perf_report command for the table row: `python3 <skills>/perf-pass/scripts/perf_report.py --after <csv> --baseline <csv> [--floor <floor csv>] --md Logs/harness/perf/<label>.md`; paste the result line and key numbers.
