using System;
using UnityEngine;
using UnityEngine.Pool;
using Object = UnityEngine.Object;

namespace Harness.Arch
{
    /// <summary>
    /// Prefab pool on top of UnityEngine.Pool.ObjectPool&lt;T&gt; (stack-based, NOT thread-safe).
    /// collectionCheck (default on) throws on double release; turn it off in release builds if profiling says so.
    /// </summary>
    public sealed class ComponentPool<T> : IDisposable where T : Component
    {
        readonly ObjectPool<T> pool;
        readonly T prefab;
        readonly Transform parent;

        public int CountActive => pool.CountActive;
        public int CountInactive => pool.CountInactive;
        public int CountAll => pool.CountAll;

        public ComponentPool(T prefab, Transform parent = null, int defaultCapacity = 16, int maxSize = 512, bool collectionCheck = true)
        {
            this.prefab = prefab != null ? prefab : throw new ArgumentNullException(nameof(prefab));
            this.parent = parent;
            pool = new ObjectPool<T>(Create, OnGet, OnRelease, OnDestroyItem, collectionCheck, defaultCapacity, maxSize);
        }

        public T Get(Vector3 position, Quaternion rotation)
        {
            var item = pool.Get();
            item.transform.SetPositionAndRotation(position, rotation);
            return item;
        }

        public T Get() => pool.Get();

        public void Release(T item) => pool.Release(item);

        /// <summary>Instantiate up front (call during a loading screen) so the first wave doesn't hitch.</summary>
        public void Prewarm(int count)
        {
            var tmp = new T[count];
            for (int i = 0; i < count; i++) tmp[i] = pool.Get();
            for (int i = 0; i < count; i++) pool.Release(tmp[i]);
        }

        public void Clear() => pool.Clear();
        public void Dispose() => pool.Dispose();

        T Create()
        {
            var item = Object.Instantiate(prefab, parent);
            item.gameObject.SetActive(false);
            var handle = item.gameObject.GetComponent<PooledObject>();
            if (handle == null) handle = item.gameObject.AddComponent<PooledObject>();
            handle.component = item;
            handle.callbacks = item.GetComponentsInChildren<IPoolable>(true);
            handle.release = h => pool.Release((T)h.component);
            return item;
        }

        static PooledObject Handle(T item) => item.GetComponent<PooledObject>();

        static void OnGet(T item)
        {
            var h = Handle(item);
            h.InPool = false;
            item.gameObject.SetActive(true);
            foreach (var c in h.callbacks) c.OnSpawned();
        }

        static void OnRelease(T item)
        {
            var h = Handle(item);
            foreach (var c in h.callbacks) c.OnDespawned();
            h.InPool = true;
            item.gameObject.SetActive(false);
        }

        static void OnDestroyItem(T item)
        {
            if (item == null) return;
            if (Application.isPlaying) Object.Destroy(item.gameObject);
            else Object.DestroyImmediate(item.gameObject);
        }
    }
}
