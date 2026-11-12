using System;
using System.Collections;
using System.Threading;
using UnityEngine;

namespace Harness.Feel
{
    /// <summary>
    /// Dependency-free tween helpers for feedback (position, scale, colour, any float). Coroutine-based: the
    /// tween stops when <paramref name="host"/> is disabled or destroyed; stop it early with host.StopCoroutine.
    /// unscaled = true keeps animating during hit-stop / pause (Time.timeScale == 0).
    /// Each call allocates a coroutine and a closure: fine for events (hits, UI), not for per-frame use on
    /// hundreds of objects (animate those in one Update loop instead; see perf-pass).
    /// For a larger tween library use PrimeTween / LitMotion / DOTween; this file has no dependencies.
    /// </summary>
    public static class Tween
    {
        public static Coroutine Value(MonoBehaviour host, float from, float to, float duration, Action<float> setter,
            Ease ease = Ease.OutQuad, bool unscaled = false, Action onComplete = null)
        {
            if (!CanRun(host)) { setter(to); onComplete?.Invoke(); return null; }
            return host.StartCoroutine(Run(from, to, duration, setter, ease, unscaled, onComplete));
        }

        public static Coroutine Move(MonoBehaviour host, Transform target, Vector3 to, float duration,
            Ease ease = Ease.OutQuad, bool unscaled = false, bool local = true, Action onComplete = null)
        {
            Vector3 from = local ? target.localPosition : target.position;
            return Value(host, 0f, 1f, duration, k =>
            {
                if (target == null) return;
                Vector3 p = Vector3.LerpUnclamped(from, to, k);
                if (local) target.localPosition = p; else target.position = p;
            }, ease, unscaled, onComplete);
        }

        public static Coroutine Scale(MonoBehaviour host, Transform target, Vector3 to, float duration,
            Ease ease = Ease.OutQuad, bool unscaled = false, Action onComplete = null)
        {
            Vector3 from = target.localScale;
            return Value(host, 0f, 1f, duration, k =>
            {
                if (target != null) target.localScale = Vector3.LerpUnclamped(from, to, k);
            }, ease, unscaled, onComplete);
        }

        public static Coroutine Color(MonoBehaviour host, SpriteRenderer target, Color to, float duration,
            Ease ease = Ease.Linear, bool unscaled = false, Action onComplete = null)
        {
            Color from = target.color;
            return Value(host, 0f, 1f, duration, k =>
            {
                if (target != null) target.color = UnityEngine.Color.LerpUnclamped(from, to, k);
            }, ease, unscaled, onComplete);
        }

        /// <summary>The coroutine body; usable directly (yield return Tween.Run(...)) inside your own coroutines.</summary>
        public static IEnumerator Run(float from, float to, float duration, Action<float> setter,
            Ease ease = Ease.OutQuad, bool unscaled = false, Action onComplete = null)
        {
            if (duration > 0f)
            {
                setter(from);
                float t = 0f;
                while (t < duration)
                {
                    yield return null;
                    t += unscaled ? Time.unscaledDeltaTime : Time.deltaTime;
                    setter(Mathf.LerpUnclamped(from, to, Easing.Evaluate(ease, t / duration)));
                }
            }
            setter(to);
            onComplete?.Invoke();
        }

        /// <summary>Awaitable variant (Unity 6): await Tween.RunAsync(...) in an async method. Cancel with the token
        /// (e.g. destroyCancellationToken); cancellation throws OperationCanceledException as usual.</summary>
        public static async Awaitable RunAsync(float from, float to, float duration, Action<float> setter,
            Ease ease = Ease.OutQuad, bool unscaled = false, CancellationToken token = default)
        {
            if (duration > 0f)
            {
                setter(from);
                float t = 0f;
                while (t < duration)
                {
                    await Awaitable.NextFrameAsync(token);
                    t += unscaled ? Time.unscaledDeltaTime : Time.deltaTime;
                    setter(Mathf.LerpUnclamped(from, to, Easing.Evaluate(ease, t / duration)));
                }
            }
            setter(to);
        }

        static bool CanRun(MonoBehaviour host) => host != null && host.isActiveAndEnabled && Application.isPlaying;
    }
}
