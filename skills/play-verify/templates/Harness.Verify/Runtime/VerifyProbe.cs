using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Harness.Verify
{
    /// <summary>
    /// Structured state reporter for play verification. Every report is one console line:
    /// <c>[VERIFY] key=value key2=value2</c> (values without spaces, or "quoted"), which
    /// scripts/check_criteria.py and PlayMode tests can assert on.
    ///
    /// Three ways to feed it (mix freely):
    /// 1. Game code pushes values:     <c>VerifyProbe.Set("player.hp", hp);</c>
    /// 2. Game code registers getters: <c>VerifyProbe.Register("rooms", () => dungeon.RoomCount);</c>
    /// 3. No code change: add this component and fill <see cref="watches"/> with
    ///    <c>key=GameObjectPath:ComponentType.memberName</c> (public or private field/property, read by reflection).
    ///
    /// Built-in keys: t (time since start), frame, scene, fps (average over the interval), fps.min,
    /// log.errors / log.exceptions / log.warnings (counted since start, so "log.errors=0" is a criterion).
    /// Reports happen every <see cref="interval"/> seconds (0 = only on demand), on <see cref="Dump"/>,
    /// and once on quit/disable. Active in the Editor and development builds; a no-op in release builds
    /// unless <see cref="ForceEnable"/> is set.
    /// </summary>
    [DefaultExecutionOrder(-9000)]
    [DisallowMultipleComponent]
    public sealed class VerifyProbe : MonoBehaviour
    {
        public const string Prefix = "[VERIFY]";

        [Tooltip("Seconds between automatic reports. 0 = only on demand (Dump/DumpAll) and on disable.")]
        public float interval = 1f;

        [Tooltip("key=GameObjectPath:ComponentType.member, e.g. player.hp=Player:Health.current")]
        public List<string> watches = new List<string>();

        [Tooltip("Survive scene loads (recommended for multi-scene runs).")]
        public bool dontDestroyOnLoad = true;

        /// <summary>Set before play to keep the probe active in release builds.</summary>
        public static bool ForceEnable;

        static readonly Dictionary<string, string> s_Values = new Dictionary<string, string>();
        static readonly Dictionary<string, Func<object>> s_Getters = new Dictionary<string, Func<object>>();
        static int s_Errors, s_Exceptions, s_Warnings;
        static bool s_Hooked;
        static float s_StartTime;
        static VerifyProbe s_Instance;

        float m_Next;
        int m_Frames;
        float m_WindowStart;
        float m_MinFps = float.MaxValue;
        readonly List<WatchSpec> m_Watches = new List<WatchSpec>();

        struct WatchSpec
        {
            public string key, path, type, member;
        }

        /// <summary>Probe is active (Editor, development build, or forced).</summary>
        public static bool Active => Application.isEditor || Debug.isDebugBuild || ForceEnable;

        /// <summary>The probe in the scene, created on first use if missing.</summary>
        public static VerifyProbe Instance
        {
            get
            {
                if (s_Instance == null && Application.isPlaying)
                {
                    var go = new GameObject("[VerifyProbe]");
                    s_Instance = go.AddComponent<VerifyProbe>();
                }
                return s_Instance;
            }
        }

        // Enter Play Mode Options with domain reload disabled keep statics alive between runs: reset them here.
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            s_Values.Clear();
            s_Getters.Clear();
            s_Errors = s_Exceptions = s_Warnings = 0;
            s_Instance = null;
            s_StartTime = 0f;
            if (s_Hooked) Application.logMessageReceived -= OnLog;
            s_Hooked = false;
            HookLog();
        }

        static void HookLog()
        {
            if (s_Hooked) return;
            Application.logMessageReceived += OnLog;
            s_Hooked = true;
        }

        static void OnLog(string condition, string stackTrace, LogType type)
        {
            if (condition != null && condition.StartsWith(Prefix, StringComparison.Ordinal)) return;
            switch (type)
            {
                case LogType.Exception: s_Exceptions++; break;
                case LogType.Error:
                case LogType.Assert: s_Errors++; break;
                case LogType.Warning: s_Warnings++; break;
            }
        }

        // ------------------------------------------------------------------ static API

        /// <summary>Forgets stored values, getters and log counters and restarts t. Call at the start of each
        /// PlayMode test or verification run: values survive between tests in one Play session.</summary>
        public static void ResetAll()
        {
            s_Values.Clear();
            s_Getters.Clear();
            s_Errors = s_Exceptions = s_Warnings = 0;
            s_StartTime = Time.time;
            HookLog();
        }

        /// <summary>Stores a value (reported with the next dump). Does not log by itself.</summary>
        public static void Set(string key, object value)
        {
            if (!Active || string.IsNullOrEmpty(key)) return;
            s_Values[key] = Format(value);
        }

        /// <summary>Stores a value and logs it immediately as one [VERIFY] line.</summary>
        public static void Log(string key, object value)
        {
            if (!Active || string.IsNullOrEmpty(key)) return;
            string v = Format(value);
            s_Values[key] = v;
            Debug.Log(Prefix + " " + key + "=" + v);
        }

        /// <summary>Logs a marker event, e.g. Mark("boss.spawned") → [VERIFY] event=boss.spawned t=12.30</summary>
        public static void Mark(string name)
        {
            if (!Active) return;
            Debug.Log(Prefix + " event=" + Quote(name) + " t=" + Format(Time.time - s_StartTime));
        }

        /// <summary>Registers a getter evaluated at every dump.</summary>
        public static void Register(string key, Func<object> getter)
        {
            if (string.IsNullOrEmpty(key) || getter == null) return;
            s_Getters[key] = getter;
        }

        public static void Unregister(string key) => s_Getters.Remove(key);

        /// <summary>Adds a watch at runtime (e.g. from execute_code): "player.hp=Player:Health.current".</summary>
        public static void Watch(string spec)
        {
            var probe = Instance;
            if (probe == null || string.IsNullOrEmpty(spec)) return;
            if (!probe.watches.Contains(spec)) probe.watches.Add(spec);
            probe.ParseWatches();
        }

        /// <summary>Latest value of a key (getters and watches are evaluated now).</summary>
        public static bool TryGet(string key, out string value)
        {
            if (s_Instance != null) s_Instance.Collect();
            else CollectGetters();
            if (key == "log.errors") { value = s_Errors.ToString(CultureInfo.InvariantCulture); return true; }
            if (key == "log.exceptions") { value = s_Exceptions.ToString(CultureInfo.InvariantCulture); return true; }
            if (key == "log.warnings") { value = s_Warnings.ToString(CultureInfo.InvariantCulture); return true; }
            return s_Values.TryGetValue(key, out value);
        }

        /// <summary>Latest value parsed as float (NaN when missing or not numeric).</summary>
        public static float GetFloat(string key)
        {
            string s;
            float f;
            if (TryGet(key, out s) && float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out f)) return f;
            if (s == "true") return 1f;
            if (s == "false") return 0f;
            return float.NaN;
        }

        public static int ErrorCount => s_Errors + s_Exceptions;

        /// <summary>Logs every known key as one [VERIFY] line. Safe to call from execute_code during Play Mode.</summary>
        public static string DumpAll()
        {
            if (!Active) return "";
            if (s_Instance != null) s_Instance.Collect();
            else CollectGetters();
            var sb = new StringBuilder(Prefix);
            sb.Append(" t=").Append(Format(Time.time - s_StartTime));
            sb.Append(" frame=").Append(Time.frameCount);
            sb.Append(" scene=").Append(Quote(SceneManager.GetActiveScene().name));
            sb.Append(" log.errors=").Append(s_Errors);
            sb.Append(" log.exceptions=").Append(s_Exceptions);
            sb.Append(" log.warnings=").Append(s_Warnings);
            foreach (var kv in s_Values) sb.Append(' ').Append(kv.Key).Append('=').Append(kv.Value);
            string line = sb.ToString();
            Debug.Log(line);
            return line;
        }

        /// <summary>Instance shortcut for UnityEvents / SendMessage("Dump").</summary>
        public void Dump() => DumpAll();

        // ------------------------------------------------------------------ component

        void Awake()
        {
            if (s_Instance != null && s_Instance != this)
            {
                // One probe per run (e.g. a DontDestroyOnLoad probe meets the next scene's probe):
                // keep the first, adopt the newcomer's watches.
                foreach (var w in watches)
                    if (!s_Instance.watches.Contains(w)) s_Instance.watches.Add(w);
                s_Instance.ParseWatches();
                Destroy(this);
                return;
            }
            s_Instance = this;
            HookLog();
            if (s_StartTime <= 0f) s_StartTime = Time.time;
            if (dontDestroyOnLoad && transform.parent == null) DontDestroyOnLoad(gameObject);
            ParseWatches();
            m_WindowStart = Time.unscaledTime;
            m_Next = Time.unscaledTime + Mathf.Max(0.05f, interval);
        }

        void Update()
        {
            if (!Active) return;
            m_Frames++;
            float now = Time.unscaledTime;
            float dt = Time.unscaledDeltaTime;
            if (dt > 0f && Time.frameCount > 5) m_MinFps = Mathf.Min(m_MinFps, 1f / dt);
            if (interval > 0f && now >= m_Next)
            {
                UpdateFps(now);
                DumpAll();
                m_Next = now + interval;
            }
        }

        void UpdateFps(float now)
        {
            float span = now - m_WindowStart;
            if (span > 0f) s_Values["fps"] = Format(m_Frames / span);
            if (m_MinFps < float.MaxValue) s_Values["fps.min"] = Format(m_MinFps);
            m_Frames = 0;
            m_WindowStart = now;
            m_MinFps = float.MaxValue;
        }

        void OnDisable()
        {
            if (s_Instance != this || !Active) return;
            UpdateFps(Time.unscaledTime);
            DumpAll();
        }

        void OnDestroy()
        {
            if (s_Instance == this) s_Instance = null;
        }

        void ParseWatches()
        {
            m_Watches.Clear();
            foreach (var w in watches)
            {
                // key=Path:Type.member
                if (string.IsNullOrEmpty(w)) continue;
                int eq = w.IndexOf('=');
                int colon = w.LastIndexOf(':');
                int dot = w.LastIndexOf('.');
                if (eq <= 0 || colon <= eq || dot <= colon)
                {
                    Debug.LogWarning("VerifyProbe: bad watch '" + w + "' (want key=Path:Type.member)");
                    continue;
                }
                m_Watches.Add(new WatchSpec
                {
                    key = w.Substring(0, eq).Trim(),
                    path = w.Substring(eq + 1, colon - eq - 1).Trim(),
                    type = w.Substring(colon + 1, dot - colon - 1).Trim(),
                    member = w.Substring(dot + 1).Trim()
                });
            }
        }

        void Collect()
        {
            CollectGetters();
            foreach (var w in m_Watches) s_Values[w.key] = ReadWatch(w);
        }

        static void CollectGetters()
        {
            foreach (var kv in s_Getters)
            {
                try { s_Values[kv.Key] = Format(kv.Value()); }
                catch (Exception e) { s_Values[kv.Key] = Quote("ERR:" + e.GetType().Name); }
            }
        }

        static string ReadWatch(WatchSpec w)
        {
            var go = GameObject.Find(w.path);
            if (go == null) return "missing";
            var comp = go.GetComponent(w.type);
            if (comp == null) return "missing";
            const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            for (var t = comp.GetType(); t != null; t = t.BaseType)
            {
                var f = t.GetField(w.member, flags);
                if (f != null) return Format(f.GetValue(comp));
                var p = t.GetProperty(w.member, flags);
                if (p != null && p.GetIndexParameters().Length == 0) return Format(p.GetValue(comp, null));
            }
            return "missing";
        }

        // ------------------------------------------------------------------ formatting

        static string Format(object value)
        {
            if (value == null) return "null";
            if (value is float f) return f.ToString("0.###", CultureInfo.InvariantCulture);
            if (value is double d) return d.ToString("0.###", CultureInfo.InvariantCulture);
            if (value is bool b) return b ? "true" : "false";
            if (value is Vector2 v2) return Format(v2.x) + "," + Format(v2.y);
            if (value is Vector3 v3) return Format(v3.x) + "," + Format(v3.y) + "," + Format(v3.z);
            if (value is UnityEngine.Object o) return o == null ? "null" : Quote(o.name);
            if (value is IFormattable fm) return Quote(fm.ToString(null, CultureInfo.InvariantCulture));
            return Quote(value.ToString());
        }

        static string Quote(string s)
        {
            if (string.IsNullOrEmpty(s)) return "\"\"";
            foreach (char c in s)
                if (char.IsWhiteSpace(c) || c == '"' || c == '=')
                    return "\"" + s.Replace("\"", "'") + "\"";
            return s;
        }
    }
}
