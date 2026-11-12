using System.Collections;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace Harness.Feel.Tests
{
    public class FeelPlayModeTests
    {
        readonly List<GameObject> spawned = new List<GameObject>();

        GameObject Make(string name, params System.Type[] components)
        {
            var go = new GameObject(name, components);
            spawned.Add(go);
            return go;
        }

        [SetUp]
        public void SetUp()
        {
            FeelLog.Enabled = true;
            FeelSettings.ShakeScale = 1f;
            FeelSettings.ReduceFlashing = false;
            FeelSettings.HitStopScale = 1f;
            Time.timeScale = 1f;
        }

        [TearDown]
        public void TearDown()
        {
            HitStop.Cancel();
            Time.timeScale = 1f;
            foreach (var go in spawned) if (go != null) Object.Destroy(go);
            spawned.Clear();
            if (DamageNumbers.Main != null) Object.Destroy(DamageNumbers.Main.gameObject);
        }

        static IEnumerator WaitUntilRealtime(System.Func<bool> condition, float timeout)
        {
            float start = Time.realtimeSinceStartup;
            while (!condition() && Time.realtimeSinceStartup - start < timeout) yield return null;
        }

        [UnityTest]
        public IEnumerator Tween_Move_ReachesTargetAndCallsOnComplete()
        {
            var host = Make("host", typeof(FeelTestHost)).GetComponent<FeelTestHost>();
            bool done = false;
            var to = new Vector3(3f, -1f, 0f);
            Tween.Move(host, host.transform, to, 0.2f, Ease.OutBack, unscaled: false, local: true, onComplete: () => done = true);
            yield return WaitUntilRealtime(() => done, 3f);
            Assert.IsTrue(done, "onComplete was not called");
            Assert.Less(Vector3.Distance(host.transform.localPosition, to), 1e-4f);
        }

        [UnityTest]
        public IEnumerator Tween_Unscaled_CompletesWhileTimeScaleIsZero_ScaledDoesNot()
        {
            var host = Make("host", typeof(FeelTestHost)).GetComponent<FeelTestHost>();
            Time.timeScale = 0f;
            bool unscaledDone = false, scaledDone = false;
            float value = 0f;
            Tween.Value(host, 0f, 1f, 0.15f, v => value = v, Ease.Linear, unscaled: true, onComplete: () => unscaledDone = true);
            Tween.Value(host, 0f, 1f, 0.15f, _ => { }, Ease.Linear, unscaled: false, onComplete: () => scaledDone = true);
            yield return WaitUntilRealtime(() => unscaledDone, 3f);
            Assert.IsTrue(unscaledDone);
            Assert.AreEqual(1f, value, 1e-6f);
            Assert.IsFalse(scaledDone, "a scaled tween must not advance at timeScale 0");
            Time.timeScale = 1f;
            yield return WaitUntilRealtime(() => scaledDone, 3f);
            Assert.IsTrue(scaledDone);
        }

        [UnityTest]
        public IEnumerator HitStop_Nested_FreezesUntilLatestEnd_ThenRestores()
        {
            LogAssert.Expect(LogType.Log, new Regex(@"^\[FEEL\] name=HitStop duration=0\.1 nested=0"));
            LogAssert.Expect(LogType.Log, new Regex(@"^\[FEEL\] name=HitStop duration=0\.2 nested=1"));
            HitStop.Request(0.1f);
            Assert.AreEqual(0f, Time.timeScale);
            yield return new WaitForSecondsRealtime(0.05f);
            HitStop.Request(0.2f);                     // ends ~0.25 s after the first request
            yield return new WaitForSecondsRealtime(0.1f);
            Assert.AreEqual(0f, Time.timeScale, "first request's end must not restore while the nested one runs");
            Assert.IsTrue(HitStop.IsActive);
            yield return WaitUntilRealtime(() => !HitStop.IsActive, 2f);
            Assert.AreEqual(1f, Time.timeScale, "time scale restored");
        }

        [UnityTest]
        public IEnumerator FeedbackPlayer_ImpactStack_LogsFeelLines_AndRestoresState()
        {
            // Camera rig -> CameraShake (ScreenShake) -> Main Camera
            var rig = Make("CameraRig");
            var shakeGo = new GameObject("CameraShake", typeof(ScreenShake));
            shakeGo.transform.SetParent(rig.transform, false);
            var cam = new GameObject("Main Camera", typeof(Camera), typeof(AudioListener));
            cam.transform.SetParent(shakeGo.transform, false);
            cam.tag = "MainCamera";

            // Enemy: physics root + visual child with two sprites (shader path + tint path)
            var enemy = Make("Enemy", typeof(Rigidbody2D), typeof(Knockback), typeof(FeedbackPlayer), typeof(AudioVariation));
            enemy.GetComponent<Rigidbody2D>().gravityScale = 0f;
            var visual = new GameObject("Visual", typeof(SpriteRenderer), typeof(SquashStretch), typeof(Flash));
            visual.transform.SetParent(enemy.transform, false);
            var tex = new Texture2D(4, 4);
            var sprite = Sprite.Create(tex, new Rect(0, 0, 4, 4), new Vector2(0.5f, 0f), 4f);
            var srTint = visual.GetComponent<SpriteRenderer>();
            srTint.sprite = sprite;
            var blockGo = new GameObject("Overlay", typeof(SpriteRenderer));
            blockGo.transform.SetParent(visual.transform, false);
            var srBlock = blockGo.GetComponent<SpriteRenderer>();
            srBlock.sprite = sprite;
            Shader flashShader = Shader.Find("Harness/SpriteFlashUnlit");
            if (flashShader != null) srBlock.sharedMaterial = new Material(flashShader);

            var particlesGo = new GameObject("HitParticles", typeof(ParticleSystem));
            particlesGo.transform.SetParent(enemy.transform, false);
            var audio = enemy.GetComponent<AudioVariation>();
            var clip = AudioClip.Create("blip", 441, 1, 44100, false);
            clip.SetData(new float[441], 0);
            audio.clips = new[] { clip };

            bool eventFired = false;
            var player = enemy.GetComponent<FeedbackPlayer>();
            player.feedbacks = new List<FeedbackEntry>
            {
                new FeedbackEntry { label = "freeze", kind = FeedbackKind.HitStop, duration = 0.06f },
                new FeedbackEntry { label = "flash", kind = FeedbackKind.Flash, duration = 0.1f },
                new FeedbackEntry { label = "squash", kind = FeedbackKind.SquashStretch, intensity = -0.25f },
                new FeedbackEntry { label = "push", kind = FeedbackKind.Knockback, intensity = 6f },
                new FeedbackEntry { label = "sfx", kind = FeedbackKind.Audio, intensity = 1f },
                new FeedbackEntry { label = "sparks", kind = FeedbackKind.Particles, intensity = 8f },
                new FeedbackEntry { label = "number", kind = FeedbackKind.DamageNumber },
                new FeedbackEntry { label = "shake", kind = FeedbackKind.ScreenShake, intensity = 0.4f, delay = 0.02f },
                new FeedbackEntry { label = "custom", kind = FeedbackKind.Event, onPlay = new UnityEngine.Events.UnityEvent() },
            };
            player.feedbacks[8].onPlay.AddListener(() => eventFired = true);
            yield return null; // let Awake/OnEnable run

            Color baseColor = srTint.color;
            Vector3 baseScale = visual.transform.localScale;
            foreach (var n in new[] { "FeedbackPlayer", "HitStop", "Flash", "SquashStretch", "Knockback", "Audio", "Particles", "DamageNumber", "Event", "ScreenShake" })
                LogAssert.Expect(LogType.Log, new Regex(@"^\[FEEL\] name=" + n + @"\b"));

            int before = FeelLog.Count;
            player.Play(enemy.transform.position + Vector3.left, Vector2.right, 12);

            Assert.AreEqual(0f, Time.timeScale, "hit-stop active");
            if (flashShader != null) Assert.IsTrue(srBlock.HasPropertyBlock(), "shader path uses a MaterialPropertyBlock");
            Assert.AreNotEqual(baseColor, srTint.color, "tint path changed the colour");
            Assert.Greater(enemy.GetComponent<Rigidbody2D>().linearVelocity.x, 0f, "pushed to +x");
            Assert.IsTrue(eventFired);

            yield return new WaitForSecondsRealtime(0.05f);
            Assert.Greater(ScreenShake.Main.Trauma, 0f, "delayed shake fired during the hit-stop (unscaled delay)");

            yield return WaitUntilRealtime(() => !HitStop.IsActive, 2f);
            yield return new WaitForSecondsRealtime(0.4f);
            Assert.AreEqual(1f, Time.timeScale);
            Assert.AreEqual(baseColor, srTint.color, "tint restored");
            Assert.IsFalse(srBlock.HasPropertyBlock(), "property block cleared");
            Assert.Less(Vector3.Distance(baseScale, visual.transform.localScale), 1e-3f, "scale restored");
            Assert.GreaterOrEqual(FeelLog.Count - before, 10);
            Assert.IsNotNull(DamageNumbers.Main, "damage number pool created on first spawn");
            LogAssert.NoUnexpectedReceived();
        }

        [UnityTest]
        public IEnumerator Accessibility_ShakeScaleZero_DisablesShake()
        {
            var go = Make("Cam", typeof(ScreenShake));
            yield return null;
            FeelSettings.ShakeScale = 0f;
            ScreenShake.Add(1f);
            Assert.AreEqual(0f, go.GetComponent<ScreenShake>().Trauma);
            FeelSettings.ShakeScale = 0.5f;
            LogAssert.Expect(LogType.Log, new Regex(@"^\[FEEL\] name=ScreenShake trauma=0\.5 main=1"));
            ScreenShake.Add(1f);
            Assert.AreEqual(0.5f, go.GetComponent<ScreenShake>().Trauma, 1e-5f);
        }
    }
}
