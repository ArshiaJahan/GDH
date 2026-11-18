using System;
using System.Text;
using NUnit.Framework;
using UnityEngine;

namespace Gdw.Replay.Tests
{
    /// <summary>
    /// Frozen golden vectors for the deterministic RNG and the canonical state hash
    /// (gdw-replay-state/1). If these change, every recorded run and replay diverges.
    /// </summary>
    public class RandomAndHashTests
    {
        sealed class TestProvider : IReplayStateProvider
        {
            readonly string _id;
            readonly Action<StateWriter> _write;

            public TestProvider(string id, Action<StateWriter> write) { _id = id; _write = write; }

            public string Id => _id;
            public void WriteState(StateWriter writer) => _write(writer);
        }

        static string Hex(byte[] bytes)
        {
            var sb = new StringBuilder(bytes.Length * 2);
            foreach (var b in bytes) sb.Append(b.ToString("x2"));
            return sb.ToString();
        }

        [Test]
        public void SeededRng_GoldenValues_AreStable()
        {
            Assert.AreEqual(2166136261u, RunSeed.Fnv1a(""));
            Assert.AreEqual(1881022441u, RunSeed.FromString("2026-11-06"));

            var r = new SeededRng(42);
            Assert.AreEqual(3669911245u, r.NextUInt());
            Assert.AreEqual(3667817022u, r.NextUInt());
            Assert.AreEqual(2414785042u, r.NextUInt());
        }

        [Test]
        public void GdwRandom_NamedStreams_AreDeterministicAndIndependent()
        {
            GdwRandom.Reset(99);
            var a = GdwRandom.Stream("map");
            var a1 = a.NextUInt();
            var a2 = a.NextUInt();

            GdwRandom.Reset(99);
            var b = GdwRandom.Stream("map");
            Assert.AreEqual(a1, b.NextUInt());
            Assert.AreEqual(a2, b.NextUInt());

            // A different name derives a different stream from the same seed.
            GdwRandom.Reset(99);
            var c = GdwRandom.Stream("loot");
            Assert.AreNotEqual(a1, c.NextUInt());
        }

        [Test]
        public void StateWriter_GoldenV1_MatchesByteForByte()
        {
            var writer = new StateWriter();
            writer.WriteBool("alive", true);
            writer.WriteInt32("hp", 100);

            Assert.AreEqual("020000000500616c6976650101020068700264000000", Hex(writer.ToBytes()));
        }

        [Test]
        public void Registry_GoldenV1_AggregateAndProviderHash()
        {
            var registry = new ReplayRegistry();
            registry.Register("game.hp", new TestProvider("game.hp", w =>
            {
                w.WriteBool("alive", true);
                w.WriteInt32("hp", 100);
            }));

            var hashes = registry.ComputeAll();
            Assert.AreEqual("542d2da118d9b08e78cfa33f4a7e426ad5c742bfda979db68f7bb082282b2dfb", hashes.Aggregate);
            Assert.AreEqual("dcc1e59d918fcabdaa053a20728959a187053f348fc818f118d1b5396b9d61d4", hashes.Providers["game.hp"]);
        }

        [Test]
        public void Registry_GoldenV2_Matches()
        {
            var registry = new ReplayRegistry();
            registry.Register("game.state", new TestProvider("game.state", w =>
            {
                w.WriteBytes("blob", new byte[] { 0x00, 0xff, 0x10 });
                w.WriteInt64("delta", -2);
                w.WriteFloat("f32", 1.5f);
                w.WriteDouble("f64", 3.25);
                w.WriteString("name", "héllo");
                w.WriteVector3("pos", new Vector3(1f, -2.5f, 0f));
                w.WriteQuaternion("q", new Quaternion(0f, 0f, 0f, 1f));
                w.WriteUInt64("ticks", ulong.MaxValue);
            }));

            Assert.AreEqual("7d362c286a4b10523b3940a4c812363b8299c490579bdd0d4796e8ec833bc211", registry.ComputeAll().Aggregate);
        }

        [Test]
        public void Registry_GoldenV3_TwoProvidersSortedById()
        {
            var registry = new ReplayRegistry();
            registry.Register("unity.rng", new TestProvider("unity.rng", w =>
            {
                w.WriteUInt32("seed", 12345u);
                w.WriteUInt64("stream.combat.draws", 0uL);
                w.WriteUInt32("stream.combat.state", 0x6E624EB7u);
                w.WriteUInt64("stream.loot.draws", 3uL);
                w.WriteUInt32("stream.loot.state", 0xDEADBEEFu);
            }));
            registry.Register("game.inventory", new TestProvider("game.inventory", w =>
            {
                w.WriteUInt32("count", 2u);
                w.WriteFloat("negzero", -0.0f);
                w.WriteString("slot.0", "sword");
                w.WriteString("slot.1", "potion");
            }));

            Assert.AreEqual("7903c8fb91600773d718253be4deb42c43887c8b8080560b53aa31133b568e1f", registry.ComputeAll().Aggregate);
        }

        [Test]
        public void Registry_Ids_AreSortedOrdinal()
        {
            var registry = new ReplayRegistry();
            registry.Register("z.provider", new TestProvider("z.provider", _ => { }));
            registry.Register("a.provider", new TestProvider("a.provider", _ => { }));
            registry.Register("m.provider", new TestProvider("m.provider", _ => { }));

            Assert.AreEqual(new[] { "a.provider", "m.provider", "z.provider" }, registry.Ids);
        }

        [Test]
        public void StateWriter_Rejects_NaN_Duplicate_AndInvalidNames()
        {
            Assert.Throws<ReplayStateException>(() => new StateWriter().WriteFloat("f", float.NaN));
            Assert.Throws<ReplayStateException>(() => new StateWriter().WriteDouble("d", double.NaN));

            var duplicate = new StateWriter();
            duplicate.WriteBool("x", true);
            Assert.Throws<ReplayStateException>(() => duplicate.WriteBool("x", false));

            Assert.Throws<ReplayStateException>(() => new StateWriter().WriteBool("0starts-with-digit", true));
            Assert.Throws<ReplayStateException>(() => new StateWriter().WriteBool("has space", true));
        }
    }
}
