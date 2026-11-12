using System;
using UnityEngine;

namespace Harness.Feel
{
    /// <summary>
    /// Trauma-based screen shake (Squirrel Eiserloh, GDC 2016): AddTrauma(0..1) accumulates, shake = trauma^exponent,
    /// offsets come from Perlin noise (smooth, not random jitter), trauma decays linearly.
    /// Put it on a CAMERA OFFSET transform whose local pose nothing else writes: e.g. CameraRig (follow script)
    /// -> CameraShake (this) -> Main Camera. It writes localPosition/localRotation around the pose it had on Awake.
    /// With Cinemachine 3 the Brain overwrites the camera transform: use the optional CinemachineShake adapter
    /// (Harness.Feel.Cinemachine), which listens to <see cref="TraumaAdded"/>.
    /// Respects FeelSettings.ShakeScale (0 = off). Uses unscaled time by default so it runs during hit-stop.
    /// </summary>
    public sealed class ScreenShake : MonoBehaviour
    {
        [Tooltip("Max offset in world units at trauma 1 (2D pixel art: about 0.2-0.5).")]
        public float maxOffset = 0.35f;
        [Tooltip("Max roll in degrees at trauma 1 (0 = no rotation).")]
        public float maxAngle = 2f;
        [Tooltip("Noise speed. 15-30 feels like impact, 5-10 like rumble.")]
        public float frequency = 22f;
        [Tooltip("Trauma lost per second.")]
        public float decayPerSecond = 1.6f;
        [Tooltip("shake = trauma^exponent. 2 (quadratic) keeps small hits subtle.")]
        public float exponent = 2f;
        public bool unscaledTime = true;

        /// <summary>The first enabled ScreenShake; target of the static <see cref="Add"/>.</summary>
        public static ScreenShake Main { get; private set; }

        /// <summary>Raised by <see cref="Add"/> with the already-scaled trauma (adapters such as Cinemachine).</summary>
        public static event Action<float> TraumaAdded;

        public float Trauma { get; private set; }

        Vector3 restPosition;
        Quaternion restRotation;
        float seed;
        float noiseTime;
        bool applied;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            Main = null;
            TraumaAdded = null;
        }

        /// <summary>Shake the main camera (and any adapter). amount is trauma 0..1, e.g. 0.2 light hit, 0.5 heavy, 0.8 explosion.</summary>
        public static void Add(float amount)
        {
            float scaled = amount * FeelSettings.ShakeScale;
            if (scaled <= 0f) return;
            if (Main != null) Main.AddTraumaInternal(scaled);
            TraumaAdded?.Invoke(scaled);
            FeelLog.Log("ScreenShake", "trauma", Main != null ? Main.Trauma : scaled, "main", Main != null ? 1f : 0f);
        }

        /// <summary>Shake this camera only.</summary>
        public void AddTrauma(float amount)
        {
            float scaled = amount * FeelSettings.ShakeScale;
            if (scaled <= 0f) return;
            AddTraumaInternal(scaled);
            FeelLog.Log("ScreenShake", "trauma", Trauma, "main", Main == this ? 1f : 0f, this);
        }

        public void ResetRestPose()
        {
            restPosition = transform.localPosition;
            restRotation = transform.localRotation;
        }

        void AddTraumaInternal(float scaled) => Trauma = Mathf.Clamp01(Trauma + scaled);

        void Awake()
        {
            ResetRestPose();
            seed = UnityEngine.Random.value * 100f;
        }

        void OnEnable()
        {
            if (Main == null) Main = this;
        }

        void OnDisable()
        {
            if (Main == this) Main = null;
            Trauma = 0f;
            if (applied) { transform.localPosition = restPosition; transform.localRotation = restRotation; applied = false; }
        }

        void LateUpdate()
        {
            if (Trauma <= 0f)
            {
                if (applied) { transform.localPosition = restPosition; transform.localRotation = restRotation; applied = false; }
                return;
            }
            float dt = unscaledTime ? Time.unscaledDeltaTime : Time.deltaTime;
            noiseTime += dt * frequency;
            float shake = Mathf.Pow(Trauma, exponent);
            float x = Mathf.PerlinNoise(seed, noiseTime) * 2f - 1f;
            float y = Mathf.PerlinNoise(seed + 13.7f, noiseTime) * 2f - 1f;
            float r = Mathf.PerlinNoise(seed + 27.3f, noiseTime) * 2f - 1f;
            transform.localPosition = restPosition + new Vector3(x, y, 0f) * (maxOffset * shake);
            transform.localRotation = restRotation * Quaternion.Euler(0f, 0f, r * maxAngle * shake);
            applied = true;
            Trauma = Mathf.Max(0f, Trauma - decayPerSecond * dt);
        }
    }
}
