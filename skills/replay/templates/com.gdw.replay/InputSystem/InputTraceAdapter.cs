using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;
using UnityEngine.InputSystem.Users;

namespace Gdw.Replay
{
    /// <summary>
    /// Records and replays gameplay input with the Input System's <see cref="InputEventTrace"/>.
    ///
    /// Recording and replay both run the Input System in <see cref="InputSettings.UpdateMode.ProcessEventsManually"/>:
    /// <see cref="ProcessInputUpdate"/> is the single controlled input update for a replay frame and is what
    /// ReplayLoop invokes from its EarlyUpdate hook. Frame markers are recorded so ReplayController can pace one
    /// recorded frame per input update. The trace is written to <c>input.inputtrace</c> in the run directory.
    ///
    /// Replay maps every recorded device to a fresh, non-native device, disables native (physical) devices,
    /// suppresses PlayerInput auto-switching, pairs each PlayerInput with the virtual device of the same layout,
    /// and restores devices, pairing, settings and hooks on <see cref="Dispose"/>.
    /// </summary>
    public sealed class InputTraceAdapter : IDisposable, IReplayStateProvider, IReplayInputAdapter
    {
        /// <summary>Framework provider id for the input trace (contracts §4).</summary>
        public const string ProviderId = "unity.input";

        /// <summary>Archive member / run directory file name for the native trace.</summary>
        public const string TraceFileName = "input.inputtrace";

        enum Mode { None, Recording, Replaying }

        readonly string _runDirectory;
        readonly string _tracePath;
        readonly long _maxTraceBytes;

        Mode _mode = Mode.None;
        bool _disposed;

        InputEventTrace _trace;
        InputEventTrace.ReplayController _controller;
        byte[] _pendingTraceBytes;
        byte[] _loadedTraceBytes;
        string _loadedTraceSha256 = "";
        double _recordedFirstEventTime;
        double _replayBaseTime;

        int _frameEventStart;
        int _frameEventCount;
        long _eventsDelivered;
        long _framesProcessed;
        bool _hasOldestEventTime;
        double _oldestEventTime;

        InputSettings _settings;
        InputSettings.UpdateMode _savedUpdateMode;
        InputSettings.BackgroundBehavior _savedBackgroundBehavior;
#if UNITY_EDITOR
        InputSettings.EditorInputBehaviorInPlayMode _savedEditorBehavior;
#endif

        readonly List<InputDevice> _disabledDevices = new List<InputDevice>();
        readonly List<PlayerInputState> _playerInputs = new List<PlayerInputState>();
        bool _pairedPlayerInputs;

        Action _loopInputUpdate;
        Func<FrameInputInfo> _loopInputInfo;
        Action _previousLoopInputUpdate;
        Func<FrameInputInfo> _previousLoopInputInfo;

        /// <summary>Creates an adapter for one run directory. The trace is <c>&lt;runDirectory&gt;/input.inputtrace</c>.</summary>
        public InputTraceAdapter(string runDirectory, int maxTraceMb = 256)
        {
            if (string.IsNullOrEmpty(runDirectory)) throw new ArgumentException("run directory is required", nameof(runDirectory));
            if (maxTraceMb < 1 || maxTraceMb > 4096)
                throw new ArgumentOutOfRangeException(nameof(maxTraceMb), "maxTraceMb must be between 1 and 4096");

            _runDirectory = runDirectory;
            _tracePath = Path.Combine(runDirectory, TraceFileName);
            _maxTraceBytes = (long)maxTraceMb * 1024L * 1024L;
        }

        /// <inheritdoc />
        public string Id => ProviderId;

        /// <summary>Directory that holds the trace file.</summary>
        public string RunDirectory => _runDirectory;

        /// <summary>Path of the native trace written by recording / loaded by replay.</summary>
        public string TracePath => _tracePath;

        /// <summary>Number of trace events delivered so far (record or replay). Includes frame markers.</summary>
        public long EventCount => _eventsDelivered;

        /// <summary>Number of replay frames pumped through this adapter.</summary>
        public long Frames => _framesProcessed;

        /// <summary>Trace event ordinal at the start of the last pumped frame.</summary>
        public int FrameEventStart => _frameEventStart;

        /// <summary>Number of trace events in the last pumped frame.</summary>
        public int FrameEventCount => _frameEventCount;

