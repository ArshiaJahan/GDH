using System;
using UnityEngine;

namespace GdwKit
{
    /// <summary>
    /// Base for tunable ScriptableObjects. Changed fires when the asset is edited in the Inspector
    /// (also during Play Mode) or overridden from JSON, so systems can re-read values without a restart.
    /// Never write runtime state into a config asset: in the editor that change is saved to disk.
    /// </summary>
    public abstract class ConfigAsset : ScriptableObject
    {
        public event Action<ConfigAsset> Changed;

        /// <summary>Clamp and keep fields consistent. Called from OnValidate and after JSON overrides.</summary>
        protected virtual void Sanitize() { }

        protected virtual void OnValidate()
        {
            Sanitize();
            Changed?.Invoke(this);
        }

        /// <summary>Overwrite fields from JSON (JsonUtility field names), then sanitize and notify.</summary>
        public void ApplyJson(string json)
        {
            JsonUtility.FromJsonOverwrite(json, this);
            Sanitize();
            Changed?.Invoke(this);
        }

        public string ToJson(bool pretty = true) => JsonUtility.ToJson(this, pretty);
    }
}
