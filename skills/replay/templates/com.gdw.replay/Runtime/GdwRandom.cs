using System;
using System.Collections.Generic;

namespace Gdw.Replay
{
    /// <summary>Serializable snapshot of every cached RNG stream, for the unity.rng provider and reset.</summary>
    [Serializable]
    public sealed class GdwRandomState
    {
        public uint Seed;
        public string[] Names;
        public uint[] States;
        public ulong[] Draws;
    }

    /// <summary>
    /// A cached named stream. Mirrors SeededRng's public methods while counting draws,
    /// so the unity.rng provider can report both state and draw count deterministically.
    /// </summary>
    public sealed class GdwRandomStream
    {
        readonly SeededRng _rng;

        public uint State => _rng.State;
        public ulong Draws { get; private set; }
        public SeededRng Rng => _rng;

        internal GdwRandomStream(SeededRng rng) { _rng = rng; }

        public uint NextUInt() { Draws++; return _rng.NextUInt(); }

        public int Range(int minInclusive, int maxExclusive)
        {
            if (maxExclusive <= minInclusive) return minInclusive;
            Draws++;
            return _rng.Range(minInclusive, maxExclusive);
        }

        public float NextFloat() { Draws++; return _rng.NextFloat(); }

        public float Range(float min, float max) { Draws++; return _rng.Range(min, max); }

        public bool Chance(float probability) { Draws++; return _rng.Chance(probability); }

        public T Pick<T>(IReadOnlyList<T> list) { Draws++; return _rng.Pick(list); }

        public int WeightedIndex(IReadOnlyList<int> weights)
        {
            int total = 0;
            for (int i = 0; i < weights.Count; i++) total += Math.Max(0, weights[i]);
            if (total == 0) return -1;
            Draws++;
            return _rng.WeightedIndex(weights);
        }

        public void Shuffle<T>(IList<T> list)
        {
            if (list == null) throw new ArgumentNullException(nameof(list));
            for (int i = list.Count - 1; i > 0; i--)
            {
                int j = Range(0, i + 1);
                (list[i], list[j]) = (list[j], list[i]);
            }
        }

        internal void SetDraws(ulong draws) { Draws = draws; }
    }

    /// <summary>
    /// Route gameplay randomness to cached, named streams: drawing extra loot never changes the map layout.
    /// Stream seed = SeededRng.Hash(seed ^ Fnv1a(name)), matching the architecture-patterns SeededRng derivation.
    /// </summary>
    public static class GdwRandom
    {
        static uint _seed;
        static readonly Dictionary<string, GdwRandomStream> _streams = new Dictionary<string, GdwRandomStream>(StringComparer.Ordinal);

        public static uint Seed => _seed;

        public static IReadOnlyList<string> StreamNames
        {
            get
            {
                var names = new List<string>(_streams.Keys);
                names.Sort(StringComparer.Ordinal);
                return names;
            }
        }

        public static void Reset(uint seed)
        {
            _seed = seed;
            _streams.Clear();
        }

        public static GdwRandomStream Stream(string name)
        {
            if (name == null) throw new ArgumentNullException(nameof(name));
            if (!_streams.TryGetValue(name, out var stream))
            {
                stream = new GdwRandomStream(new SeededRng(SeededRng.Hash(_seed ^ RunSeed.Fnv1a(name))));
                _streams.Add(name, stream);
            }
            return stream;
        }

        public static GdwRandomState ExportStates()
        {
            var names = new List<string>(_streams.Keys);
            names.Sort(StringComparer.Ordinal);
            var state = new GdwRandomState
            {
                Seed = _seed,
                Names = names.ToArray(),
                States = new uint[names.Count],
                Draws = new ulong[names.Count],
            };
            for (int i = 0; i < names.Count; i++)
            {
                var stream = _streams[names[i]];
                state.States[i] = stream.State;
                state.Draws[i] = stream.Draws;
            }
            return state;
        }

        public static void ImportStates(GdwRandomState state)
        {
            if (state == null) throw new ArgumentNullException(nameof(state));
            _seed = state.Seed;
            _streams.Clear();
            if (state.Names == null) return;
            for (int i = 0; i < state.Names.Length; i++)
            {
                uint rawState = state.States != null && i < state.States.Length ? state.States[i] : 0u;
                ulong draws = state.Draws != null && i < state.Draws.Length ? state.Draws[i] : 0uL;
                var stream = new GdwRandomStream(SeededRng.FromState(rawState));
                stream.SetDraws(draws);
                _streams[state.Names[i]] = stream;
            }
        }
    }
}
