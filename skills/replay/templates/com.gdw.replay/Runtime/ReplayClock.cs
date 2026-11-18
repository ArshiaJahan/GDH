namespace Gdw.Replay
{
    /// <summary>
    /// Deterministic time for opted-in gameplay code. Driven by the ReplayLoop's fixed-tick counter,
    /// not by wall time; identical on every replay of a run.
    /// </summary>
    public static class ReplayClock
    {
        public static double Tick => ReplayLoop.Tick;
        public static float Delta => ReplayLoop.FixedDelta;
        public static double UnscaledTime => ReplayLoop.Tick * ReplayLoop.FixedDelta;
        public static float FixedDelta => ReplayLoop.FixedDelta;
    }
}