        /// <summary>
        /// True when the bounded trace buffer filled (or the oldest event changed) during recording.
        /// Overflow invalidates verification; the caller must not finalise the run as a pass.
        /// </summary>
        public bool Overflowed { get; private set; }

        public bool IsCapturing => _mode == Mode.Recording;
        public bool IsReplaying => _mode == Mode.Replaying;

        /// <summary>
        /// Replay rejects Hold/Tap/SlowTap/MultiTap interactions when true. Defaults to true because
        /// action timing is driven by Input System update time, which manual replay updates cannot pin to the
        /// recorded timeline. Set false only after the pinned 1.20.1 fixture proves timed interactions replay
        /// identically.
        /// </summary>
        public bool StrictTimedInteractions { get; set; } = true;

        /// <summary>
        /// Preserve recorded event time deltas when feeding replay events: each event keeps its offset from the
        /// first recorded event, rebased onto the replay start time. Frame spacing still comes from frame markers.
        /// </summary>
        public bool PreserveEventTiming { get; set; } = true;

        /// <summary>SHA-256 of the trace bytes loaded for replay (empty while recording).</summary>
        public string LoadedTraceSha256 => _loadedTraceSha256;

        /// <summary>True once ReplayController reports that the trace is exhausted.</summary>
        public bool ReplayFinished { get; private set; }

        /// <summary>Supplies trace bytes when the caller already extracted them from an archive.</summary>
        public void SetTrace(byte[] traceBytes)
        {
            if (_mode != Mode.None) throw new ReplayStateException("cannot replace the trace while the adapter is active");
            _pendingTraceBytes = traceBytes == null ? null : (byte[])traceBytes.Clone();
        }

        /// <summary>Returns the trace bytes for the archive: recorded file, supplied bytes, or loaded bytes.</summary>
        public byte[] GetTraceBytes()
        {
            if (_pendingTraceBytes != null) return (byte[])_pendingTraceBytes.Clone();
            if (_loadedTraceBytes != null) return (byte[])_loadedTraceBytes.Clone();
            if (File.Exists(_tracePath)) return File.ReadAllBytes(_tracePath);
            return new byte[0];
        }

        /// <summary>Starts bounded recording. <see cref="ProcessInputUpdate"/> must be called once per frame.</summary>
        public void StartCapture()
        {
            ThrowIfDisposedOrActive("capture");
            if (Overflowed) throw new ReplayStateException("input trace already overflowed");
            Directory.CreateDirectory(_runDirectory);

            SaveAndApplySettings();

            try
            {
                _trace = new InputEventTrace(_maxTraceBytes, growBuffer: false)
                {
                    recordFrameMarkers = true,
                    onFilterEvent = FilterRecordedEvent,
                };
                _trace.Enable();
            }
            catch
            {
                if (_trace != null)
                {
                    _trace.Dispose();
                    _trace = null;
                }
                RestoreSettings();
                throw;
            }

            _mode = Mode.Recording;
            ResetCounters();
            ReplayRegistry.Instance.Register(Id, this);
            InstallLoopHooks();
        }

        /// <summary>
        /// Starts replay of <see cref="TracePath"/> (or the bytes supplied with <see cref="SetTrace"/>).
        /// <see cref="ProcessInputUpdate"/> must be called once per frame.
        /// </summary>
        public void StartReplay()
        {
            ThrowIfDisposedOrActive("replay");

            byte[] traceBytes = _pendingTraceBytes ?? (File.Exists(_tracePath) ? File.ReadAllBytes(_tracePath) : null);
            if (traceBytes == null) throw new ReplayStateException("input trace not found: " + _tracePath);
            if (traceBytes.Length == 0) throw new ReplayStateException("input trace is empty: " + _tracePath);

            if (StrictTimedInteractions) RejectTimedInteractions();

            _loadedTraceBytes = traceBytes;
            _loadedTraceSha256 = Digest.Sha256Hex(traceBytes);
            ResetCounters();
            ReplayFinished = false;

            try
            {
                using (var stream = new MemoryStream(traceBytes, false))
                    _trace = InputEventTrace.LoadFrom(stream);
            }
            catch (Exception e)
            {
                throw new ReplayCompatibilityException("invalid input trace: " + e.Message, e);
            }

            _recordedFirstEventTime = FirstEventTime(_trace);
            _replayBaseTime = Time.realtimeSinceStartupAsDouble;

            SaveAndApplySettings();
            DisableNativeDevices();

            try
            {
                // A run with no input still has frames; there is simply nothing to replay.
                if (_trace.eventCount > 0)
                {
                    _controller = _trace.Replay().WithAllDevicesMappedToNewInstances();
                    _controller.OnEvent(RetimestampReplayEvent);
                    _controller.OnFinished(OnReplayFinished);
                    _controller.PlayAllFramesOneByOne();
                }
                else
                {
                    ReplayFinished = true;
                }
            }
            catch
            {
                _controller?.Dispose();
                _controller = null;
                RestoreDevices();
                RestoreSettings();
                _trace?.Dispose();
                _trace = null;
                throw;
            }

            _mode = Mode.Replaying;
            ReplayRegistry.Instance.Register(Id, this);
            InstallLoopHooks();
        }

