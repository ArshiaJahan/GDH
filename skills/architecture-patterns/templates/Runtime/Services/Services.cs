using System;
using System.Collections.Generic;
using UnityEngine;

namespace Harness.Arch
{
    /// <summary>
    /// Minimal service locator for cross-cutting systems (save store, audio, scene loader). Register in the
    /// Bootstrap scene, Get from gameplay code. Prefer serialized references for anything scene-local.
    /// Cleared at play start so domain-reload-off sessions don't keep stale services.
    /// </summary>
    public static class Services
    {
        static readonly Dictionary<Type, object> map = new Dictionary<Type, object>();

        public static void Register<T>(T service) where T : class
        {
            if (service == null) throw new ArgumentNullException(nameof(service));
            if (map.ContainsKey(typeof(T))) Debug.LogWarning($"[Services] replacing {typeof(T).Name}");
            map[typeof(T)] = service;
        }

        public static void Unregister<T>(T service) where T : class
        {
            if (map.TryGetValue(typeof(T), out var s) && ReferenceEquals(s, service)) map.Remove(typeof(T));
        }

        public static T Get<T>() where T : class
        {
            if (map.TryGetValue(typeof(T), out var s)) return (T)s;
            throw new InvalidOperationException($"[Services] {typeof(T).Name} not registered. Is the Bootstrap scene loaded?");
        }

        public static bool TryGet<T>(out T service) where T : class
        {
            if (map.TryGetValue(typeof(T), out var s)) { service = (T)s; return true; }
            service = null;
            return false;
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        public static void Reset() => map.Clear();
    }
}
