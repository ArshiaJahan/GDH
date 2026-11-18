using System;

namespace Gdw.Replay
{
    /// <summary>
    /// Stable subject identities that replace Unity instance IDs in hashed state.
    /// Authored GUIDs and deterministic spawn IDs must be unique within a provider.
    /// </summary>
    public static class ReplayIdentity
    {
        public static string Authored(Guid guid) => "authored." + guid.ToString("N");

        public static string Spawn(string spawnId)
        {
            if (string.IsNullOrEmpty(spawnId)) throw new ArgumentNullException(nameof(spawnId));
            return "spawn." + spawnId;
        }
    }
}