        /// <summary>
        /// Issues exactly one Input System update for the current replay frame and records the trace event range.
        /// This is the method ReplayLoop calls from its EarlyUpdate hook.
        /// </summary>
        public void ProcessInputUpdate()
        {
            if (_disposed) throw new ReplayStateException("input trace adapter is disposed");

            if (_mode == Mode.Recording)
            {
                long before = _trace.eventCount;
                InputSystem.Update();
                long after = _trace.eventCount;
                SetFrameInfo(before, after - before);
                _framesProcessed++;
                DetectOverflow();
                return;
            }

            if (_mode == Mode.Replaying)
            {
                SuppressPhysicalDevices();
                EnsurePlayerInputPairing();
                int before = _controller != null ? _controller.position : 0;
                InputSystem.Update();
                int after = _controller != null ? _controller.position : 0;
                SetFrameInfo(before, after - before);
                _framesProcessed++;
                return;
            }

            throw new ReplayStateException("input trace adapter is not capturing or replaying");
        }

        /// <summary>Stops recording and atomically writes the trace file. Safe to call more than once.</summary>
        public void StopCapture()
        {
            if (_mode != Mode.Recording) return;
            _trace.Disable();
            WriteTraceFile();
            _mode = Mode.None;
        }

        /// <summary>Writes event count, frame count and the trace digest field for canonical state hashing.</summary>
        public void WriteState(StateWriter writer)
        {
            if (writer == null) throw new ArgumentNullException(nameof(writer));
            writer.WriteUInt64("events", (ulong)_eventsDelivered);
            writer.WriteUInt64("frames", (ulong)_framesProcessed);
            // The recording's final trace digest is only known after its last frame, while frame hashes are
            // produced during the run. Leave this field empty in both modes so record and replay hashes agree;
            // the archive header/manifest carry the real digest.
            writer.WriteString("trace_sha256", "");
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            if (_mode == Mode.Recording)
            {
                try { StopCapture(); }
                catch (Exception e) { Debug.LogWarning("[Gdw.Replay] failed to stop input capture: " + e.Message); }
            }

            if (_controller != null)
            {
                try { _controller.Dispose(); }
                catch (Exception e) { Debug.LogWarning("[Gdw.Replay] failed to dispose replay controller: " + e.Message); }
                _controller = null;
            }

            RestorePlayerInputs();
            RestoreDevices();
            RestoreSettings();
            RemoveLoopHooks();

            if (ReplayRegistry.Instance.IsRegistered(Id)) ReplayRegistry.Instance.Unregister(Id);

            if (_trace != null)
            {
                try { _trace.Dispose(); }
                catch (Exception e) { Debug.LogWarning("[Gdw.Replay] failed to dispose input trace: " + e.Message); }
                _trace = null;
            }

            _mode = Mode.None;
        }

        // ---------------------------------------------------------------- lifecycle helpers

        void ThrowIfDisposedOrActive(string what)
        {
            if (_disposed) throw new ReplayStateException("input trace adapter is disposed");
            if (_mode != Mode.None) throw new ReplayStateException("input trace adapter is already active; cannot start " + what);
            if (_trace != null) throw new ReplayStateException("input trace adapter still holds a trace");
        }

        void ResetCounters()
        {
            Overflowed = false;
            _frameEventStart = 0;
            _frameEventCount = 0;
            _eventsDelivered = 0;
            _framesProcessed = 0;
            _hasOldestEventTime = false;
            _oldestEventTime = 0;
            _pairedPlayerInputs = false;
            _playerInputs.Clear();
            _disabledDevices.Clear();
        }

