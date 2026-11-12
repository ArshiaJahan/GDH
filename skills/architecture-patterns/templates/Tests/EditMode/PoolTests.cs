using System;
using NUnit.Framework;
using UnityEngine;
using Object = UnityEngine.Object;

namespace Harness.Arch.Tests
{
    public class PoolTests
    {
        sealed class Counter : MonoBehaviour, IPoolable
        {
            public int spawned, despawned;
            public void OnSpawned() => spawned++;
            public void OnDespawned() => despawned++;
        }

        GameObject prefabGo;
        ComponentPool<Transform> pool;

        [SetUp]
        public void SetUp()
        {
            prefabGo = new GameObject("PooledPrefab");
            prefabGo.AddComponent<Counter>();
            pool = new ComponentPool<Transform>(prefabGo.transform, null, 4, 8);
        }

        [TearDown]
        public void TearDown()
        {
            pool.Dispose();
            Object.DestroyImmediate(prefabGo);
        }

        [Test]
        public void GetRelease_ReusesInstances_AndCallsCallbacks()
        {
            var a = pool.Get(Vector3.one, Quaternion.identity);
            Assert.IsTrue(a.gameObject.activeSelf);
            Assert.AreEqual(Vector3.one, a.position);
            pool.Release(a);
            Assert.IsFalse(a.gameObject.activeSelf);
            var b = pool.Get();
            Assert.AreSame(a, b);
            var c = a.GetComponent<Counter>();
            Assert.AreEqual(2, c.spawned);
            Assert.AreEqual(1, c.despawned);
            Assert.AreEqual(1, pool.CountAll);
        }

        [Test]
        public void ReturnToPool_FromTheObjectItself()
        {
            var a = pool.Get();
            a.GetComponent<PooledObject>().ReturnToPool();
            Assert.AreEqual(0, pool.CountActive);
            Assert.AreEqual(1, pool.CountInactive);
        }

        [Test]
        public void DoubleRelease_Throws()
        {
            var a = pool.Get();
            pool.Release(a);
            Assert.Throws<InvalidOperationException>(() => pool.Release(a));
        }

        [Test]
        public void Prewarm_CreatesInactiveInstances()
        {
            pool.Prewarm(5);
            Assert.AreEqual(5, pool.CountInactive);
            Assert.AreEqual(0, pool.CountActive);
        }
    }
}
