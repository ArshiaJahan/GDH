using System;
using System.Collections.Generic;
using UnityEngine;

namespace Gdw.Replay
{
    /// <summary>
    /// Small deterministic RNG (xorshift32 on a hashed seed, same algorithm family as Unity.Mathematics.Random).
    /// Serializable state => a saved run resumes with the exact same rolls. Same results on every platform
    /// (pure uint math, no System.Random / UnityEngine.Random). Not for cryptography.
    /// A class, not a struct, so passing it around never silently copies the state.
    /// </summary>
    [Serializable]
    public sealed class SeededRng
    {
        [SerializeField] uint state;
        public uint State => state;

        public SeededRng(uint seed)
        {
            state = Hash(seed);
            if (state == 0) state = 0x6E624EB7u; // xorshift must not be zero
        }

        public static SeededRng FromState(uint rawState) { var r = new SeededRng(0); r.state = rawState == 0 ? 0x6E624EB7u : rawState; return r; }

        SeededRng() : this(0) { } // for the serializer

        public uint NextUInt()
        {
            uint x = state == 0 ? 0x6E624EB7u : state; // a default-constructed/deserialized-empty instance must not stick at 0
            x ^= x << 13;
            x ^= x >> 17;
            x ^= x << 5;
            state = x;
            return x;
        }

        /// <summary>[min, max) ; returns min when max &lt;= min. Uses multiply-shift (no modulo bias for small ranges).</summary>
        public int Range(int minInclusive, int maxExclusive)
        {
            if (maxExclusive <= minInclusive) return minInclusive;
            uint span = (uint)(maxExclusive - minInclusive);
            return minInclusive + (int)(((ulong)NextUInt() * span) >> 32);
        }

        /// <summary>[0, 1)</summary>
        public float NextFloat() => (NextUInt() >> 8) * (1f / 16777216f);

        public float Range(float min, float max) => min + (max - min) * NextFloat();

        public bool Chance(float probability) => NextFloat() < probability;

        public T Pick<T>(IReadOnlyList<T> list)
        {
            if (list == null || list.Count == 0) throw new ArgumentException("empty list");
            return list[Range(0, list.Count)];
        }

        /// <summary>Index chosen by weights (e.g. EnemyDef.spawnWeight). Returns -1 if all weights are 0.</summary>
        public int WeightedIndex(IReadOnlyList<int> weights)
        {
            int total = 0;
            for (int i = 0; i < weights.Count; i++) total += Math.Max(0, weights[i]);
            if (total == 0) return -1;
            int roll = Range(0, total);
            for (int i = 0; i < weights.Count; i++)
            {
                roll -= Math.Max(0, weights[i]);
                if (roll < 0) return i;
            }
            return weights.Count - 1;
        }

        /// <summary>Fisher-Yates in place.</summary>
        public void Shuffle<T>(IList<T> list)
        {
            for (int i = list.Count - 1; i > 0; i--)
            {
                int j = Range(0, i + 1);
                (list[i], list[j]) = (list[j], list[i]);
            }
        }

        /// <summary>Integer finalizer (lowbias32) used to spread nearby seeds.</summary>
        public static uint Hash(uint x)
        {
            x ^= x >> 16; x *= 0x7feb352du;
            x ^= x >> 15; x *= 0x846ca68bu;
            x ^= x >> 16;
            return x;
        }
    }

    /// <summary>Stable seed derivation (FNV-1a), independent of locale and string.GetHashCode.</summary>
    public static class RunSeed
    {
        public static uint FromString(string text) => Fnv1a(text);

        public static uint Fnv1a(string text)
        {
            uint h = 2166136261u;
            if (text == null) return h;
            foreach (char c in text) { h ^= c; h *= 16777619u; }
            return h;
        }
    }
}
