using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
#if UNITY_EDITOR
using UnityEditor;
#endif
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace Gdw.Replay.Tests
{
    /// <summary>
    /// Generic replay verification test. Reads request.json (from -gdwReplayRequest CLI arg or
    /// EditorPrefs), validates compatibility, loads the scene, replays to the recorded end,
    /// compares every checkpoint, asserts zero unexpected console errors, and always restores state.
    ///
    /// This is the single [UnityTest] entry point referenced by the batch CLI:
    ///   unity test &lt;fixture&gt; --mode PlayMode --filter Gdw.Replay.Tests.ReplayVerificationTests.LogMatchesCheckpoints
    /// </summary>
    public class ReplayVerificationTests
    {
        static string RequestPath
        {
            get
            {
                string[] args = Environment.GetCommandLineArgs();
                for (int i = 0; i < args.Length - 1; i++)
                {
                    if (string.Equals(args[i], "-gdwReplayRequest", StringComparison.OrdinalIgnoreCase))
                        return args[i + 1];
                }
                #if UNITY_EDITOR
                return EditorPrefs.GetString("Gdw.Replay.Editor.RequestPath", null);
#else
                return null;
#endif
            }
        }

        [UnityTest]
        public IEnumerator LogMatchesCheckpoints()
        {
            // --- Setup ---
            string requestPath = RequestPath;
            if (string.IsNullOrEmpty(requestPath))
            {
                Assert.Ignore("No -gdwReplayRequest argument or EditorPrefs request path: nothing to verify (expected in ad-hoc runs)");
            }
            if (!File.Exists(requestPath))
            {
                Assert.Fail("request.json not found: " + requestPath);
            }

            ReplayRequest request = null;
            try
            {
                request = ReplayContracts.ReadRequest(requestPath);
            }
            catch (Exception e)
            {
                Assert.Fail("Failed to parse request.json: " + e.Message);
            }

            Assert.AreEqual("gdw.replay.request/1", request.Schema, "Schema mismatch");
            Assert.IsNotNull(request.RunId, "run_id required");
            Assert.IsNotEmpty(request.RunId, "run_id required");
            Assert.IsNotNull(request.ReplayPath, "replay_path required");
            Assert.IsNotEmpty(request.ReplayPath, "replay_path required");
            Assert.That(File.Exists(request.ReplayPath), "Archive not found: " + request.ReplayPath);

            // --- Validate compatibility ---
            ReplayArchive archive = null;
            try
            {
                archive = ReplayArchive.Read(request.ReplayPath);
            }
            catch (Exception e)
            {
                Assert.Fail("Failed to read archive: " + e.Message);
            }

            Assert.AreEqual(1, archive.Header.Major, "Incompatible archive major version");

            // --- Load scene ---
            string scenePath = request.Scene ?? archive.Header.Scene?.Path;
            if (!string.IsNullOrEmpty(scenePath))
            {
#if UNITY_EDITOR
                if (SceneUtility.GetBuildIndexByScenePath(scenePath) < 0)
                    yield return UnityEditor.SceneManagement.EditorSceneManager.LoadSceneAsyncInPlayMode(
                        scenePath, new LoadSceneParameters(LoadSceneMode.Single));
                else
#endif
                    yield return SceneManager.LoadSceneAsync(scenePath, LoadSceneMode.Single);
                yield return null; // let Awake/Start run
                yield return null;
            }

            // --- Begin replay ---
            ReplaySession session = null;
            try
            {
                session = ReplaySession.BeginReplay(request.ReplayPath);
            }
            catch (Exception e)
            {
                Assert.Fail("BeginReplay failed: " + e.Message);
            }

            Assert.IsNotNull(session, "Session should be created");

            // --- Wait for completion ---
            ReplayResult result = null;
            session.Finished += r => result = r;

            float timeout = 120f;
            float elapsed = 0f;
            while (result == null && elapsed < timeout)
            {
                yield return new WaitForSecondsRealtime(0.1f);
                elapsed += 0.1f;
            }

            // --- Assert results ---
            Assert.IsNotNull(result, "Replay did not finish within timeout");

            Assert.AreEqual("pass", result.Status,
                "Replay status should be 'pass'. Got: " + result.Status +
                " Divergent frame: " + result.FirstDivergentFrame +
                " Provider: " + result.DivergentProviderId +
                " Expected: " + result.ExpectedHash +
                " Actual: " + result.ActualHash +
                " Message: " + result.Message);

            Assert.Greater(result.Frames, 0, "Should have replayed frames");
            Assert.AreEqual(-1, result.FirstDivergentFrame,
                "Should have no divergent frame. Got: " + result.FirstDivergentFrame);

            // --- Assert zero unexpected console errors ---
            // (Unity's test framework captures logs; LogAssert is used per-test)
            // We verify no errors were logged during replay.
            LogAssert.NoUnexpectedReceived();

            // --- Cleanup ---
            // ReplaySession.OnLoopFinished destroys the GameObject, restoring settings.
            // If result is still set, the session is already cleaned up.
        }
    }
}
