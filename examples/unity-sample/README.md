# Coin Dash: a sample Unity project

A tiny Unity 6000.3 project for trying GameDevWorkstation and for its Unity eval tasks. It isn't a game
anyone should ship: one scene, a capsule you move with WASD or the arrow keys, and eight coins placed
from a seeded random stream.

- `Assets/Scripts/ScoreBoard.cs`: the rules, kept out of MonoBehaviours so EditMode tests can check them.
- `Assets/Scripts/GameState.cs`: registers the `game.score` replay state provider (score, coins, won).
- `Assets/Scripts/PlayerMover.cs`: Input System movement; the player's transform is tracked for replay.
- `Assets/Scripts/CoinField.cs`: coins from `GdwRandom.Stream("coins")`, collected by distance, no physics.
- `Assets/Tests/Editor/ScoreBoardTests.cs`: the EditMode tests named in `BACKLOG.md`.
- `Assets/Editor/SampleSceneBuilder.cs`: rebuilds `Assets/Scenes/Main.unity`
  (`Unity -batchmode -projectPath . -executeMethod SampleSceneBuilder.Build -quit`).
- `BACKLOG.md`: one finished story (M0-S01) and one open story (M1-S01 Dash) for the quality ladder.

`Packages/manifest.json` loads the replay package straight from this repository
(`file:../../../skills/replay/templates/com.gdw.replay`). If you copy the project somewhere else, change that
path or run `unity op=replay_install` from a GameDevWorkstation session.

Open it with Unity 6000.3.21f1 (Input System 1.20.1, Test Framework 1.6.0).
