// Harness.Ship: player smoke test (Unity 6000.3). Inert unless the player is launched with -smoketest.
//   Game.app/Contents/MacOS/Game -smoketest [-smokeSeconds 5] [-smokeOut /abs/result.txt] [-smokeScene Name]
//                                [-smokeAllowErrors] [-logFile player.log]
// Put the component on any GameObject in the first build scene (its Inspector value is the default duration),
// or leave it out: with -smoketest a runner is created automatically after the first scene loads.
// The runner loads -smokeScene if given, waits N seconds of real time, counts exceptions/asserts/errors via
// Application.logMessageReceivedThreaded (hooked before the first scene loads), writes the result file and calls
// Application.Quit(0 ok | 1 fail). Never runs inside the Editor.
// Result file (default Application.persistentDataPath/smoketest.txt): first line "ok" or "fail: <reason>",
// then key=value lines (scene, seconds, frames, fps, exceptions, asserts, errors, version, ...) and up to 20 messages.
// WebGL: no command line; append ?smoketest to the page URL, the result goes to the browser console as "[SMOKE] ok".
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Harness.Ship
{
    [DisallowMultipleComponent]
    public sealed class SmokeTest : MonoBehaviour
    {
        [Tooltip("Seconds to run when -smokeSeconds is not given.")]
        [SerializeField] float defaultSeconds = 5f;

        static readonly object s_Lock = new object();
        static readonly List<string> s_Messages = new List<string>();
        static int s_Exceptions, s_Errors, s_Asserts;
        static bool s_Hooked, s_Creating;
        static SmokeTest s_Runner;
        static float s_PendingSeconds = 5f;

        float m_Seconds;
        string m_OutPath;
        string m_Scene;
        bool m_AllowErrors;

        /// <summary>True in a player started with -smoketest (WebGL: URL contains "smoketest").</summary>
        public static bool Requested()
        {
            if (Application.isEditor) return false;
            if (Application.platform == RuntimePlatform.WebGLPlayer)
                return (Application.absoluteURL ?? "").IndexOf("smoketest", StringComparison.OrdinalIgnoreCase) >= 0;
            return HasArg("-smoketest");
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void HookLogEarly()
        {
            if (!Requested() || s_Hooked) return;
            s_Hooked = true;
            Application.logMessageReceivedThreaded += OnLog;
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void EnsureRunner()
        {
            if (Requested() && s_Runner == null) CreateRunner(5f);
        }

        static void CreateRunner(float seconds)
        {
            s_PendingSeconds = seconds;
            var go = new GameObject("[Harness.SmokeTest]");
            DontDestroyOnLoad(go);
            s_Creating = true;
            try { go.AddComponent<SmokeTest>(); }
            finally { s_Creating = false; }
        }

        void Awake()
        {
            if (s_Creating)
            {
                s_Runner = this;
                m_Seconds = s_PendingSeconds;
                return;
            }
            // Scene-placed component: hand over to a DontDestroyOnLoad runner so -smokeScene can switch scenes.
            enabled = false;
            if (Requested() && s_Runner == null) CreateRunner(defaultSeconds > 0 ? defaultSeconds : 5f);
        }

        static string[] Args() { return Environment.GetCommandLineArgs(); }

        static bool HasArg(string name)
        {
            foreach (var a in Args()) if (string.Equals(a, name, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        static string GetArg(string name)
        {
            var args = Args();
            for (int i = 0; i < args.Length - 1; i++)
                if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase)) return args[i + 1];
            return null;
        }

        static void OnLog(string condition, string stackTrace, LogType type)
        {
            if (type == LogType.Log || type == LogType.Warning) return;
            lock (s_Lock)
            {
                if (type == LogType.Exception) s_Exceptions++;
                else if (type == LogType.Assert) s_Asserts++;
                else s_Errors++;
                if (s_Messages.Count < 20)
                {
                    var first = string.IsNullOrEmpty(stackTrace) ? "" : stackTrace.Split('\n')[0];
                    s_Messages.Add(type + ": " + (condition ?? "").Split('\n')[0] + (first.Length > 0 ? " @ " + first : ""));
                }
            }
        }

        IEnumerator Start()
        {
            if (s_Runner != this) yield break;
            if (!s_Hooked) { s_Hooked = true; Application.logMessageReceivedThreaded += OnLog; }

            float s;
            var sec = GetArg("-smokeSeconds");
            if (sec != null && float.TryParse(sec, NumberStyles.Float, CultureInfo.InvariantCulture, out s) && s > 0) m_Seconds = s;
            if (m_Seconds <= 0) m_Seconds = 5f;
            m_OutPath = GetArg("-smokeOut");
            if (string.IsNullOrEmpty(m_OutPath)) m_OutPath = Path.Combine(Application.persistentDataPath, "smoketest.txt");
            m_Scene = GetArg("-smokeScene");
            m_AllowErrors = HasArg("-smokeAllowErrors");
            Debug.Log("[SMOKE] start seconds=" + m_Seconds.ToString(CultureInfo.InvariantCulture) + " out=" + m_OutPath
                      + " version=" + Application.version);

            if (!string.IsNullOrEmpty(m_Scene) && SceneManager.GetActiveScene().name != m_Scene)
            {
                if (!Application.CanStreamedLevelBeLoaded(m_Scene))
                {
                    Finish("fail: scene not in build: " + m_Scene);
                    yield break;
                }
                yield return SceneManager.LoadSceneAsync(m_Scene);
            }
            if (SceneManager.sceneCountInBuildSettings == 0 || !SceneManager.GetActiveScene().IsValid())
            {
                Finish("fail: no scene loaded");
                yield break;
            }
            int startFrame = Time.frameCount;
            float start = Time.realtimeSinceStartup;
            yield return new WaitForSecondsRealtime(m_Seconds);
            int frames = Time.frameCount - startFrame;
            float elapsed = Mathf.Max(0.001f, Time.realtimeSinceStartup - start);

            string verdict;
            lock (s_Lock)
            {
                if (s_Exceptions > 0) verdict = "fail: " + s_Exceptions + " exception(s)";
                else if (s_Asserts > 0) verdict = "fail: " + s_Asserts + " assert(s)";
                else if (s_Errors > 0 && !m_AllowErrors) verdict = "fail: " + s_Errors + " error(s)";
                else if (frames < 2) verdict = "fail: frames did not advance";
                else verdict = "ok";
            }
            Finish(verdict, frames, frames / elapsed);
        }

        void Finish(string verdict, int frames = 0, float fps = 0f)
        {
            var inv = CultureInfo.InvariantCulture;
            var sb = new StringBuilder();
            sb.Append(verdict).Append('\n');
            lock (s_Lock)
            {
                sb.Append("scene=").Append(SceneManager.GetActiveScene().name).Append('\n');
                sb.Append("seconds=").Append(m_Seconds.ToString(inv)).Append('\n');
                sb.Append("frames=").Append(frames).Append('\n');
                sb.Append("fps=").Append(fps.ToString("0.0", inv)).Append('\n');
                sb.Append("exceptions=").Append(s_Exceptions).Append('\n');
                sb.Append("asserts=").Append(s_Asserts).Append('\n');
                sb.Append("errors=").Append(s_Errors).Append('\n');
                sb.Append("version=").Append(Application.version).Append('\n');
                sb.Append("product=").Append(Application.productName).Append('\n');
                sb.Append("unity=").Append(Application.unityVersion).Append('\n');
                sb.Append("platform=").Append(Application.platform).Append('\n');
                sb.Append("utc=").Append(DateTime.UtcNow.ToString("o", inv)).Append('\n');
                foreach (var m in s_Messages) sb.Append("message=").Append(m).Append('\n');
            }
            bool ok = verdict == "ok";
            Debug.Log("[SMOKE] " + verdict);
            if (Application.platform == RuntimePlatform.WebGLPlayer)
            {
                Debug.Log("[SMOKE] result\n" + sb);
                return;
            }
            try
            {
                var dir = Path.GetDirectoryName(m_OutPath);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                File.WriteAllText(m_OutPath, sb.ToString());
            }
            catch (Exception e)
            {
                Debug.LogWarning("[SMOKE] could not write " + m_OutPath + ": " + e.Message);
                ok = false;
            }
            Application.logMessageReceivedThreaded -= OnLog;
            Application.Quit(ok ? 0 : 1);
        }
    }
}
