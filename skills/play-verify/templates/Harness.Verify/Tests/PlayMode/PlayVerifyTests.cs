using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;
#if HARNESS_INPUTSYSTEM
using UnityEngine.InputSystem;
#endif

namespace Harness.Verify.Tests
{
    /// <summary>
    /// PlayMode test template for the headless play-verify path (batchmode -runTests -testPlatform PlayMode,
    /// or MCP run_tests(mode="PlayMode")). Copy GameScene_MeetsAcceptanceCriteria per scene/criterion set and
    /// edit ScenePath, WarmupSeconds, the input script and the asserts. Test names are the evidence in VERIFY.md.
    /// Any Debug.LogError / exception during a test fails it (Test Framework LogAssert default), so the
    /// "0 console errors" criterion is enforced for free; do not add LogAssert.ignoreFailingMessages.
    /// </summary>
    public class PlayVerifyTests
    {
        // ---- edit these for your game -------------------------------------------------------------
        const string ScenePath = "Assets/Scenes/Game.unity";   // loaded without Build Settings (Editor only)
        const float WarmupSeconds = 2f;                         // let generation/spawn finish
        const string InputScript = "wait 0.5; probe";           // ScriptedInput commands, see ScriptedInput.cs
        const float ScriptTimeout = 30f;
        // --------------------------------------------------------------------------------------------

        [UnityTest, Category("PlayVerify")]
        public IEnumerator GameScene_MeetsAcceptanceCriteria()
        {
            VerifyProbe.ResetAll();          // before loading: values/counters otherwise survive from earlier tests
#if UNITY_EDITOR
            if (UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEditor.SceneAsset>(ScenePath) == null)
                Assert.Ignore("Scene not found: " + ScenePath + " (edit ScenePath in PlayVerifyTests)");
            yield return UnityEditor.SceneManagement.EditorSceneManager.LoadSceneAsyncInPlayMode(
                ScenePath, new LoadSceneParameters(LoadSceneMode.Single));
#else
            yield return SceneManager.LoadSceneAsync(System.IO.Path.GetFileNameWithoutExtension(ScenePath));
#endif
            var probe = VerifyProbe.Instance;               // finds the scene's probe or creates one
            Assert.IsNotNull(probe);
            yield return new WaitForSeconds(WarmupSeconds);

            ScriptedInput.Run(InputScript);
            float deadline = Time.realtimeSinceStartup + ScriptTimeout;
            while (!ScriptedInput.Done && Time.realtimeSinceStartup < deadline) yield return null;
            Assert.IsTrue(ScriptedInput.Done, "input script did not finish in " + ScriptTimeout + " s");
            Assert.IsFalse(ScriptedInput.Failed, "input script failed (see [VERIFY] script.failed line)");

            VerifyProbe.DumpAll();
            Assert.AreEqual(0, VerifyProbe.ErrorCount, "errors/exceptions were logged during the run");
            // Criterion examples (keys come from VerifyProbe.Set/Register/watches in your game):
            // Assert.AreEqual(100f, VerifyProbe.GetFloat("player.hp"), "AC-1 player starts at full HP");
            // Assert.GreaterOrEqual(VerifyProbe.GetFloat("rooms"), 5f, "AC-2 dungeon has >= 5 rooms");
            // Assert.GreaterOrEqual(VerifyProbe.GetFloat("fps"), 30f, "AC-9 fps >= 30 (meaningless with -nographics)");
        }

    }

    /// <summary>Self-tests of the harness itself (no scene needed, fast). Keep them: they prove the probe,
    /// the script runner and the virtual keyboard work in this project.</summary>
    public class HarnessSelfTests
    {
        GameObject m_Target;

        [SetUp]
        public void SetUp()
        {
            VerifyProbe.ResetAll();
            m_Target = new GameObject("VerifyTarget");
            m_Target.SetActive(false);                       // so VerifyProbe.Awake sees the watches
            m_Target.AddComponent<VerifyTestStub>();
            var probe = m_Target.AddComponent<VerifyProbe>();
            probe.interval = 0f;
            probe.dontDestroyOnLoad = false;
            probe.watches.Add("player.hp=VerifyTarget:VerifyTestStub.current");
            m_Target.SetActive(true);
        }

        [UnityTearDown]
        public IEnumerator TearDown()
        {
            if (ScriptedInput.Current != null) Object.Destroy(ScriptedInput.Current.gameObject);
            Object.Destroy(m_Target);
            yield return null;                               // Destroy is deferred: let it happen before the next test
        }

        [UnityTest]
        public IEnumerator Probe_ReportsWatchedSetAndRegisteredValues()
        {
            yield return null;
            Assert.AreEqual(100f, VerifyProbe.GetFloat("player.hp"));
            m_Target.GetComponent<VerifyTestStub>().current = 40;
            VerifyProbe.Set("rooms", 7);
            VerifyProbe.Register("alive", () => true);
            yield return null;
            Assert.AreEqual(40f, VerifyProbe.GetFloat("player.hp"));
            Assert.AreEqual(7f, VerifyProbe.GetFloat("rooms"));
            Assert.AreEqual(1f, VerifyProbe.GetFloat("alive"));
            StringAssert.Contains("player.hp=40", VerifyProbe.DumpAll());
            VerifyProbe.Unregister("alive");
        }

        [UnityTest]
        public IEnumerator ScriptedInput_SendsMessagesAndWaitsForProbeValues()
        {
            ScriptedInput.Run("send VerifyTarget Damage 30; until player.hp <= 70 2; mark hit; probe");
            float deadline = Time.realtimeSinceStartup + 5f;
            while (!ScriptedInput.Done && Time.realtimeSinceStartup < deadline) yield return null;
            Assert.IsTrue(ScriptedInput.Done);
            Assert.IsFalse(ScriptedInput.Failed);
            Assert.AreEqual(70f, VerifyProbe.GetFloat("player.hp"));
            Assert.AreEqual(0, VerifyProbe.ErrorCount);
        }

#if HARNESS_INPUTSYSTEM
        [UnityTest]
        public IEnumerator ScriptedInput_PressesVirtualKeys()
        {
            int performed = 0;
            var action = new InputAction("jump", InputActionType.Button, "<Keyboard>/space");
            action.performed += _ => performed++;
            action.Enable();
            try
            {
                ScriptedInput.Run("tap Space 3; frames 5");
                float deadline = Time.realtimeSinceStartup + 5f;
                while (!ScriptedInput.Done && Time.realtimeSinceStartup < deadline) yield return null;
                Assert.IsFalse(ScriptedInput.Failed);
                Assert.GreaterOrEqual(performed, 1, "virtual Space press did not reach the InputAction");
            }
            finally
            {
                action.Disable();
                action.Dispose();
                VirtualKeyboard.Restore();
            }
        }
#endif
    }
}
