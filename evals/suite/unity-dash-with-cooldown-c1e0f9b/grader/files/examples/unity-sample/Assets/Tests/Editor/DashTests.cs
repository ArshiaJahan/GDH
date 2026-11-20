using NUnit.Framework;

namespace CoinDash.Tests
{
    public class DashTests
    {
        const float Dt = 1f / 60f;

        static void Advance(Dash dash, float seconds)
        {
            int frames = UnityEngine.Mathf.RoundToInt(seconds / Dt);
            for (int i = 0; i < frames; i++) dash.Tick(Dt);
        }

        [Test]
        public void DashBoostsThenCoolsDown()
        {
            const float speed = 5f;
            var dash = new Dash();

            Assert.IsFalse(dash.TryStart(moving: false), "no dash while standing still");
            Assert.AreEqual(speed, speed * dash.Multiplier);

            Assert.IsTrue(dash.TryStart(moving: true));
            Assert.AreEqual(3f * speed, speed * dash.Multiplier, 1e-5f);

            Advance(dash, 0.1f);
            Assert.IsTrue(dash.IsDashing, "still boosted inside 0.2 s");
            Assert.IsFalse(dash.TryStart(moving: true), "no re-dash while boosted");

            Advance(dash, 0.1f + Dt);
            Assert.IsFalse(dash.IsDashing, "boost ends after 0.2 s");
            Assert.AreEqual(speed, speed * dash.Multiplier);

            Advance(dash, 0.5f);
            Assert.IsFalse(dash.TryStart(moving: true), "still cooling down before 1 s");

            Advance(dash, 0.5f);
            Assert.IsTrue(dash.Ready, "ready again after 1 s");
            Assert.IsTrue(dash.TryStart(moving: true));
        }
    }
}
