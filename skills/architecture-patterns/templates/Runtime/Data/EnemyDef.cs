using UnityEngine;

namespace Harness.Arch
{
    [CreateAssetMenu(menuName = "Harness/Definitions/Enemy", fileName = "EnemyDef")]
    public sealed class EnemyDef : Definition
    {
        [Min(1)] public int maxHealth = 3;
        [Min(0)] public float moveSpeed = 2f;
        [Min(0)] public int contactDamage = 1;
        [Tooltip("Relative chance in a spawn table")] [Min(0)] public int spawnWeight = 10;
        [Tooltip("First depth/floor this enemy can appear on")] [Min(0)] public int minDepth;
        public GameObject prefab;
    }
}
