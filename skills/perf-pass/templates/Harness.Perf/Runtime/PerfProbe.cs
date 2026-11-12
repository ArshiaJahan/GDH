using System;
using System.Globalization;
using System.IO;
using System.Text;
using Unity.Profiling;
using UnityEngine;

namespace Harness.Perf
{
    /// <summary>
    /// Runtime perf sampler on ProfilerRecorder (no Profiler window needed). After a warm-up it samples every frame
    /// and logs one <c>[PERF] kind=window ...</c> line per window and a <c>[PERF] kind=summary ...</c> line at the end,
    /// and writes the same rows to a CSV for scripts/perf_report.py.
    ///
    /// Keys (suffix _avg / _max, plus _p95 for times and _nz_pct = % of frames with a non-zero value for gc_alloc):
    ///   frame_ms     Internal "Main Thread" (whole main-thread frame, includes vsync/targetFrameRate waits)
    ///   cpu_main_ms  Render "CPU Main Thread Frame Time" (work only; players need Frame Timing Stats enabled)
    ///   gc_alloc     Memory "GC Allocated In Frame" (bytes)         ⚠ Editor + Development players only
    ///   gc_alloc_count, gc_used_mb, gc_reserved_mb, sys_used_mb, go_count
    ///   batches, setpass, drawcalls, tris                       (0 under -nographics: nothing is rendered)
    ///   p2d_ms (marker "Physics2D.Simulate"), p2d_bodies, p2d_awake, p2d_contacts, p2d_queries  ⚠ Editor + Development only
    /// Metrics whose recorder is not valid on the platform are left out of the log and empty in the CSV.
    /// ⚠ batchmode -nographics: the profiler never completes a frame, every recorder stays empty (HasSamples false,
    /// one kind=warning line). Measure in the Editor, a player, or batchmode WITHOUT -nographics.
    ///
    /// Start: PerfProbe.Begin("baseline", seconds: 20) (e.g. from execute_code in Play Mode or a PlayMode test),
    /// or a player/batch command line: -perfProbe baseline -perfSeconds 20 [-perfWarmup 3] [-perfCsv path] [-perfQuit].
    /// The probe's own logging allocates; the frame after each log line is excluded from sampling.
    /// </summary>
    [DefaultExecutionOrder(-32000)]
    public sealed class PerfProbe : MonoBehaviour
    {
        public const string Prefix = "[PERF]";

        public string label = "run";
        [Tooltip("Seconds ignored at the start (loading, shader warm-up, first GC).")]
        public float warmupSeconds = 3f;
        [Tooltip("Seconds to measure after warm-up; 0 = until End() or disable.")]
        public float durationSeconds;
        public float windowSeconds = 1f;
        public bool logWindows = true;
        public bool writeCsv = true;
        [Tooltip("Empty = <project>/Logs/harness/perf/<label>-<time>.csv in the Editor, persistentDataPath/perf/ in players.")]
        public string csvPath = "";
        public bool quitWhenDone;
        [Tooltip("Frames kept for the run-wide p95 (36000 = 10 min at 60 fps).")]
        public int maxFrames = 36000;

        public static PerfProbe Current { get; private set; }
        public bool IsDone { get; private set; }
        public string LastSummary { get; private set; }
        public string CsvFile { get; private set; }
        public int MeasuredFrames => run.frames;
        /// <summary>False when no recorder delivered a value (e.g. batchmode -nographics): the run has no data.</summary>
        public bool HasSamples { get; private set; }

        struct Def
        {
            public string key, stat;
            public ProfilerCategory category;
            public double scale;
            public bool p95, nonZero;
            public Def(string key, ProfilerCategory category, string stat, double scale, bool p95 = false, bool nonZero = false)
            { this.key = key; this.category = category; this.stat = stat; this.scale = scale; this.p95 = p95; this.nonZero = nonZero; }
        }