        void SetFrameInfo(long eventStart, long eventCount)
        {
            if (eventStart < 0) eventStart = 0;
            if (eventCount < 0) eventCount = 0;
            _frameEventStart = (int)Math.Min(eventStart, int.MaxValue);
            _frameEventCount = (int)Math.Min(eventCount, int.MaxValue);
            _eventsDelivered += eventCount;
        }

        void SaveAndApplySettings()
        {
            _settings = InputSystem.settings;
            _savedUpdateMode = _settings.updateMode;
            _savedBackgroundBehavior = _settings.backgroundBehavior;
#if UNITY_EDITOR
            _savedEditorBehavior = _settings.editorInputBehaviorInPlayMode;
            _settings.editorInputBehaviorInPlayMode =
                InputSettings.EditorInputBehaviorInPlayMode.AllDeviceInputAlwaysGoesToGameView;
#endif
            _settings.backgroundBehavior = InputSettings.BackgroundBehavior.IgnoreFocus;
            _settings.updateMode = InputSettings.UpdateMode.ProcessEventsManually;
        }

        void RestoreSettings()
        {
            if (_settings == null) return;
            try
            {
                _settings.updateMode = _savedUpdateMode;
                _settings.backgroundBehavior = _savedBackgroundBehavior;
#if UNITY_EDITOR
                _settings.editorInputBehaviorInPlayMode = _savedEditorBehavior;
#endif
            }
            catch (Exception e)
            {
                Debug.LogWarning("[Gdw.Replay] failed to restore Input System settings: " + e.Message);
            }
        }

        void InstallLoopHooks()
        {
            _previousLoopInputUpdate = ReplayLoop.InputUpdate;
            _previousLoopInputInfo = ReplayLoop.InputInfo;

            _loopInputUpdate = OnLoopInputUpdate;
            _loopInputInfo = CurrentFrameInfo;
            ReplayLoop.InputUpdate = _loopInputUpdate;
            ReplayLoop.InputInfo = _loopInputInfo;
        }

        void RemoveLoopHooks()
        {
            if (_loopInputUpdate != null && ReplayLoop.InputUpdate == _loopInputUpdate)
                ReplayLoop.InputUpdate = _previousLoopInputUpdate;
            if (_loopInputInfo != null && ReplayLoop.InputInfo == _loopInputInfo)
                ReplayLoop.InputInfo = _previousLoopInputInfo;
            _loopInputUpdate = null;
            _loopInputInfo = null;
            _previousLoopInputUpdate = null;
            _previousLoopInputInfo = null;
        }

        /// <summary>ReplayLoop hook: tolerates StopCapture happening before the loop is finished.</summary>
        void OnLoopInputUpdate()
        {
            if (_mode == Mode.Recording || _mode == Mode.Replaying) ProcessInputUpdate();
        }

        FrameInputInfo CurrentFrameInfo()
        {
            return new FrameInputInfo
            {
                InputUpdate = true,
                EventStart = _frameEventStart,
                EventCount = _frameEventCount,
            };
        }

        // ---------------------------------------------------------------- recording

        bool FilterRecordedEvent(InputEventPtr eventPtr, InputDevice device)
        {
            if (!eventPtr.valid) return false;
            if (eventPtr.type == InputEventTrace.FrameMarkerEvent) return true;
            if (device == null || !device.added) return false;
            // Keep only state transitions; text/IME and other event kinds are outside the v1 replay contract.
            int eventType = (int)eventPtr.type;
            if (eventType != StateEvent.Type && eventType != DeltaStateEvent.Type) return false;
            // Never record the synthetic devices the replay controller creates.
            if (IsSyntheticDevice(device)) return false;
            return true;
        }

        static bool IsSyntheticDevice(InputDevice device)
        {
            if (device == null) return true;
            if (device.native) return false;
            string name = device.name;
            return name != null && name.StartsWith("GdwReplay", StringComparison.Ordinal);
        }

        void DetectOverflow()
        {
            if (Overflowed || _trace == null) return;

            // The InputEventTrace circular buffer may have unusable trailing bytes
            // (alignment padding), so totalEventSizeInBytes can be slightly less than
            // allocatedSizeInBytes even when the buffer has wrapped.  Use a 10 % margin.
            bool full = _trace.totalEventSizeInBytes >= _trace.allocatedSizeInBytes * 0.9;
            bool wrapped = false;
            InputEventPtr first = default;
            if (_trace.GetNextEvent(ref first))
            {
                double t = first.time;
                wrapped = _hasOldestEventTime && t > _oldestEventTime + 1e-9;
                _oldestEventTime = t;
                _hasOldestEventTime = true;
            }

            if (!full && !wrapped) return;
            Overflowed = true;
            _trace.Disable();
            Debug.LogWarning("[Gdw.Replay] input trace buffer overflowed; the recording is invalid for verification.");
        }

