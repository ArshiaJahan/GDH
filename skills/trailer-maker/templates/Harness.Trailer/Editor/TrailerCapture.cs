// Harness.Trailer: scripted gameplay capture with the Unity Recorder (Editor + Play Mode only).
//
// Entry points (all static, safe to call from MCP execute_code):
//   TrailerCapture.Start("Trailer/<slug>/shots.json", "s01,s02") -> "started <n> shots" | "error: ..."
//   TrailerCapture.Status()   -> "idle" | "running s03 take 2/3" | "done ok=12 failed=0 report=<path>"
//   TrailerCapture.Cancel()   -> stops a running job cleanly
//   TrailerCapture.RunFromCli -> Unity -projectPath . -executeMethod Harness.Trailer.TrailerCapture.RunFromCli
//                                  -trailerShots <path> [-trailerOnly s01,s02]     (GUI editor, NOT -batchmode)
//
// Design: ONE Play Mode session for the whole job; the scene is reloaded for every take (LoadSceneInPlayMode, so the
// scene does not have to be in Build Settings). Entering Play Mode reloads the domain, so the state machine lives in
// JobState (Temp/HarnessTrailer/job.json + SessionState) and is resumed by the static constructor.
//
// Game View is the capture source because the URP 2D renderer has no capture pass for the Recorder's Targeted Camera
// input. Output must be outside Assets/ (videos would be imported by the AssetDatabase). The Recorder does not run in
// -batchmode ("graphics pipeline is not initialized"), hence RunFromCli needs a logged-in display.
// Everything that touches Unity.Recorder is under #if HARNESS_RECORDER so the assembly compiles without the package.
//
// Take status: "failed" if the recording did not start/finish, the output file is missing, the setup method threw,
// or any Error/Exception/Assert was logged during the take (errors count is reported either way).

using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEditor.SceneManagement;
#if HARNESS_RECORDER
using UnityEditor.Recorder;
using UnityEditor.Recorder.Encoder;
using UnityEditor.Recorder.Input;
#endif
using UnityEngine;
using UnityEngine.Audio;
using UnityEngine.SceneManagement;

namespace Harness.Trailer
{
    [InitializeOnLoad]
    public static class TrailerCapture
    {
        const BindingFlags AnyStatic = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;

        static JobState S;                       // null = no job known
        static TrailerShotList s_List;
        static List<TrailerShot> s_Shots;
        static AsyncOperation s_Load;
        static readonly List<MixerBackup> s_Mixers = new List<MixerBackup>();

        struct MixerBackup { public AudioMixer mixer; public string param; public float value; }

        static TrailerCapture()
        {
            EditorApplication.playModeStateChanged -= OnPlayMode;
            EditorApplication.playModeStateChanged += OnPlayMode;
            EditorApplication.update -= Tick;
            EditorApplication.update += Tick;
            Application.logMessageReceived -= OnLog;
            Application.logMessageReceived += OnLog;
            try { S = TrailerJob.LoadState(); } catch (Exception) { S = null; } // resume after the domain reload
        }

        // ---- public API ----------------------------------------------------------------------------------------

        public static string Start(string shotsJsonPath, string onlyShots = "")
        {
            return StartInternal(shotsJsonPath, onlyShots, false);
        }

        static string StartInternal(string shotsPath, string only, bool cli)
        {
#if !HARNESS_RECORDER
            return "error: install com.unity.recorder (5.x) first";
#else
            if (EditorApplication.isPlayingOrWillChangePlaymode) return "error: editor is in (or entering) Play Mode; stop it first";
            if (EditorApplication.isCompiling || EditorApplication.isUpdating) return "error: editor is compiling or importing; retry in a moment";
            if (S != null && S.Active) return "error: a trailer job is already running (" + Status() + ")";
            if (!TrailerJob.TryLoad(shotsPath, out TrailerShotList list, out string err)) return "error: " + err;
            var shots = TrailerJob.Filter(list, only, out err);
            if (err != null) return "error: " + err;
            if (shots.Count == 0) return "error: no shots selected";

            s_List = list;
            s_Shots = shots;
            S = new JobState
            {
                shots_path = shotsPath, only = only ?? "", cli = cli,
                report_path = TrailerJob.ReportPath(list),
                phase = TrailerPhase.EnterPlay, phase_started = EditorApplication.timeSinceStartup,
            };
            TrailerJob.CliStartedThisSession = cli;
            TrailerJob.SaveState(S);
            EditorApplication.EnterPlaymode();
            return "started " + shots.Count + " shots";
#endif
        }

