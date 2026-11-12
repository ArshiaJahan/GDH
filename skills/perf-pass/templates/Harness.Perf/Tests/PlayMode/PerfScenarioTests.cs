using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace Harness.Perf.Tests
{
    /// <summary>
    /// Perf scenario template + PerfProbe self-test. For your game, copy Scenario_Swarm_Pooled: load the real scene
    /// (SceneManager.LoadScene) or spawn the worst case (max enemies, projectiles, particles), then measure.
    /// CSVs go to Logs/harness/perf/test-&lt;label&gt;.csv for scripts/perf_report.py.
    /// Run headless WITHOUT -nographics when you need render counters (batches/setpass are 0 otherwise).
    /// </summary>
    [Category("Perf")]
    public class PerfScenarioTests
    {
        const int Enemies = 300;
        const int ShotsPerFrame = 6;
        const float Warmup = 1f, Seconds = 3f;

        GameObject root;

        static string CsvPath(string label) =>
            Path.Combine(Path.GetDirectoryName(Application.dataPath) ?? ".", "Logs", "harness", "perf", "test-" + label + ".csv");

        [TearDown]
        public void TearDown()
        {
            if (root != null) Object.Destroy(root);
            PerfProbe.End();
        }

        /// <summary>Template: the worst-case swarm, measured. Copy and point it at your real scene.</summary>
        [UnityTest, Timeout(120000)]
        public IEnumerator Scenario_Swarm()
        {
            PerfProbe probe = null;
            yield return RunScenario("swarm", false, p => probe = p);
            Dictionary<string, double> s = Parse(probe.LastSummary);
            Assert.IsTrue(s.ContainsKey("frame_ms_p95"), "frame time recorded: " + probe.LastSummary);
            Assert.IsTrue(s.ContainsKey("gc_alloc_avg"), "GC alloc recorder valid in the Editor");
            Assert.IsTrue(s.ContainsKey("p2d_bodies_avg"), "Physics2D counters valid in the Editor");
            Assert.GreaterOrEqual(s["p2d_bodies_avg"], Enemies, "all enemy bodies counted");
            Assert.IsTrue(File.Exists(probe.CsvFile), "CSV written: " + probe.CsvFile);
        }

        /// <summary>Self-test: the probe must see the garbage that Instantiate/Destroy + LINQ + string concat make.</summary>
        [UnityTest, Timeout(180000)]
        public IEnumerator Probe_DetectsPerFrameGarbage()
        {
            PerfProbe pooled = null, allocating = null;
            yield return RunScenario("pooled", false, p => pooled = p);
            Object.Destroy(root);
            yield return null;
            yield return RunScenario("allocating", true, p => allocating = p);
            Dictionary<string, double> a = Parse(pooled.LastSummary), b = Parse(allocating.LastSummary);
            Assert.Greater(b["gc_alloc_avg"], a["gc_alloc_avg"] + 1000,
                "allocating scenario must allocate more per frame.\n pooled: " + pooled.LastSummary + "\n allocating: " + allocating.LastSummary);
            Assert.Greater(b["gc_alloc_nz_pct"], 90, "garbage on (almost) every frame");
        }

        IEnumerator RunScenario(string label, bool allocating, System.Action<PerfProbe> result)
        {
            root = new GameObject("PerfScenario");
            var cam = new GameObject("Main Camera", typeof(Camera));
            cam.transform.SetParent(root.transform);
            var c = cam.GetComponent<Camera>();
            c.orthographic = true;
            c.orthographicSize = 12f;
            cam.transform.position = new Vector3(0f, 0f, -10f);
            var tex = new Texture2D(8, 8);
            var sprite = Sprite.Create(tex, new Rect(0, 0, 8, 8), new Vector2(0.5f, 0.5f), 8f);
            root.AddComponent<SwarmScenario>().Init(sprite, Enemies, ShotsPerFrame, allocating);

            PerfProbe probe = PerfProbe.Begin("test-" + label, Seconds, Warmup, CsvPath(label));
            float timeout = Time.realtimeSinceStartup + Warmup + Seconds + 30f;
            while (!probe.IsDone && Time.realtimeSinceStartup < timeout) yield return null;
            Assert.IsTrue(probe.IsDone, "probe finished");
            if (!probe.HasSamples)
                Assert.Ignore("ProfilerRecorder delivered no samples (batchmode -nographics never completes profiler frames). Run without -nographics.");
            StringAssert.StartsWith("[PERF] kind=summary label=test-" + label, probe.LastSummary);
            result(probe);
        }

        static Dictionary<string, double> Parse(string summary)
        {
            var d = new Dictionary<string, double>();
            if (summary == null) return d;
            foreach (Match m in Regex.Matches(summary, @"(\w+)=(-?[0-9.]+)\b"))
                d[m.Groups[1].Value] = double.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture);
            return d;
        }
    }
}
