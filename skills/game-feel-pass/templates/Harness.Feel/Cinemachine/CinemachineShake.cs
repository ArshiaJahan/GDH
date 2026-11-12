using Unity.Cinemachine;
using UnityEngine;

namespace Harness.Feel
{
    /// <summary>
    /// Optional Cinemachine 3 adapter (assembly only compiles when com.unity.cinemachine >= 3.0 is installed).
    /// Setup: add a CinemachineImpulseSource + this component to any object (e.g. the camera rig), and a
    /// CinemachineImpulseListener extension to the CinemachineCamera. ScreenShake.Add(trauma) then also
    /// generates an impulse with force = trauma * forceAtFullTrauma (trauma already includes FeelSettings.ShakeScale).
    /// Do not also put ScreenShake on the Brain's camera: the Brain overwrites that transform.
    /// </summary>
    [RequireComponent(typeof(CinemachineImpulseSource))]
    public sealed class CinemachineShake : MonoBehaviour
    {
        public float forceAtFullTrauma = 1f;
        [Tooltip("Shake on every ScreenShake.Add call.")]
        public bool listenToScreenShake = true;

        CinemachineImpulseSource source;

        void Awake() => source = GetComponent<CinemachineImpulseSource>();

        void OnEnable()
        {
            if (listenToScreenShake) ScreenShake.TraumaAdded += Shake;
        }

        void OnDisable() => ScreenShake.TraumaAdded -= Shake;

        public void Shake(float trauma)
        {
            if (trauma <= 0f || source == null) return;
            float force = Mathf.Clamp01(trauma) * forceAtFullTrauma;
            source.GenerateImpulseWithForce(force);
            FeelLog.Log("CinemachineShake", "force", force, null, 0f, this);
        }
    }
}