        const double Ms = 1e-6, Mb = 1.0 / (1024.0 * 1024.0);
        static readonly Def[] Defs =
        {
            new Def("frame_ms", ProfilerCategory.Internal, "Main Thread", Ms, p95: true),
            new Def("cpu_main_ms", ProfilerCategory.Render, "CPU Main Thread Frame Time", Ms, p95: true),
            new Def("gc_alloc", ProfilerCategory.Memory, "GC Allocated In Frame", 1, nonZero: true),
            new Def("gc_alloc_count", ProfilerCategory.Memory, "GC Allocation In Frame Count", 1),
            new Def("gc_used_mb", ProfilerCategory.Memory, "GC Used Memory", Mb),
            new Def("gc_reserved_mb", ProfilerCategory.Memory, "GC Reserved Memory", Mb),
            new Def("sys_used_mb", ProfilerCategory.Memory, "System Used Memory", Mb),
            new Def("go_count", ProfilerCategory.Memory, "Game Object Count", 1),
            new Def("batches", ProfilerCategory.Render, "Batches Count", 1),
            new Def("setpass", ProfilerCategory.Render, "SetPass Calls Count", 1),
            new Def("drawcalls", ProfilerCategory.Render, "Draw Calls Count", 1),
            new Def("tris", ProfilerCategory.Render, "Triangles Count", 1),
            new Def("p2d_ms", ProfilerCategory.Physics2D, "Physics2D.Simulate", Ms, p95: true),
            new Def("p2d_bodies", ProfilerCategory.Physics2D, "Total Bodies", 1),
            new Def("p2d_awake", ProfilerCategory.Physics2D, "Awake Bodies", 1),
            new Def("p2d_contacts", ProfilerCategory.Physics2D, "Total Contacts", 1),
            new Def("p2d_queries", ProfilerCategory.Physics2D, "Total Queries", 1),
        };

        sealed class Acc
        {
            public double sum, max;
            public int n, nonZero;
            public float[] values;
            public void Reset() { sum = 0; max = 0; n = 0; nonZero = 0; }
            public void Add(double v)
            {
                if (values != null && n < values.Length) values[n] = (float)v;
                sum += v;
                if (n == 0 || v > max) max = v;
                if (v > 0) nonZero++;
                n++;
            }
        }

        sealed class Span
        {
            public Acc[] acc;
            public int frames;
            public double start;
        }

        ProfilerRecorder[] recorders;
        bool[] valid;
        readonly Span window = new Span();
        readonly Span run = new Span();
        float[] scratch;
        bool started, skipNext, warnedNoSamples;
        double warmupEnd;
        StringBuilder sb;
        StreamWriter csv;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics() => Current = null;

        /// <summary>Create a probe that survives scene loads. seconds = 0 measures until End().</summary>
        public static PerfProbe Begin(string label, float seconds = 0f, float warmup = 3f, string csv = null)
        {
            if (Current != null) Current.Finish();
            var go = new GameObject("[PerfProbe]");
            DontDestroyOnLoad(go);
            var p = go.AddComponent<PerfProbe>();
            p.label = string.IsNullOrEmpty(label) ? "run" : label;
            p.durationSeconds = seconds;
            p.warmupSeconds = warmup;
            if (!string.IsNullOrEmpty(csv)) p.csvPath = csv;
            return p;
        }

        /// <summary>Finish the current probe now; returns the summary line (also logged).</summary>
        public static string End() => Current != null ? Current.Finish() : null;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void FromCommandLine()
        {
            string[] args = Environment.GetCommandLineArgs();
            string lbl = Arg(args, "-perfProbe");
            if (lbl == null) return;
            var p = Begin(lbl, ParseF(Arg(args, "-perfSeconds"), 20f), ParseF(Arg(args, "-perfWarmup"), 3f), Arg(args, "-perfCsv"));
            p.quitWhenDone = Array.IndexOf(args, "-perfQuit") >= 0;
        }

        static string Arg(string[] args, string name)
        {
            int i = Array.IndexOf(args, name);
            if (i < 0) return null;
            return i + 1 < args.Length && !args[i + 1].StartsWith("-") ? args[i + 1] : "run";
        }

        static float ParseF(string s, float fallback) =>
            float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out float v) ? v : fallback;

        void Awake()
        {
            if (Current != null && Current != this) Current.Finish();
            Current = this;
        }

