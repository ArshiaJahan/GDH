using System;
using UnityEngine;

namespace Harness.Arch
{
    /// <summary>Payload-less event asset (PlayerDied, RunEnded, PauseRequested).</summary>
    [CreateAssetMenu(menuName = "Harness/Events/Void Channel", fileName = "VoidEventChannel")]
    public sealed class VoidEventChannel : ScriptableObject, IResettable
    {
        public event Action Raised;
        public int ListenerCount => Raised?.GetInvocationList().Length ?? 0;

        public void Raise() => Raised?.Invoke();

        // Subscribers left from a previous play session (domain reload off) are dropped at play start.
        public void ResetRuntimeState() => Raised = null;
        void OnEnable() => RuntimeAssetReset.Track(this);
        void OnDisable() => RuntimeAssetReset.Untrack(this);
    }
}
