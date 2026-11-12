using System;
using System.Collections.Generic;
using UnityEngine;

namespace Harness.Arch
{
    /// <summary>Base for every definition asset (static design data). Saves store <see cref="Id"/>, never object refs or paths.</summary>
    public abstract class Definition : ScriptableObject
    {
        [SerializeField, Tooltip("Stable id stored in saves. Never change it after release.")]
        string id;
        [SerializeField] string displayName;
        [SerializeField] Sprite icon;

        public string Id => id;
        public string DisplayName => string.IsNullOrEmpty(displayName) ? name : displayName;
        public Sprite Icon => icon;

        /// <summary>For tests and editor tools that build definitions in code.</summary>
        public void SetId(string newId) => id = newId;

#if UNITY_EDITOR
        protected virtual void OnValidate()
        {
            if (string.IsNullOrWhiteSpace(id)) id = name.ToLowerInvariant().Replace(' ', '_');
        }
#endif
    }
}