        void Start()
        {
            int n = Defs.Length;
            recorders = new ProfilerRecorder[n];
            valid = new bool[n];
            window.acc = new Acc[n];
            run.acc = new Acc[n];
            int maxWindowFrames = 8192;
            for (int i = 0; i < n; i++)
            {
                recorders[i] = Defs[i].stat == "Main Thread"
                    ? ProfilerRecorder.StartNew(Defs[i].category, Defs[i].stat, 15)
                    : ProfilerRecorder.StartNew(Defs[i].category, Defs[i].stat);
                valid[i] = recorders[i].Valid;
                window.acc[i] = new Acc { values = Defs[i].p95 ? new float[maxWindowFrames] : null };
                run.acc[i] = new Acc { values = Defs[i].p95 ? new float[Mathf.Max(1024, maxFrames)] : null };
            }
            scratch = new float[Mathf.Max(maxWindowFrames, Mathf.Max(1024, maxFrames))];
            sb = new StringBuilder(1024);
            double now = Time.realtimeSinceStartupAsDouble;
            warmupEnd = now + Mathf.Max(0f, warmupSeconds);
            OpenCsv();
            started = true;
            Debug.Log(Prefix + " kind=start label=" + label + " warmup=" + F(warmupSeconds) + " seconds=" + F(durationSeconds) +
                      " csv=" + (CsvFile ?? "none") + " editor=" + (Application.isEditor ? 1 : 0) +
                      " dev=" + (Debug.isDebugBuild ? 1 : 0) + " valid=" + ValidKeys());
            skipNext = true;
        }

        void Update()
        {
            if (!started || IsDone) return;
            double now = Time.realtimeSinceStartupAsDouble;
            if (now < warmupEnd) return;
            if (run.frames == 0 && window.frames == 0 && run.start == 0) { run.start = now; window.start = now; }
            if (skipNext) { skipNext = false; }
            else
            {
                for (int i = 0; i < Defs.Length; i++)
                {
                    // Count == 0: no completed profiler frame yet (always the case under batchmode -nographics).
                    if (!valid[i] || recorders[i].Count == 0) continue;
                    double v = recorders[i].LastValue * Defs[i].scale;
                    window.acc[i].Add(v);
                    run.acc[i].Add(v);
                    HasSamples = true;
                }
            }
            window.frames++;
            run.frames++;
            if (!HasSamples && !warnedNoSamples && run.frames == 60)
            {
                warnedNoSamples = true;
                Debug.LogWarning(Prefix + " kind=warning reason=no-profiler-samples hint=batchmode_-nographics_never_completes_profiler_frames;_run_without_-nographics");
            }
            if (now - window.start >= windowSeconds) EmitWindow(now);
            if (durationSeconds > 0f && now - run.start >= durationSeconds) Finish();
        }

        void EmitWindow(double now)
        {
            string line = Format("window", window, now - window.start, now - run.start);
            if (logWindows) Debug.Log(line);
            WriteCsv("window", window, now - window.start, now - run.start);
            for (int i = 0; i < Defs.Length; i++) window.acc[i].Reset();
            window.frames = 0;
            window.start = now;
            skipNext = true;
        }

        /// <summary>Emit the summary (once), close the CSV, dispose recorders.</summary>
        public string Finish()
        {
            if (IsDone) return LastSummary;
            IsDone = true;
            if (started)
            {
                double now = Time.realtimeSinceStartupAsDouble;
                double seconds = run.start > 0 ? now - run.start : 0;
                if (window.frames > 0 && logWindows) EmitWindow(now);
                LastSummary = Format("summary", run, seconds, seconds);
                Debug.Log(LastSummary);
                WriteCsv("summary", run, seconds, seconds);
                for (int i = 0; i < recorders.Length; i++) recorders[i].Dispose();
            }
            csv?.Dispose();
            csv = null;
            if (Current == this) Current = null;
            if (quitWhenDone)
            {
#if UNITY_EDITOR
                UnityEditor.EditorApplication.isPlaying = false;
#else
                Application.Quit(0);
#endif
            }
            return LastSummary;
        }

        void OnDestroy()
        {
            if (!IsDone) Finish();
        }

        void OnApplicationQuit()
        {
            if (!IsDone) Finish();
        }

        // ---------------------------------------------------------------- formatting

