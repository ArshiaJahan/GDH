using System;
using System.Collections.Generic;
using UnityEngine;

namespace Harness.Arch
{
    /// <summary>Live registry of scene objects (e.g. all enemies alive). State is never serialized.</summary>
    public abstract class RuntimeSet<T> : ScriptableObject, IResettable
    {
        [NonSerialized] readonly List<T> items = new List<T>();
        public IReadOnlyList<T> Items => items;
        public int Count => items.Count;
        public event Action<T> Added;
        public event Action<T> Removed;

        public void Add(T item)
        {
            if (items.Contains(item)) return;
            items.Add(item);
            Added?.Invoke(item);
        }

        public void Remove(T item)
        {
            if (items.Remove(item)) Removed?.Invoke(item);
        }

        public void ResetRuntimeState() => items.Clear();
        protected virtual void OnEnable() { items.Clear(); RuntimeAssetReset.Track(this); }
        protected virtual void OnDisable() => RuntimeAssetReset.Untrack(this);
    }
}
