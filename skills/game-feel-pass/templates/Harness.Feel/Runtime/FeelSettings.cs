using UnityEngine;

namespace Harness.Feel
{
    /// <summary>
    /// Player-facing accessibility settings read by every feedback. Wire them to the options menu:
    /// ShakeScale 0..1 (0 = no screen shake), ReduceFlashing (weaker, single flashes), HitStopScale 0..1.
    /// Call <see cref="Load"/> once at boot and <see cref="Save"/> when the menu changes them.
    /// </summary>
    public static class FeelSettings
    {
        public static float ShakeScale = 1f;
        public static bool ReduceFlashing;
        public static float HitStopScale = 1f;

        /// <summary>Flash strength used when ReduceFlashing is on (0..1).</summary>
        public const float ReducedFlashAmount = 0.35f;

        const string KeyShake = "harness.feel.shakeScale";
        const string KeyFlash = "harness.feel.reduceFlashing";
        const string KeyHitStop = "harness.feel.hitStopScale";

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            ShakeScale = 1f;
            ReduceFlashing = false;
            HitStopScale = 1f;
        }

        public static void Load()
        {
            ShakeScale = Mathf.Clamp01(PlayerPrefs.GetFloat(KeyShake, 1f));
            ReduceFlashing = PlayerPrefs.GetInt(KeyFlash, 0) == 1;
            HitStopScale = Mathf.Clamp01(PlayerPrefs.GetFloat(KeyHitStop, 1f));
        }

        public static void Save()
        {
            PlayerPrefs.SetFloat(KeyShake, Mathf.Clamp01(ShakeScale));
            PlayerPrefs.SetInt(KeyFlash, ReduceFlashing ? 1 : 0);
            PlayerPrefs.SetFloat(KeyHitStop, Mathf.Clamp01(HitStopScale));
            PlayerPrefs.Save();
        }
    }
}
