using System;
using System.Collections.Generic;
using UnityEngine;

namespace Harness.Arch
{
    /// <summary>Shared mutable value (e.g. player HP read by HUD). Runtime value is never written to the asset.</summary>
    public abstract class Variable<T> : ScriptableObject, IResettable
    {
        [SerializeField] T initialValue;
        [NonSerialized] T value;
        [NonSerialized] bool initialized;
        public event Action<T> Changed;

        public T InitialValue => initialValue;

        public T Value
        {
            get { if (!initialized) ResetRuntimeState(); return value; }
            set
            {
                if (!initialized) ResetRuntimeState();
                if (EqualityComparer<T>.Default.Equals(this.value, value)) return;
                this.value = value;
                Changed?.Invoke(value);
            }
        }

        public void ResetRuntimeState() { value = initialValue; initialized = true; }
        protected virtual void OnEnable() { initialized = false; RuntimeAssetReset.Track(this); }
        protected virtual void OnDisable() => RuntimeAssetReset.Untrack(this);
    }

    /// <summary>Inspector field that is either a constant or an IntVariable.</summary>
    [Serializable]
    public struct IntReference
    {
        public bool useConstant;
        public int constant;
        public IntVariable variable;
        public int Value => useConstant || variable == null ? constant : variable.Value;
    }
}
