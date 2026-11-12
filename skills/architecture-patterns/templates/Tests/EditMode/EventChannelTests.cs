using NUnit.Framework;
using UnityEngine;

namespace Harness.Arch.Tests
{
    public class EventChannelTests
    {
        [Test]
        public void VoidChannel_RaisesToSubscribers_AndStopsAfterUnsubscribe()
        {
            var ch = ScriptableObject.CreateInstance<VoidEventChannel>();
            int calls = 0;
            void Handler() => calls++;
            ch.Raised += Handler;
            ch.Raise();
            ch.Raised -= Handler;
            ch.Raise();
            Assert.AreEqual(1, calls);
            Assert.AreEqual(0, ch.ListenerCount);
            Object.DestroyImmediate(ch);
        }

        [Test]
        public void TypedChannel_PassesPayload()
        {
            var ch = ScriptableObject.CreateInstance<IntEventChannel>();
            int got = -1;
            ch.Raised += v => got = v;
            ch.Raise(7);
            Assert.AreEqual(7, got);
            Object.DestroyImmediate(ch);
        }

        [Test]
        public void Raise_WithNoListeners_DoesNotThrow()
        {
            var ch = ScriptableObject.CreateInstance<IntEventChannel>();
            Assert.DoesNotThrow(() => ch.Raise(1));
            Object.DestroyImmediate(ch);
        }

        [Test]
        public void ResetRuntimeState_DropsStaleSubscribers()
        {
            var ch = ScriptableObject.CreateInstance<VoidEventChannel>();
            ch.Raised += () => { };
            Assert.AreEqual(1, ch.ListenerCount);
            RuntimeAssetReset.ResetAll(); // what happens at play start with domain reload off
            Assert.AreEqual(0, ch.ListenerCount);
            Object.DestroyImmediate(ch);
        }

        [Test]
        public void Variable_ResetsToInitial_AndNotifiesOnChange()
        {
            var v = ScriptableObject.CreateInstance<IntVariable>();
            int notified = 0;
            v.Changed += _ => notified++;
            v.Value = 5;
            v.Value = 5; // same value: no event
            Assert.AreEqual(1, notified);
            v.ResetRuntimeState();
            Assert.AreEqual(v.InitialValue, v.Value);
            Object.DestroyImmediate(v);
        }

        [Test]
        public void DefinitionDatabase_FindsById_AndFlagsDuplicates()
        {
            var db = ScriptableObject.CreateInstance<DefinitionDatabase>();
            var a = ScriptableObject.CreateInstance<ItemDef>(); a.SetId("potion");
            var b = ScriptableObject.CreateInstance<EnemyDef>(); b.SetId("slime");
            var c = ScriptableObject.CreateInstance<ItemDef>(); c.SetId("potion");
            db.Add(a); db.Add(b);
            Assert.IsTrue(db.TryGet<ItemDef>("potion", out var found));
            Assert.AreSame(a, found);
            Assert.IsFalse(db.TryGet<ItemDef>("slime", out _)); // wrong type
            Assert.IsEmpty(db.Validate());
            db.Add(c);
            Assert.AreEqual(1, db.Validate().Count);
            foreach (var o in new Object[] { db, a, b, c }) Object.DestroyImmediate(o);
        }
    }
}
