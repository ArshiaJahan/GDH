using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace Harness.Arch.Tests
{
    public class ListenerPlayModeTests
    {
        [UnityTest]
        public IEnumerator Listener_ForwardsChannelToUnityEvent_WhileEnabled()
        {
            var ch = ScriptableObject.CreateInstance<IntEventChannel>();
            var go = new GameObject("Listener");
            var listener = go.AddComponent<IntEventListener>();
            int got = 0;
            listener.Response.AddListener(v => got = v);
            listener.SetChannel(ch);
            yield return null;

            ch.Raise(3);
            Assert.AreEqual(3, got);

            go.SetActive(false); // OnDisable unsubscribes
            ch.Raise(9);
            Assert.AreEqual(3, got);
            Assert.AreEqual(0, ch.ListenerCount);

            Object.Destroy(go);
            Object.Destroy(ch);
        }

        [UnityTest]
        public IEnumerator Pool_WorksInPlayMode()
        {
            var prefab = new GameObject("Bullet");
            var pool = new ComponentPool<Transform>(prefab.transform);
            var a = pool.Get();
            yield return null;
            a.GetComponent<PooledObject>().ReturnToPool();
            Assert.AreEqual(1, pool.CountInactive);
            pool.Dispose();
            Object.Destroy(prefab);
        }
    }
}
