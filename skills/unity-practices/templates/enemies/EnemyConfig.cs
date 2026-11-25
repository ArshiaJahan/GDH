using UnityEngine;

namespace GdwKit
{
    /// <summary>Stats for one enemy type. Variants are more assets of this type, not new classes.</summary>
    [CreateAssetMenu(menuName = "Game/Enemy Config", fileName = "EnemyConfig")]
    public sealed class EnemyConfig : ScriptableObject
    {
        [Header("Identity")]
        [SerializeField] private string displayName = "Grunt";
        [SerializeField] private GameObject prefab;

        [Header("Health")]
        [Tooltip("Hit points at difficulty 1.")]
        [SerializeField, Min(1f)] private float maxHealth = 30f;

        [Header("Movement")]
        [Tooltip("Units per second.")]
        [SerializeField, Min(0f)] private float moveSpeed = 3f;

        [Header("Senses and attack")]
        [Tooltip("Distance (units) at which the enemy notices a target.")]
        [SerializeField, Min(0f)] private float aggroRange = 8f;
        [Tooltip("Distance (units) at which the enemy can attack.")]
        [SerializeField, Min(0f)] private float attackRange = 1.5f;
        [Tooltip("Damage per attack.")]
        [SerializeField, Min(0f)] private float attackDamage = 5f;
        [Tooltip("Seconds between attacks.")]
        [SerializeField, Min(0.05f)] private float attackCooldown = 1f;
        [Tooltip("Seconds between decisions (target search). 0.1-0.25 keeps many enemies cheap.")]
        [SerializeField, Range(0.02f, 1f)] private float thinkInterval = 0.2f;

        [Header("Rewards")]
        [SerializeField, Min(0)] private int score = 10;

        public string DisplayName => displayName;
        public GameObject Prefab => prefab;
        public float MaxHealth => maxHealth;
        public float MoveSpeed => moveSpeed;
        public float AggroRange => aggroRange;
        public float AttackRange => attackRange;
        public float AttackDamage => attackDamage;
        public float AttackCooldown => attackCooldown;
        public float ThinkInterval => thinkInterval;
        public int Score => score;

        private void OnValidate()
        {
            if (attackRange > aggroRange) attackRange = aggroRange; // can't attack what it can't see
        }
    }
}
