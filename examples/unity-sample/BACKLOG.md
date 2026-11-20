# Backlog: Coin Dash

Current milestone: M1
Rules: one playable increment per milestone; each story has >= 1 criterion; each criterion has a test type and an observable signal.
Validate: `python3 <skills>/gdd-to-backlog/scripts/backlog_lint.py BACKLOG.md` (must print RESULT: OK).

## M0 Collect coins
Goal: The player walks a small arena and collects seeded coins for points.
Exit: All M0 criteria pass; the EditMode suite is green in batchmode.
Status: done

### M0-S01 Coins score points
- Status: done
- Owner skill: architecture-patterns

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M0-S01-AC1 | Given 3 coins, When 2 are collected, Then the score is 2 coins' worth | EditMode | test:ScoreBoardTests.M0_S01_CollectAddsPointsPerCoin |
| M0-S01-AC2 | Given 2 coins, When all are collected and one more pickup fires, Then the game is won and the score stops | EditMode | test:ScoreBoardTests.M0_S01_CollectingEveryCoinWinsAndStopsScoring |

## M1 Movement feel
Goal: Movement has a dash that feels quick and can't be spammed.
Exit: All M1 criteria pass; a recorded run replays with every checkpoint hash matching.
Status: active

### M1-S01 Dash
- Status: todo
- Owner skill: architecture-patterns

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M1-S01-AC1 | Given speed 5, When Space is pressed while moving, Then the player moves at 3x speed for 0.2 s and can't dash again for 1 s | EditMode | test:DashTests.M1_S01_DashBoostsThenCoolsDown |
| M1-S01-AC2 | Given a recorded run that dashes, When it is replayed in batchmode, Then every checkpoint hash matches | headless | test:ReplayVerificationTests.LogMatchesCheckpoints |