        void WriteTraceFile()
        {
            Directory.CreateDirectory(_runDirectory);
            string tmp = _tracePath + ".tmp." + Guid.NewGuid().ToString("N");
            try
            {
                _trace.WriteTo(tmp);
                if (File.Exists(_tracePath)) File.Delete(_tracePath);
                File.Move(tmp, _tracePath);
            }
            catch
            {
                if (File.Exists(tmp)) File.Delete(tmp);
                throw;
            }
        }

        // ---------------------------------------------------------------- replay

        static double FirstEventTime(InputEventTrace trace)
        {
            double first = 0;
            bool found = false;
            InputEventPtr ptr = default;
            while (trace.GetNextEvent(ref ptr))
            {
                if (!found || ptr.time < first)
                {
                    first = ptr.time;
                    found = true;
                }
            }
            return found ? first : 0;
        }

        void RetimestampReplayEvent(InputEventPtr eventPtr)
        {
            if (!PreserveEventTiming || !eventPtr.valid) return;
            eventPtr.time = _replayBaseTime + (eventPtr.time - _recordedFirstEventTime);
        }

        void OnReplayFinished()
        {
            ReplayFinished = true;
        }

        /// <summary>Disables every native (physical) device so only replay devices feed gameplay.</summary>
        void DisableNativeDevices()
        {
            foreach (var device in InputSystem.devices)
            {
                if (device == null || !device.added || !device.native || !device.enabled) continue;
                InputSystem.DisableDevice(device);
                _disabledDevices.Add(device);
            }
        }

        /// <summary>Catches devices plugged in during replay; replay-created devices are non-native.</summary>
        void SuppressPhysicalDevices()
        {
            foreach (var device in InputSystem.devices)
            {
                if (device == null || !device.added || !device.native || !device.enabled) continue;
                InputSystem.DisableDevice(device);
                if (!_disabledDevices.Contains(device)) _disabledDevices.Add(device);
            }
        }

        void RestoreDevices()
        {
            for (int i = 0; i < _disabledDevices.Count; i++)
            {
                var device = _disabledDevices[i];
                if (device == null || !device.added) continue;
                try { InputSystem.EnableDevice(device); }
                catch (Exception e) { Debug.LogWarning("[Gdw.Replay] failed to re-enable input device: " + e.Message); }
            }
            _disabledDevices.Clear();
        }

