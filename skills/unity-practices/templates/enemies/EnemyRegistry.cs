using System.Collections.Generic;
using UnityEngine;

namespace GdwKit
{
    /// <summary>Live enemies and targets without FindObjectsByType. Members add themselves in OnEnable.</summary>
    public static class EnemyRegistry
    {
        private static readonly List<EnemyBrain> _enemies = new List<EnemyBrain>(256);
        private static readonly List<Transform> _targets = new List<Transform>(8);

        public static IReadOnlyList<EnemyBrain> Enemies => _enemies;
        public static IReadOnlyList<Transform> Targets => _targets;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetStatics()
        {
            _enemies.Clear();
            _targets.Clear();
        }

        public static void Add(EnemyBrain e) { if (!_enemies.Contains(e)) _enemies.Add(e); }
        public static void Remove(EnemyBrain e) => _enemies.Remove(e);
        public static void AddTarget(Transform t) { if (t && !_targets.Contains(t)) _targets.Add(t); }
        public static void RemoveTarget(Transform t) => _targets.Remove(t);

        /// <summary>The nearest target within range (squared distances, no allocation), or null.</summary>
        public static Transform NearestTarget(Vector3 from, float range)
        {
            Transform best = null;
            float bestSq = range * range;
            for (int i = 0; i < _targets.Count; i++)
            {
                var t = _targets[i];
                if (!t || !t.gameObject.activeInHierarchy) continue;
                float sq = (t.position - from).sqrMagnitude;
                if (sq <= bestSq) { bestSq = sq; best = t; }
            }
            return best;
        }
    }
}
