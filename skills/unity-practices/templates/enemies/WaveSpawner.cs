using UnityEngine;

namespace GdwKit
{
    /// <summary>Plays a WaveConfig: spawns through PoolService at random spawn points, waits for the wave to be cleared.</summary>
    public sealed class WaveSpawner : MonoBehaviour
    {
        [SerializeField] private WaveConfig waves;
        [SerializeField] private Transform[] spawnPoints = new Transform[0];
        [SerializeField] private bool playOnStart = true;

        public int WaveIndex { get; private set; }
        public int Loop { get; private set; }
        public int Alive => EnemyRegistry.Enemies.Count;

        private void Start()
        {
            if (playOnStart) _ = Run();
        }

        private async Awaitable Run()
        {
            try { await RunWaves(destroyCancellationToken); }
            catch (System.OperationCanceledException) { } // the spawner was destroyed
        }

        private async Awaitable RunWaves(System.Threading.CancellationToken token)
        {
            while (waves && waves.Waves.Count > 0 && !token.IsCancellationRequested)
            {
                for (WaveIndex = 0; WaveIndex < waves.Waves.Count; WaveIndex++)
                {
                    var wave = waves.Waves[WaveIndex];
                    float scale = Mathf.Pow(Mathf.Max(waves.LoopCountScale, 1f), Loop);
                    foreach (var entry in wave.entries)
                    {
                        int count = Mathf.CeilToInt(entry.count * scale);
                        for (int i = 0; i < count; i++)
                        {
                            SpawnOne(entry.enemy);
                            if (entry.interval > 0f) await Awaitable.WaitForSecondsAsync(entry.interval, token);
                        }
                    }
                    while (Alive > 0) await Awaitable.NextFrameAsync(token);
                    if (wave.restAfter > 0f) await Awaitable.WaitForSecondsAsync(wave.restAfter, token);
                }
                if (waves.LoopCountScale <= 0f) break;
                Loop++;
            }
        }

        /// <summary>Spawn one enemy now (also used by debug commands).</summary>
        public EnemyBrain SpawnOne(EnemyConfig enemy)
        {
            if (!enemy || !enemy.Prefab) return null;
            var point = spawnPoints.Length > 0 ? spawnPoints[Random.Range(0, spawnPoints.Length)] : transform;
            var po = PoolService.Instance.Spawn(enemy.Prefab, point.position, point.rotation);
            if (po.TryGetComponent(out EnemyBrain brain)) brain.Init(enemy);
            return brain;
        }
    }
}
