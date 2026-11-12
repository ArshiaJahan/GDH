using System;
using System.Collections.Generic;

namespace Harness.Arch
{
    /// <summary>
    /// Meta-progression: survives death and app restarts (unlocks, currency, stats). Saved in its own file ("meta").
    /// Version history: v1 had "gold"; v2 renamed it to "currency" and added "bestDepth".
    /// </summary>
    [Serializable]
    public sealed class MetaProgress : SaveData
    {
        public const int CurrentVersion = 2;
        public override int LatestVersion => CurrentVersion;

        public int currency;
        public int runsStarted;
        public int runsWon;
        public int bestDepth;
        public List<string> unlockedIds = new List<string>();

        public MetaProgress() { version = CurrentVersion; }

        public bool IsUnlocked(string id) => unlockedIds.Contains(id);
        public void Unlock(string id) { if (!unlockedIds.Contains(id)) unlockedIds.Add(id); }

        // Old shape, kept only for migration. Never edit a DTO once a build with it has shipped.
        [Serializable]
        public sealed class V1
        {
            public int version;
            public int gold;
            public int runsStarted;
            public int runsWon;
            public List<string> unlockedIds = new List<string>();
        }

        static readonly SaveMigrator migrator = new SaveMigrator()
            .Register<V1, MetaProgress>(1, old => new MetaProgress
            {
                currency = old.gold,
                runsStarted = old.runsStarted,
                runsWon = old.runsWon,
                bestDepth = 0,
                unlockedIds = old.unlockedIds ?? new List<string>(),
            });

        public override SaveMigrator Migrations => migrator;
    }
}
