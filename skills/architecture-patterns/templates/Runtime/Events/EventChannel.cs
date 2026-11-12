using System;
using UnityEngine;

namespace Harness.Arch
{
    /// <summary>Typed event asset. Declare one concrete subclass per payload type (Unity cannot create generic assets).</summary>
    public abstract class EventChannel<T> : ScriptableObject, IResettable
    {
        public event Action<T> Raised;
        public int ListenerCount => Raised?.GetInvocationList().Length ?? 0;

        public void Raise(T value) => Raised?.Invoke(value);

        public void ResetRuntimeState() => Raised = null;
        protected virtual void OnEnable() => RuntimeAssetReset.Track(this);
        protected virtual void OnDisable() => RuntimeAssetReset.Untrack(this);
    }
}
