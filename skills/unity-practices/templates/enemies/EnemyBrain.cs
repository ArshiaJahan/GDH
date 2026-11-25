using UnityEngine;

namespace GdwKit
{
    /// <summary>
    /// A small enum state machine: Idle → Chase → Attack, Dead. Decisions run on a staggered timer
    /// (config.ThinkInterval); movement runs every frame. Moves the transform; swap Move() for a
    /// NavMeshAgent or Rigidbody when the game needs one.
    /// </summary>
    [RequireComponent(typeof(Health))]
    public sealed class EnemyBrain : MonoBehaviour, IPoolable
    {
        public enum State { Idle, Chase, Attack, Dead }

        [SerializeField] private EnemyConfig config;

        public State Current { get; private set; }
        public EnemyConfig Config => config;
        public Transform Target { get; private set; }

        private Health _health;
        private float _nextThink;
        private float _nextAttack;

        private void Awake()
        {
            _health = GetComponent<Health>();
            if (config) _health.SetMax(config.MaxHealth);
        }

        private void OnEnable()
        {
            _health.Died += OnDied;
            EnemyRegistry.Add(this);
            ResetBrain();
        }

        private void OnDisable()
        {
            _health.Died -= OnDied;
            EnemyRegistry.Remove(this);
        }

        /// <summary>Spawners set the config of a pooled enemy before or right after spawning it.</summary>
        public void Init(EnemyConfig cfg)
        {
            config = cfg;
            _health.SetMax(cfg.MaxHealth);
            ResetBrain();
        }

        public void OnGetFromPool() => ResetBrain();

        public void OnReleaseToPool() => Target = null;

        private void ResetBrain()
        {
            Current = State.Idle;
            Target = null;
            // Stagger first decisions so a wave doesn't think on the same frame.
            _nextThink = Time.time + Random.value * (config ? config.ThinkInterval : 0.2f);
        }

        private void Update()
        {
            if (Current == State.Dead || !config) return;
            if (Time.time >= _nextThink)
            {
                _nextThink = Time.time + config.ThinkInterval;
                Think();
            }
            Act();
        }

        private void Think()
        {
            Target = EnemyRegistry.NearestTarget(transform.position, config.AggroRange);
            if (!Target) { Current = State.Idle; return; }
            float sq = (Target.position - transform.position).sqrMagnitude;
            Current = sq <= config.AttackRange * config.AttackRange ? State.Attack : State.Chase;
        }

        private void Act()
        {
            switch (Current)
            {
                case State.Chase:
                    if (Target) Move(Target.position);
                    break;
                case State.Attack:
                    TryAttack();
                    break;
            }
        }

        private void Move(Vector3 destination)
        {
            transform.position = Vector3.MoveTowards(transform.position, destination, config.MoveSpeed * Time.deltaTime);
        }

        private void TryAttack()
        {
            if (Time.time < _nextAttack || !Target) return;
            _nextAttack = Time.time + config.AttackCooldown;
            if (Target.TryGetComponent(out IDamageable victim) && victim.IsAlive)
            {
                var dir = (Target.position - transform.position).normalized;
                victim.TakeDamage(new DamageInfo(config.AttackDamage, Target.position, dir, gameObject));
            }
        }

        private void OnDied(Health _) => Current = State.Dead;

        private void OnDrawGizmosSelected()
        {
            if (!config) return;
            DebugDrawCompat.Circle(transform.position, config.AggroRange, Color.yellow);
            DebugDrawCompat.Circle(transform.position, config.AttackRange, Color.red);
        }
    }

    /// <summary>Gizmo circles without depending on the debug kit.</summary>
    internal static class DebugDrawCompat
    {
        public static void Circle(Vector3 center, float radius, Color color)
        {
            Gizmos.color = color;
            Gizmos.DrawWireSphere(center, radius);
        }
    }
}
