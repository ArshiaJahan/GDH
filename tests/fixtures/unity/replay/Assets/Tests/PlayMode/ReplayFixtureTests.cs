using System.Collections;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;
using UnityEngine.InputSystem.Utilities;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace Gdw.Replay.Fixture.Tests
{
    /// <summary>
    /// Fixture PlayMode tests that exercise the full record/replay lifecycle.
    /// Record 600 frames, replay twice (in-process and fresh), verify identical hashes.
    /// Tests: held button, no-input frames, controlled perturbation, non-deterministic divergence.
    /// </summary>
    public class ReplayFixtureTests
    {
        ReplayResult _lastReplayResult;
        Keyboard _keyboard;

        [TearDown]
        public void TearDownEach()
        {
            NonDeterministicProvider.Enabled = false;
            TransformStateProvider.Instance.Untrack("actor");
            if (_keyboard != null && _keyboard.added) InputSystem.RemoveDevice(_keyboard);
            _keyboard = null;
            // Scene-based tests leave fixture objects (spinner/HP provider) behind; remove them so later tests start clean.
            foreach (var name in new[] { "SpinningCube", "HpManager", "Spawner" })
            {
                var go = GameObject.Find(name);
                if (go != null) Object.DestroyImmediate(go);
            }
            if (ReplaySession.Current != null)
                Object.Destroy(ReplaySession.Current.gameObject);
        }

        [OneTimeSetUp]
        public void OneTimeSetUp()
        {
            if (ReplayInput.Factory == null)
            {
                ReplayInput.Factory = (dir, mb) => new InputTraceAdapter(dir, mb);
            }
        }

        static string TraceSummary(byte[] traceBytes)
        {
            if (traceBytes == null || traceBytes.Length == 0) return "trace empty";
            var counts = new Dictionary<string, int>();
            using (var ms = new MemoryStream(traceBytes, false))
            using (var trace = InputEventTrace.LoadFrom(ms))
            {
                foreach (var e in trace)
                {
                    string k = e.type.ToString();
                    counts[k] = counts.ContainsKey(k) ? counts[k] + 1 : 1;
                }
            }
            var sb = new System.Text.StringBuilder("trace bytes=" + traceBytes.Length);
            foreach (var kv in counts) sb.Append(" " + kv.Key + "=" + kv.Value);
            return sb.ToString();
        }

        static string Describe(ReplayResult r)
        {
            return "status=" + r.Status + " frames=" + r.Frames + " firstDivergent=" + r.FirstDivergentFrame +
                   " provider=" + r.DivergentProviderId + " expected=" + r.ExpectedHash + " actual=" + r.ActualHash +
                   " message=" + r.Message;
        }

        /// <summary>Counts trace events that are not frame markers (real input state/delta events).</summary>
        static int CountInputEvents(byte[] traceBytes)
        {
            if (traceBytes == null || traceBytes.Length == 0) return 0;
            int n = 0;
            using (var ms = new MemoryStream(traceBytes, false))
            using (var trace = InputEventTrace.LoadFrom(ms))
            {
                foreach (var e in trace)
                    if (e.type != InputEventTrace.FrameMarkerEvent) n++;
            }
            return n;
        }

        /// <summary>Loads a scene that may not be in the build settings (batch test runner clears them).</summary>
        static IEnumerator LoadFixtureScene(string scenePath)
        {
#if UNITY_EDITOR
            if (SceneUtility.GetBuildIndexByScenePath(scenePath) < 0)
            {
                yield return UnityEditor.SceneManagement.EditorSceneManager.LoadSceneAsyncInPlayMode(
                    scenePath, new LoadSceneParameters(LoadSceneMode.Single));
                yield break;
            }
#endif
            yield return SceneManager.LoadSceneAsync(scenePath, LoadSceneMode.Single);
        }

        string GetArchivePath(string runId)
        {
            return Path.Combine(Application.dataPath, "..", "Logs", "harness", "replay", runId, "run.gdwreplay");
        }

        void EnsureClean(string path)
        {
            if (File.Exists(path))
                File.Delete(path);
            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir) && Directory.Exists(dir))
                Directory.Delete(dir, true);
        }

        IEnumerator WaitForFrames(int count)
        {
            for (int i = 0; i < count; i++)
                yield return null;
        }

        IEnumerator WaitForSessionEnd(ReplaySession session, float timeout = 60f)
        {
            _lastReplayResult = null;
            session.Finished += r => _lastReplayResult = r;
            float elapsed = 0f;
            while (_lastReplayResult == null && elapsed < timeout)
            {
                yield return new WaitForSecondsRealtime(0.05f);
                elapsed += 0.05f;
            }
            Assert.IsNotNull(_lastReplayResult, "Session did not finish within " + timeout + "s");
        }

        /// <summary>Set up a minimal input action asset with a Vector2 WASD action bound to keyboard.</summary>
        InputActionAsset CreateWasmoveAction()
        {
            var asset = ScriptableObject.CreateInstance<InputActionAsset>();
            var map = new InputActionMap("Gameplay");
            var moveAction = map.AddAction("Move", InputActionType.Value);
            moveAction.AddCompositeBinding("2DVector")
                .With("Up", "<Keyboard>/w")
                .With("Down", "<Keyboard>/s")
                .With("Left", "<Keyboard>/a")
                .With("Right", "<Keyboard>/d");
            asset.AddActionMap(map);
            asset.Enable();
            return asset;
        }

        [UnityTest]
        public IEnumerator Record600Frames_ReplayTwice_IdenticalHashes()
        {
            string runId = "test_fixture_600fr";
            string archivePath = GetArchivePath(runId);
            EnsureClean(archivePath);

            var hpGo = new GameObject("HP");
            var hp = hpGo.AddComponent<HpProvider>();
            yield return null;

            var options = new ReplayOptions
            {
                Seed = 12345,
                RunId = runId,
                FixedDeltaTime = 1f / 60f,
                Strict = true,
            };
            var session = ReplaySession.BeginRecord(options);
            Assert.IsNotNull(session, "Record session created");
            Assert.AreEqual("recording", session.State);

            yield return WaitForFrames(600);

            session.Stop();
            yield return null;
            yield return null;

            Assert.IsTrue(File.Exists(archivePath), "Archive written: " + archivePath);

            // In-process replay
            var replaySession1 = ReplaySession.BeginReplay(archivePath);
            Assert.IsNotNull(replaySession1, "Replay session 1 created");
            yield return WaitForSessionEnd(replaySession1);
            Assert.AreEqual("pass", _lastReplayResult.Status, "First replay should pass: " + Describe(_lastReplayResult));

            Assert.IsNull(ReplaySession.Current, "No active session after first replay");

            // Second replay
            var replaySession2 = ReplaySession.BeginReplay(archivePath);
            Assert.IsNotNull(replaySession2, "Replay session 2 created");
            yield return WaitForSessionEnd(replaySession2);
            Assert.AreEqual("pass", _lastReplayResult.Status, "Second replay should pass: " + Describe(_lastReplayResult));

            Object.Destroy(hpGo);
        }

        [UnityTest]
        public IEnumerator HeldButton_ReplaysIdentically()
        {
            // Record a run where the W key is held for 120+ consecutive frames,
            // then replay and assert identical per-frame hashes AND that the actor
            // moved the expected held distance.
            string runId = "test_fixture_heldbtn";
            string archivePath = GetArchivePath(runId);
            EnsureClean(archivePath);

            var asset = CreateWasmoveAction();
            var moveActionRef = InputActionReference.Create(asset.FindAction("Gameplay/Move"));

            var actorGo = new GameObject("Actor");
            actorGo.transform.position = Vector3.zero;
            var actor = actorGo.AddComponent<ReplayActor>();
            actor.speed = 5f;
            actor.moveAction = moveActionRef;

            var hpGo = new GameObject("HP");
            var hp = hpGo.AddComponent<HpProvider>();
            // Put the actor's position into every frame hash so identical hashes imply identical movement.
            TransformStateProvider.Instance.Track("actor", actorGo.transform);
            yield return null;

            var keyboard = InputSystem.AddDevice<Keyboard>();
            _keyboard = keyboard;
            // Batch-mode editor has no focus: devices added meanwhile come up disabled.
            InputSystem.EnableDevice(keyboard);

            var options = new ReplayOptions
            {
                Seed = 42,
                RunId = runId,
                FixedDeltaTime = 1f / 60f,
                Strict = true,
            };
            var session = ReplaySession.BeginRecord(options);
            Assert.IsNotNull(session, "Record session created");
            Assert.AreEqual("recording", session.State);
            InputSystem.EnableDevice(keyboard);

            // Hold W for 150 consecutive frames
            int holdFrames = 150;
            var diag = new System.Text.StringBuilder();
            for (int i = 0; i < holdFrames; i++)
            {
                InputSystem.QueueStateEvent(keyboard, new KeyboardState(Key.W));
                yield return null;
                if (i < 4)
                    diag.Append("[f" + i + " w=" + keyboard.wKey.isPressed + " act=" + asset.FindAction("Gameplay/Move").ReadValue<Vector2>() +
                                " y=" + actorGo.transform.position.y + " dt=" + Time.deltaTime + " mode=" + InputSystem.settings.updateMode + "]");
            }
            InputSystem.QueueStateEvent(keyboard, new KeyboardState());
            yield return null;

            session.Stop();
            yield return null;
            yield return null;

            Assert.IsTrue(File.Exists(archivePath), "Archive written: " + archivePath);

            // Recorded position: W held for holdFrames frames at speed*dt per frame (+-1 frame of input latency).
            float recordedY = actorGo.transform.position.y;
            float perFrame = 5f * (1f / 60f);
            float expectedY = perFrame * holdFrames;
            Assert.AreEqual(expectedY, recordedY, perFrame * 1.01f,
                "Actor should have moved the expected held distance; enabled=" + asset.FindAction("Gameplay/Move").enabled +
                " controls=" + asset.FindAction("Gameplay/Move").controls.Count + " wPressed=" + keyboard.wKey.isPressed +
                " kbEnabled=" + keyboard.enabled + " keyboards=" + Keyboard.all.Count + " updateMode=" + InputSystem.settings.updateMode +
                " dt=" + Time.deltaTime + " " + diag);
            Assert.AreEqual(0f, actorGo.transform.position.x, 1e-6f, "No sideways movement");

            var archive = ReplayArchive.Read(archivePath);
            Assert.Greater(CountInputEvents(archive.InputTrace), 0, "Held key must produce input events; " + TraceSummary(archive.InputTrace));
            Assert.GreaterOrEqual(archive.Frames.Count, holdFrames, "Recording covers the whole hold");

            // Replay from the same starting state
            actor.ResetPosition();
            Assert.AreEqual(0f, actorGo.transform.position.y, 0f);
            var replaySession = ReplaySession.BeginReplay(archivePath);
            Assert.IsNotNull(replaySession, "Replay session created");
            yield return WaitForSessionEnd(replaySession);
            Assert.AreEqual("pass", _lastReplayResult.Status,
                "Replay should pass (every per-frame hash identical). Divergent frame " + _lastReplayResult.FirstDivergentFrame +
                " provider " + _lastReplayResult.DivergentProviderId);
            Assert.AreEqual(-1, _lastReplayResult.FirstDivergentFrame);
            Assert.AreEqual(archive.Frames.Count, _lastReplayResult.Frames, "Every recorded frame hash was compared");

            // Verify identical position after replay
            float replayedY = actorGo.transform.position.y;
            Assert.AreEqual(recordedY, replayedY, 1e-4f, "Replayed position should match recorded position");

            TransformStateProvider.Instance.Untrack("actor");
            InputSystem.RemoveDevice(keyboard);
            Object.Destroy(asset);
            Object.Destroy(actorGo);
            Object.Destroy(hpGo);
        }

        [UnityTest]
        public IEnumerator NoInputFrames_ReplayMatches()
        {
            // Record 300 frames with no input events and assert identical hashes
            // AND zero input events in the trace.
            string runId = "test_fixture_noinput";
            string archivePath = GetArchivePath(runId);
            EnsureClean(archivePath);

            var hpGo = new GameObject("HP");
            var hp = hpGo.AddComponent<HpProvider>();
            yield return null;

            var options = new ReplayOptions
            {
                Seed = 99,
                RunId = runId,
                FixedDeltaTime = 1f / 60f,
                Strict = true,
            };
            var session = ReplaySession.BeginRecord(options);
            Assert.IsNotNull(session, "Record session created");

            yield return WaitForFrames(300);

            session.Stop();
            yield return null;
            yield return null;

            Assert.IsTrue(File.Exists(archivePath), "Archive written: " + archivePath);

            // Read archive and verify zero input events
            var archive = ReplayArchive.Read(archivePath);
            // Manifest.Events counts trace entries including the per-frame markers; count real input events.
            Assert.AreEqual(0, CountInputEvents(archive.InputTrace), "Zero input events (non frame-marker) in the trace");
            Assert.GreaterOrEqual(archive.Frames.Count, 300, "300 frames recorded");

            // Replay
            var replaySession = ReplaySession.BeginReplay(archivePath);
            Assert.IsNotNull(replaySession, "Replay session created");
            yield return WaitForSessionEnd(replaySession);
            Assert.AreEqual("pass", _lastReplayResult.Status, "Replay should pass");
            Assert.AreEqual(-1, _lastReplayResult.FirstDivergentFrame);
            Assert.AreEqual(archive.Frames.Count, _lastReplayResult.Frames, "Every recorded frame hash was compared");

            Object.Destroy(hpGo);
        }

        [UnityTest]
        public IEnumerator NonDeterministicProvider_Caught()
        {
            // Uses runtime toggle NonDeterministicProvider.Enabled instead of a scripting define.
            // Records with wall-clock data, replays without it -> comparator reports diverged
            // with provider id "game.nondeterministic".
            string runId = "test_fixture_nondet";
            string archivePath = GetArchivePath(runId);
            EnsureClean(archivePath);

            var ndGo = new GameObject("NonDet");
            var nd = ndGo.AddComponent<NonDeterministicProvider>();

            NonDeterministicProvider.Enabled = true;
            yield return null;

            Assert.IsTrue(ReplayRegistry.Instance.IsRegistered("game.nondeterministic"),
                "Non-deterministic provider should be registered when Enabled=true");

            var options = new ReplayOptions { Seed = 42, RunId = runId, FixedDeltaTime = 1f / 60f };
            var session = ReplaySession.BeginRecord(options);

            for (int i = 0; i < 300; i++)
                yield return null;

            session.Stop();
            yield return null;
            yield return null;

            NonDeterministicProvider.Enabled = false;

            var replaySession = ReplaySession.BeginReplay(archivePath);
            ReplayResult result = null;
            replaySession.Finished += r => result = r;

            while (result == null)
                yield return null;

            Assert.AreEqual("diverged", result.Status,
                "Non-deterministic provider should cause divergence");
            Assert.GreaterOrEqual(result.FirstDivergentFrame, 0,
                "Should have a divergent frame");
            Assert.AreEqual("game.nondeterministic", result.DivergentProviderId,
                "Divergent provider should be game.nondeterministic");

            Object.Destroy(ndGo);
        }

        [UnityTest]
        public IEnumerator InProcessVerify_ThroughRuntimeApi()
        {
            // Record a run, then verify in-process using ReplaySession.BeginReplay + ReplayArchive
            // — the same comparison LogMatchesCheckpoints uses, but without ReplayCommands.
            string runId = "test_fixture_inproc_verify";
            string archivePath = GetArchivePath(runId);
            EnsureClean(archivePath);

            var hpGo = new GameObject("HP");
            var hp = hpGo.AddComponent<HpProvider>();
            yield return null;

            var options = new ReplayOptions
            {
                Seed = 777,
                RunId = runId,
                FixedDeltaTime = 1f / 60f,
                Strict = true,
            };
            var session = ReplaySession.BeginRecord(options);
            yield return WaitForFrames(200);
            session.Stop();
            yield return null;
            yield return null;

            Assert.IsTrue(File.Exists(archivePath), "Archive written");

            // Read the archive to validate it round-trips
            var archive = ReplayArchive.Read(archivePath);
            Assert.AreEqual(1, archive.Header.Major, "Archive major version should be 1");
            Assert.AreEqual(runId, archive.Header.RunId, "RunId should match");
            Assert.Greater(archive.Frames.Count, 0, "Should have recorded frames");
            Assert.IsTrue(archive.Manifest.Complete, "Manifest should mark complete");

            // Replay in-process (same path LogMatchesCheckpoints uses)
            var replaySession = ReplaySession.BeginReplay(archivePath);
            Assert.IsNotNull(replaySession, "Replay session created");
            yield return WaitForSessionEnd(replaySession);
            Assert.AreEqual("pass", _lastReplayResult.Status,
                "In-process verify should pass. Got: " + _lastReplayResult.Status +
                " Divergent frame: " + _lastReplayResult.FirstDivergentFrame +
                " Provider: " + _lastReplayResult.DivergentProviderId);
            Assert.AreEqual(-1, _lastReplayResult.FirstDivergentFrame, "No divergent frame");
            Assert.AreEqual(archive.Frames.Count, _lastReplayResult.Frames, "Every recorded checkpoint compared");
            Assert.Greater(_lastReplayResult.Frames, 0);

            Object.Destroy(hpGo);
        }

        /// <summary>
        /// Loads the fixture scene, records 600 frames to a fixed path (Logs/harness/replay/verify_fresh_run/run.gdwreplay)
        /// so that a separate Unity process can verify it via ReplayVerificationTests.LogMatchesCheckpoints.
        /// </summary>
        [UnityTest]
        public IEnumerator RecordSceneRun_ForFreshProcessVerify()
        {
            string runId = "verify_fresh_run";
            string archivePath = GetArchivePath(runId);
            EnsureClean(archivePath);

            const string scenePath = "Assets/Scenes/ReplayFixture.unity";
            yield return LoadFixtureScene(scenePath);
            yield return null;
            yield return null;

            var options = new ReplayOptions
            {
                Seed = 12345,
                RunId = runId,
                FixedDeltaTime = 1f / 60f,
                ScenePath = scenePath,
                Strict = true,
            };
            var session = ReplaySession.BeginRecord(options);
            yield return WaitForFrames(600);
            session.Stop();
            yield return null;
            yield return null;

            Assert.IsTrue(File.Exists(archivePath), "Archive written: " + archivePath);
            var archive = ReplayArchive.Read(archivePath);
            Assert.AreEqual(scenePath, archive.Header.Scene.Path);
            Assert.GreaterOrEqual(archive.Frames.Count, 600);

            // Replay must start from the same scene state: reload the scene (the spinner has rotated during recording).
            yield return LoadFixtureScene(scenePath);
            yield return null;
            yield return null;

            // Also verify it in the same process so a failure here is distinguishable from a fresh-process failure.
            var replay = ReplaySession.BeginReplay(archivePath);
            yield return WaitForSessionEnd(replay);
            Assert.AreEqual("pass", _lastReplayResult.Status, Describe(_lastReplayResult));

            // Leave no scene providers registered for later tests.
            foreach (var root in SceneManager.GetActiveScene().GetRootGameObjects())
                Object.Destroy(root);
            yield return null;
            yield return null;
        }

        /// <summary>
        /// Capture smoke: records the fixture scene for 600 frames, reloads it, then replays it while writing one PNG
        /// per frame through the Editor PNG backend (Gdw.Replay.ReplayCapture, called by reflection so this assembly
        /// stays a PlayMode assembly). Output: Logs/harness/replay/capture_smoke/capture/frames/frame-%06d.png.
        /// </summary>
        [UnityTest]
        public IEnumerator CaptureSmoke_PngFramesFromReplay()
        {
#if UNITY_EDITOR
            string runId = "capture_smoke";
            string archivePath = GetArchivePath(runId);
            EnsureClean(archivePath);
            const string scenePath = "Assets/Scenes/ReplayFixture.unity";

            yield return LoadFixtureScene(scenePath);
            yield return null;
            yield return null;
            var rec = ReplaySession.BeginRecord(new ReplayOptions
            {
                Seed = 2024, RunId = runId, FixedDeltaTime = 1f / 60f, ScenePath = scenePath, Strict = true,
            });
            yield return WaitForFrames(600);
            rec.Stop();
            yield return null;
            yield return null;
            Assert.IsTrue(File.Exists(archivePath), "Archive written");

            yield return LoadFixtureScene(scenePath);
            yield return null;
            yield return null;

            var captureType = System.Type.GetType("Gdw.Replay.ReplayCapture, Gdw.Replay.Editor");
            Assert.IsNotNull(captureType, "ReplayCapture type (Gdw.Replay.Editor) must be loadable");
            var start = captureType.GetMethod("Start");
            var capture = captureType.GetMethod("CaptureFrame");
            var stop = captureType.GetMethod("Stop");
            string framesDir = Path.Combine(Path.GetDirectoryName(archivePath), "capture", "frames");
            if (Directory.Exists(framesDir)) Directory.Delete(framesDir, true);

            var replay = ReplaySession.BeginReplay(archivePath);
            ReplayResult result = null;
            replay.Finished += r => result = r;
            Assert.AreEqual("ok", (string)start.Invoke(null, new object[] { framesDir, 600, 60 }));
            int written = 0;
            float guard = 0f;
            while (result == null && written < 600 && guard < 120f)
            {
                string r = (string)capture.Invoke(null, null);
                Assert.AreEqual("ok", r, "CaptureFrame result");
                written++;
                guard += Time.unscaledDeltaTime;
                yield return null;
            }
            while (result == null && guard < 120f) { guard += 0.05f; yield return new WaitForSecondsRealtime(0.05f); }
            stop.Invoke(null, null);
            Assert.IsNotNull(result, "Replay finished");
            Assert.AreEqual("pass", result.Status, Describe(result));
            Assert.GreaterOrEqual(written, 590, "Frames captured");
            Assert.GreaterOrEqual(Directory.GetFiles(framesDir, "frame-*.png").Length, written, "PNG files on disk");
#else
            Assert.Ignore("Editor-only capture backend");
            yield break;
#endif
        }
    }
}
