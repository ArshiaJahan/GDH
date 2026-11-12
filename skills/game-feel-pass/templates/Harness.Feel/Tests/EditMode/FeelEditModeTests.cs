using System;
using NUnit.Framework;

namespace Harness.Feel.Tests
{
    public class HitStopControllerTests
    {
        [Test]
        public void SingleRequest_FreezesThenRestoresOnce()
        {
            var c = new HitStopController();
            Assert.AreEqual(0f, c.Request(10.0, 0.1f, 0f, 1f));
            Assert.IsTrue(c.Active);
            Assert.IsFalse(c.Tick(10.05, 0f, out _), "still inside the stop");
            Assert.IsTrue(c.Tick(10.101, 0f, out float apply)); // 0.1f is 0.1000000015 as a double
            Assert.AreEqual(1f, apply);
            Assert.IsFalse(c.Active);
            Assert.IsFalse(c.Tick(10.2, 1f, out _), "restores exactly once");
        }

        [Test]
        public void NestedRequests_MergeToLatestEnd_AndRestoreOriginalScale()
        {
            var c = new HitStopController();
            c.Request(0.0, 0.10f, 0f, 1f);                // ends 0.10
            c.Request(0.02, 0.05f, 0f, 0f);               // ends 0.07: inside, must not shorten
            c.Request(0.05, 0.20f, 0f, 0f);               // ends 0.25: extends
            Assert.AreEqual(3, c.Depth);
            Assert.AreEqual(0.25, c.EndTime, 1e-6);
            Assert.AreEqual(1f, c.BaseTimeScale, "base comes from the FIRST request, not the frozen 0");
            Assert.IsFalse(c.Tick(0.11, 0f, out _));
            Assert.IsTrue(c.Tick(0.251, 0f, out float apply));
            Assert.AreEqual(1f, apply);
        }

        [Test]
        public void NestedRequests_UseLowestTimeScale()
        {
            var c = new HitStopController();
            Assert.AreEqual(0.2f, c.Request(0.0, 0.1f, 0.2f, 1f), 1e-6f);
            Assert.AreEqual(0.05f, c.Request(0.01, 0.1f, 0.05f, 0.2f), 1e-6f);
            Assert.AreEqual(0.05f, c.Request(0.02, 0.1f, 0.5f, 0.05f), 1e-6f);
        }

        [Test]
        public void RestoresNonUnitBaseTimeScale()
        {
            var c = new HitStopController();
            c.Request(0.0, 0.1f, 0f, 0.5f);               // game was in slow motion
            Assert.IsTrue(c.Tick(0.2, 0f, out float apply));
            Assert.AreEqual(0.5f, apply);
        }

        [Test]
        public void ExternalTimeScaleChange_IsNotOverwritten()
        {
            var c = new HitStopController();
            c.Request(0.0, 0.1f, 0.1f, 1f);
            Assert.IsFalse(c.Tick(0.2, 0.7f, out float apply), "someone else set 0.7 during the stop");
            Assert.AreEqual(0.7f, apply);
            Assert.IsFalse(c.Active);
        }

        [Test]
        public void SetBaseTimeScale_DuringStop_IsWhatGetsRestored()
        {
            var c = new HitStopController();
            c.Request(0.0, 0.1f, 0f, 1f);
            c.SetBaseTimeScale(0f);                       // pause menu opened mid-stop
            Assert.IsTrue(c.Tick(0.2, 0f, out float apply));
            Assert.AreEqual(0f, apply);
        }

        [Test]
        public void MaxTotal_CapsAStreamOfHits()
        {
            var c = new HitStopController();
            for (int i = 0; i < 20; i++) c.Request(i * 0.05, 0.1f, 0f, i == 0 ? 1f : 0f, 0.4);
            Assert.AreEqual(0.4, c.EndTime, 1e-6);
        }

        [Test]
        public void Cancel_ReturnsBase_AndZeroDurationIsIgnored()
        {
            var c = new HitStopController();
            Assert.AreEqual(1f, c.Request(0.0, 0f, 0f, 1f));
            Assert.IsFalse(c.Active);
            c.Request(0.0, 0.1f, 0f, 1f);
            Assert.AreEqual(1f, c.Cancel());
            Assert.IsFalse(c.Active);
        }
    }

    public class EasingAndTimingTests
    {
        [Test]
        public void EveryEase_StartsAt0_EndsAt1()
        {
            foreach (Ease e in Enum.GetValues(typeof(Ease)))
            {
                Assert.AreEqual(0f, Easing.Evaluate(e, 0f), 1e-4f, e.ToString());
                Assert.AreEqual(1f, Easing.Evaluate(e, 1f), 1e-4f, e.ToString());
                Assert.AreEqual(1f, Easing.Evaluate(e, 3f), 1e-4f, e + " clamps t");
            }
        }

        [Test]
        public void InputBuffer_FiresOnceWithinWindow()
        {
            var b = new InputBuffer(0.1f);
            Assert.IsFalse(b.Consume(0f));
            b.Press(1.00f);
            Assert.IsTrue(b.Consume(1.08f));
            Assert.IsFalse(b.Consume(1.09f), "consumed");
            b.Press(2.00f);
            Assert.IsFalse(b.Consume(2.2f), "expired");
        }

        [Test]
        public void CoyoteTimer_AllowsJumpShortlyAfterLeavingGround()
        {
            var c = new CoyoteTimer(0.1f);
            Assert.IsFalse(c.CanJump(0f));
            c.SetGrounded(true, 1f);
            c.SetGrounded(false, 1.02f);
            Assert.IsTrue(c.CanJump(1.08f));
            Assert.IsFalse(c.CanJump(1.2f));
            c.SetGrounded(true, 2f);
            c.Consume();
            Assert.IsFalse(c.CanJump(2f));
        }
    }
}
