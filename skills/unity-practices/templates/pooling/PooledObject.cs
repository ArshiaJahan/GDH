using UnityEngine;
using UnityEngine.Pool;

namespace GdwKit
{
    /// <summary>Added to every pooled instance by PoolService. Call Release() instead of Destroy().</summary>
    [DisallowMultipleComponent]
    public sealed class PooledObject : MonoBehaviour
    {
        private IObjectPool<PooledObject> _pool;
        private IPoolable[] _poolables;
        private bool _released;

        public GameObject Prefab { get; private set; }
        public bool IsReleased => _released;

        internal void Bind(IObjectPool<PooledObject> pool, GameObject prefab)
        {
            _pool = pool;
            Prefab = prefab;
            _poolables = GetComponentsInChildren<IPoolable>(true);
        }

        internal void NotifyGet()
        {
            _released = false;
            for (int i = 0; i < _poolables.Length; i++) _poolables[i].OnGetFromPool();
        }

        internal void NotifyRelease()
        {
            _released = true;
            for (int i = 0; i < _poolables.Length; i++) _poolables[i].OnReleaseToPool();
        }

        /// <summary>Return this object to its pool. Safe to call twice (the second call is ignored).</summary>
        public void Release()
        {
            if (_released) return;
            if (_pool != null) _pool.Release(this);
            else Destroy(gameObject); // not spawned through a pool
        }
    }
}
