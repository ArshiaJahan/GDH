namespace CoinDash
{
    /// <summary>Dash timing rules, kept out of MonoBehaviours so EditMode tests can check them.</summary>
    public sealed class Dash
    {
        public const float SpeedMultiplier = 3f;
        public const float Duration = 0.2f;
        public const float Cooldown = 1f;

        /// <summary>Seconds of boost left; > 0 while dashing.</summary>
        public float ActiveTime { get; private set; }
        /// <summary>Seconds until the next dash is allowed, counted from the dash start.</summary>
        public float CooldownTime { get; private set; }

        public bool IsDashing => ActiveTime > 0f;
        public bool Ready => CooldownTime <= 0f;
        public float Multiplier => IsDashing ? SpeedMultiplier : 1f;

        /// <summary>Starts a dash if moving and off cooldown. Returns true when a dash started.</summary>
        public bool TryStart(bool moving)
        {
            if (!moving || !Ready) return false;
            ActiveTime = Duration;
            CooldownTime = Cooldown;
            return true;
        }

        public void Tick(float dt)
        {
            if (ActiveTime > 0f) ActiveTime = ActiveTime > dt ? ActiveTime - dt : 0f;
            if (CooldownTime > 0f) CooldownTime = CooldownTime > dt ? CooldownTime - dt : 0f;
        }
    }
}
