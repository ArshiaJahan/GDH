using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.LowLevel;
using UnityEngine.PlayerLoop;

namespace Gdw.Replay
{
    /// <summary>Per-frame input bookkeeping supplied by the InputTraceAdapter (task C).</summary>
    internal struct FrameInputInfo
    {
        public bool InputUpdate;
        public int EventStart;
        public int EventCount;
    }

    /// <summary>Data collected by a finished replay loop, handed back to ReplaySession.</summary>
    internal sealed class ReplayLoopResult
    {
        public List<ReplayFrame> Frames = new List<ReplayFrame>();
        public List<ReplayMarker> Markers = new List<ReplayMarker>();
        public double Ticks;
        public long FramesCompared;
        public long FirstDivergentFrame = -1;
        public string DivergentProviderId;
        public string ExpectedHash;
        public string ActualHash;
        public string Error;
    }

    /// <summary>
    /// Drives the deterministic frame/tick schedule via PlayerLoop hooks:
    /// frame boundary + one manual input update -> Unity FixedUpdate callbacks -> script-mode physics
    /// (once per fixed tick) -> Update/LateUpdate -> post-LateUpdate checkpoint. Restores every
    /// time/input/physics/loop setting on stop, error or exit.
    /// </summary>
    internal static class ReplayLoop
    {
        enum Mode { None, Record, Replay }

        /// <summary>Called exactly once per frame, before fixed ticks; InputTraceAdapter wires this.</summary>
        internal static Action InputUpdate;

        /// <summary>Called at each checkpoint to fill input_update / event_start / event_count.</summary>
        internal static Func<FrameInputInfo> InputInfo;

        static Mode _mode = Mode.None;
        static ReplaySession _session;
        static PlayerLoopSystem _originalLoop;

        static float _savedFixedDeltaTime;
        static float _savedCaptureDeltaTime;
        static int _savedCaptureFramerate;
        static float _savedTimeScale;
        static float _savedMaximumDeltaTime;
        static SimulationMode _savedSimulationMode;
        static bool _savedAutoSimulation;
        static bool _savedAutoSyncTransforms;
        static SimulationMode2D _savedSimulationMode2D;

        static float _fixedDelta = 1f / 60f;
        static double _tick;
        static long _frame;
        static int _ticksThisFrame;
        static List<ReplayFrame> _frames = new List<ReplayFrame>();
        static List<ReplayMarker> _markers = new List<ReplayMarker>();
        static List<ReplayFrame> _replayFrames;
        static int _replayFrameIndex;
        static long _framesCompared;
        static long _firstDivergentFrame = -1;
        static string _divergentProviderId;
        static string _expectedHash;
        static string _actualHash;

        internal static double Tick => _tick;
        internal static float FixedDelta => _fixedDelta;

        internal static void Begin(ReplaySession session, ReplayOptions options, List<ReplayFrame> replayFrames)
        {
            if (_mode != Mode.None) throw new ReplayStateException("replay loop already active");
            if (session == null) throw new ArgumentNullException(nameof(session));
            if (options == null) throw new ArgumentNullException(nameof(options));

            _session = session;
            _fixedDelta = options.FixedDeltaTime > 0f ? options.FixedDeltaTime : 1f / 60f;
            _replayFrames = replayFrames;
            _mode = replayFrames == null ? Mode.Record : Mode.Replay;
            _tick = 0;
            _frame = -1;
            _ticksThisFrame = 0;
            _frames = new List<ReplayFrame>();
            _markers = new List<ReplayMarker>();
            _replayFrameIndex = 0;
            _framesCompared = 0;
            _firstDivergentFrame = -1;
            _divergentProviderId = null;
            _expectedHash = null;
            _actualHash = null;

            SaveSettings();
            ApplySettings();

            var initial = CaptureFrame(-1, 0, 0);
            if (_mode == Mode.Record)
            {
                _frames.Add(initial);
            }
            else
            {
                CompareFrame(initial, _replayFrames, _replayFrameIndex);
                _replayFrameIndex = 1;
            }

            InstallLoop();
        }

        internal static void Mark(string label, string dataJson)
        {
            if (_mode != Mode.Record) return;
            _markers.Add(new ReplayMarker
            {
                Frame = _frame < 0 ? -1 : _frame,
                Tick = (long)_tick,
                Label = label ?? "",
                Data = dataJson,
            });
        }

