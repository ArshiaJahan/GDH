using UnityEngine;

namespace Harness.Feel
{
    /// <summary>
    /// Squash and stretch on a VISUAL child (not the physics root: scaling a collider changes gameplay).
    /// Play(+0.25) stretches tall and thin (jump take-off), Play(-0.25) squashes wide and flat (landing, hit).
    /// preserveArea keeps x * y constant so the sprite does not look like it grows. Put the sprite pivot at the
    /// feet (Bottom) so squash stays on the ground. Retriggering restarts from the base scale (no drift).
    /// </summary>
    public sealed class SquashStretch : MonoBehaviour
    {
        [Tooltip("Transform to scale. Empty = this transform.")]
        public Transform visual;
        public float duration = 0.18f;
        public Ease ease = Ease.OutElastic;
        public bool preserveArea = true;
        public bool unscaledTime;

        Vector3 baseScale;
        Coroutine running;
        bool initialised;

        void Awake() => Init();

        void Init()
        {
            if (initialised) return;
            if (visual == null) visual = transform;
            baseScale = visual.localScale;
            initialised = true;
        }

        /// <param name="amount">+ stretches vertically, - squashes. Typical range -0.4..0.4.</param>
        public void Play(float amount) => Play(amount, duration);

        public void Play(float amount, float seconds)
        {
            float sy = Mathf.Max(0.05f, 1f + amount);
            float sx = preserveArea ? 1f / sy : Mathf.Max(0.05f, 1f - amount);
            PlayScale(new Vector2(sx, sy), seconds);
        }

        /// <summary>Jump to baseScale * scale, then ease back to baseScale.</summary>
        public void PlayScale(Vector2 scale, float seconds)
        {
            Init();
            if (!isActiveAndEnabled) return;
            if (running != null) StopCoroutine(running);
            Vector3 from = Vector3.Scale(baseScale, new Vector3(scale.x, scale.y, 1f));
            Transform v = visual;
            Vector3 to = baseScale;
            v.localScale = from;
            running = Tween.Value(this, 0f, 1f, seconds, k => v.localScale = Vector3.LerpUnclamped(from, to, k),
                ease, unscaledTime, () => running = null);
            FeelLog.Log("SquashStretch", "x", scale.x, "y", scale.y, this);
        }

        void OnDisable()
        {
            if (initialised && visual != null) visual.localScale = baseScale;
            running = null;
        }
    }
}