        public static string Status()
        {
            if (S == null) S = TrailerJob.LoadState();
            if (S == null || string.IsNullOrEmpty(S.phase)) return "idle";
            if (S.phase == TrailerPhase.Done)
                return "done ok=" + S.ok + " failed=" + S.failed + " report=" + S.report_path
                    + (string.IsNullOrEmpty(S.message) ? "" : " (" + S.message + ")");
            if (!EnsureList(out _) || S.shot_index >= s_Shots.Count) return "running (finishing)";
            var shot = s_Shots[S.shot_index];
            return "running " + shot.id + " take " + (S.take_index + 1) + "/" + shot.takes;
        }

        public static string Cancel()
        {
            if (S == null || !S.Active) return "idle (nothing to cancel)";
            Finish("cancelled", true);
            return "cancelled";
        }

        /// <summary>-executeMethod Harness.Trailer.TrailerCapture.RunFromCli -trailerShots path [-trailerOnly s01,s02]</summary>
        public static void RunFromCli()
        {
            if (Application.isBatchMode)
            {
                Debug.LogError("[TRAILER] the Unity Recorder does not run in -batchmode; launch the GUI editor without -batchmode");
                EditorApplication.Exit(2);
                return;
            }
            string shots = CliArg("-trailerShots");
            if (string.IsNullOrEmpty(shots))
            {
                Debug.LogError("[TRAILER] missing -trailerShots <path>");
                EditorApplication.Exit(2);
                return;
            }
            string r = StartInternal(shots, CliArg("-trailerOnly"), true);
            if (r.StartsWith("started", StringComparison.Ordinal)) Debug.Log("[TRAILER] " + r);
            else { Debug.LogError("[TRAILER] " + r); EditorApplication.Exit(2); }
        }

        [MenuItem("Tools/Harness/Trailer/Status")]
        static void MenuStatus() { Debug.Log("[TRAILER] " + Status()); }

        static string CliArg(string name)
        {
            var a = Environment.GetCommandLineArgs();
            for (int i = 0; i < a.Length - 1; i++) if (a[i] == name) return a[i + 1];
            return "";
        }

        // ---- plumbing ------------------------------------------------------------------------------------------

        static bool EnsureList(out string err)
        {
            err = null;
            if (S == null) { err = "no job"; return false; }
            if (s_Shots != null) return true;
            if (!TrailerJob.TryLoad(S.shots_path, out s_List, out err)) return false;
            s_Shots = TrailerJob.Filter(s_List, S.only, out err);
            return err == null;
        }

        static bool InTake()
        {
            if (S == null) return false;
            switch (S.phase)
            {
                case TrailerPhase.Loading: case TrailerPhase.Setup: case TrailerPhase.Warmup:
                case TrailerPhase.Recording: case TrailerPhase.Finalize: return true;
                default: return false;
            }
        }

        static void SetPhase(string phase)
        {
            S.phase = phase;
            S.phase_started = EditorApplication.timeSinceStartup;
            TrailerJob.SaveState(S);
        }

        static double Elapsed() { return EditorApplication.timeSinceStartup - S.phase_started; }

        static void OnLog(string condition, string stackTrace, LogType type)
        {
            if (!InTake()) return;
            if (type != LogType.Error && type != LogType.Exception && type != LogType.Assert) return;
            if (condition != null && condition.StartsWith("[TRAILER]", StringComparison.Ordinal)) return;
            S.errors++;
        }

        static void OnPlayMode(PlayModeStateChange c)
        {
            if (S == null || !S.Active) return;
            if (c == PlayModeStateChange.EnteredPlayMode && S.phase == TrailerPhase.EnterPlay)
                SetPhase(TrailerPhase.BeginTake);
            else if (c == PlayModeStateChange.EnteredEditMode && S.phase != TrailerPhase.EnterPlay)
                Finish("play mode ended unexpectedly", true);
        }

        // ---- state machine -------------------------------------------------------------------------------------

        static void Tick()
        {
            if (S == null) return;
            try { TickInner(); }
            catch (Exception e) { Debug.LogWarning("[TRAILER] state machine error: " + e); if (S.Active) Finish("internal error: " + e.Message, true); }
        }

