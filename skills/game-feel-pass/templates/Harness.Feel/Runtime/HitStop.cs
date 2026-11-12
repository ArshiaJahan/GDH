using System;
using UnityEngine;

namespace Harness.Feel
{
    /// <summary>
    /// Pure hit-stop state (no Unity time access, unit-testable). Overlapping requests merge into ONE stop:
    /// the end time is the latest requested end, the stop time scale is the lowest requested, and the time scale
    /// captured by the FIRST request is restored exactly once when the merged stop ends.
    /// If something else changed Time.timeScale during the stop (pause menu), the end does not overwrite it.
    /// </summary>
    public sealed class HitStopController
    {
        public bool Active { get; private set; }
        public double StartTime { get; private set; }
        public double EndTime { get; private set; }
        public float StopTimeScale { get; private set; }
        public float BaseTimeScale { get; private set; } = 1f;
        public int Depth { get; private set; }

        /// <param name="maxTotal">Cap for the merged stop measured from the first request (seconds).</param>
        /// <returns>The time scale to apply now.</returns>
        public float Request(double now, float duration, float stopTimeScale, float currentTimeScale,
            double maxTotal = double.PositiveInfinity)
        {
            stopTimeScale = Mathf.Clamp01(stopTimeScale);
            if (duration <= 0f) return Active ? StopTimeScale : currentTimeScale;
            if (!Active)
            {
                Active = true;
                BaseTimeScale = currentTimeScale;
                StopTimeScale = stopTimeScale;
                StartTime = now;
                EndTime = now + Math.Min(duration, maxTotal);
                Depth = 1;
            }
            else
            {
                EndTime = Math.Min(Math.Max(EndTime, now + duration), StartTime + maxTotal);
                StopTimeScale = Mathf.Min(StopTimeScale, stopTimeScale);
                Depth++;
            }
            return StopTimeScale;
        }

        /// <returns>True when the caller must set Time.timeScale = <paramref name="apply"/>.</returns>
        public bool Tick(double now, float currentTimeScale, out float apply)
        {
            apply = currentTimeScale;
            if (!Active || now < EndTime) return false;
            Active = false;
            Depth = 0;
            if (!Mathf.Approximately(currentTimeScale, StopTimeScale)) return false; // someone else owns timeScale now
            apply = BaseTimeScale;
            return true;
        }

        /// <returns>The time scale to restore.</returns>
        public float Cancel()
        {
            Active = false;
            Depth = 0;
            return BaseTimeScale;
        }

        /// <summary>Change what the stop restores to (pause menus call this while a stop is active).</summary>
        public void SetBaseTimeScale(float timeScale) => BaseTimeScale = timeScale;
    }

    /// <summary>
    /// Hit-stop (freeze frames) through Time.timeScale, timed in unscaled real time so it always ends.
    /// Usage: <c>HitStop.Request(0.06f);</c> (a hidden "[HitStop]" object is created on first use).
    /// Nesting-safe: see <see cref="HitStopController"/>. Pause menus: call <see cref="SetBaseTimeScale"/>
    /// instead of writing Time.timeScale directly, or <see cref="Cancel"/> first.
    /// Things that must keep moving during a stop (UI, shake, flash) use unscaled time.
    /// </summary>
    [DefaultExecutionOrder(-1000)]
    public sealed class HitStop : MonoBehaviour
    {
        [Tooltip("Upper bound for one request, seconds.")]
        public float maxDuration = 0.25f;
        [Tooltip("Upper bound for one merged stop (many hits in a row), seconds, so a hit stream cannot freeze the game.")]
        public float maxTotal = 0.4f;

        static HitStop instance;
        readonly HitStopController controller = new HitStopController();

        public static bool IsActive => instance != null && instance.controller.Active;
        public static HitStopController Controller => instance != null ? instance.controller : null;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics() => instance = null;

        /// <param name="duration">Seconds of real time (scaled by FeelSettings.HitStopScale).</param>
        /// <param name="timeScale">Time scale during the stop: 0 = full freeze, 0.05 = slow-mo.</param>
        public static void Request(float duration, float timeScale = 0f)
        {
            if (!Application.isPlaying) return;
            duration *= FeelSettings.HitStopScale;
            if (duration <= 0f) return;
            HitStop hs = Ensure();
            duration = Mathf.Min(duration, hs.maxDuration);
            bool nested = hs.controller.Active;
            Time.timeScale = hs.controller.Request(Time.unscaledTimeAsDouble, duration, timeScale, Time.timeScale, hs.maxTotal);
            FeelLog.Log("HitStop", "duration", duration, "nested", nested ? 1f : 0f, hs);
        }

        public static void Cancel()
        {
            if (instance == null || !instance.controller.Active) return;
            Time.timeScale = instance.controller.Cancel();
        }

        public static void SetBaseTimeScale(float timeScale)
        {
            if (instance != null && instance.controller.Active) instance.controller.SetBaseTimeScale(timeScale);
            else Time.timeScale = timeScale;
        }

        static HitStop Ensure()
        {
            if (instance != null) return instance;
            var go = new GameObject("[HitStop]") { hideFlags = HideFlags.DontSave };
            DontDestroyOnLoad(go);
            instance = go.AddComponent<HitStop>();
            return instance;
        }

        void Awake()
        {
            if (instance != null && instance != this) { Destroy(this); return; }
            instance = this;
        }

        void Update()
        {
            if (controller.Tick(Time.unscaledTimeAsDouble, Time.timeScale, out float apply)) Time.timeScale = apply;
        }

        void OnDisable()
        {
            if (controller.Active) Time.timeScale = controller.Cancel(); // never leave the game frozen
        }

        void OnDestroy()
        {
            if (instance == this) instance = null;
        }
    }
}
