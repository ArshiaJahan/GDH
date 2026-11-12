// harness-version: 3
// Harness.Headless: batchmode entry points for headless-ops/scripts/unity.sh (Unity 6000.3).
// (Keep the version line first: GameDevWorkstation reads it to offer upgrades. Edited copies are never overwritten.)
//   -executeMethod Harness.Headless.HarnessCli.Compile      [-forceRecompile]
//   -executeMethod Harness.Headless.HarnessCli.ImportAssets [-importPaths "Assets/a;Assets/b"] [-forceReimport]
//   -executeMethod Harness.Headless.HarnessCli.Build        (-buildProfile Assets/...asset | -buildTarget <name>)
//                                                           -out <path> (or -buildOutput <path>) [-dev] [-cleanBuild]
//                                                           [-scenes "a;b"] [-buildReport file.json]
//   -executeMethod Harness.Headless.HarnessCli.MenuItem     -menu "Path/To/Item"   (then AssetDatabase.SaveAssets)
//   -executeMethod Harness.Headless.HarnessCli.Screenshot   -out <png> [-scene Assets/...unity] [-camera <name>]
//                                                           [-camPos x,y,z] [-camRot x,y,z] [-camFov f] [-width 1920 -height 1080]
//                                                           (needs a graphics device: never pass -nographics; never saves the scene)
// Every entry point ends with a deferred EditorApplication.Exit(code): 0 ok, 1 failed, 2 bad arguments/setup.
// Run them WITHOUT -quit (see Exit). Called from an interactive editor (MCP execute_code) they log but never exit.
// Progress lines are logged as "[HARNESS] ..." so unity.sh can grep them from the -logFile.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Profile;
using UnityEditor.Build.Reporting;
using UnityEditor.Compilation;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Harness.Headless
{
    public static class HarnessCli
    {
        public const string Marker = "[HARNESS] ";

        public static void Say(string message)
        {
            Application.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
            Debug.Log(Marker + message);
        }

        /// <summary>
        /// Ends a batchmode run with an exit code; does nothing in an interactive editor (e.g. when called via MCP).
        /// ⚠ version-sensitive: on 6000.3.21f1 calling EditorApplication.Exit synchronously inside -executeMethod at
        /// startup crashed during domain unload (Burst, "MonoManager is NULL", exit 134). Deferring it by one editor
        /// tick avoids that, so callers must NOT pass -quit (it would quit with 0 before the deferred exit runs).
        /// A domain reload (e.g. after a forced recompile) drops the delayCall, so the code is also kept in SessionState
        /// and ExitAfterReload finishes the job.
        /// </summary>
        public static void Exit(int code)
        {
            Say("EXIT " + code);
            if (!Application.isBatchMode) return;
            SessionState.SetInt(PendingExitKey, code + 1);
            EditorApplication.delayCall += () => EditorApplication.Exit(code);
        }

        const string PendingExitKey = "Harness.Headless.PendingExit";

        [InitializeOnLoadMethod]
        static void ExitAfterReload()
        {
            if (!Application.isBatchMode) return;
            int pending = SessionState.GetInt(PendingExitKey, 0);
            if (pending == 0) return;
            SessionState.EraseInt(PendingExitKey);
            Say("EXIT " + (pending - 1) + " (after domain reload)");
            EditorApplication.delayCall += () => EditorApplication.Exit(pending - 1);
        }

        // ------------------------------------------------------------------ Compile

        static readonly List<string> s_CompileErrors = new List<string>();
        static double s_CompileDeadline;

        /// <summary>
        /// Reports whether all scripts compiled. Batchmode compiles on startup and aborts (exit 1) before this runs
        /// when there are compiler errors, so reaching here usually means success. -forceRecompile requests a clean
        /// recompile and exits from CompilationPipeline.compilationFinished (do not pass -quit with it).
        /// </summary>
        public static void Compile()
        {
            if (EditorUtility.scriptCompilationFailed)
            {
                Say("COMPILE FAIL scripts have compiler errors");
                Exit(1);
                return;
            }
            if (!HarnessArgs.Has("forceRecompile"))
            {
                Say("COMPILE OK assemblies=" + CompilationPipeline.GetAssemblies(AssembliesType.Editor).Length);
                Exit(0);
                return;
            }

            s_CompileErrors.Clear();
            CompilationPipeline.assemblyCompilationFinished += OnAssemblyCompiled;
            CompilationPipeline.compilationFinished += OnCompilationFinished;
            s_CompileDeadline = EditorApplication.timeSinceStartup + HarnessArgs.GetInt("compileTimeout", 600);
            EditorApplication.update += CompileWatchdog;
            Say("COMPILE requesting clean recompile");
            CompilationPipeline.RequestScriptCompilation(RequestScriptCompilationOptions.CleanBuildCache);
        }

        static void OnAssemblyCompiled(string assembly, CompilerMessage[] messages)
        {
            foreach (var m in messages)
                if (m.type == CompilerMessageType.Error) s_CompileErrors.Add(m.message);
        }

        static void OnCompilationFinished(object context)
        {
            CompilationPipeline.assemblyCompilationFinished -= OnAssemblyCompiled;
            CompilationPipeline.compilationFinished -= OnCompilationFinished;
            EditorApplication.update -= CompileWatchdog;
            bool failed = s_CompileErrors.Count > 0 || EditorUtility.scriptCompilationFailed;
            foreach (var e in s_CompileErrors.Distinct().Take(50)) Say("COMPILE ERROR " + e);
            Say(failed ? "COMPILE FAIL errors=" + s_CompileErrors.Count : "COMPILE OK (forced recompile)");
            Exit(failed ? 1 : 0);
        }

        static void CompileWatchdog()
        {
            if (EditorApplication.timeSinceStartup < s_CompileDeadline) return;
            EditorApplication.update -= CompileWatchdog;
            Say("COMPILE FAIL compilationFinished never fired (timeout)");
            Exit(1);
        }

        // ------------------------------------------------------------------ ImportAssets

        /// <summary>
        /// No -importPaths: AssetDatabase.Refresh. With paths (Assets/... or Packages/..., files or folders):
        /// ImportAsset each inside StartAssetEditing/StopAssetEditing, then checks each has a GUID.
        /// Errors and exceptions logged during the import count as failures.
        /// </summary>
        public static void ImportAssets()
        {
            var paths = HarnessArgs.GetList("importPaths").Select(p => p.Replace('\\', '/').TrimEnd('/')).ToList();
            var options = ImportAssetOptions.ForceSynchronousImport;
            if (HarnessArgs.Has("forceReimport")) options |= ImportAssetOptions.ForceUpdate;

            var logged = new List<string>();
            Application.LogCallback onLog = (msg, stack, type) =>
            {
                if (type == LogType.Error || type == LogType.Exception || type == LogType.Assert)
                    if (!msg.StartsWith(Marker)) logged.Add(type + ": " + FirstLine(msg));
            };
            Application.logMessageReceived += onLog;
            var failures = new List<string>();
            try
            {
                if (paths.Count == 0)
                {
                    AssetDatabase.Refresh(options);
                }
                else
                {
                    var valid = new List<string>();
                    foreach (var p in paths)
                    {
                        if (!(p.StartsWith("Assets/") || p == "Assets" || p.StartsWith("Packages/")))
                            failures.Add(p + ": not an Assets/ or Packages/ path");
                        else if (!File.Exists(p) && !Directory.Exists(p))
                            failures.Add(p + ": does not exist on disk");
                        else valid.Add(p);
                    }
                    AssetDatabase.StartAssetEditing();
                    try
                    {
                        foreach (var p in valid)
                            AssetDatabase.ImportAsset(p, Directory.Exists(p) ? options | ImportAssetOptions.ImportRecursive : options);
                    }
                    finally
                    {
                        AssetDatabase.StopAssetEditing();
                    }
                    foreach (var p in valid)
                    {
                        if (string.IsNullOrEmpty(AssetDatabase.AssetPathToGUID(p, AssetPathToGUIDOptions.OnlyExistingAssets)))
                            failures.Add(p + ": no GUID after import");
                        else if (File.Exists(p) && AssetDatabase.LoadMainAssetAtPath(p) == null)
                            failures.Add(p + ": imported but main asset failed to load");
                    }
                }
            }
            catch (Exception e)
            {
                failures.Add("exception: " + FirstLine(e.Message));
            }
            finally
            {
                Application.logMessageReceived -= onLog;
            }

            failures.AddRange(logged);
            foreach (var f in failures.Take(50)) Say("IMPORT FAILURE " + f);
            Say("IMPORT " + (failures.Count == 0 ? "ok" : "fail") + " paths=" + (paths.Count == 0 ? "refresh" : paths.Count.ToString())
                + " failures=" + failures.Count);
            Exit(failures.Count == 0 ? 0 : 1);
        }

        // ------------------------------------------------------------------ MenuItem

        /// <summary>
        /// Runs a menu item by its path (-menu "Tools/Rebuild Atlas") with EditorApplication.ExecuteMenuItem, then saves
        /// modified assets (AssetDatabase.SaveAssets). Exit 1 when the item doesn't exist, is disabled (its validate
        /// function said no) or throws; exit 2 without -menu. Errors logged while it runs are reported but don't fail it
        /// (many menu items log as they go). Items that open a window or a modal dialog can't work in batchmode.
        /// </summary>
        public static void MenuItem()
        {
            string item = HarnessArgs.Get("menu");
            if (string.IsNullOrEmpty(item)) { Say("MENU FAIL missing -menu \"Path/To/Item\""); Exit(2); return; }

            var logged = new List<string>();
            Application.LogCallback onLog = (msg, stack, type) =>
            {
                if (type == LogType.Error || type == LogType.Exception || type == LogType.Assert)
                    if (!msg.StartsWith(Marker)) logged.Add(type + ": " + FirstLine(msg));
            };
            Application.logMessageReceived += onLog;
            bool ran;
            try
            {
                Say("MENU run " + item);
                ran = EditorApplication.ExecuteMenuItem(item);
            }
            catch (Exception e)
            {
                Application.logMessageReceived -= onLog;
                Say("MENU FAIL exception " + FirstLine(e.Message));
                Exit(1);
                return;
            }
            Application.logMessageReceived -= onLog;
            foreach (var l in logged.Distinct().Take(30)) Say("MENU LOGGED " + l);
            if (!ran)
            {
                Say("MENU FAIL not found or disabled: " + item);
                Exit(1);
                return;
            }
            AssetDatabase.SaveAssets();
            Say("MENU OK " + item + " logged_errors=" + logged.Count);
            Exit(0);
        }

        // ------------------------------------------------------------------ Screenshot

        const string ShotCameraName = "HarnessScreenshotCamera";

        /// <summary>
        /// Renders one PNG of a scene with the Editor closed (the gallery's batch route; unity.sh screenshot).
        /// -out &lt;png&gt; (required), -scene Assets/...unity (default: the first enabled build scene), -camera &lt;name&gt; (an
        /// existing camera, by name or hierarchy path), -camPos x,y,z and -camRot x,y,z (euler degrees, world space),
        /// -camFov f, -width/-height (default 1920x1080), -timeOfDay (free text, ignored). The scene is opened with
        /// EditorSceneManager.OpenScene(Single) and NEVER saved. Without -camera, or with -camPos/-camRot, a temporary
        /// camera (HideAndDontSave, copied from the named camera or Camera.main when there is one) is created and destroyed
        /// again. Rendering needs a graphics device: run WITHOUT -nographics. Batch mode only (opening a scene in an
        /// interactive editor would drop its unsaved changes). Exit 0 ok, 1 failed, 2 bad arguments.
        /// ⚠ version-sensitive: uses RenderPipeline.SubmitRenderRequest(StandardRequest) under a scriptable render pipeline
        /// (Unity 2023.1+), Camera.Render() otherwise. Not run against a real Unity here (checked statically).
        /// </summary>
        public static void Screenshot()
        {
            if (!Application.isBatchMode)
            {
                Say("SHOT FAIL Screenshot() runs only in batch mode (it opens a scene without saving the current one)");
                return;
            }
            string outArg = HarnessArgs.Get("out");
            if (string.IsNullOrEmpty(outArg) || !outArg.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
            {
                Say("SHOT FAIL missing -out <path>.png");
                Exit(2);
                return;
            }
            int width = Mathf.Clamp(HarnessArgs.GetInt("width", 1920), 16, 8192);
            int height = Mathf.Clamp(HarnessArgs.GetInt("height", 1080), 16, 8192);
            string timeOfDay = HarnessArgs.Get("timeOfDay");
            if (!string.IsNullOrEmpty(timeOfDay)) Say("SHOT note -timeOfDay is ignored: " + timeOfDay);

            string scenePath = HarnessArgs.Get("scene");
            if (string.IsNullOrEmpty(scenePath))
                scenePath = EditorBuildSettings.scenes.Where(s => s.enabled && !string.IsNullOrEmpty(s.path)).Select(s => s.path).FirstOrDefault();
            if (string.IsNullOrEmpty(scenePath))
            {
                Say("SHOT FAIL no scene: pass -scene Assets/...unity or enable a scene in the build scene list");
                Exit(2);
                return;
            }
            scenePath = scenePath.Replace('\\', '/');
            if (!scenePath.StartsWith("Assets/") || !scenePath.EndsWith(".unity", StringComparison.OrdinalIgnoreCase) || !File.Exists(scenePath))
            {
                Say("SHOT FAIL scene not found (an Assets/...unity path): " + scenePath);
                Exit(2);
                return;
            }

            Vector3 pos, rot;
            bool hasPos = TryParseVector(HarnessArgs.Get("camPos"), out pos);
            bool hasRot = TryParseVector(HarnessArgs.Get("camRot"), out rot);
            if ((HarnessArgs.Get("camPos") != null && !hasPos) || (HarnessArgs.Get("camRot") != null && !hasRot))
            {
                Say("SHOT FAIL -camPos / -camRot must be x,y,z (numbers)");
                Exit(2);
                return;
            }
            float fov = 0f;
            string fovArg = HarnessArgs.Get("camFov");
            if (fovArg != null && !(float.TryParse(fovArg, System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out fov) && fov > 0.1f && fov < 179f))
            {
                Say("SHOT FAIL -camFov must be a number between 0.1 and 179");
                Exit(2);
                return;
            }

            GameObject temp = null;
            Camera cam = null;
            RenderTexture rt = null;
            RenderTexture prevTarget = null;
            RenderTexture prevActive = RenderTexture.active;
            Texture2D tex = null;
            int code = 1;
            try
            {
                var scene = EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single);
                string camName = HarnessArgs.Get("camera");
                Camera named = null;
                if (!string.IsNullOrEmpty(camName))
                {
                    named = FindCamera(scene, camName);
                    if (named == null)
                    {
                        Say("SHOT FAIL camera not found in " + scenePath + ": " + camName);
                        return;
                    }
                }
                string what;
                if (named != null && !hasPos && !hasRot)
                {
                    cam = named;  // render the scene's own camera as it is (the scene is never saved)
                    what = "camera=" + named.name;
                }
                else
                {
                    Camera source = named != null ? named : (Camera.main != null ? Camera.main : FindCamera(scene, null));
                    temp = EditorUtility.CreateGameObjectWithHideFlags(ShotCameraName, HideFlags.HideAndDontSave, typeof(Camera));
                    cam = temp.GetComponent<Camera>();
                    if (source != null)
                    {
                        cam.CopyFrom(source);
                        temp.transform.SetPositionAndRotation(source.transform.position, source.transform.rotation);
                        CopyPipelineCameraData(source, temp);
                    }
                    if (hasPos) temp.transform.position = pos;
                    if (hasRot) temp.transform.rotation = Quaternion.Euler(rot);
                    what = "temp camera" + (source != null ? " (from " + source.name + ")" : "");
                }
                if (fov > 0f) cam.fieldOfView = fov;

                rt = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
                rt.antiAliasing = 1;
                rt.Create();
                prevTarget = cam.targetTexture;
                RenderCamera(cam, rt);
                RenderTexture.active = rt;
                tex = new Texture2D(width, height, TextureFormat.RGB24, false);
                tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                tex.Apply();
                byte[] png = tex.EncodeToPNG();
                string full = Path.GetFullPath(outArg);
                Directory.CreateDirectory(Path.GetDirectoryName(full));
                File.WriteAllBytes(full, png);
                var t = cam.transform;
                Say("SHOT OK " + full + " " + width + "x" + height + " scene=" + scenePath + " " + what
                    + " pos=" + Vec(t.position) + " rot=" + Vec(t.eulerAngles) + " fov=" + cam.fieldOfView.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture)
                    + " bytes=" + png.Length);
                code = 0;
            }
            catch (Exception e)
            {
                Say("SHOT FAIL exception " + FirstLine(e.Message));
                code = 1;
            }
            finally
            {
                RenderTexture.active = prevActive;
                if (cam != null && temp == null) cam.targetTexture = prevTarget;
                if (tex != null) UnityEngine.Object.DestroyImmediate(tex);
                if (rt != null) { rt.Release(); UnityEngine.Object.DestroyImmediate(rt); }
                if (temp != null) UnityEngine.Object.DestroyImmediate(temp);
                Exit(code);
            }
        }

        /// <summary>Renders cam into rt: a render request under a scriptable render pipeline, Camera.Render() otherwise.</summary>
        static void RenderCamera(Camera cam, RenderTexture rt)
        {
            if (UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline != null)
            {
                var request = new UnityEngine.Rendering.RenderPipeline.StandardRequest { destination = rt };
                if (UnityEngine.Rendering.RenderPipeline.SupportsRenderRequest(cam, request))
                {
                    UnityEngine.Rendering.RenderPipeline.SubmitRenderRequest(cam, request);
                    return;
                }
            }
            cam.targetTexture = rt;
            cam.Render();
        }

        /// <summary>URP / HDRP keep post-processing and renderer settings on a separate *AdditionalCameraData component.</summary>
        static void CopyPipelineCameraData(Camera source, GameObject target)
        {
            try
            {
                foreach (var c in source.GetComponents<Component>())
                {
                    if (c == null || !c.GetType().Name.EndsWith("AdditionalCameraData", StringComparison.Ordinal)) continue;
                    if (UnityEditorInternal.ComponentUtility.CopyComponent(c))
                        UnityEditorInternal.ComponentUtility.PasteComponentAsNew(target);
                }
            }
            catch (Exception e)
            {
                Say("SHOT note could not copy the render pipeline camera data: " + FirstLine(e.Message));
            }
        }

        /// <summary>A camera of the scene by name or hierarchy path (case-insensitive); null name = the first enabled one.</summary>
        static Camera FindCamera(UnityEngine.SceneManagement.Scene scene, string name)
        {
            Camera first = null;
            foreach (var root in scene.GetRootGameObjects())
            {
                foreach (var c in root.GetComponentsInChildren<Camera>(true))
                {
                    if (name == null)
                    {
                        if (c.enabled && c.gameObject.activeInHierarchy) return c;
                        if (first == null) first = c;
                        continue;
                    }
                    if (string.Equals(c.name, name, StringComparison.OrdinalIgnoreCase)
                        || string.Equals(HierarchyPath(c.transform), name.Trim('/'), StringComparison.OrdinalIgnoreCase))
                        return c;
                }
            }
            return first;
        }

        static string HierarchyPath(Transform t)
        {
            string p = t.name;
            for (var x = t.parent; x != null; x = x.parent) p = x.name + "/" + p;
            return p;
        }

        static bool TryParseVector(string s, out Vector3 v)
        {
            v = Vector3.zero;
            if (string.IsNullOrEmpty(s)) return false;
            var parts = s.Split(',');
            if (parts.Length != 3) return false;
            var f = new float[3];
            for (int i = 0; i < 3; i++)
                if (!float.TryParse(parts[i].Trim(), System.Globalization.NumberStyles.Float,
                        System.Globalization.CultureInfo.InvariantCulture, out f[i])) return false;
            v = new Vector3(f[0], f[1], f[2]);
            return true;
        }

        static string Vec(Vector3 v)
        {
            var ci = System.Globalization.CultureInfo.InvariantCulture;
            return v.x.ToString("0.###", ci) + "," + v.y.ToString("0.###", ci) + "," + v.z.ToString("0.###", ci);
        }

        // ------------------------------------------------------------------ Build

        [Serializable]
        public class BuildSummaryJson
        {
            public string result;
            public string platform;
            public string outputPath;
            public string profile;
            public bool development;
            public long totalSize;
            public int totalErrors;
            public int totalWarnings;
            public double totalSeconds;
            public string startedUtc;
            public string endedUtc;
            public string productName;
            public string version;
            public string unityVersion;
            public string[] scenes;
            public string[] errorMessages;
        }

        /// <summary>
        /// Builds a player. ⚠ version-sensitive: with -buildProfile uses the Unity 6 overload
        /// BuildPipeline.BuildPlayer(BuildPlayerWithProfileOptions); otherwise BuildPlayerOptions with the scenes from
        /// -scenes or EditorBuildSettings. The active target cannot be switched in batchmode, so start Unity with
        /// -buildTarget X (or -activeBuildProfile P); a mismatch fails. Writes build-report.json next to the output.
        /// </summary>
        public static void Build()
        {
            string profilePath = HarnessArgs.Get("buildProfile");
            string targetArg = HarnessArgs.Get("buildTarget");
            // -buildOutput is the Unity CLI's spelling (unity build --execute-method); -out is unity.sh's.
            string outArg = HarnessArgs.Get("out", HarnessArgs.Get("buildOutput"));
            if (string.IsNullOrEmpty(outArg)) { Say("BUILD FAIL missing -out <path> (or -buildOutput <path>)"); Exit(2); return; }

            BuildProfile profile = null;
            BuildTarget target = EditorUserBuildSettings.activeBuildTarget;
            if (!string.IsNullOrEmpty(profilePath))
            {
                profile = AssetDatabase.LoadAssetAtPath<BuildProfile>(profilePath);
                if (profile == null) { Say("BUILD FAIL build profile not found or not a BuildProfile: " + profilePath); Exit(2); return; }
            }
            else if (!string.IsNullOrEmpty(targetArg))
            {
                BuildTarget requested;
                if (!TryParseTarget(targetArg, out requested)) { Say("BUILD FAIL unknown -buildTarget " + targetArg); Exit(2); return; }
                if (requested != target)
                {
                    Say("BUILD FAIL active target is " + target + " but " + requested + " was requested; start Unity with -buildTarget " + targetArg);
                    Exit(2);
                    return;
                }
            }
            else { Say("BUILD FAIL give -buildProfile <Assets/...asset> or -buildTarget <name>"); Exit(2); return; }

            var opts = BuildOptions.None;
            bool dev = HarnessArgs.Has("dev");
            if (dev) opts |= BuildOptions.Development;
            if (HarnessArgs.Has("cleanBuild")) opts |= BuildOptions.CleanBuildCache;
            if (HarnessArgs.Has("strict")) opts |= BuildOptions.StrictMode;
            if (HarnessArgs.Has("detailedReport")) opts |= BuildOptions.DetailedBuildReport;

            string location = ResolveLocation(Path.GetFullPath(outArg), target);
            string reportPath = HarnessArgs.Get("buildReport");
            if (string.IsNullOrEmpty(reportPath))
                reportPath = Path.Combine(IsFolderTarget(target) ? location : Path.GetDirectoryName(location), "build-report.json");
            Directory.CreateDirectory(Path.GetDirectoryName(location));

            string[] scenes;
            BuildReport report;
            Say("BUILD start target=" + target + " profile=" + (profilePath ?? "-") + " out=" + location);
            try
            {
                if (profile != null)
                {
                    if (HarnessArgs.Get("scenes") != null) Say("BUILD note -scenes is ignored with a build profile");
                    scenes = profile.GetScenesForBuild().Where(s => s.enabled).Select(s => s.path).ToArray();
                    report = BuildPipeline.BuildPlayer(new BuildPlayerWithProfileOptions
                    {
                        buildProfile = profile,
                        locationPathName = location,
                        options = opts
                    });
                }
                else
                {
                    var list = HarnessArgs.GetList("scenes");
                    scenes = list.Count > 0 ? list.ToArray()
                        : EditorBuildSettings.scenes.Where(s => s.enabled && !string.IsNullOrEmpty(s.path)).Select(s => s.path).ToArray();
                    if (scenes.Length == 0)
                    {
                        Say("BUILD FAIL no scenes: add scenes to Build Profiles > Scene List (EditorBuildSettings) or pass -scenes");
                        Exit(2);
                        return;
                    }
                    report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
                    {
                        scenes = scenes,
                        locationPathName = location,
                        target = target,
                        targetGroup = BuildPipeline.GetBuildTargetGroup(target),
                        options = opts
                    });
                }
            }
            catch (Exception e)
            {
                Say("BUILD FAIL exception " + FirstLine(e.Message));
                Exit(1);
                return;
            }

            var s = report.summary;
            var errors = new List<string>();
            foreach (var step in report.steps)
                foreach (var m in step.messages)
                    if (m.type == LogType.Error || m.type == LogType.Exception) errors.Add(FirstLine(m.content));

            var json = new BuildSummaryJson
            {
                result = s.result.ToString(),
                platform = s.platform.ToString(),
                outputPath = s.outputPath,
                profile = profilePath ?? "",
                development = dev,
                totalSize = (long)s.totalSize,
                totalErrors = s.totalErrors,
                totalWarnings = s.totalWarnings,
                totalSeconds = Math.Round(s.totalTime.TotalSeconds, 1),
                // BuildSummary times are already UTC (observed on 6000.3.21f1); do not call ToUniversalTime again.
                startedUtc = DateTime.SpecifyKind(s.buildStartedAt, DateTimeKind.Utc).ToString("o"),
                endedUtc = DateTime.SpecifyKind(s.buildEndedAt, DateTimeKind.Utc).ToString("o"),
                productName = PlayerSettings.productName,
                version = PlayerSettings.bundleVersion,
                unityVersion = Application.unityVersion,
                scenes = scenes,
                errorMessages = errors.Distinct().Take(50).ToArray()
            };
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(reportPath));
                File.WriteAllText(reportPath, JsonUtility.ToJson(json, true));
                Say("REPORT " + reportPath);
            }
            catch (Exception e)
            {
                Say("BUILD could not write report: " + e.Message);
            }
            Say("BUILD " + s.result + " size=" + s.totalSize + " errors=" + s.totalErrors + " time=" + json.totalSeconds + "s");
            Exit(s.result == BuildResult.Succeeded ? 0 : 1);
        }

        /// <summary>Accepts CLI spellings (osxuniversal, win64, webgl, ...) and BuildTarget names (StandaloneOSX, ...).</summary>
        public static bool TryParseTarget(string name, out BuildTarget target)
        {
            switch ((name ?? "").Trim().ToLowerInvariant())
            {
                case "osxuniversal": case "osx": case "macos": case "mac": case "standaloneosx": target = BuildTarget.StandaloneOSX; return true;
                case "win64": case "windows": case "windows64": case "standalonewindows64": target = BuildTarget.StandaloneWindows64; return true;
                case "win": case "standalonewindows": target = BuildTarget.StandaloneWindows; return true;
                case "linux64": case "linux": case "standalonelinux64": target = BuildTarget.StandaloneLinux64; return true;
                case "webgl": case "web": target = BuildTarget.WebGL; return true;
                case "android": target = BuildTarget.Android; return true;
                case "ios": target = BuildTarget.iOS; return true;
            }
            return Enum.TryParse(name, true, out target);
        }

        static bool IsFolderTarget(BuildTarget t) { return t == BuildTarget.WebGL || t == BuildTarget.iOS; }

        static string PlayerExtension(BuildTarget t)
        {
            switch (t)
            {
                case BuildTarget.StandaloneOSX: return ".app";
                case BuildTarget.StandaloneWindows:
                case BuildTarget.StandaloneWindows64: return ".exe";
                case BuildTarget.StandaloneLinux64: return ".x86_64";
                case BuildTarget.Android: return EditorUserBuildSettings.buildAppBundle ? ".aab" : ".apk";
                default: return "";
            }
        }

        /// <summary>-out may be the player path (Game.app, Game.exe, ...) or a folder; folders get &lt;productName&gt;&lt;ext&gt;.</summary>
        static string ResolveLocation(string outPath, BuildTarget target)
        {
            if (IsFolderTarget(target)) return outPath;
            string ext = PlayerExtension(target);
            if (ext.Length > 0 && outPath.EndsWith(ext, StringComparison.OrdinalIgnoreCase)) return outPath;
            string name = string.Concat(PlayerSettings.productName.Split(Path.GetInvalidFileNameChars())).Trim();
            if (name.Length == 0) name = "Player";
            return Path.Combine(outPath, name + ext);
        }

        static string FirstLine(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            int i = s.IndexOfAny(new[] { '\n', '\r' });
            return i < 0 ? s : s.Substring(0, i);
        }
    }
}
