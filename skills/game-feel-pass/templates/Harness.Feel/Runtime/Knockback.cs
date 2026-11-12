using UnityEngine;

namespace Harness.Feel
{
    /// <summary>
    /// Knockback on a Rigidbody2D. ⚠ Unity 6: use Rigidbody2D.linearVelocity (Rigidbody2D.velocity is obsolete,
    /// warning CS0618 on 6000.3). Speed-based by default (same push regardless of mass, predictable for design);
    /// set useImpulse to respect mass. Kinematic bodies get a velocity that decays to zero over stunDuration.
    /// Movement code must skip writing velocity while <see cref="IsStunned"/>, or it cancels the push.
    /// </summary>
    [RequireComponent(typeof(Rigidbody2D))]
    public sealed class Knockback : MonoBehaviour
    {
        [Tooltip("Push speed in units/s (or impulse when useImpulse).")]
        public float speed = 8f;
        [Tooltip("Seconds the target ignores its own movement input.")]
        public float stunDuration = 0.15f;
        public bool useImpulse;
        [Tooltip("Zero the current velocity first so knockback is consistent.")]
        public bool resetVelocity = true;

        Rigidbody2D body;
        float stunUntil;
        Vector2 kinematicVelocity;

        public bool IsStunned => Time.time < stunUntil;

        void Awake() => body = GetComponent<Rigidbody2D>();

        /// <summary>Push away from a world position (attacker, explosion centre).</summary>
        public void ApplyFrom(Vector2 sourcePosition) => Apply((Vector2)transform.position - sourcePosition, speed);

        public void Apply(Vector2 direction) => Apply(direction, speed);

        public void Apply(Vector2 direction, float pushSpeed)
        {
            if (body == null) body = GetComponent<Rigidbody2D>();
            if (direction.sqrMagnitude < 1e-6f) direction = Vector2.up;
            direction.Normalize();
            if (pushSpeed <= 0f) pushSpeed = speed;
            if (body.bodyType == RigidbodyType2D.Dynamic)
            {
                if (resetVelocity) body.linearVelocity = Vector2.zero;
                if (useImpulse) body.AddForce(direction * pushSpeed, ForceMode2D.Impulse);
                else body.linearVelocity += direction * pushSpeed;
            }
            else if (body.bodyType == RigidbodyType2D.Kinematic)
            {
                kinematicVelocity = direction * pushSpeed;
                body.linearVelocity = kinematicVelocity;
            }
            stunUntil = Time.time + stunDuration;
            FeelLog.Log("Knockback", "speed", pushSpeed, "stun", stunDuration, this);
        }

        void FixedUpdate()
        {
            if (body == null || body.bodyType != RigidbodyType2D.Kinematic || kinematicVelocity == Vector2.zero) return;
            float remaining = stunUntil - Time.time;
            if (remaining <= 0f || stunDuration <= 0f)
            {
                kinematicVelocity = Vector2.zero;
                body.linearVelocity = Vector2.zero;
                return;
            }
            body.linearVelocity = kinematicVelocity * (remaining / stunDuration);
        }
    }
}
