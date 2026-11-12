using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;

namespace Harness.Feel
{
    public enum FeedbackKind { ScreenShake, HitStop, Flash, SquashStretch, Knockback, Audio, Particles, DamageNumber, Event }

    /// <summary>One row of a FeedbackPlayer. Field meaning depends on <see cref="kind"/> (see tooltips).</summary>
    [Serializable]
    public class FeedbackEntry
    {
        public string label;
        public FeedbackKind kind;
        public bool enabled = true;
        [Min(0f), Tooltip("Seconds before this feedback plays (real time when the player uses unscaled delays).")]
        public float delay;
        [Tooltip("ScreenShake: trauma 0..1. SquashStretch: amount (+stretch / -squash). Knockback: push speed " +
                 "(0 = component default). Audio: volume scale. Particles: particles to Emit (0 = Play()).")]
        public float intensity = 0.3f;
        [Tooltip("HitStop: seconds. Flash / SquashStretch: seconds (0 = component default).")]
        public float duration;
        [Tooltip("HitStop: time scale during the stop (0 = freeze).")]
        [Range(0f, 1f)] public float timeScale;
        [Tooltip("Flash, SquashStretch, Knockback, AudioVariation, ParticleSystem or DamageNumbers. " +
                 "Empty = first matching component on this object or its children (DamageNumbers: DamageNumbers.Main).")]
        public Component target;
        [Tooltip("Event: invoked when the row plays.")]
        public UnityEvent onPlay;
    }

    /// <summary>
    /// Plays a designer-editable list of feedbacks with one call (an "impact stack"): e.g. on enemy hit
    /// HitStop 0.05 + Flash + SquashStretch -0.2 + Knockback + Audio + DamageNumber + ScreenShake 0.2.
    /// Call Play() or Play(hitPoint, hitDirection, damage). Logs one [FEEL] line for itself and one per feedback.
    /// </summary>
    public sealed class FeedbackPlayer : MonoBehaviour
    {
        public List<FeedbackEntry> feedbacks = new List<FeedbackEntry>();
        [Tooltip("Delays use real time, so they still elapse during hit-stop.")]
        public bool unscaledDelays = true;
        [Tooltip("Ignore Play calls closer together than this (seconds, unscaled).")]
        public float cooldown;

        float lastPlay = float.NegativeInfinity;

        public void Play() => Play(transform.position, Vector2.zero, 0);

        /// <param name="position">Where the impact happened (damage numbers, particles).</param>
        /// <param name="direction">Push direction for Knockback (zero = away from position).</param>
        /// <param name="value">Number shown by DamageNumber rows.</param>
        public void Play(Vector3 position, Vector2 direction, int value)
        {
            if (!isActiveAndEnabled) return;
            float now = Time.unscaledTime;
            if (now - lastPlay < cooldown) return;
            lastPlay = now;
            FeelLog.Log("FeedbackPlayer", FeelLog.Enabled ? "player=" + name + " feedbacks=" + feedbacks.Count : null, this);
            for (int i = 0; i < feedbacks.Count; i++)
            {
                FeedbackEntry e = feedbacks[i];
                if (e == null || !e.enabled) continue;
                if (e.delay > 0f) StartCoroutine(PlayDelayed(e, position, direction, value));
                else PlayEntry(e, position, direction, value);
            }
        }

        IEnumerator PlayDelayed(FeedbackEntry e, Vector3 position, Vector2 direction, int value)
        {
            if (unscaledDelays) yield return new WaitForSecondsRealtime(e.delay);
            else yield return new WaitForSeconds(e.delay);
            PlayEntry(e, position, direction, value);
        }

        void PlayEntry(FeedbackEntry e, Vector3 position, Vector2 direction, int value)
        {
            switch (e.kind)
            {
                case FeedbackKind.ScreenShake:
                    ScreenShake.Add(e.intensity);
                    break;
                case FeedbackKind.HitStop:
                    HitStop.Request(e.duration > 0f ? e.duration : 0.05f, e.timeScale);
                    break;
                case FeedbackKind.Flash:
                {
                    var f = Resolve<Flash>(e);
                    if (f != null) { if (e.duration > 0f) f.Play(e.duration); else f.Play(); }
                    break;
                }
                case FeedbackKind.SquashStretch:
                {
                    var s = Resolve<SquashStretch>(e);
                    if (s != null) { if (e.duration > 0f) s.Play(e.intensity, e.duration); else s.Play(e.intensity); }
                    break;
                }
                case FeedbackKind.Knockback:
                {
                    var k = Resolve<Knockback>(e);
                    if (k == null) break;
                    if (direction.sqrMagnitude > 1e-6f) k.Apply(direction, e.intensity);
                    else k.Apply((Vector2)k.transform.position - (Vector2)position, e.intensity);
                    break;
                }
                case FeedbackKind.Audio:
                {
                    var a = Resolve<AudioVariation>(e);
                    if (a != null) a.Play(e.intensity > 0f ? e.intensity : 1f);
                    break;
                }
                case FeedbackKind.Particles:
                {
                    var ps = Resolve<ParticleSystem>(e);
                    if (ps == null) break;
                    if (e.intensity >= 1f)
                    {
                        var ep = new ParticleSystem.EmitParams { position = position, applyShapeToPosition = true };
                        ps.Emit(ep, (int)e.intensity);
                    }
                    else ps.Play();
                    FeelLog.Log("Particles", "count", e.intensity, null, 0f, ps);
                    break;
                }
                case FeedbackKind.DamageNumber:
                {
                    var dn = e.target as DamageNumbers;
                    if (dn != null) dn.Show(position, value, value < 0 ? dn.healColor : dn.normalColor);
                    else DamageNumbers.Spawn(position, value);
                    break;
                }
                case FeedbackKind.Event:
                    e.onPlay?.Invoke();
                    FeelLog.Log("Event", FeelLog.Enabled ? "label=" + (string.IsNullOrEmpty(e.label) ? "-" : e.label.Replace(' ', '_')) : null, this);
                    break;
            }
        }

        T Resolve<T>(FeedbackEntry e) where T : Component
        {
            if (e.target is T t) return t;
            t = GetComponentInChildren<T>(true);
            if (t != null) e.target = t; // cache the lookup
            else Debug.LogWarning("[FEEL] FeedbackPlayer '" + name + "': no " + typeof(T).Name + " for row '" + e.label + "'", this);
            return t;
        }
    }
}
