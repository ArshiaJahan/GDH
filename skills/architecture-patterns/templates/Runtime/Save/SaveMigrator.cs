using System;
using System.Collections.Generic;
using UnityEngine;

namespace Harness.Arch
{
    public sealed class SaveVersionException : Exception
    {
        public SaveVersionException(string message) : base(message) { }
    }

    /// <summary>
    /// Chain of json-to-json steps keyed by the version they upgrade FROM. Each step must raise "version".
    /// Typed steps (old DTO -> new DTO) via <see cref="Step{TOld,TNew}"/> keep migrations readable and testable.
    /// </summary>
    public sealed class SaveMigrator
    {
        readonly Dictionary<int, Func<string, string>> steps = new Dictionary<int, Func<string, string>>();

        public SaveMigrator Register(int fromVersion, Func<string, string> step)
        {
            steps[fromVersion] = step ?? throw new ArgumentNullException(nameof(step));
            return this;
        }

        public SaveMigrator Register<TOld, TNew>(int fromVersion, Func<TOld, TNew> map) where TNew : SaveData
            => Register(fromVersion, Step(map));

        /// <summary>Deserialize as the old DTO, map to the new one, serialize. The new DTO's version is set for you.</summary>
        public static Func<string, string> Step<TOld, TNew>(Func<TOld, TNew> map) where TNew : SaveData
            => json =>
            {
                var next = map(JsonUtility.FromJson<TOld>(json));
                next.version = next.LatestVersion;
                return JsonUtility.ToJson(next);
            };

        /// <summary>Upgrades json to targetVersion. Throws SaveVersionException for newer files or gaps.</summary>
        public string Migrate(string json, int targetVersion, out int fromVersion)
        {
            int v = ReadVersion(json);
            fromVersion = v;
            if (v > targetVersion)
                throw new SaveVersionException($"save version {v} is newer than this build ({targetVersion}); refusing to load");
            while (v < targetVersion)
            {
                if (!steps.TryGetValue(v, out var step))
                    throw new SaveVersionException($"no migration registered from version {v}");
                json = step(json);
                int next = ReadVersion(json);
                if (next <= v) throw new SaveVersionException($"migration from {v} did not raise the version");
                v = next;
            }
            return json;
        }

        [Serializable] sealed class VersionProbe { public int version; }

        public static int ReadVersion(string json)
        {
            var probe = JsonUtility.FromJson<VersionProbe>(json);
            if (probe == null) throw new FormatException("not a JSON object");
            return probe.version;
        }
    }
}
