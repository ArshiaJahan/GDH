using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace Harness.Arch.Tests
{
    public class SeededRngTests
    {
        static List<uint> Draw(SeededRng r, int n) => Enumerable.Range(0, n).Select(_ => r.NextUInt()).ToList();

        [Test]
        public void SameSeed_SameSequence()
        {
            CollectionAssert.AreEqual(Draw(new SeededRng(42), 100), Draw(new SeededRng(42), 100));
        }

        [Test]
        public void DifferentSeeds_DifferentSequences()
        {
            CollectionAssert.AreNotEqual(Draw(new SeededRng(1), 10), Draw(new SeededRng(2), 10));
        }

        [Test]
        public void KnownValues_AreStableAcrossPlatformsAndVersions()
        {
            // Golden values: if these change, every saved run and shared seed changes. Do not update casually.
            // Values computed by an independent Python implementation of lowbias32 + xorshift32 and FNV-1a.
            Assert.AreEqual(2166136261u, RunSeed.Fnv1a(""));
            Assert.AreEqual(1881022441u, RunSeed.FromString("2026-11-06"));
            CollectionAssert.AreEqual(new uint[] { 3669911245u, 3667817022u, 2414785042u }, Draw(new SeededRng(42), 3));
            var r = new SeededRng(0);
            Assert.AreEqual(SeededRng.FromState(r.State).NextUInt(), r.NextUInt());
        }

        [Test]
        public void Streams_AreIndependentOfEachOther()
        {
            var s1 = new RngStreams(99);
            var mapA = Draw(s1.Get("map"), 20);

            var s2 = new RngStreams(99);
            var loot = s2.Get("loot");
            for (int i = 0; i < 1000; i++) loot.NextUInt(); // lots of loot rolls first
            var mapB = Draw(s2.Get("map"), 20);

            CollectionAssert.AreEqual(mapA, mapB);
        }

        [Test]
        public void State_SurvivesJsonRoundTrip()
        {
            var r = new SeededRng(7);
            Draw(r, 13);
            var copy = JsonUtility.FromJson<RunState>(JsonUtility.ToJson(new RunState { lootRng = r })).lootRng;
            CollectionAssert.AreEqual(Draw(r, 20), Draw(copy, 20));
        }

        [Test]
        public void Range_StaysInBounds_AndCoversAllValues()
        {
            var r = new SeededRng(5);
            var seen = new HashSet<int>();
            for (int i = 0; i < 10000; i++)
            {
                int v = r.Range(-3, 4);
                Assert.That(v, Is.InRange(-3, 3));
                seen.Add(v);
                float f = r.NextFloat();
                Assert.That(f, Is.GreaterThanOrEqualTo(0f).And.LessThan(1f));
            }
            Assert.AreEqual(7, seen.Count);
        }

        [Test]
        public void Shuffle_IsDeterministic_AndAPermutation()
        {
            var a = Enumerable.Range(0, 50).ToList();
            var b = Enumerable.Range(0, 50).ToList();
            new SeededRng(11).Shuffle(a);
            new SeededRng(11).Shuffle(b);
            CollectionAssert.AreEqual(a, b);
            CollectionAssert.AreEquivalent(Enumerable.Range(0, 50), a);
        }

        [Test]
        public void WeightedIndex_RespectsZeroWeights()
        {
            var r = new SeededRng(3);
            var w = new[] { 0, 5, 0 };
            for (int i = 0; i < 100; i++) Assert.AreEqual(1, r.WeightedIndex(w));
            Assert.AreEqual(-1, r.WeightedIndex(new[] { 0, 0 }));
        }
    }
}