        static void TickInner()
        {
            if (S.phase == TrailerPhase.Done)
            {
                // CLI mode: leave the editor once Play Mode is fully over (survives the domain reload via job state).
                // Only when RunFromCli started the job in THIS editor session: a stale job.json (cli=true) from an
                // earlier run must not close an editor the user opened normally.
                if (S.cli && TrailerJob.CliStartedThisSession && !S.exit_requested
                    && !EditorApplication.isPlayingOrWillChangePlaymode && !EditorApplication.isCompiling)
                {
                    S.exit_requested = true;
                    TrailerJob.SaveState(S);
                    EditorApplication.Exit(S.failed == 0 && S.ok > 0 ? 0 : 1);
                }
                return;
            }
            if (!S.Active) return;

            if (S.phase == TrailerPhase.EnterPlay)
            {
                if (EditorApplication.isPlaying && Time.frameCount > 2) SetPhase(TrailerPhase.BeginTake);
                else if (Elapsed() > 90) Finish("could not enter Play Mode", false);
                return;
            }
            if (!EditorApplication.isPlaying) { Finish("play mode ended unexpectedly", true); return; }

            if (!EnsureList(out string err)) { Finish("error: " + err, false); return; }
            if (S.phase != TrailerPhase.BeginTake && S.shot_index >= s_Shots.Count) { Finish(null, false); return; }
            TrailerShot shot = S.shot_index < s_Shots.Count ? s_Shots[S.shot_index] : null;

            switch (S.phase)
            {
                case TrailerPhase.BeginTake:
                    if (shot == null) { Finish(null, false); return; }
                    S.errors = 0;
                    S.rec_frames = 0;
                    Time.timeScale = 1f;
                    try { s_Load = EditorSceneManager.LoadSceneInPlayMode(shot.scene, new LoadSceneParameters(LoadSceneMode.Single)); }
                    catch (Exception e) { CompleteTake(false, "scene load failed: " + e.Message); return; }
                    SetPhase(TrailerPhase.Loading);
                    break;

                case TrailerPhase.Loading:
                    if (s_Load != null && !s_Load.isDone) { if (Elapsed() > 120) CompleteTake(false, "scene load timed out"); return; }
                    S.load_frame = Time.frameCount;
                    SetPhase(TrailerPhase.Setup);
                    break;

                case TrailerPhase.Setup:
                    if (Time.frameCount - S.load_frame < 2) return; // let Awake/Start run
                    string setupErr = ApplyShot(shot);
                    if (setupErr != null) { CompleteTake(false, setupErr); return; }
                    SetPhase(TrailerPhase.Warmup);
                    break;

                case TrailerPhase.Warmup:
                    if (Elapsed() < shot.warmup_s) return; // real (unscaled) time
                    string recErr = BeginRecording(shot, S.take_index + 1);
                    if (recErr != null) { CompleteTake(false, recErr); return; }
                    S.rec_start_frame = Time.frameCount;
                    S.rec_target = Mathf.Max(1, Mathf.RoundToInt(shot.duration_s * s_List.fps));
                    SetPhase(TrailerPhase.Recording);
                    break;

                case TrailerPhase.Recording:
                    // Constant-rate playback advances game time by 1/fps per recorded frame, so frames = frameCount delta.
                    S.rec_frames = Time.frameCount - S.rec_start_frame;
                    if (!RecorderRunning() && S.rec_frames > 3) { CompleteTake(false, "recorder stopped by itself"); return; }
                    if (S.rec_frames >= S.rec_target) { StopRecorder(); SetPhase(TrailerPhase.Finalize); }
                    break;

                case TrailerPhase.Finalize:
                    if (Elapsed() < 1.0 || (RecorderRunning() && Elapsed() < 10)) return; // let the encoder flush
                    CompleteTake(true, "");
                    break;
            }
        }

        /// <summary>Setup method, time scale, camera, hide list, mixer mute, scripted input. Returns an error or null.</summary>
        static string ApplyShot(TrailerShot shot)
        {
            if (!string.IsNullOrEmpty(shot.setup))
            {
                string e = InvokeSetup(shot.setup, shot.setup_arg);
                if (e != null) return e;
            }
            Time.timeScale = shot.time_scale;
            if (shot.camera.ortho_size > 0f && Camera.main != null && Camera.main.orthographic)
                Camera.main.orthographicSize = shot.camera.ortho_size;
            if (!string.IsNullOrEmpty(shot.camera.cinemachine))
                Debug.Log("[TRAILER] camera.cinemachine='" + shot.camera.cinemachine + "' is advisory (no compile-time Cinemachine reference); activate it from the setup method");
            foreach (string name in shot.hide.objects)
            {
                var go = GameObject.Find(name);
                if (go != null) go.SetActive(false); else Debug.LogWarning("[TRAILER] hide: object not found: " + name);
            }
            if (shot.hide.cursor) Cursor.visible = false;
            if (s_List.audio.mute_mixer_params.Length > 0) MuteMixerParams(s_List.audio.mute_mixer_params);
            if (!string.IsNullOrWhiteSpace(shot.input)) RunScriptedInput(shot.input);
            return null;
        }