        void EnsurePlayerInputPairing()
        {
            if (_pairedPlayerInputs || _controller == null) return;
            var virtualDevices = new List<InputDevice>();
            foreach (var device in _controller.createdDevices)
            {
                if (device != null && device.added) virtualDevices.Add(device);
            }
            if (virtualDevices.Count == 0) return;

            _pairedPlayerInputs = true;
            PlayerInput[] players;
            try
            {
                players = UnityEngine.Object.FindObjectsByType<PlayerInput>(
                    FindObjectsInactive.Include, FindObjectsSortMode.None);
            }
            catch (Exception e)
            {
                Debug.LogWarning("[Gdw.Replay] could not enumerate PlayerInput components: " + e.Message);
                return;
            }

            foreach (var player in players)
            {
                if (player == null) continue;
                try
                {
                    var state = new PlayerInputState
                    {
                        Player = player,
                        Scheme = player.currentControlScheme,
                        NeverAutoSwitch = player.neverAutoSwitchControlSchemes,
                    };
                    InputUser user = player.user;
                    if (user.valid)
                    {
                        foreach (var paired in user.pairedDevices) state.Devices.Add(paired);
                    }
                    _playerInputs.Add(state);

                    player.neverAutoSwitchControlSchemes = true;
                    var chosen = ChooseReplayDevices(state, virtualDevices);
                    if (chosen.Count == 0) continue;

                    if (!string.IsNullOrEmpty(state.Scheme))
                    {
                        player.SwitchCurrentControlScheme(state.Scheme, chosen.ToArray());
                    }
                    else if (user.valid)
                    {
                        user.UnpairDevices();
                        foreach (var device in chosen) InputUser.PerformPairingWithDevice(device, user);
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[Gdw.Replay] failed to pair PlayerInput with replay devices: " + e.Message);
                }
            }
        }

        static List<InputDevice> ChooseReplayDevices(PlayerInputState state, List<InputDevice> virtualDevices)
        {
            var chosen = new List<InputDevice>();
            var used = new HashSet<int>();
            for (int i = 0; i < state.Devices.Count; i++)
            {
                string layout = state.Devices[i] != null ? state.Devices[i].layout : null;
                if (string.IsNullOrEmpty(layout)) continue;
                for (int j = 0; j < virtualDevices.Count; j++)
                {
                    var candidate = virtualDevices[j];
                    if (candidate == null || used.Contains(candidate.deviceId) || candidate.layout != layout) continue;
                    chosen.Add(candidate);
                    used.Add(candidate.deviceId);
                    break;
                }
            }
            if (chosen.Count == 0 && virtualDevices.Count > 0) chosen.Add(virtualDevices[0]);
            return chosen;
        }

        void RestorePlayerInputs()
        {
            for (int i = 0; i < _playerInputs.Count; i++)
            {
                var state = _playerInputs[i];
                var player = state.Player;
                if (player == null) continue;
                try
                {
                    player.neverAutoSwitchControlSchemes = state.NeverAutoSwitch;
                    var devices = new List<InputDevice>();
                    foreach (var device in state.Devices)
                    {
                        if (device != null && device.added) devices.Add(device);
                    }
                    InputUser user = player.user;
                    if (!string.IsNullOrEmpty(state.Scheme) && devices.Count > 0)
                    {
                        player.SwitchCurrentControlScheme(state.Scheme, devices.ToArray());
                    }
                    else if (user.valid)
                    {
                        user.UnpairDevices();
                        foreach (var device in devices) InputUser.PerformPairingWithDevice(device, user);
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[Gdw.Replay] failed to restore PlayerInput devices: " + e.Message);
                }
            }
            _playerInputs.Clear();
            _pairedPlayerInputs = false;
        }

        void RejectTimedInteractions()
        {
            var found = new List<string>();
            var seenAssets = new HashSet<InputActionAsset>();
            var assets = new List<InputActionAsset>(Resources.FindObjectsOfTypeAll<InputActionAsset>());
            var projectWide = InputSystem.actions;
            if (projectWide != null && !assets.Contains(projectWide)) assets.Add(projectWide);

            foreach (var asset in assets)
            {
                if (asset == null || !seenAssets.Add(asset)) continue;
                foreach (var map in asset.actionMaps)
                {
                    foreach (var action in map.actions)
                    {
                        string label = asset.name + "/" + map.name + "/" + action.name;
                        CollectTimed(action.interactions, label, found);
                        foreach (var binding in action.bindings)
                        {
                            if (binding.isComposite) continue;
                            CollectTimed(binding.interactions, label + "@" + binding.path, found);
                        }
                    }
                }
            }

            if (found.Count == 0) return;
            int shown = Math.Min(found.Count, 5);
            string list = string.Join(", ", found.GetRange(0, shown));
            if (found.Count > shown) list += ", ... (" + found.Count + " total)";
            throw new ReplayStateException(
                "timed interactions are not deterministic under manual replay updates: " + list +
                ". Set InputTraceAdapter.StrictTimedInteractions = false only after fixture validation proves they replay identically.");
        }

        static void CollectTimed(string interactions, string label, List<string> found)
        {
            if (string.IsNullOrEmpty(interactions)) return;
            string[] parts = interactions.Split(';');
            for (int i = 0; i < parts.Length; i++)
            {
                string name = parts[i].Trim();
                int paren = name.IndexOf('(');
                if (paren >= 0) name = name.Substring(0, paren).Trim();
                if (IsTimedInteractionName(name)) found.Add(label + ":" + name);
            }
        }

        static bool IsTimedInteractionName(string name)
        {
            return string.Equals(name, "Hold", StringComparison.OrdinalIgnoreCase)
                || string.Equals(name, "Tap", StringComparison.OrdinalIgnoreCase)
                || string.Equals(name, "SlowTap", StringComparison.OrdinalIgnoreCase)
                || string.Equals(name, "MultiTap", StringComparison.OrdinalIgnoreCase);
        }

        sealed class PlayerInputState
        {
            public PlayerInput Player;
            public string Scheme;
            public bool NeverAutoSwitch;
            public readonly List<InputDevice> Devices = new List<InputDevice>();
        }
    }
}
