using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Pool;

namespace GdwKit
{
    /// <summary>
    /// One ObjectPool per prefab. Put one in the bootstrap scene, or let PoolService.Instance create it.
    /// Spawn: PoolService.Instance.Spawn(prefab, pos, rot). Despawn: pooledObject.Release().
    /// </summary>
    public sealed class PoolService : MonoBehaviour
    {
        [System.Serializable]
        public struct Prewarm
        {
            public GameObject prefab;
            [Min(0)] public int count;
            [Min(1)] public int maxSize;
        }

        [Tooltip("Pools created and filled in Awake, so the first fight doesn't allocate.")]
        [SerializeField] private Prewarm[] prewarm = new Prewarm[0];
        [Tooltip("Default largest number of inactive objects a pool keeps.")]
        [SerializeField, Min(1)] private int defaultMaxSize = 256;
        [Tooltip("Catches double releases. Costs a lookup per release; development builds only.")]
        [SerializeField] private bool collectionCheck = true;

        private readonly Dictionary<GameObject, ObjectPool<PooledObject>> _pools = new Dictionary<GameObject, ObjectPool<PooledObject>>();
        private static PoolService _instance;

        public static PoolService Instance
        {
            get
            {
                if (!_instance) _instance = new GameObject(nameof(PoolService)).AddComponent<PoolService>();
                return _instance;
            }
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetStatics() => _instance = null; // Enter Play Mode without Domain Reload

        private void Awake()
        {
            if (_instance && _instance != this) { Destroy(gameObject); return; }
            _instance = this;
            foreach (var p in prewarm)
                if (p.prefab) Warm(p.prefab, p.count, p.maxSize > 0 ? p.maxSize : defaultMaxSize);
        }

        /// <summary>Create the pool for a prefab (if needed) and fill it with `count` inactive objects.</summary>
        public void Warm(GameObject prefab, int count, int maxSize = 0)
        {
            var pool = PoolFor(prefab, maxSize > 0 ? maxSize : defaultMaxSize);
            var temp = new List<PooledObject>(count);
            for (int i = 0; i < count; i++) temp.Add(pool.Get());
            for (int i = 0; i < temp.Count; i++) pool.Release(temp[i]);
        }

        public PooledObject Spawn(GameObject prefab, Vector3 position, Quaternion rotation, Transform parent = null)
        {
            var obj = PoolFor(prefab, defaultMaxSize).Get();
            var t = obj.transform;
            if (parent) t.SetParent(parent, false);
            t.SetPositionAndRotation(position, rotation);
            obj.gameObject.SetActive(true); // after positioning, so OnEnable/OnGetFromPool see the spawn point
            obj.NotifyGet();
            return obj;
        }

        public T Spawn<T>(T prefab, Vector3 position, Quaternion rotation, Transform parent = null) where T : Component
            => Spawn(prefab.gameObject, position, rotation, parent).GetComponent<T>();

        /// <summary>Active and inactive counts per prefab, for the debug overlay.</summary>
        public IEnumerable<(string name, int active, int inactive)> Stats()
        {
            foreach (var kv in _pools)
                yield return (kv.Key ? kv.Key.name : "?", kv.Value.CountActive, kv.Value.CountInactive);
        }

        private ObjectPool<PooledObject> PoolFor(GameObject prefab, int maxSize)
        {
            if (_pools.TryGetValue(prefab, out var pool)) return pool;
            ObjectPool<PooledObject> created = null;
            created = new ObjectPool<PooledObject>(
                createFunc: () =>
                {
                    var go = Instantiate(prefab, transform);
                    go.SetActive(false);
                    if (!go.TryGetComponent(out PooledObject po)) po = go.AddComponent<PooledObject>();
                    po.Bind(created, prefab);
                    return po;
                },
                actionOnGet: null, // Spawn activates after positioning
                actionOnRelease: po =>
                {
                    po.NotifyRelease();
                    po.gameObject.SetActive(false);
                    if (po.transform.parent != transform) po.transform.SetParent(transform, false);
                },
                actionOnDestroy: po => { if (po) Destroy(po.gameObject); },
                collectionCheck: collectionCheck && Debug.isDebugBuild,
                defaultCapacity: 16,
                maxSize: maxSize);
            _pools.Add(prefab, created);
            return created;
        }

        private void OnDestroy()
        {
            foreach (var pool in _pools.Values) pool.Dispose();
            _pools.Clear();
            if (_instance == this) _instance = null;
        }
    }
}
