using System;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace Gdw.Replay.Editor
{
    /// <summary>
    /// Editor commands for the record/replay lifecycle. Start/Status/Cancel persist job identity
    /// across domain reload via EditorPrefs, emit [HARNESS] REPLAY {json} lines per contracts §5,
    /// and read the -gdwReplayRequest CLI argument.
    /// A record started in Edit Mode enters Play Mode first and begins once Play Mode is running:
    /// entering Play Mode reloads the domain, which would drop a session started before it.
    /// </summary>
    [InitializeOnLoad]
    public static class ReplayCommands
    {
        const string JobIdPrefKey = "Gdw.Replay.Editor.JobId";
        const string RunIdPrefKey = "Gdw.Replay.Editor.RunId";
        const string RequestPathPrefKey = "Gdw.Replay.Editor.RequestPath";
        // A record request waiting for Play Mode. SessionState survives the domain reload.
        const string PendingRecordKey = "Gdw.Replay.Editor.PendingRecord";

        static ReplayCommands()
        {
            EditorApplication.playModeStateChanged -= OnPlayModeStateChanged;
            EditorApplication.playModeStateChanged += OnPlayModeStateChanged;
        }

        /// <summary>True while a record request is waiting for Play Mode to start.</summary>
        public static bool RecordPending => !string.IsNullOrEmpty(SessionState.GetString(PendingRecordKey, ""));
        const string CliArg = "-gdwReplayRequest";

        static string _jobId;
        static string _runId;
        static string _requestPath;

        /// <summary>Job identity: persists across domain reload via EditorPrefs.</summary>
        public static string JobId
        {
            get
            {
                if (string.IsNullOrEmpty(_jobId))
                    _jobId = EditorPrefs.GetString(JobIdPrefKey, null);
                return _jobId;
            }
            private set
            {
                _jobId = value;
                if (!string.IsNullOrEmpty(value))
                    EditorPrefs.SetString(JobIdPrefKey, value);
                else
                    EditorPrefs.DeleteKey(JobIdPrefKey);
            }
        }

        public static string RunId
        {
            get
            {
                if (string.IsNullOrEmpty(_runId))
                    _runId = EditorPrefs.GetString(RunIdPrefKey, null);
                return _runId;
            }
            private set
            {
                _runId = value;
                if (!string.IsNullOrEmpty(value))
                    EditorPrefs.SetString(RunIdPrefKey, value);
                else
                    EditorPrefs.DeleteKey(RunIdPrefKey);
            }
        }

        static string RequestPath
        {
            get
            {
                if (string.IsNullOrEmpty(_requestPath))
                    _requestPath = EditorPrefs.GetString(RequestPathPrefKey, null);
                return _requestPath;
            }
            set
            {
                _requestPath = value;
                if (!string.IsNullOrEmpty(value))
                    EditorPrefs.SetString(RequestPathPrefKey, value);
                else
                    EditorPrefs.DeleteKey(RequestPathPrefKey);
            }
        }

        /// <summary>
        /// Start a record or replay session from a request JSON file.
        /// Returns the jobId as a JSON string.
        /// </summary>
        public static string Start(string requestPath)
        {
            try
            {
                if (string.IsNullOrEmpty(requestPath))
                    throw new ArgumentException("requestPath is required");

                if (!File.Exists(requestPath))
                    throw new FileNotFoundException("Replay request file not found", requestPath);

                var request = ReplayContracts.ReadRequest(requestPath);
                RequestPath = requestPath;

                // Generate or reuse job identity
                if (string.IsNullOrEmpty(JobId))
                    JobId = Guid.NewGuid().ToString("N");

                RunId = request.RunId ?? "rr_" + Guid.NewGuid().ToString("N").Substring(0, 16);

                // Ensure the InputSystem adapter factory is registered
                if (ReplayInput.Factory == null)
                {
                    ReplayInput.Factory = (dir, mb) => new InputTraceAdapter(dir, mb);
                }

                // Scan for legacy Input Manager usage — surface as a readiness error
                string projectRoot = Path.GetDirectoryName(Application.dataPath);
                var legacyReport = LegacyInputDetector.ScanProject(projectRoot);
                string refusal = LegacyInputDetector.RefusalMessage(legacyReport);
                if (refusal != null)
                {
                    WriteRefusalReport(projectRoot, request, refusal);
                    throw new InvalidOperationException(refusal);
                }

                // Log start
                EmitHarnessLine(new
                {
                    v = 1,
                    run_id = RunId,
                    @event = "start",
                    status = request.Op == "record" ? "recording" : "replaying",
                    job_id = JobId,
                    legacy_input = legacyReport.HasLegacyGameplay ? legacyReport.Message : "",
                });

                if (request.Op == "record")
                {
                    if (!EditorApplication.isPlaying)
                    {
                        // Open the scene, enter Play Mode, and begin in OnPlayModeStateChanged.
                        if (!string.IsNullOrEmpty(request.Scene))
                        {
                            UnityEditor.SceneManagement.EditorSceneManager.OpenScene(request.Scene);
                        }
                        SessionState.SetString(PendingRecordKey, requestPath);
                        EditorApplication.EnterPlaymode();
                        return JsonSerialize(new { ok = true, job_id = JobId, run_id = RunId, status = "entering_play_mode" });
                    }
                    BeginRecord(request);
                }
                else
                {
                    var replayPath = request.ReplayPath;
                    if (string.IsNullOrEmpty(replayPath))
                        throw new ArgumentException("replay_path is required for replay/verify ops");
                    if (!string.IsNullOrEmpty(request.Scene))
                    {
                        UnityEditor.SceneManagement.EditorSceneManager.OpenScene(request.Scene);
                    }
                    ReplaySession.BeginReplay(replayPath);
                }

                return JsonSerialize(new { ok = true, job_id = JobId, run_id = RunId });
            }
            catch (Exception e)
            {
                EmitHarnessLine(new
                {
                    v = 1,
                    run_id = RunId ?? "",
                    @event = "error",
                    status = "error",
                    message = e.Message,
                });
                return JsonSerialize(new { ok = false, error = e.Message });
            }
        }

        static void BeginRecord(ReplayRequest request)
        {
            var options = new ReplayOptions
            {
                Seed = request.Seed,
                FixedDeltaTime = request.FixedDt != null ? request.FixedDt.Value : 1f / 60f,
                ScenePath = request.Scene,
                RunId = RunId,
                Strict = true,
            };
            ReplaySession.BeginRecord(options);
        }

        static void OnPlayModeStateChanged(PlayModeStateChange change)
        {
            string pending = SessionState.GetString(PendingRecordKey, "");
            if (string.IsNullOrEmpty(pending)) return;
            if (change == PlayModeStateChange.EnteredEditMode)
            {
                // Play Mode never started (or was left before it did): drop the request.
                SessionState.EraseString(PendingRecordKey);
                return;
            }
            if (change != PlayModeStateChange.EnteredPlayMode) return;
            SessionState.EraseString(PendingRecordKey);
            try
            {
                if (ReplayInput.Factory == null)
                    ReplayInput.Factory = (dir, mb) => new InputTraceAdapter(dir, mb);
                BeginRecord(ReplayContracts.ReadRequest(pending));
                EmitHarnessLine(new { v = 1, run_id = RunId ?? "", @event = "progress", status = "recording", job_id = JobId });
            }
            catch (Exception e)
            {
                EmitHarnessLine(new { v = 1, run_id = RunId ?? "", @event = "error", status = "error", message = e.Message });
            }
        }

        static void WriteRefusalReport(string projectRoot, ReplayRequest request, string message)
        {
            try
            {
                string dir = Path.Combine(projectRoot, "Logs", "harness", "replay", RunId);
                Directory.CreateDirectory(dir);
                var report = new ReplayReport
                {
                    RunId = RunId,
                    Status = "error",
                    Message = message,
                    StartedUtc = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"),
                    EndedUtc = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'"),
                };
                File.WriteAllText(Path.Combine(dir, "report.json"), Json.Serialize(report.ToJson()));
            }
            catch (Exception e)
            {
                Debug.LogWarning("[Gdw.Replay] could not write refusal report: " + e.Message);
            }
        }

        /// <summary>
        /// Returns the current session status as a JSON string, and emits a [HARNESS] REPLAY progress line.
        /// </summary>
        public static string Status()
        {
            try
            {
                var session = ReplaySession.Current;
                string state = session != null ? session.State : (RecordPending ? "starting" : "idle");
                int frame = -1;
                long tick = 0;

                if (session != null)
                {
                    // Access frame/tick info from the active session via ReplayLoop internals
                    // ReplayLoop.Tick and the frame counter are internal; we approximate from options.
                    frame = (int)(ReplayClock.Tick > 0 ? ReplayClock.Tick : 0);
                    tick = (long)ReplayClock.Tick;
                }

                var report = new
                {
                    v = 1,
                    run_id = RunId ?? "",
                    @event = "progress",
                    status = state,
                    frame,
                    tick,
                    job_id = JobId,
                };

                EmitHarnessLine(report);
                return JsonSerialize(report);
            }
            catch (Exception e)
            {
                return JsonSerialize(new { v = 1, run_id = RunId ?? "", @event = "error", status = "error", message = e.Message });
            }
        }

        /// <summary>
        /// Cancel the active replay session and clear job state.
        /// </summary>
        public static string Cancel()
        {
            try
            {
                var session = ReplaySession.Current;
                if (session != null)
                {
                    session.Stop();
                }

                // Clear persistent state
                SessionState.EraseString(PendingRecordKey);
                JobId = null;
                RunId = null;
                RequestPath = null;

                EmitHarnessLine(new
                {
                    v = 1,
                    run_id = RunId ?? "",
                    @event = "done",
                    status = "cancelled",
                });

                return JsonSerialize(new { ok = true, status = "cancelled" });
            }
            catch (Exception e)
            {
                return JsonSerialize(new { ok = false, error = e.Message });
            }
        }

        /// <summary>
        /// Entry point for -executeMethod from CLI batch mode.
        /// Reads the -gdwReplayRequest CLI argument and calls Start().
        /// </summary>
        public static void RunFromCli()
        {
            try
            {
                string requestPath = null;
                string[] args = Environment.GetCommandLineArgs();
                for (int i = 0; i < args.Length - 1; i++)
                {
                    if (string.Equals(args[i], CliArg, StringComparison.OrdinalIgnoreCase))
                    {
                        requestPath = args[i + 1];
                        break;
                    }
                }

                if (string.IsNullOrEmpty(requestPath))
                {
                    // Fallback: check EditorPrefs for a stored request path
                    requestPath = EditorPrefs.GetString(RequestPathPrefKey, null);
                }

                if (string.IsNullOrEmpty(requestPath))
                {
                    EmitHarnessLine(new
                    {
                        v = 1,
                        run_id = "",
                        @event = "error",
                        status = "error",
                        message = "no -gdwReplayRequest argument provided",
                    });
                    Debug.LogError("[HARNESS] REPLAY {\"v\":1,\"event\":\"error\",\"status\":\"error\",\"message\":\"no -gdwReplayRequest argument\"}");
                    EditorApplication.Exit(1);
                    return;
                }

                var result = Start(requestPath);
                Debug.Log("[HARNESS] REPLAY " + result);

                // Subscribe to session finish for batch-mode exit
                if (ReplaySession.Current != null)
                {
                    ReplaySession.Current.Finished += OnSessionFinished;
                }
                else
                {
                    // Session already finished synchronously — emit report
                    EmitDone();
                }
            }
            catch (Exception e)
            {
                Debug.LogError("[HARNESS] REPLAY {\"v\":1,\"event\":\"error\",\"status\":\"error\",\"message\":\"" + EscapeJson(e.Message) + "\"}");
                EditorApplication.Exit(1);
            }
        }

        static void OnSessionFinished(ReplayResult result)
        {
            ReplaySession.Current.Finished -= OnSessionFinished;

            string status = result.Status;
            string eventType = status == "pass" || status == "diverged" || status == "error" || status == "cancelled"
                ? "done" : "progress";

            EmitHarnessLine(new
            {
                v = 1,
                run_id = RunId ?? result.ReportPath ?? "",
                @event = eventType,
                status = status,
                frame = result.Frames,
                tick = result.Ticks,
                provider_id = result.DivergentProviderId,
                expected_hash = result.ExpectedHash,
                actual_hash = result.ActualHash,
                report = result.ReportPath,
                message = result.Message,
            });

            if (status == "pass" || status == "diverged" || status == "error" || status == "cancelled")
            {
                EmitDone();
            }
        }

        static void EmitDone()
        {
            Debug.Log("[HARNESS] REPORT " + (RequestPath ?? ""));
            if (Application.isBatchMode)
            {
                EditorApplication.Exit(0);
            }
        }

        static void EmitHarnessLine(object data)
        {
            string json = JsonSerialize(data);
            Debug.Log("[HARNESS] REPLAY " + json);
        }

        static string JsonSerialize(object obj)
        {
            // Simple manual JSON serialization for anonymous objects
            var sb = new StringBuilder();
            SerializeObject(sb, obj);
            return sb.ToString();
        }

        static void SerializeObject(StringBuilder sb, object obj)
        {
            if (obj == null) { sb.Append("null"); return; }
            var type = obj.GetType();
            if (type.IsPrimitive || obj is string)
            {
                if (obj is string s)
                {
                    sb.Append('"');
                    sb.Append(EscapeJson(s));
                    sb.Append('"');
                }
                else if (obj is bool b)
                {
                    sb.Append(b ? "true" : "false");
                }
                else if (obj is long l)
                {
                    sb.Append(l);
                }
                else if (obj is int i)
                {
                    sb.Append(i);
                }
                else if (obj is float f)
                {
                    sb.Append(f.ToString("G"));
                }
                else if (obj is double d)
                {
                    sb.Append(d.ToString("G"));
                }
                else
                {
                    sb.Append(obj.ToString());
                }
                return;
            }
            // Anonymous type or POCO
            sb.Append('{');
            bool first = true;
            foreach (var prop in type.GetProperties(BindingFlags.Public | BindingFlags.Instance))
            {
                if (!first) sb.Append(',');
                first = false;
                sb.Append('"');
                sb.Append(prop.Name);
                sb.Append("\":");
                SerializeObject(sb, prop.GetValue(obj, null));
            }
            sb.Append('}');
        }

        static string EscapeJson(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            var sb = new StringBuilder(s.Length);
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }
    }
}