        static string InvokeSetup(string spec, string arg)
        {
            int dot = spec.LastIndexOf('.');
            if (dot <= 0) return "setup must be 'Namespace.Type.Method': " + spec;
            Type t = TrailerJob.FindType(spec.Substring(0, dot));
            if (t == null) return "setup type not found: " + spec.Substring(0, dot);
            string method = spec.Substring(dot + 1);
            object[] args = { arg ?? "" };
            MethodInfo m = t.GetMethod(method, AnyStatic, null, new[] { typeof(string) }, null);
            if (m == null) { m = t.GetMethod(method, AnyStatic, null, Type.EmptyTypes, null); args = new object[0]; }
            if (m == null) return "setup method not found (static, taking string): " + spec;
            try { m.Invoke(null, args); }
            catch (TargetInvocationException e) { return "setup threw: " + (e.InnerException != null ? e.InnerException.Message : e.Message); }
            catch (Exception e) { return "setup failed: " + e.Message; }
            return null;
        }

        static void RunScriptedInput(string script)
        {
            // Reflection only: play-verify (Harness.Verify) is optional.
            Type t = TrailerJob.FindType("Harness.Verify.ScriptedInput");
            MethodInfo run = t != null ? t.GetMethod("Run", BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(string) }, null) : null;
            if (run == null) { Debug.LogWarning("[TRAILER] input ignored: Harness.Verify.ScriptedInput not installed"); return; }
            try { run.Invoke(null, new object[] { script }); }
            catch (Exception e) { Debug.LogWarning("[TRAILER] ScriptedInput.Run failed: " + (e.InnerException != null ? e.InnerException.Message : e.Message)); }
        }

        static void MuteMixerParams(string[] names)
        {
            foreach (var mixer in Resources.FindObjectsOfTypeAll<AudioMixer>())
                foreach (string p in names)
                    if (mixer.GetFloat(p, out float v))
                    {
                        s_Mixers.Add(new MixerBackup { mixer = mixer, param = p, value = v });
                        mixer.SetFloat(p, -80f);
                    }
        }

        static void RestoreMixers()
        {
            foreach (var b in s_Mixers) if (b.mixer != null) b.mixer.SetFloat(b.param, b.value);
            s_Mixers.Clear();
        }

        static string OutputBase(TrailerShot shot, int take)
        {
            return Path.Combine(Path.Combine(TrailerJob.Resolve(s_List.output_dir), shot.id), "take-" + take.ToString("00"));
        }

        static string FindOutputFile(TrailerShot shot, int take)
        {
            string b = OutputBase(shot, take);
            string dir = Path.GetDirectoryName(b);
            if (!Directory.Exists(dir)) return "";
            string[] hits = Directory.GetFiles(dir, Path.GetFileName(b) + ".*");
            return hits.Length > 0 ? hits[0] : "";
        }

        /// <summary>Stops the recorder, restores globals, records the take result and advances to the next take.</summary>
        static void CompleteTake(bool recorded, string message)
        {
            var shot = s_Shots[S.shot_index];
            int take = S.take_index + 1;
            EndRecording();
            RestoreMixers();
            Time.timeScale = 1f;
            Cursor.visible = true;

            string file = FindOutputFile(shot, take);
            bool ok = recorded;
            if (ok && string.IsNullOrEmpty(file)) { ok = false; message = "output file not found"; }
            if (ok && S.errors > 0) { ok = false; message = S.errors + " error(s) logged during the take"; }
            int fps = s_List.fps;

            TrailerShotReport sr = S.report.shots.Find(x => x.id == shot.id);
            if (sr == null) { sr = new TrailerShotReport { id = shot.id }; S.report.shots.Add(sr); }
            sr.takes.Add(new TrailerTakeReport
            {
                take = take, file = file, frames = S.rec_frames, fps = fps,
                // the PLANNED length (shots.json), so `trailer_edl.py check --capture` can compare frames against it
                duration_s = shot.duration_s, status = ok ? "ok" : "failed", errors = S.errors, message = message ?? "",
            });
            if (ok) S.ok++; else S.failed++;
            string status = ok ? "ok" : "failed";
            if (ok) Debug.Log("[TRAILER] shot=" + shot.id + " take=" + take + " status=" + status + " frames=" + S.rec_frames + " file=" + file);
            else Debug.LogWarning("[TRAILER] shot=" + shot.id + " take=" + take + " status=" + status + " frames=" + S.rec_frames + " file=" + file + " (" + message + ")");

            S.take_index++;
            if (S.take_index >= shot.takes) { S.shot_index++; S.take_index = 0; }
            S.errors = 0;
            TrailerJob.WriteReport(S);
            SetPhase(TrailerPhase.BeginTake);
        }

