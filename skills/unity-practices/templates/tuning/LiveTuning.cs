using UnityEngine;
using UnityEngine.Events;

namespace GdwKit
{
    /// <summary>
    /// Re-applies a config whenever it changes (Inspector edits in Play Mode, JSON overrides).
    /// Wire onChanged in the Inspector, or subscribe to ConfigAsset.Changed from code instead.
    /// </summary>
    public sealed class LiveTuning : MonoBehaviour
    {
        [SerializeField] private ConfigAsset config;
        [SerializeField] private UnityEvent onChanged = new UnityEvent();
        [Tooltip("Also invoke once on enable, so the first values are applied the same way.")]
        [SerializeField] private bool applyOnEnable = true;

        private void OnEnable()
        {
            if (!config) return;
            config.Changed += OnConfigChanged;
            if (applyOnEnable) onChanged.Invoke();
        }

        private void OnDisable()
        {
            if (config) config.Changed -= OnConfigChanged;
        }

        private void OnConfigChanged(ConfigAsset _) => onChanged.Invoke();
    }
}
