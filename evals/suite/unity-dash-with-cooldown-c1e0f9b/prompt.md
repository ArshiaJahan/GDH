Coin Dash sample: a dash with a cooldown

Movement needs a dash that feels quick but can't be spammed. Add the
dash timing rules as a plain C# class in the CoinDash assembly so
EditMode tests can check them without a scene:

- a dash only starts while the player is moving
- it triples the speed for 0.2 s
- another dash is allowed 1 s after the previous one started
- ticking with the frame's delta time counts both timers down

Interface the tests use (declarations only; the change adds or changes these):
- `public sealed class Dash`
- `public bool IsDashing`
- `public bool Ready`
- `public float Multiplier`
- `public bool TryStart(bool moving)`
- `public void Tick(float dt)`