        static void Finish(string message, bool failCurrentTake)
        {
            if (S == null) return;
            if (failCurrentTake && InTake() && s_Shots != null && S.shot_index < s_Shots.Count) CompleteTake(false, message ?? "aborted");
            EndRecording();
            RestoreMixers();
            if (EditorApplication.isPlaying) { Time.timeScale = 1f; Cursor.visible = true; }
            S.message = message ?? "";
            TrailerJob.WriteReport(S);
            SetPhase(TrailerPhase.Done);
            Debug.Log("[TRAILER] done ok=" + S.ok + " failed=" + S.failed + " report=" + S.report_path);
            if (EditorApplication.isPlaying || EditorApplication.isPlayingOrWillChangePlaymode) EditorApplication.ExitPlaymode();
        }

        // ---- Unity Recorder (only compiled when com.unity.recorder is installed) ---------------------------------

#if HARNESS_RECORDER
        static RecorderController s_Ctrl;
        static RecorderControllerSettings s_CtrlSettings;
        static MovieRecorderSettings s_Movie;

        static string BeginRecording(TrailerShot shot, int take)
        {
            try
            {
                EndRecording();
                string basePath = OutputBase(shot, take);
                Directory.CreateDirectory(Path.GetDirectoryName(basePath));
                int fps = s_List.fps;

                s_Movie = ScriptableObject.CreateInstance<MovieRecorderSettings>();
                s_Movie.name = "Harness Trailer " + shot.id;
                s_Movie.Enabled = true;
                s_Movie.OutputFile = basePath; // absolute, no extension: the Recorder appends .mp4 / .mov
                s_Movie.CaptureAudio = s_List.audio.capture;
                s_Movie.FrameRate = fps;
                s_Movie.FrameRatePlayback = FrameRatePlayback.Constant;
                s_Movie.CapFrameRate = true;
                s_Movie.ImageInputSettings = new GameViewInputSettings { OutputWidth = s_List.resolution.w, OutputHeight = s_List.resolution.h };
                if (s_List.codec == "prores")
                    s_Movie.EncoderSettings = new ProResEncoderSettings { Format = ProResEncoderSettings.OutputFormat.ProRes422HQ };
                else
                    s_Movie.EncoderSettings = new CoreEncoderSettings
                    {
                        Codec = CoreEncoderSettings.OutputCodec.MP4,
                        EncodingQuality = CoreEncoderSettings.VideoEncodingQuality.High,
                    };

                s_CtrlSettings = ScriptableObject.CreateInstance<RecorderControllerSettings>();
                s_CtrlSettings.AddRecorderSettings(s_Movie);
                s_CtrlSettings.SetRecordModeToManual();
                s_CtrlSettings.FrameRate = fps;
                s_CtrlSettings.FrameRatePlayback = FrameRatePlayback.Constant;
                s_CtrlSettings.CapFrameRate = true;
                s_CtrlSettings.ExitPlayMode = false;

                s_Ctrl = new RecorderController(s_CtrlSettings);
                s_Ctrl.PrepareRecording();
                if (!s_Ctrl.StartRecording()) return "recorder refused to start (check Recorder settings / console)";
                return null;
            }
            catch (Exception e) { EndRecording(); return "recorder setup failed: " + e.Message; }
        }

        static bool RecorderRunning() { return s_Ctrl != null && s_Ctrl.IsRecording(); }

        /// <summary>Stops capturing but keeps the settings alive while the encoder flushes.</summary>
        static void StopRecorder()
        {
            if (s_Ctrl == null) return;
            try { if (s_Ctrl.IsRecording()) s_Ctrl.StopRecording(); } catch (Exception e) { Debug.LogWarning("[TRAILER] StopRecording: " + e.Message); }
        }

        static void EndRecording()
        {
            StopRecorder();
            s_Ctrl = null;
            if (s_Movie != null) { UnityEngine.Object.DestroyImmediate(s_Movie); s_Movie = null; }
            if (s_CtrlSettings != null) { UnityEngine.Object.DestroyImmediate(s_CtrlSettings); s_CtrlSettings = null; }
        }
#else
        static string BeginRecording(TrailerShot shot, int take) { return "install com.unity.recorder (5.x) first"; }
        static bool RecorderRunning() { return false; }
        static void StopRecorder() { }
        static void EndRecording() { }
#endif
    }
}
