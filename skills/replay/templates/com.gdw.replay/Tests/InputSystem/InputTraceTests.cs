using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;

namespace Gdw.Replay.Tests
{
    /// <summary>
    /// PlayMode tests for <see cref="InputTraceAdapter"/> using the Input System test fixture: record a key
    /// sequence, replay it one frame at a time and compare action callbacks per frame, exercise the bounded
    /// buffer, and verify that settings and devices are restored on teardown.
    /// </summary>
    public class InputTraceTests : InputTestFixture
    {
        string _dir;
        Keyboard _keyboard;
        InputAction _action;
        readonly List<string> _callbacks = new List<string>();
        int _frame;

        public override void Setup()
        {
            base.Setup();
            _dir = Path.Combine(Path.GetTempPath(), "gdw-replay-input", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_dir);
            _keyboard = InputSystem.AddDevice<Keyboard>();
            _action = new InputAction("a", InputActionType.Button, "<Keyboard>/a");
            _action.performed += OnPerformed;
            _action.canceled += OnCanceled;
        }

        public override void TearDown()
        {
            if (_action != null)
            {
                _action.Disable();
                _action.Dispose();
                _action = null;
            }
            if (Directory.Exists(_dir)) Directory.Delete(_dir, true);
            base.TearDown();
        }

        void OnPerformed(InputAction.CallbackContext context) => _callbacks.Add(_frame + ":performed");

        void OnCanceled(InputAction.CallbackContext context) => _callbacks.Add(_frame + ":canceled");

        [Test]
        public void CapturedKeyPressesReplayWithSameActionCallbacksPerFrame()
        {
            var record = new InputTraceAdapter(_dir, 4);
            record.StartCapture();
            _action.Enable();

            _callbacks.Clear();
            for (int frame = 0; frame < 24; frame++)
            {
                _frame = frame;
                bool down = (frame / 3) % 2 == 0;
                InputSystem.QueueStateEvent(_keyboard,
                    down ? new KeyboardState(Key.A) : new KeyboardState());
                record.ProcessInputUpdate();
            }
            _action.Disable();

            var recordedCallbacks = new List<string>(_callbacks);
            long recordedEvents = record.EventCount;
            Assert.That(record.Overflowed, Is.False, "the bounded buffer must not overflow in a 24-frame run");
            Assert.That(recordedEvents, Is.GreaterThanOrEqualTo(24L), "at least the state event of every frame");
            record.Dispose();

            Assert.That(File.Exists(Path.Combine(_dir, InputTraceAdapter.TraceFileName)), Is.True,
                "recording must write input.inputtrace");

            // Clear physical state and action bookkeeping before replay.
            InputSystem.QueueStateEvent(_keyboard, new KeyboardState());
            InputSystem.Update();
            _callbacks.Clear();

            var replay = new InputTraceAdapter(_dir, 4);
            replay.StartReplay();
            _action.Enable();
            for (int frame = 0; frame < 24; frame++)
            {
                _frame = frame;
                replay.ProcessInputUpdate();
            }
            _action.Disable();

            Assert.That(_callbacks, Is.EqualTo(recordedCallbacks),
                "the same actions must perform and cancel on the same replay frames");
            Assert.That(replay.EventCount, Is.EqualTo(recordedEvents),
                "replay must deliver the whole recorded trace");
            replay.Dispose();
        }

        [Test]
        public void BufferOverflowIsReported()
        {
            string runDir = Path.Combine(_dir, "overflow");
            var adapter = new InputTraceAdapter(runDir, 1);
            adapter.StartCapture();
            _action.Enable();

            for (int frame = 0; frame < 40 && !adapter.Overflowed; frame++)
            {
                for (int i = 0; i < 2000; i++)
                {
                    InputSystem.QueueStateEvent(_keyboard,
                        i % 2 == 0 ? new KeyboardState(Key.A) : new KeyboardState());
                }
                adapter.ProcessInputUpdate();
            }
            _action.Disable();

            Assert.That(adapter.Overflowed, Is.True, "a full 1 MiB trace buffer must report overflow");
            Assert.That(adapter.EventCount, Is.GreaterThan(0L));
            adapter.Dispose();
        }

        [Test]
        public void DisposeRestoresInputSettings()
        {
            var settings = InputSystem.settings;
            var originalMode = settings.updateMode;
            var originalBackground = settings.backgroundBehavior;
            settings.updateMode = InputSettings.UpdateMode.ProcessEventsInDynamicUpdate;

            string runDir = Path.Combine(_dir, "settings");
            var capture = new InputTraceAdapter(runDir, 1);
            capture.StartCapture();
            Assert.That(settings.updateMode, Is.EqualTo(InputSettings.UpdateMode.ProcessEventsManually),
                "capture must run manual input updates");
            Assert.That(settings.backgroundBehavior, Is.EqualTo(InputSettings.BackgroundBehavior.IgnoreFocus));
            capture.ProcessInputUpdate();
            capture.Dispose();

            Assert.That(settings.updateMode, Is.EqualTo(InputSettings.UpdateMode.ProcessEventsInDynamicUpdate),
                "capture teardown must restore updateMode");
            Assert.That(settings.backgroundBehavior, Is.EqualTo(originalBackground));

            settings.updateMode = InputSettings.UpdateMode.ProcessEventsInDynamicUpdate;
            var replay = new InputTraceAdapter(runDir, 1);
            replay.StartReplay();
            Assert.That(settings.updateMode, Is.EqualTo(InputSettings.UpdateMode.ProcessEventsManually),
                "replay must run manual input updates");
            replay.ProcessInputUpdate();
            replay.Dispose();

            Assert.That(settings.updateMode, Is.EqualTo(InputSettings.UpdateMode.ProcessEventsInDynamicUpdate),
                "replay teardown must restore updateMode");

            settings.updateMode = originalMode;
        }
    }
}
