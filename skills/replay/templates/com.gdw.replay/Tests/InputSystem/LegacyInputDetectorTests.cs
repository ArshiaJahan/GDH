#if UNITY_EDITOR
using System;
using System.IO;
using NUnit.Framework;

namespace Gdw.Replay.Tests
{
    /// <summary>Editor-time tests for the legacy Input Manager readiness scan.</summary>
    public class LegacyInputDetectorTests
    {
        string _root;

        [SetUp]
        public void SetUp()
        {
            _root = Path.Combine(Path.GetTempPath(), "gdw-replay-legacy", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(_root, "Assets", "Scripts"));
            Directory.CreateDirectory(Path.Combine(_root, "ProjectSettings"));
        }

        [TearDown]
        public void TearDown()
        {
            if (Directory.Exists(_root)) Directory.Delete(_root, true);
        }

        [Test]
        public void NamesFileAndCallForLegacyGameplay()
        {
            File.WriteAllText(Path.Combine(_root, "ProjectSettings", "ProjectSettings.asset"),
                "PlayerSettings:\n  activeInputHandler: 2\n");
            File.WriteAllText(Path.Combine(_root, "Assets", "Scripts", "Player.cs"),
                "using UnityEngine;\nclass Player { void Update() { float x = Input.GetAxis(\"Horizontal\"); } }\n");

            var report = LegacyInputDetector.ScanProject(_root);

            Assert.That(report.HasLegacyGameplay, Is.True);
            Assert.That(report.ActiveInputHandler, Is.EqualTo(2));
            Assert.That(report.Findings.Count, Is.EqualTo(1));
            Assert.That(report.Findings[0].File, Is.EqualTo("Assets/Scripts/Player.cs"));
            Assert.That(report.Findings[0].Line, Is.EqualTo(2));
            Assert.That(report.Findings[0].Call, Is.EqualTo("Input.GetAxis"));
            Assert.That(report.Message, Does.Contain("Assets/Scripts/Player.cs:2 Input.GetAxis"));
        }

        [Test]
        public void LegacyOnlyInputHandlerFailsEvenWithoutCalls()
        {
            File.WriteAllText(Path.Combine(_root, "ProjectSettings", "ProjectSettings.asset"),
                "PlayerSettings:\n  activeInputHandler: 0\n");

            var report = LegacyInputDetector.ScanProject(_root);

            Assert.That(report.HasLegacyGameplay, Is.True);
            Assert.That(report.Message, Does.Contain("legacy Input Manager"));
        }

        [Test]
        public void LegacyOnlyProjectIsRefusedWithFilesAndCalls()
        {
            File.WriteAllText(Path.Combine(_root, "ProjectSettings", "ProjectSettings.asset"),
                "PlayerSettings:\n  activeInputHandler: 0\n");
            File.WriteAllText(Path.Combine(_root, "Assets", "Scripts", "Player.cs"),
                "using UnityEngine;\nclass Player { void Update() { float x = Input.GetAxis(\"Horizontal\"); } }\n");

            string refusal = LegacyInputDetector.RefusalMessage(LegacyInputDetector.ScanProject(_root));

            Assert.That(refusal, Is.Not.Null);
            Assert.That(refusal, Does.Contain("refused"));
            Assert.That(refusal, Does.Contain("Assets/Scripts/Player.cs:2 Input.GetAxis"));
        }

        [Test]
        public void InputSystemOnlyProjectIsNotRefused()
        {
            File.WriteAllText(Path.Combine(_root, "ProjectSettings", "ProjectSettings.asset"),
                "PlayerSettings:\n  activeInputHandler: 1\n");
            Assert.That(LegacyInputDetector.RefusalMessage(LegacyInputDetector.ScanProject(_root)), Is.Null);
        }

        [Test]
        public void InputSystemOnlyProjectIsReady()
        {
            File.WriteAllText(Path.Combine(_root, "ProjectSettings", "ProjectSettings.asset"),
                "PlayerSettings:\n  activeInputHandler: 1\n");
            File.WriteAllText(Path.Combine(_root, "Assets", "Scripts", "Player.cs"),
                "using UnityEngine.InputSystem;\nclass Player { void Update() { var k = Keyboard.current; } }\n");

            var report = LegacyInputDetector.ScanProject(_root);

            Assert.That(report.HasLegacyGameplay, Is.False);
            Assert.That(report.Message, Is.Empty);
        }

        [Test]
        public void LegacyBlockCompiledOutForInputSystemOnlyProjectIsIgnored()
        {
            File.WriteAllText(Path.Combine(_root, "ProjectSettings", "ProjectSettings.asset"),
                "PlayerSettings:\n  activeInputHandler: 1\n");
            File.WriteAllText(Path.Combine(_root, "Assets", "Scripts", "Player.cs"),
                "using UnityEngine;\nclass Player {\n#if ENABLE_LEGACY_INPUT_MANAGER\n" +
                "void Update() { float x = Input.GetAxis(\"Horizontal\"); }\n#endif\n}\n");

            var report = LegacyInputDetector.ScanProject(_root);

            Assert.That(report.HasLegacyGameplay, Is.False);
            Assert.That(report.Findings, Is.Empty);
        }
    }
}
#endif
