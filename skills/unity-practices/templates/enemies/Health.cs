using System;
using UnityEngine;

namespace GdwKit
{
    /// <summary>Hit points with Damaged/Died events. Resets when reused from a pool.</summary>
    public sealed class Health : MonoBehaviour, IDamageable, IPoolable
    {
        [Tooltip("Used when no EnemyConfig sets it.")]
        [SerializeField, Min(1f)] private float maxHealth = 10f;
        [Tooltip("Release to the pool (or destroy) this many seconds after death. Negative: leave it.")]
        [SerializeField] private float despawnDelay = 0f;

        public event Action<Health, DamageInfo> Damaged;
        public event Action<Health> Died;

        public float Current { get; private set; }
        public float Max => maxHealth;
        public bool IsAlive => Current > 0f;

        private PooledObject _pooled;

        private void Awake()
        {
            TryGetComponent(out _pooled);
            Current = maxHealth;
        }

        /// <summary>Set by the enemy from its config when it spawns.</summary>
        public void SetMax(float value, bool refill = true)
        {
            maxHealth = Mathf.Max(1f, value);
            if (refill) Current = maxHealth;
        }

        public void TakeDamage(in DamageInfo hit)
        {
            if (!IsAlive || hit.Amount <= 0f) return;
            Current = Mathf.Max(0f, Current - hit.Amount);
            Damaged?.Invoke(this, hit);
            if (Current > 0f) return;
            Died?.Invoke(this); // raised once: IsAlive is false from here on
            if (despawnDelay < 0f) return;
            if (despawnDelay == 0f) Despawn();
            else Invoke(nameof(Despawn), despawnDelay);
        }

        public void Heal(float amount)
        {
            if (IsAlive) Current = Mathf.Min(maxHealth, Current + Mathf.Max(0f, amount));
        }

        private void Despawn()
        {
            if (_pooled) _pooled.Release();
            else Destroy(gameObject);
        }

        public void OnGetFromPool() => Current = maxHealth;

        public void OnReleaseToPool() => CancelInvoke();
    }
}
