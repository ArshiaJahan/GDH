using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using UnityEngine;

namespace Harness.Verify
{
    /// <summary>
    /// Plays a tiny command script during Play Mode so an agent can drive the game without a human.
    /// Start it from the Inspector (<see cref="script"/> + <see cref="autoStart"/>), from game/test code, or from
    /// MCP execute_code while playing: <c>Harness.Verify.ScriptedInput.Run("wait 1; tap Space; wait 0.5; probe");</c>
    ///
    /// Commands (separated by ';' or new lines, '#' starts a comment):
    ///   wait SECONDS               block for game seconds          frames N        block for N rendered frames
    ///   send PATH METHOD [ARG]     GameObject.Find(PATH).SendMessage(METHOD, ARG)  (ARG: int, float, true/false or text)
    ///   call TYPE.METHOD [ARG]     static method by full type name (any loaded assembly), e.g. call MyGame.Cheats.GodMode
    ///   down KEY / up KEY          press / release a key           tap KEY [FRAMES=3]   hold KEY SECONDS
    ///   until KEY OP VALUE [TIMEOUT=5]  block until VerifyProbe value matches (OP: == != &gt; &gt;= &lt; &lt;=); abort on timeout
    ///   probe                      VerifyProbe.DumpAll()           mark NAME       VerifyProbe.Mark(NAME)
    ///   shot FILE [SUPERSIZE]      ScreenCapture.CaptureScreenshot (path relative to the project folder; written at
    ///                              end of frame, incl. overlay UI). In batchmode it falls back to render.
    ///   render FILE [W H]          render Camera.main to a PNG now (no overlay UI; default 1280x720)
    ///   timescale X                Time.timeScale = X              fps N           Time.captureFramerate = N (0 = off)
    ///   end                        stop the script
    /// Key commands need a key backend: VirtualKeyboard (Harness.Verify.InputSystem, Input System package) installs
    /// itself automatically; otherwise set <see cref="KeyHandler"/> yourself or use send/call to invoke game methods.
    /// Progress is logged as [VERIFY] lines: script.step=N, script.done=1, script.failed=1.
    /// </summary>
    public sealed class ScriptedInput : MonoBehaviour
    {
        [TextArea(3, 12)] public string script = "";
        public bool autoStart = true;

        /// <summary>Key backend: (keyName, pressed). Returns false if the key name is unknown.</summary>
        public static Func<string, bool, bool> KeyHandler;

        public static bool Done { get; private set; } = true;
        public static bool Failed { get; private set; }
        public static ScriptedInput Current { get; private set; }

        const int MaxCommandsPerFrame = 64;
        readonly List<string[]> m_Cmds = new List<string[]>();
        readonly Dictionary<string, float> m_ReleaseAt = new Dictionary<string, float>();
        readonly Dictionary<string, int> m_ReleaseFrame = new Dictionary<string, int>();
        int m_Pc;
        float m_WaitUntil = -1f;
        int m_WaitFrame = -1;
        string[] m_Until;
        float m_UntilDeadline;
        bool m_Running;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            Done = true;
            Failed = false;
            Current = null;
            // KeyHandler is re-installed by backends in their own RuntimeInitializeOnLoadMethod.
            KeyHandler = null;
        }

        /// <summary>Creates a runner object and starts the script (stops a running one).</summary>
        public static ScriptedInput Run(string commands)
        {
            if (Current != null) Current.Stop();
            var go = new GameObject("[ScriptedInput]");
            var si = go.AddComponent<ScriptedInput>();
            si.autoStart = false;
            si.script = commands;
            si.Begin();
            return si;
        }

        void Start()
        {
            if (autoStart && !string.IsNullOrEmpty(script)) Begin();
        }

