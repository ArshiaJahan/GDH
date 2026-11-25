using System;
using System.Collections.Generic;
using UnityEngine;

namespace GdwKit
{
    /// <summary>Waves as data: which enemies, how many, how fast. Tune in the Inspector.</summary>
    [CreateAssetMenu(menuName = "Game/Wave Config", fileName = "WaveConfig")]
    public sealed class WaveConfig : ScriptableObject
    {
        [Serializable]
        public struct Entry
        {
            public EnemyConfig enemy;
            [Min(1)] public int count;
            [Tooltip("Seconds between spawns of this entry.")]
            [Min(0f)] public float interval;
        }

        [Serializable]
        public struct Wave
        {
            public Entry[] entries;
            [Tooltip("Seconds to wait after this wave is cleared.")]
            [Min(0f)] public float restAfter;
        }

        [SerializeField] private List<Wave> waves = new List<Wave>();
        [Tooltip("Multiplier on enemy count per loop once all waves are done. 0 stops after the last wave.")]
        [SerializeField, Min(0f)] private float loopCountScale = 1.25f;

        public IReadOnlyList<Wave> Waves => waves;
        public float LoopCountScale => loopCountScale;
    }
}
