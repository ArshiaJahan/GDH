using System;
using UnityEngine;

namespace Harness.Arch
{
    /// <summary>Optional callbacks for pooled objects (reset state in OnSpawned, stop effects in OnDespawned).</summary>
    public interface IPoolable
    {
        void OnSpawned();
        void OnDespawned();
    }

    /// <summary>Added to every pooled instance; lets an object return itself (bullet hits wall -> ReturnToPool()).</summary>
    public sealed class PooledObject : MonoBehaviour
    {
        internal Action<PooledObject> release;
        internal IPoolable[] callbacks = Array.Empty<IPoolable>();
        internal Component component;
        public bool InPool { get; internal set; }
        public void ReturnToPool() => release?.Invoke(this);
    }
}