        public void Begin()
        {
            m_Cmds.Clear();
            foreach (var raw in script.Split(';', '\n'))
            {
                var line = raw.Trim();
                int hash = line.IndexOf('#');
                if (hash >= 0) line = line.Substring(0, hash).Trim();
                if (line.Length > 0) m_Cmds.Add(line.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries));
            }
            m_Pc = 0;
            m_WaitUntil = -1f;
            m_WaitFrame = -1;
            m_Until = null;
            Done = false;
            Failed = false;
            Current = this;
            m_Running = true;
            VerifyProbe.Set("script.done", 0);   // stale values from a previous script must not satisfy waits
            VerifyProbe.Set("script.failed", 0);
            VerifyProbe.Log("script.steps", m_Cmds.Count);
        }

        public void Stop()
        {
            foreach (var k in new List<string>(m_ReleaseAt.Keys)) Key(k, false);
            foreach (var k in new List<string>(m_ReleaseFrame.Keys)) Key(k, false);
            m_ReleaseAt.Clear();
            m_ReleaseFrame.Clear();
            m_Running = false;
            Done = true;
            if (Current == this) Current = null;
        }

        void OnDisable()
        {
            if (m_Running) Stop();
        }

        void Update()
        {
            if (!m_Running) return;
            float now = Time.time;
            ReleaseDue(now);
            for (int n = 0; n < MaxCommandsPerFrame; n++)
            {
                if (m_WaitUntil >= 0f) { if (now < m_WaitUntil) return; m_WaitUntil = -1f; }
                if (m_WaitFrame >= 0) { if (Time.frameCount < m_WaitFrame) return; m_WaitFrame = -1; }
                if (m_Until != null)
                {
                    if (Check(m_Until)) m_Until = null;
                    else if (now >= m_UntilDeadline) { Fail("until timed out: " + string.Join(" ", m_Until, 1, 3)); return; }
                    else return;
                }
                if (m_Pc >= m_Cmds.Count) { Finish(); return; }
                var cmd = m_Cmds[m_Pc++];
                try { Exec(cmd); }
                catch (Exception e) { Fail(cmd[0] + ": " + e.GetType().Name + " " + e.Message); return; }
                if (!m_Running) return;
            }
        }

        void Finish()
        {
            Stop();
            VerifyProbe.Log("script.done", 1);
        }

        void Fail(string why)
        {
            Failed = true;
            Stop();
            VerifyProbe.Set("script.failed", 1);
            Debug.LogWarning(VerifyProbe.Prefix + " script.failed=1 reason=\"" + why.Replace("\"", "'") + "\"");
        }

        void ReleaseDue(float now)
        {
            List<string> due = null;
            foreach (var kv in m_ReleaseAt) if (now >= kv.Value) (due = due ?? new List<string>()).Add(kv.Key);
            foreach (var kv in m_ReleaseFrame) if (Time.frameCount >= kv.Value) (due = due ?? new List<string>()).Add(kv.Key);
            if (due == null) return;
            foreach (var k in due)
            {
                m_ReleaseAt.Remove(k);
                m_ReleaseFrame.Remove(k);
                Key(k, false);
            }
        }

        static void Key(string key, bool down)
        {
            if (KeyHandler == null)
                throw new InvalidOperationException("no key backend (add Harness.Verify.InputSystem or set ScriptedInput.KeyHandler)");
            if (!KeyHandler(key, down)) throw new ArgumentException("unknown key '" + key + "'");
        }

        static float F(string s) => float.Parse(s, NumberStyles.Float, CultureInfo.InvariantCulture);

        void Exec(string[] c)
        {
            VerifyProbe.Set("script.step", m_Pc);
            switch (c[0].ToLowerInvariant())
            {
                case "wait": m_WaitUntil = Time.time + F(c[1]); break;
                case "frames": m_WaitFrame = Time.frameCount + int.Parse(c[1], CultureInfo.InvariantCulture); break;
                case "down": m_ReleaseAt.Remove(c[1]); m_ReleaseFrame.Remove(c[1]); Key(c[1], true); break;
                case "up": m_ReleaseAt.Remove(c[1]); m_ReleaseFrame.Remove(c[1]); Key(c[1], false); break;
                case "tap":
                    Key(c[1], true);
                    m_ReleaseFrame[c[1]] = Time.frameCount + (c.Length > 2 ? int.Parse(c[2], CultureInfo.InvariantCulture) : 3);
                    break;
                case "hold":
                    Key(c[1], true);
                    m_ReleaseAt[c[1]] = Time.time + F(c[2]);
                    break;
                case "send":
                {
                    var go = GameObject.Find(c[1]);
                    if (go == null) throw new ArgumentException("GameObject not found: " + c[1]);
                    if (c.Length > 3) go.SendMessage(c[2], ParseArg(string.Join(" ", c, 3, c.Length - 3)), SendMessageOptions.RequireReceiver);
                    else go.SendMessage(c[2], SendMessageOptions.RequireReceiver);
                    break;
                }
                case "call": CallStatic(c[1], c.Length > 2 ? string.Join(" ", c, 2, c.Length - 2) : null); break;
                case "until":
                    if (c.Length < 4) throw new ArgumentException("until KEY OP VALUE [TIMEOUT]");
                    m_Until = c;
                    m_UntilDeadline = Time.time + (c.Length > 4 ? F(c[4]) : 5f);
                    break;
                case "probe": VerifyProbe.DumpAll(); break;
                case "mark": VerifyProbe.Mark(c.Length > 1 ? c[1] : "mark"); break;
                case "shot":
                {
                    // ScreenCapture needs a Game view: in batchmode (PlayMode tests) render the camera instead.
                    if (Application.isBatchMode) { RenderCamera(c[1], 0, 0); break; }
                    string dir = System.IO.Path.GetDirectoryName(c[1]);
                    if (!string.IsNullOrEmpty(dir)) System.IO.Directory.CreateDirectory(dir);
                    ScreenCapture.CaptureScreenshot(c[1], c.Length > 2 ? int.Parse(c[2], CultureInfo.InvariantCulture) : 1);
                    VerifyProbe.Log("shot", c[1]);
                    break;
                }
                case "render":
                    RenderCamera(c[1], c.Length > 3 ? int.Parse(c[2], CultureInfo.InvariantCulture) : 0,
                        c.Length > 3 ? int.Parse(c[3], CultureInfo.InvariantCulture) : 0);
                    break;
                case "timescale": Time.timeScale = F(c[1]); break;
                case "fps": Time.captureFramerate = int.Parse(c[1], CultureInfo.InvariantCulture); break;
                case "end": m_Pc = m_Cmds.Count; break;
                default: throw new ArgumentException("unknown command '" + c[0] + "'");
            }
        }

        /// <summary>Renders the main camera into a PNG (synchronous; no Screen Space-Overlay UI). Works in batchmode
        /// with graphics; under -nographics it logs shot.skipped instead.</summary>
        static void RenderCamera(string path, int width, int height)
        {
            if (SystemInfo.graphicsDeviceType == UnityEngine.Rendering.GraphicsDeviceType.Null)
            {
                VerifyProbe.Log("shot.skipped", "nographics");
                return;
            }
            var cam = Camera.main != null ? Camera.main : UnityEngine.Object.FindAnyObjectByType<Camera>();
            if (cam == null) throw new InvalidOperationException("render: no camera in the scene");
            if (width <= 0 || height <= 0) { width = 1280; height = 720; }
            var rt = RenderTexture.GetTemporary(width, height, 24, RenderTextureFormat.ARGB32);
            var oldTarget = cam.targetTexture;
            var oldActive = RenderTexture.active;
            var tex = new Texture2D(width, height, TextureFormat.RGB24, false);
            try
            {
                cam.targetTexture = rt;
                cam.Render();
                RenderTexture.active = rt;
                tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                tex.Apply();
                string dir = System.IO.Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir)) System.IO.Directory.CreateDirectory(dir);
                System.IO.File.WriteAllBytes(path, tex.EncodeToPNG());
            }
            finally
            {
                cam.targetTexture = oldTarget;
                RenderTexture.active = oldActive;
                RenderTexture.ReleaseTemporary(rt);
                UnityEngine.Object.Destroy(tex);
            }
            VerifyProbe.Log("shot", path);
        }

        static object ParseArg(string s)
        {
            int i;
            float f;
            if (int.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out i)) return i;
            if (float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out f)) return f;
            if (s == "true") return true;
            if (s == "false") return false;
            return s;
        }

        static void CallStatic(string typeDotMethod, string arg)
        {
            int dot = typeDotMethod.LastIndexOf('.');
            if (dot <= 0) throw new ArgumentException("call wants Full.Type.Method");
            string typeName = typeDotMethod.Substring(0, dot), method = typeDotMethod.Substring(dot + 1);
            Type type = null;
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                type = asm.GetType(typeName, false);
                if (type != null) break;
            }
            if (type == null) throw new ArgumentException("type not found: " + typeName);
            const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
            int argc = arg == null ? 0 : 1;
            foreach (var m in type.GetMethods(flags))
            {
                if (m.Name != method || m.GetParameters().Length != argc) continue;
                object[] args = argc == 0 ? null : new[] { Convert.ChangeType(ParseArg(arg), m.GetParameters()[0].ParameterType, CultureInfo.InvariantCulture) };
                m.Invoke(null, args);
                return;
            }
            throw new ArgumentException("static method not found: " + typeDotMethod + " with " + argc + " arg(s)");
        }

        static bool Check(string[] c)
        {
            string key = c[1], op = c[2], want = c[3];
            float a = VerifyProbe.GetFloat(key), b;
            if (!float.IsNaN(a) && float.TryParse(want, NumberStyles.Float, CultureInfo.InvariantCulture, out b))
            {
                switch (op)
                {
                    case "==": return Mathf.Abs(a - b) < 1e-4f;
                    case "!=": return Mathf.Abs(a - b) >= 1e-4f;
                    case ">": return a > b;
                    case ">=": return a >= b;
                    case "<": return a < b;
                    case "<=": return a <= b;
                }
                return false;
            }
            string s;
            bool has = VerifyProbe.TryGet(key, out s);
            if (op == "==") return has && s == want;
            if (op == "!=") return !has || s != want;
            return false;
        }
    }
}
