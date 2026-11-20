using System;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace Gdw.Replay
{
    /// <summary>
    /// MonoBehaviour anchor for a record or replay run. The bootstrap creates it after the scene is
    /// loaded and providers are registered; ReplayLoop drives the actual frame/tick schedule.
    /// </summary>
    public sealed class ReplaySession : MonoBehaviour
    {
        static ReplaySession _current;

        public static ReplaySession Current => _current;

        public ReplayOptions Options { get; private set; }
        public string State { get; private set; } = "idle";
        public event Action<ReplayResult> Finished;

        bool _record;
        bool _active;
        string _initialHash;
        // Provider id -> schema digest, taken when recording starts: an adapter can unregister its
        // provider (unity.input) before the archive is written.
        readonly System.Collections.Generic.Dictionary<string, string> _providerSchemas =
            new System.Collections.Generic.Dictionary<string, string>(StringComparer.Ordinal);
        ReplayOptions _options;
        IReplayInputAdapter _adapter;

        /// <summary>Where a recording is written; the Editor layer may override the default project-relative path.</summary>
        internal string OutputPath { get; set; }

        public static ReplaySession BeginRecord(ReplayOptions options)
        {
            if (options == null) throw new ArgumentNullException(nameof(options));
            if (_current != null) throw new ReplayStateException("a replay session is already active");

            var session = CreateSession();
            try
            {
                session._record = true;
                session.Options = options;
                session._options = options;
                session.State = "recording";
                session.OutputPath = DefaultOutputPath(options);
                session._initialHash = ReplayRegistry.Instance.ComputeAll().Aggregate;

                var adapter = ReplayInput.Create(Path.GetDirectoryName(session.OutputPath));
                adapter.StartCapture();
                session._adapter = adapter;
                foreach (var id in ReplayRegistry.Instance.Ids)
                    session._providerSchemas[id] = ReplayRegistry.Instance.SchemaSha256(id);

                session.StartLoop(null);
                return session;
            }
            catch
            {
                DestroySession(session);
                throw;
            }
        }

        public static ReplaySession BeginReplay(string path)
        {
            if (path == null) throw new ArgumentNullException(nameof(path));
            if (_current != null) throw new ReplayStateException("a replay session is already active");

            var archive = ReplayArchive.Read(path);
            var options = OptionsFromHeader(archive.Header);
            var session = CreateSession();
            try
            {
                session._record = false;
                session.Options = options;
                session._options = options;
                session.State = "replaying";
                session.OutputPath = archive.Path;
                session._initialHash = ReplayRegistry.Instance.ComputeAll().Aggregate;

                var adapter = ReplayInput.Create(Path.GetDirectoryName(path));
                if (archive.InputTrace != null && archive.InputTrace.Length > 0)
                    adapter.SetTrace(archive.InputTrace);
                adapter.StartReplay();
                session._adapter = adapter;

                session.StartLoop(archive.Frames);
                return session;
            }
            catch
            {
                DestroySession(session);
                throw;
            }
        }

        static void DestroySession(ReplaySession session)
        {
            _current = null;
            if (session != null)
            {
                session._active = false;
                if (session.gameObject != null)
                    UnityEngine.Object.Destroy(session.gameObject);
            }
        }

        static ReplaySession CreateSession()
        {
            var go = new GameObject("Gdw.Replay.Session");
            if (Application.isPlaying) DontDestroyOnLoad(go);
            var session = go.AddComponent<ReplaySession>();
            session._active = true;
            _current = session;
            return session;
        }

        void StartLoop(System.Collections.Generic.List<ReplayFrame> replayFrames)
        {
            Application.quitting += OnApplicationQuitting;
            ReplayLoop.Begin(this, _options, replayFrames);
        }

        public void Mark(string label, string dataJson = null)
        {
            if (!_active) return;
            ReplayLoop.Mark(label, dataJson);
        }

        public void Stop()
        {
            if (!_active || _current != this) return;
            ReplayLoop.Finish();
        }

        internal void OnLoopFinished(ReplayLoopResult result)
        {
            var replayResult = new ReplayResult
            {
                Frames = _record ? result.Frames.Count : result.FramesCompared,
                Ticks = (long)result.Ticks,
                FirstDivergentFrame = result.FirstDivergentFrame,
                DivergentProviderId = result.DivergentProviderId,
                ExpectedHash = result.ExpectedHash,
                ActualHash = result.ActualHash,
                Message = result.Error,
            };

            try
            {
                if (_record)
                {
                    if (result.Error != null)
                    {
                        replayResult.Status = "error";
                    }
                    else
                    {
                        // The input trace file is only written when capture stops; finalize it before archiving.
                        try { _adapter?.Dispose(); }
                        catch (Exception e) { Debug.LogWarning("[Gdw.Replay] failed to finalize input trace: " + e.Message); }
                        WriteArchive(result);
                        replayResult.Status = "pass";
                        replayResult.ReportPath = OutputPath;
                    }
                }
                else
                {
                    replayResult.Status = result.Error != null ? "error" : (result.FirstDivergentFrame >= 0 ? "diverged" : "pass");
                }
            }
            catch (Exception e)
            {
                replayResult.Status = "error";
                replayResult.Message = e.Message;
            }

            State = replayResult.Status;
            _active = false;
            _current = null;
            Application.quitting -= OnApplicationQuitting;

            if (_adapter != null)
            {
                try { _adapter.Dispose(); }
                catch (Exception e) { Debug.LogWarning("[Gdw.Replay] failed to dispose input adapter: " + e.Message); }
                _adapter = null;
            }

            Finished?.Invoke(replayResult);
            if (this != null) Destroy(gameObject);
        }

        void OnApplicationQuitting() { Abort(); }

        void OnDestroy() { Abort(); }

        void Abort()
        {
            if (!_active) return;
            _active = false;
            ReplayLoop.Abort();
            Application.quitting -= OnApplicationQuitting;

            if (_adapter != null)
            {
                try { _adapter.Dispose(); }
                catch (Exception e) { Debug.LogWarning("[Gdw.Replay] failed to dispose input adapter: " + e.Message); }
                _adapter = null;
            }

            if (_current == this) _current = null;
        }

        void WriteArchive(ReplayLoopResult result)
        {
            var header = BuildHeader(_initialHash, result.Frames.Count > 0 ? result.Frames[0].Providers.Keys : null);
            string finalHash = result.Frames.Count > 0 ? result.Frames[result.Frames.Count - 1].Hash : "";
            var manifest = BuildManifest(result, finalHash);

            byte[] traceBytes = _adapter?.GetTraceBytes() ?? new byte[0];
            manifest.Events = _adapter?.EventCount ?? 0;

            ReplayArchive.Write(OutputPath, header, result.Frames, result.Markers, traceBytes, manifest);
        }

        ReplayHeader BuildHeader(string initialHash, System.Collections.Generic.IEnumerable<string> frameProviderIds)
        {
            var header = new ReplayHeader
            {
                Format = "gdwreplay",
                Major = 1,
                Minor = 0,
                RunId = _options.RunId ?? DefaultRunId(),
                CreatedUtc = UtcNow(),
                ToolVersion = "0.1.0",
                Seed = _options.Seed,
                FixedDt = Rational.FromFloat(_options.FixedDeltaTime),
                RenderDt = new Rational(1, 60),
            };
            header.Unity.Version = Application.unityVersion;
            header.Unity.Revision = "";
            header.Unity.ScriptingBackend = ScriptingBackend();
            header.Os.Platform = SystemInfo.operatingSystem;
            header.Os.Version = "";
            header.Cpu.Model = SystemInfo.processorType;
            header.Cpu.Architecture = "";
            header.Cpu.Cores = SystemInfo.processorCount;
            string root = ProjectRoot();
            string scenePath = !string.IsNullOrEmpty(_options.ScenePath)
                ? _options.ScenePath
                : UnityEngine.SceneManagement.SceneManager.GetActiveScene().path ?? "";
            header.Project.Id = Application.identifier;
            header.Project.Name = Application.productName;
            header.Project.ContentSha256 = ProjectContentSha256(root);
            header.Project.Dirty = false;
            header.Scene.Guid = SceneGuid(root, scenePath);
            header.Scene.Path = scenePath;
            header.Scene.ContentSha256 = FileSha256(root, scenePath);
            header.Packages.LockSha256 = FileSha256(root, "Packages/packages-lock.json");
            // Input settings, actions and layouts are not captured yet: the empty-input digest says so.
            header.Input.SettingsSha256 = EmptySha256;
            header.Input.ActionsSha256 = EmptySha256;
            header.Input.LayoutsSha256 = EmptySha256;
            header.Coverage.Notes = "input settings, actions and layouts digests are not captured (sha256 of empty input)";
            header.Input.SystemVersion = "1.20.1";
            header.ResetAdapter.Id = "scene-reset";
            header.ResetAdapter.InitialStateSha256 = initialHash ?? "";
            header.StateHash.Algorithm = "sha256";
            header.StateHash.Encoding = "gdw-replay-state/1";
            // The header lists the providers the frames hold, so the two always agree.
            var ids = new System.Collections.Generic.List<string>(frameProviderIds ?? ReplayRegistry.Instance.Ids);
            ids.Sort(StringComparer.Ordinal);
            foreach (var id in ids)
            {
                string schema;
                if (!_providerSchemas.TryGetValue(id, out schema))
                    schema = ReplayRegistry.Instance.IsRegistered(id) ? ReplayRegistry.Instance.SchemaSha256(id) : EmptySha256;
                header.Providers.Add(new ReplayProviderInfo
                {
                    Id = id,
                    SchemaSha256 = schema,
                    Gameplay = !id.StartsWith("unity.", StringComparison.Ordinal),
                });
            }
            return header;
        }

        static readonly string EmptySha256 = Digest.Sha256Hex(new byte[0]);

        static string ProjectRoot() => Path.GetDirectoryName(Application.dataPath) ?? "";

        /// <summary>SHA-256 of a project-relative file's bytes; the empty-input digest when it's missing.</summary>
        static string FileSha256(string root, string relativePath)
        {
            if (string.IsNullOrEmpty(relativePath)) return EmptySha256;
            try
            {
                string path = Path.Combine(root, relativePath);
                return File.Exists(path) ? Digest.Sha256Hex(File.ReadAllBytes(path)) : EmptySha256;
            }
            catch (Exception) { return EmptySha256; }
        }

        /// <summary>Digest over the package manifest, lock file and core project settings.</summary>
        static string ProjectContentSha256(string root)
        {
            var parts = new[]
            {
                "Packages/manifest.json", "Packages/packages-lock.json",
                "ProjectSettings/ProjectSettings.asset", "ProjectSettings/ProjectVersion.txt",
            };
            var sb = new System.Text.StringBuilder();
            foreach (var rel in parts) sb.Append(rel).Append(' ').Append(FileSha256(root, rel)).Append('\n');
            return Digest.Sha256Hex(Digest.Utf8(sb.ToString()));
        }

        /// <summary>The scene's GUID from its .meta file (lowercase), or "" when unknown.</summary>
        static string SceneGuid(string root, string scenePath)
        {
            if (string.IsNullOrEmpty(scenePath)) return "";
            try
            {
                string meta = Path.Combine(root, scenePath + ".meta");
                if (!File.Exists(meta)) return "";
                foreach (var line in File.ReadAllLines(meta))
                {
                    if (line.StartsWith("guid:", StringComparison.Ordinal))
                        return line.Substring(5).Trim().ToLowerInvariant();
                }
            }
            catch (Exception) { }
            return "";
        }

        static ReplayManifest BuildManifest(ReplayLoopResult result, string finalHash)
        {
            return new ReplayManifest
            {
                Format = "gdwreplay-manifest",
                Version = 1,
                Complete = true,
                Frames = result.Frames.Count,
                Ticks = (long)result.Ticks,
                Events = 0,
                FinalFrameHash = finalHash ?? "",
                CreatedUtc = UtcNow(),
                ToolVersion = "0.1.0",
                Console = new ReplayConsoleCounts(),
            };
        }

        static ReplayOptions OptionsFromHeader(ReplayHeader header)
        {
            return new ReplayOptions
            {
                Seed = header.Seed,
                FixedDeltaTime = header.FixedDt != null ? header.FixedDt.Value : 1f / 60f,
                ScenePath = header.Scene != null ? header.Scene.Path : null,
                RunId = header.RunId,
                Strict = true,
            };
        }

        static string ScriptingBackend()
        {
#if ENABLE_IL2CPP
            return "il2cpp";
#else
            return "mono";
#endif
        }

        static string UtcNow() => DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);

        static string DefaultRunId() => "rr_" + Guid.NewGuid().ToString("N").Substring(0, 16);

        static string DefaultOutputPath(ReplayOptions options)
        {
            string runId = options.RunId ?? DefaultRunId();
            // Project root = parent of Assets/ (contract §3: project-relative Logs/...)
            string projectRoot = Path.GetDirectoryName(Application.dataPath);
            return Path.Combine(projectRoot, "Logs", "harness", "replay", runId, "run.gdwreplay");
        }
    }
}
