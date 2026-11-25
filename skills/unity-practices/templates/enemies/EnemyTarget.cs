using UnityEngine;

namespace GdwKit
{
    /// <summary>Put on the player (or anything enemies should chase).</summary>
    public sealed class EnemyTarget : MonoBehaviour
    {
        private void OnEnable() => EnemyRegistry.AddTarget(transform);
        private void OnDisable() => EnemyRegistry.RemoveTarget(transform);
    }
}
