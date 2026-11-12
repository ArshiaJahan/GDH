// Harness.Trailer: data models and job persistence for the trailer capture tool.
//
// Entry points live in TrailerCapture (Start/Status/Cancel/RunFromCli) and TrailerCards (Render).
// This file holds:
//   - JsonUtility models that mirror shots.json (TrailerShotList) and report.json (TrailerReport),
//   - JobState, the state machine record persisted to Temp/HarnessTrailer/job.json and mirrored in SessionState so the
//     job survives the domain reload that entering Play Mode triggers,
//   - helpers: Load/validate, project-relative path resolution, reflection type lookup.
//
// Why Game View capture: the harness pins the URP 2D renderer, which has no capture pass for the Recorder's
// "Targeted Camera" input; Game View (or a Render Texture) is the supported source.
// Why output must be outside Assets/: multi-hundred-MB videos inside Assets/ get imported by the AssetDatabase
// (slow, bloats Library/, triggers reimports and can break the L1 gate). Paths are relative to the Unity project root.

using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Harness.Trailer
{
    // ---- shots.json ------------------------------------------------------------------------------------------

    [Serializable] public class TrailerResolution { public int w = 1920; public int h = 1080; }
    [Serializable] public class TrailerAudio { public bool capture; public string[] mute_mixer_params = new string[0]; }
    [Serializable] public class TrailerHide { public string[] objects = new string[0]; public bool cursor; }
    [Serializable] public class TrailerCameraSpec { public string cinemachine = ""; public float ortho_size; }

    [Serializable]
    public class TrailerShot
    {
        public string id = "";
        public string beat = "";
        public string scene = "";
        public string setup = "";
        public string setup_arg = "";
        public string input = "";
        public float warmup_s;
        public float duration_s;
        public float time_scale = 1f; // 0 means 1
        public int takes = 1;
        public TrailerHide hide = new TrailerHide();
        public TrailerCameraSpec camera = new TrailerCameraSpec();
        public string notes = "";
    }

    [Serializable]
    public class TrailerShotList
    {
        public int version = 1;
        public int fps = 60;
        public TrailerResolution resolution = new TrailerResolution();
        public string source = "game_view"; // "game_view" | "render_texture" (render_texture falls back to game_view)
        public string codec = "mp4";        // "mp4" | "prores"
        public string output_dir = "";
        public TrailerAudio audio = new TrailerAudio();
        public TrailerShot[] shots = new TrailerShot[0];
    }

    // ---- report.json -----------------------------------------------------------------------------------------

    [Serializable]
    public class TrailerTakeReport
    {
        public int take;
        public string file = "";
        public int frames;
        public int fps;
        public float duration_s;          // planned length from shots.json (frames / fps is what was recorded)
        public string status = "failed"; // "ok" | "failed"
        public int errors;
        public string message = "";
    }

    [Serializable] public class TrailerShotReport { public string id = ""; public List<TrailerTakeReport> takes = new List<TrailerTakeReport>(); }
    [Serializable] public class TrailerReport { public List<TrailerShotReport> shots = new List<TrailerShotReport>(); }

    // ---- job state (Temp/HarnessTrailer/job.json + SessionState) -----------------------------------------------

    public static class TrailerPhase
    {
        public const string EnterPlay = "enter_play"; // waiting for Play Mode after Start()
        public const string BeginTake = "begin_take"; // pick the next shot/take, start the scene load
        public const string Loading = "loading";
        public const string Setup = "setup";          // setup method, time scale, hide, input
        public const string Warmup = "warmup";
        public const string Recording = "recording";
        public const string Finalize = "finalize";    // recorder stopped, waiting for the encoder/file
        public const string Done = "done";
    }

    [Serializable]
    public class JobState
    {
        public string shots_path = "";
        public string only = "";
        public bool cli;               // launched via RunFromCli: exit the editor when done
        public bool exit_requested;
        public string phase = "";
        public int shot_index;
        public int take_index;         // 0-based
        public double phase_started;   // EditorApplication.timeSinceStartup
        public int load_frame;
        public int rec_start_frame;
        public int rec_target;
        public int rec_frames;
        public int errors;             // errors/exceptions logged during the current take
        public int ok;
        public int failed;
        public string message = "";
        public string report_path = "";
        public TrailerReport report = new TrailerReport();

        public bool Active { get { return !string.IsNullOrEmpty(phase) && phase != TrailerPhase.Done; } }
    }

    public static class TrailerJob
    {
        public const string TempDir = "Temp/HarnessTrailer";
        const string SessionKey = "Harness.Trailer.JobState";
        // Set by RunFromCli in THIS editor session (SessionState survives domain reloads, not editor restarts), so a
        // stale job.json with cli=true left in Temp/ by an earlier run never makes a normal editor session exit.
        const string CliSessionKey = "Harness.Trailer.CliStartedThisSession";

        public static bool CliStartedThisSession
        {
            get { return SessionState.GetBool(CliSessionKey, false); }
            set { SessionState.SetBool(CliSessionKey, value); }
        }

        public static string ProjectRoot { get { return Directory.GetParent(Application.dataPath).FullName; } }
        public static string JobFile { get { return Path.Combine(ProjectRoot, TempDir, "job.json"); } }

        /// <summary>Project-relative (or absolute) path to an absolute, normalized path.</summary>
        public static string Resolve(string p)
        {
            if (string.IsNullOrEmpty(p)) return "";
            return Path.GetFullPath(Path.IsPathRooted(p) ? p : Path.Combine(ProjectRoot, p));
        }

        public static bool IsUnderAssets(string absPath)
        {
            string assets = Path.GetFullPath(Application.dataPath).TrimEnd('/', '\\');
            string p = Path.GetFullPath(absPath).TrimEnd('/', '\\');
            return p.Equals(assets, StringComparison.OrdinalIgnoreCase)
                || p.StartsWith(assets + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                || p.StartsWith(assets + "/", StringComparison.OrdinalIgnoreCase);
        }

        public static Type FindType(string fullName)
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                try { var t = asm.GetType(fullName, false); if (t != null) return t; }
                catch (Exception) { /* dynamic/partial assemblies can throw; skip */ }
            }
            return null;
        }

        public static string ReportPath(TrailerShotList list) { return Path.Combine(Resolve(list.output_dir), "report.json"); }

        // ---- loading / validation ----

        public static bool TryLoad(string shotsPath, out TrailerShotList list, out string error)
        {
            list = null;
            error = null;
            string abs = Resolve(shotsPath);
            if (string.IsNullOrEmpty(abs) || !File.Exists(abs)) { error = "shots file not found: " + shotsPath; return false; }
            try { list = JsonUtility.FromJson<TrailerShotList>(File.ReadAllText(abs)); }
            catch (Exception e) { error = "invalid JSON in " + shotsPath + ": " + e.Message; return false; }
            if (list == null) { error = "empty shots file: " + shotsPath; return false; }
            Normalize(list);
            error = Validate(list);
            if (error != null) { list = null; return false; }
            return true;
        }

        static void Normalize(TrailerShotList l)
        {
            if (l.resolution == null) l.resolution = new TrailerResolution();
            if (l.audio == null) l.audio = new TrailerAudio();
            if (l.audio.mute_mixer_params == null) l.audio.mute_mixer_params = new string[0];
            if (l.shots == null) l.shots = new TrailerShot[0];
            if (string.IsNullOrEmpty(l.codec)) l.codec = "mp4";
            l.codec = l.codec.ToLowerInvariant();
            if (string.IsNullOrEmpty(l.source)) l.source = "game_view";
            foreach (var s in l.shots)
            {
                if (s == null) continue;
                if (s.hide == null) s.hide = new TrailerHide();
                if (s.hide.objects == null) s.hide.objects = new string[0];
                if (s.camera == null) s.camera = new TrailerCameraSpec();
                if (s.time_scale <= 0f) s.time_scale = 1f;
                if (s.takes <= 0) s.takes = 1;
                if (s.setup == null) s.setup = "";
                if (s.setup_arg == null) s.setup_arg = "";
                if (s.input == null) s.input = "";
            }
        }

        static string Validate(TrailerShotList l)
        {
            var errs = new List<string>();
            if (l.fps < 1 || l.fps > 240) errs.Add("fps must be 1..240");
            if (l.resolution.w < 16 || l.resolution.h < 16 || l.resolution.w > 8192 || l.resolution.h > 8192) errs.Add("resolution out of range");
            if (l.codec != "mp4" && l.codec != "prores") errs.Add("codec must be mp4 or prores");
            if (l.source != "game_view" && l.source != "render_texture") errs.Add("source must be game_view or render_texture");
            else if (l.source == "render_texture") Debug.LogWarning("[TRAILER] source=render_texture is not implemented; using game_view");
            if (string.IsNullOrEmpty(l.output_dir)) errs.Add("output_dir is required");
            else if (IsUnderAssets(Resolve(l.output_dir))) errs.Add("capture output must be outside Assets/");
            if (l.shots.Length == 0) errs.Add("no shots");
            var seen = new HashSet<string>();
            foreach (var s in l.shots)
            {
                if (s == null || string.IsNullOrEmpty(s.id)) { errs.Add("shot without id"); continue; }
                if (s.id.IndexOfAny(new[] { '/', '\\', ':' }) >= 0 || s.id.Contains("..")) errs.Add("bad shot id '" + s.id + "'");
                if (!seen.Add(s.id)) errs.Add("duplicate shot id " + s.id);
                if (string.IsNullOrEmpty(s.scene) || !File.Exists(Resolve(s.scene))) errs.Add(s.id + ": scene not found '" + s.scene + "'");
                if (s.duration_s <= 0f) errs.Add(s.id + ": duration_s must be > 0");
                if (s.warmup_s < 0f) errs.Add(s.id + ": warmup_s must be >= 0");
            }
            return errs.Count == 0 ? null : string.Join("; ", errs.ToArray());
        }

        /// <summary>Shots to run, in file order, optionally filtered by a comma/semicolon separated id list.</summary>
        public static List<TrailerShot> Filter(TrailerShotList l, string only, out string error)
        {
            error = null;
            var result = new List<TrailerShot>();
            if (string.IsNullOrWhiteSpace(only)) { result.AddRange(l.shots); return result; }
            var wanted = new List<string>(only.Split(new[] { ',', ';', ' ' }, StringSplitOptions.RemoveEmptyEntries));
            foreach (var s in l.shots) if (wanted.Remove(s.id)) result.Add(s);
            if (wanted.Count > 0) error = "unknown shot id(s): " + string.Join(",", wanted.ToArray());
            return result;
        }

        // ---- persistence ----

        public static void SaveState(JobState s)
        {
            string json = JsonUtility.ToJson(s, true);
            SessionState.SetString(SessionKey, json);
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(JobFile));
                File.WriteAllText(JobFile, json);
            }
            catch (Exception e) { Debug.LogWarning("[TRAILER] could not write job.json: " + e.Message); }
        }

        public static JobState LoadState()
        {
            string json = SessionState.GetString(SessionKey, "");
            if (string.IsNullOrEmpty(json))
            {
                try { if (File.Exists(JobFile)) json = File.ReadAllText(JobFile); } catch (Exception) { json = ""; }
            }
            if (string.IsNullOrEmpty(json)) return null;
            try { return JsonUtility.FromJson<JobState>(json); } catch (Exception) { return null; }
        }

        public static void WriteReport(JobState s)
        {
            if (string.IsNullOrEmpty(s.report_path)) return;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(s.report_path));
                File.WriteAllText(s.report_path, JsonUtility.ToJson(s.report, true));
            }
            catch (Exception e) { Debug.LogWarning("[TRAILER] could not write report: " + e.Message); }
        }
    }
}