        internal static ReplayLoopResult Finish()
        {
            if (_mode == Mode.None) return null;
            var result = new ReplayLoopResult
            {
                Frames = _frames,
                Markers = _markers,
                Ticks = _tick,
                FramesCompared = _framesCompared,
                FirstDivergentFrame = _firstDivergentFrame,
                DivergentProviderId = _divergentProviderId,
                ExpectedHash = _expectedHash,
                ActualHash = _actualHash,
            };
            StopInternal();
            var session = _session;
            _session = null;
            session?.OnLoopFinished(result);
            return result;
        }

        static void StopInternal()
        {
            if (_mode == Mode.None) return;
            _mode = Mode.None;
            RestoreSettings();
            InputUpdate = null;
            InputInfo = null;
            _replayFrames = null;
        }

        /// <summary>Restore settings and drop the active session without firing Finished (PlayMode exit).</summary>
        internal static void Abort()
        {
            if (_mode == Mode.None) return;
            StopInternal();
            _session = null;
        }

        static void SaveSettings()
        {
            _originalLoop = PlayerLoop.GetCurrentPlayerLoop();
            _savedFixedDeltaTime = Time.fixedDeltaTime;
            _savedCaptureDeltaTime = Time.captureDeltaTime;
            _savedCaptureFramerate = Time.captureFramerate;
            _savedTimeScale = Time.timeScale;
            _savedMaximumDeltaTime = Time.maximumDeltaTime;
            _savedSimulationMode = Physics.simulationMode;
            _savedAutoSimulation = Physics.autoSimulation;
            _savedAutoSyncTransforms = Physics.autoSyncTransforms;
            _savedSimulationMode2D = Physics2D.simulationMode;
        }

        static void ApplySettings()
        {
            Time.fixedDeltaTime = _fixedDelta;
            Time.captureDeltaTime = _fixedDelta;
            int fps = Mathf.RoundToInt(1f / _fixedDelta);
            Time.captureFramerate = fps > 0 ? fps : 60;
            Time.timeScale = 1f;
            Time.maximumDeltaTime = _fixedDelta;
            Physics.simulationMode = SimulationMode.Script;
            Physics.autoSimulation = false;
            Physics.autoSyncTransforms = true;
            Physics2D.simulationMode = SimulationMode2D.Script;
        }

        static void RestoreSettings()
        {
            PlayerLoop.SetPlayerLoop(_originalLoop);
            Time.fixedDeltaTime = _savedFixedDeltaTime;
            Time.captureDeltaTime = _savedCaptureDeltaTime;
            Time.captureFramerate = _savedCaptureFramerate;
            Time.timeScale = _savedTimeScale;
            Time.maximumDeltaTime = _savedMaximumDeltaTime;
            Physics.simulationMode = _savedSimulationMode;
            Physics.autoSimulation = _savedAutoSimulation;
            Physics.autoSyncTransforms = _savedAutoSyncTransforms;
            Physics2D.simulationMode = _savedSimulationMode2D;
        }

        static void InstallLoop()
        {
            var loop = PlayerLoop.GetCurrentPlayerLoop();
            loop = InsertIntoPhase(loop, new PlayerLoopSystem { type = typeof(ReplayLoop), updateDelegate = FrameStart }, typeof(EarlyUpdate), atEnd: false);
            loop = InsertIntoPhase(loop, new PlayerLoopSystem { type = typeof(ReplayLoop), updateDelegate = SimulateTick }, typeof(FixedUpdate), atEnd: true);
            loop = InsertIntoPhase(loop, new PlayerLoopSystem { type = typeof(ReplayLoop), updateDelegate = Checkpoint }, typeof(PostLateUpdate), atEnd: true);
            PlayerLoop.SetPlayerLoop(loop);
        }

        static PlayerLoopSystem InsertIntoPhase(PlayerLoopSystem root, PlayerLoopSystem system, Type phase, bool atEnd)
        {
            if (root.subSystemList == null) return root;
            var newSub = new PlayerLoopSystem[root.subSystemList.Length];
            for (int i = 0; i < root.subSystemList.Length; i++)
            {
                newSub[i] = root.subSystemList[i];
                if (root.subSystemList[i].type == phase)
                {
                    var inner = root.subSystemList[i].subSystemList;
                    var list = new List<PlayerLoopSystem>(inner ?? new PlayerLoopSystem[0]);
                    if (atEnd) list.Add(system); else list.Insert(0, system);
                    newSub[i].subSystemList = list.ToArray();
                }
            }
            root.subSystemList = newSub;
            return root;
        }

