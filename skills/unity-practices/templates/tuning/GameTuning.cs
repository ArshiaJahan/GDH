using UnityEngine;

namespace GdwKit
{
    /// <summary>Example of grouped game-wide knobs. Copy the pattern: Header, Range/Min, Tooltip with the unit.</summary>
    [CreateAssetMenu(menuName = "Game/Game Tuning", fileName = "GameTuning")]
    public sealed class GameTuning : ConfigAsset
    {
        [Header("Player")]
        [Tooltip("Units per second.")]
        [SerializeField, Range(0f, 30f)] private float playerSpeed = 6f;
        [Tooltip("Seconds of invulnerability after a hit.")]
        [SerializeField, Range(0f, 3f)] private float invulnerableSeconds = 0.6f;

        [Header("Difficulty")]
        [Tooltip("Multiplier on enemy health.")]
        [SerializeField, Range(0.1f, 5f)] private float enemyHealthScale = 1f;
        [Tooltip("Multiplier on enemy damage.")]
        [SerializeField, Range(0.1f, 5f)] private float enemyDamageScale = 1f;
        [Tooltip("Enemy health multiplier by wave number (x: wave, y: multiplier).")]
        [SerializeField] private AnimationCurve healthByWave = AnimationCurve.Linear(0f, 1f, 20f, 3f);

        [Header("Economy")]
        [Tooltip("Coins per kill before multipliers.")]
        [SerializeField, Min(0)] private int coinsPerKill = 1;

        public float PlayerSpeed => playerSpeed;
        public float InvulnerableSeconds => invulnerableSeconds;
        public float EnemyHealthScale => enemyHealthScale;
        public float EnemyDamageScale => enemyDamageScale;
        public int CoinsPerKill => coinsPerKill;

        public float EnemyHealthAt(int wave) => enemyHealthScale * Mathf.Max(0.01f, healthByWave.Evaluate(wave));

        protected override void Sanitize()
        {
            if (healthByWave == null || healthByWave.length == 0) healthByWave = AnimationCurve.Constant(0f, 1f, 1f);
        }
    }
}
