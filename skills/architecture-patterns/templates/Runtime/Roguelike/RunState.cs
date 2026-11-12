using System;
using System.Collections.Generic;

namespace Harness.Arch
{
    /// <summary>
    /// State of the current run only: created at run start, saved for suspend/resume ("run" file), deleted on death or win.
    /// Never put unlocks or currency that outlives the run here (that is MetaProgress).
    /// Stores ids of definitions, not object references, and the RNG stream states so a resumed run continues identically.
    /// </summary>
    [Serializable]
    public sealed class RunState : SaveData
    {
        public const int CurrentVersion = 1;
        public override int LatestVersion => CurrentVersion;

        public uint seed;
        public int depth;
        public int health;
        public int maxHealth;
        public int runCurrency;
        public List<string> itemIds = new List<string>();
        public SeededRng mapRng;
        public SeededRng lootRng;
        public SeededRng combatRng;

        public RunState() { version = CurrentVersion; }

        public static RunState NewRun(uint seed, int maxHealth)
        {
            var streams = new RngStreams(seed);
            return new RunState
            {
                seed = seed,
                depth = 1,
                health = maxHealth,
                maxHealth = maxHealth,
                mapRng = streams.Get("map"),
                lootRng = streams.Get("loot"),
                combatRng = streams.Get("combat"),
            };
        }
    }
}