        static void FrameStart()
        {
            if (_mode == Mode.None) return;
            _frame++;
            _ticksThisFrame = 0;
            InputUpdate?.Invoke();
        }

        static void SimulateTick()
        {
            if (_mode == Mode.None) return;
            // Unity's fixed-step accumulator carries leftover time from before the session began, so the very
            // first frames can see a different number of FixedUpdate phases in record and replay. The
            // checkpointed schedule is exactly one tick per frame; extra phases are not simulated or counted.
            if (_ticksThisFrame >= 1) return;
            RunTick();
        }

        static void RunTick()
        {
            _tick += 1;
            _ticksThisFrame++;
            float dt = _fixedDelta;
            Physics.Simulate(dt);
            Physics2D.Simulate(dt);
        }

        static void Checkpoint()
        {
            if (_mode == Mode.None) return;
            try
            {
                // Accumulator skipped this frame's fixed step: keep the schedule at exactly one tick per frame.
                if (_ticksThisFrame == 0) RunTick();
                var info = InputInfo != null ? InputInfo() : default;
                var frame = CaptureFrame(_frame, (long)_tick, _ticksThisFrame);
                frame.InputUpdate = info.InputUpdate;
                frame.EventStart = info.EventStart;
                frame.EventCount = info.EventCount;

                if (_mode == Mode.Record)
                {
                    _frames.Add(frame);
                    return;
                }

                CompareFrame(frame, _replayFrames, _replayFrameIndex);
                _replayFrameIndex++;
                if (_replayFrameIndex >= _replayFrames.Count)
                {
                    Finish();
                }
            }
            catch (Exception e)
            {
                var result = new ReplayLoopResult
                {
                    Frames = _frames,
                    Markers = _markers,
                    Ticks = _tick,
                    FramesCompared = _framesCompared,
                    FirstDivergentFrame = _firstDivergentFrame,
                    DivergentProviderId = _divergentProviderId,
                    ExpectedHash = _expectedHash,
                    ActualHash = _actualHash,
                    Error = e.Message,
                };
                StopInternal();
                var session = _session;
                _session = null;
                session?.OnLoopFinished(result);
            }
        }

        static ReplayFrame CaptureFrame(long frame, long tick, int fixedTicks)
        {
            var hashes = ReplayRegistry.Instance.ComputeAll();
            return new ReplayFrame
            {
                Frame = frame,
                Tick = tick,
                FixedTicks = fixedTicks,
                Hash = hashes.Aggregate,
                Providers = new Dictionary<string, string>(hashes.Providers, StringComparer.Ordinal),
            };
        }

        static void CompareFrame(ReplayFrame actual, List<ReplayFrame> expectedFrames, int index)
        {
            if (index < 0 || index >= expectedFrames.Count) throw new ReplayStateException("replay frame out of range");
            var expected = expectedFrames[index];
            _framesCompared++;

            bool diverged = actual.Hash != expected.Hash || actual.FixedTicks != expected.FixedTicks;
            if (!diverged && actual.Tick != expected.Tick) diverged = true;

            if (diverged && _firstDivergentFrame < 0)
            {
                _firstDivergentFrame = Math.Max(0, actual.Frame); // initial checkpoint is frame -1; -1 means 'no divergence'
                _expectedHash = expected.Hash;
                _actualHash = actual.Hash;
                _divergentProviderId = FirstDifferingProvider(expected.Providers, actual.Providers);
            }
        }

        static string FirstDifferingProvider(IReadOnlyDictionary<string, string> expected, IReadOnlyDictionary<string, string> actual)
        {
            var all = new SortedSet<string>(StringComparer.Ordinal);
            foreach (var kv in expected) all.Add(kv.Key);
            foreach (var kv in actual) all.Add(kv.Key);
            foreach (var id in all)
            {
                expected.TryGetValue(id, out var e);
                actual.TryGetValue(id, out var a);
                if (e != a) return id;
            }
            return null;
        }
    }
}
