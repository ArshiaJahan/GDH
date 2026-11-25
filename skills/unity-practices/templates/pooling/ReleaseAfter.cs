using UnityEngine;

namespace GdwKit
{
    /// <summary>Releases a pooled object after a delay (VFX, bullets, damage numbers). Restarts on reuse.</summary>
    [RequireComponent(typeof(PooledObject))]
    public sealed class ReleaseAfter : MonoBehaviour, IPoolable
    {
        [Tooltip("Seconds before the object goes back to its pool.")]
        [SerializeField, Min(0.01f)] private float seconds = 1f;
        [Tooltip("Use unscaled time (keeps running while the game is paused).")]
        [SerializeField] private bool unscaled;

        private PooledObject _pooled;
        private float _left;

        private void Awake() => _pooled = GetComponent<PooledObject>();

        public void OnGetFromPool() => _left = seconds;

        public void OnReleaseToPool() { }

        private void OnEnable() => _left = seconds; // also covers objects placed in a scene

        private void Update()
        {
            _left -= unscaled ? Time.unscaledDeltaTime : Time.deltaTime;
            if (_left <= 0f) _pooled.Release();
        }
    }
}
