namespace Harness.Feel
{
    /// <summary>
    /// Input buffer: a press is remembered for <see cref="window"/> seconds, so pressing jump/attack slightly
    /// before it becomes possible still fires (typical 0.1-0.15 s). Pass Time.time (or unscaled time for menus).
    /// </summary>
    public struct InputBuffer
    {
        public float window;
        float pressedAt;
        bool pending;

        public InputBuffer(float window)
        {
            this.window = window;
            pressedAt = 0f;
            pending = false;
        }

        public void Press(float now)
        {
            pressedAt = now;
            pending = true;
        }

        public bool IsBuffered(float now) => pending && now - pressedAt <= window;

        /// <summary>True once if a press happened within the window; clears it.</summary>
        public bool Consume(float now)
        {
            if (!IsBuffered(now)) { pending = false; return false; }
            pending = false;
            return true;
        }

        public void Clear() => pending = false;
    }

    /// <summary>
    /// Coyote time: jumping stays allowed for <see cref="window"/> seconds after walking off a ledge
    /// (typical 0.08-0.12 s). Call SetGrounded every physics step; Consume when the jump fires.
    /// </summary>
    public struct CoyoteTimer
    {
        public float window;
        float lastGrounded;
        bool valid;

        public CoyoteTimer(float window)
        {
            this.window = window;
            lastGrounded = 0f;
            valid = false;
        }

        public void SetGrounded(bool grounded, float now)
        {
            if (!grounded) return;
            lastGrounded = now;
            valid = true;
        }

        public bool CanJump(float now) => valid && now - lastGrounded <= window;

        public void Consume() => valid = false;
    }
}
