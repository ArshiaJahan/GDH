using System;

namespace Harness.Arch
{
    /// <summary>
    /// Base for every save file. JsonUtility writes public/[SerializeField] fields only, so "version" is a field.
    /// Subclasses report their current version and the migrations from older versions.
    /// </summary>
    [Serializable]
    public abstract class SaveData
    {
        public int version;

        /// <summary>Version this build writes. Bump it when the shape changes, and add a migration step.</summary>
        public abstract int LatestVersion { get; }

        /// <summary>Steps from each older version to the next one. Null = no migrations yet.</summary>
        public virtual SaveMigrator Migrations => null;
    }
}
