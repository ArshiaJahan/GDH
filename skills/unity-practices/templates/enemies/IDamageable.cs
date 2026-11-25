using UnityEngine;

namespace GdwKit
{
    /// <summary>What a hit carries. Passed with `in` so it isn't copied.</summary>
    public readonly struct DamageInfo
    {
        public readonly float Amount;
        public readonly Vector3 Point;
        public readonly Vector3 Direction;
        public readonly GameObject Source;

        public DamageInfo(float amount, Vector3 point, Vector3 direction, GameObject source)
        {
            Amount = amount;
            Point = point;
            Direction = direction;
            Source = source;
        }
    }

    /// <summary>Anything that can be hit. Projectiles use TryGetComponent&lt;IDamageable&gt;, never enemy classes.</summary>
    public interface IDamageable
    {
        bool IsAlive { get; }
        void TakeDamage(in DamageInfo hit);
    }
}