        string Format(string kind, Span s, double spanSeconds, double t)
        {
            sb.Clear().Append(Prefix).Append(" kind=").Append(kind).Append(" label=").Append(label)
              .Append(" t=").Append(F(t)).Append(" frames=").Append(s.frames)
              .Append(" fps=").Append(F(spanSeconds > 0 ? s.frames / spanSeconds : 0))
              .Append(" editor=").Append(Application.isEditor ? 1 : 0).Append(" dev=").Append(Debug.isDebugBuild ? 1 : 0);
            for (int i = 0; i < Defs.Length; i++)
            {
                if (!valid[i] || s.acc[i].n == 0) continue;
                Acc a = s.acc[i];
                string k = Defs[i].key;
                sb.Append(' ').Append(k).Append("_avg=").Append(F(a.sum / a.n));
                sb.Append(' ').Append(k).Append("_max=").Append(F(a.max));
                if (Defs[i].p95) sb.Append(' ').Append(k).Append("_p95=").Append(F(P95(a)));
                if (Defs[i].nonZero) sb.Append(' ').Append(k).Append("_nz_pct=").Append(F(100.0 * a.nonZero / a.n));
            }
            return sb.ToString();
        }

        double P95(Acc a)
        {
            int n = Mathf.Min(a.n, a.values.Length);
            if (n == 0) return 0;
            Array.Copy(a.values, scratch, n);
            Array.Sort(scratch, 0, n);
            int idx = Mathf.Clamp((int)Math.Ceiling(0.95 * n) - 1, 0, n - 1);
            return scratch[idx];
        }

        string ValidKeys()
        {
            var v = new StringBuilder();
            for (int i = 0; i < Defs.Length; i++)
                if (valid[i]) v.Append(v.Length > 0 ? "," : "").Append(Defs[i].key);
            return v.ToString();
        }

        static string F(double v) => v.ToString("0.###", CultureInfo.InvariantCulture);

        // ---------------------------------------------------------------- CSV

        void OpenCsv()
        {
            if (!writeCsv) return;
            try
            {
                string path = csvPath;
                if (string.IsNullOrEmpty(path))
                {
                    string root = Application.isEditor
                        ? Path.Combine(Path.GetDirectoryName(Application.dataPath) ?? ".", "Logs", "harness", "perf")
                        : Path.Combine(Application.persistentDataPath, "perf");
                    path = Path.Combine(root, label + "-" + DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + ".csv");
                }
                string dir = Path.GetDirectoryName(Path.GetFullPath(path));
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                csv = new StreamWriter(path, false, new UTF8Encoding(false));
                CsvFile = Path.GetFullPath(path);
                var h = new StringBuilder("kind,label,t,frames,fps,editor,dev");
                for (int i = 0; i < Defs.Length; i++)
                {
                    string k = Defs[i].key;
                    h.Append(',').Append(k).Append("_avg,").Append(k).Append("_max");
                    if (Defs[i].p95) h.Append(',').Append(k).Append("_p95");
                    if (Defs[i].nonZero) h.Append(',').Append(k).Append("_nz_pct");
                }
                csv.WriteLine(h.ToString());
                csv.Flush();
            }
            catch (Exception e)
            {
                Debug.LogWarning(Prefix + " csv disabled: " + e.Message);
                csv = null;
                CsvFile = null;
            }
        }

        void WriteCsv(string kind, Span s, double spanSeconds, double t)
        {
            if (csv == null) return;
            sb.Clear().Append(kind).Append(',').Append(label).Append(',').Append(F(t)).Append(',').Append(s.frames)
              .Append(',').Append(F(spanSeconds > 0 ? s.frames / spanSeconds : 0))
              .Append(',').Append(Application.isEditor ? 1 : 0).Append(',').Append(Debug.isDebugBuild ? 1 : 0);
            for (int i = 0; i < Defs.Length; i++)
            {
                Acc a = s.acc[i];
                bool has = valid[i] && a.n > 0;
                sb.Append(',').Append(has ? F(a.sum / a.n) : "").Append(',').Append(has ? F(a.max) : "");
                if (Defs[i].p95) sb.Append(',').Append(has ? F(P95(a)) : "");
                if (Defs[i].nonZero) sb.Append(',').Append(has ? F(100.0 * a.nonZero / a.n) : "");
            }
            csv.WriteLine(sb.ToString());
            csv.Flush();
        }
    }
}
