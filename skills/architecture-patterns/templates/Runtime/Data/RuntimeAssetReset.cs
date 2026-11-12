using System;
using System.Collections.Generic;
using UnityEngine;

namespace Harness.Arch
{
    public interface IResettable { void ResetRuntimeState(); }

    /// <summary>
    /// Resets runtime state of RuntimeSets, Variables and event channels at play start. Needed when
    /// Enter Play Mode Options disable domain reload: ScriptableObjects then keep state between sessions.
    /// </summary>
    public static class RuntimeAssetReset
    {
        static readonly HashSet<IResettable> live = new HashSet<IResettable>();
        public static void Track(IResettable r) => live.Add(r);
        public static void Untrack(IResettable r) => live.Remove(r);

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        public static void ResetAll()
        {
            foreach (var r in live) r.ResetRuntimeState();
        }
    }
}
