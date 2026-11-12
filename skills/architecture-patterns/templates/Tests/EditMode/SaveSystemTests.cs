using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace Harness.Arch.Tests
{
    public class SaveSystemTests
    {
        string root;
        JsonSaveStore store;

        [SetUp]
        public void SetUp()
        {
            root = Path.Combine(Path.GetTempPath(), "harness-save-tests-" + System.Guid.NewGuid().ToString("N"));
            store = new JsonSaveStore(root);
        }

        [TearDown]
        public void TearDown()
        {
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }

        [Test]
        public void RoundTrip_MetaProgress_PreservesFields()
        {
            var meta = new MetaProgress { currency = 42, runsStarted = 3, runsWon = 1, bestDepth = 7 };
            meta.Unlock("dagger");
            store.Save("meta", meta);

            var r = store.TryLoad<MetaProgress>("meta", out var loaded);

            Assert.IsTrue(r.ok, r.error);
            Assert.AreEqual(42, loaded.currency);
            Assert.AreEqual(7, loaded.bestDepth);
            Assert.AreEqual(MetaProgress.CurrentVersion, loaded.version);
            CollectionAssert.AreEqual(new[] { "dagger" }, loaded.unlockedIds);
        }

        [Test]
        public void RoundTrip_RunState_ResumesRngExactly()
        {
            var run = RunState.NewRun(12345u, 6);
            run.itemIds.Add("potion");
            run.lootRng.NextUInt();
            store.Save("run", run);
            uint expectedNext = SeededRng.FromState(run.lootRng.State).NextUInt();

            Assert.IsTrue(store.TryLoad<RunState>("run", out var loaded).ok);
            Assert.AreEqual(12345u, loaded.seed);
            Assert.AreEqual(expectedNext, loaded.lootRng.NextUInt());
            CollectionAssert.AreEqual(new[] { "potion" }, loaded.itemIds);
        }

        [Test]
        public void Save_IsAtomic_NoTempLeft_BackupKept()
        {
            store.Save("meta", new MetaProgress { currency = 1 });
            store.Save("meta", new MetaProgress { currency = 2 });

            Assert.IsFalse(File.Exists(store.PathFor("meta") + ".tmp"));
            Assert.IsTrue(File.Exists(store.PathFor("meta") + ".bak"));
            Assert.IsTrue(store.TryLoad<MetaProgress>("meta", out var loaded).ok);
            Assert.AreEqual(2, loaded.currency);
        }

        [Test]
        public void CorruptMainFile_FallsBackToBackup()
        {
            store.Save("meta", new MetaProgress { currency = 1 });
            store.Save("meta", new MetaProgress { currency = 2 });
            File.WriteAllText(store.PathFor("meta"), "{ this is not json");

            LogAssert.Expect(LogType.Warning, new System.Text.RegularExpressions.Regex("loaded backup"));
            var r = store.TryLoad<MetaProgress>("meta", out var loaded);

            Assert.IsTrue(r.ok, r.error);
            Assert.IsTrue(r.fromBackup);
            Assert.AreEqual(1, loaded.currency);
        }

        [Test]
        public void Missing_ReportsMissing()
        {
            var r = store.TryLoad<MetaProgress>("meta", out var loaded);
            Assert.IsFalse(r.ok);
            Assert.IsTrue(r.missing);
            Assert.IsNull(loaded);
        }

        [Test]
        public void Migration_V1GoldBecomesCurrency()
        {
            Directory.CreateDirectory(root);
            var v1 = new MetaProgress.V1 { version = 1, gold = 50, runsStarted = 4, unlockedIds = new List<string> { "bow" } };
            File.WriteAllText(store.PathFor("meta"), JsonUtility.ToJson(v1));

            var r = store.TryLoad<MetaProgress>("meta", out var loaded);

            Assert.IsTrue(r.ok, r.error);
            Assert.AreEqual(1, r.migratedFrom);
            Assert.AreEqual(50, loaded.currency);
            Assert.AreEqual(4, loaded.runsStarted);
            Assert.AreEqual(MetaProgress.CurrentVersion, loaded.version);
            CollectionAssert.AreEqual(new[] { "bow" }, loaded.unlockedIds);
        }

        [Test]
        public void NewerVersion_IsRefused_AndFileUntouched()
        {
            Directory.CreateDirectory(root);
            const string future = "{\"version\":99,\"currency\":5}";
            File.WriteAllText(store.PathFor("meta"), future);

            var r = store.TryLoad<MetaProgress>("meta", out _);

            Assert.IsFalse(r.ok);
            StringAssert.Contains("newer", r.error);
            Assert.AreEqual(future, File.ReadAllText(store.PathFor("meta")));
        }

        [Test]
        public void Migrator_MissingStep_Throws()
        {
            var m = new SaveMigrator();
            Assert.Throws<SaveVersionException>(() => m.Migrate("{\"version\":1}", 3, out _));
        }
    }
}
