using System;
using UnityEngine;
using UnityEngine.Pool;

namespace Harness.Feel
{
    /// <summary>
    /// One floating number. Default text = legacy TextMesh (built in, no package). For TextMeshPro, subclass in
    /// your own assembly (reference Unity.TextMeshPro) and override SetText/SetAlpha.
    /// </summary>
    public class DamageNumber : MonoBehaviour
    {
        public TextMesh text;
        public float lifetime = 0.7f;
        public float rise = 1.1f;
        [Tooltip("Start scale multiplier, eases to 1 in the first 20% (pop).")]
        public float popScale = 1.5f;
        public bool unscaledTime;

        internal Action<DamageNumber> release;
        float age;
        Vector3 start;
        Vector3 baseScale = Vector3.one;
        Color color;

        public virtual void SetText(string value, Color c)
        {
            if (text == null) return;
            text.text = value;
            text.color = c;
        }

        protected virtual void SetAlpha(float a)
        {
            if (text == null) return;
            Color c = color;
            c.a *= a;
            text.color = c;
        }

        internal void Launch(Vector3 position, string value, Color c, float scale)
        {
            start = position;
            age = 0f;
            color = c;
            baseScale = Vector3.one * scale;
            transform.position = position;
            transform.localScale = baseScale * popScale;
            SetText(value, c);
        }

        void Update()
        {
            age += unscaledTime ? Time.unscaledDeltaTime : Time.deltaTime;
            float k = lifetime > 0f ? age / lifetime : 1f;
            transform.position = start + Vector3.up * (rise * Easing.Evaluate(Ease.OutCubic, k));
            float pop = Mathf.Clamp01(k / 0.2f);
            transform.localScale = baseScale * Mathf.Lerp(popScale, 1f, Easing.Evaluate(Ease.OutBack, pop));
            SetAlpha(1f - Easing.Evaluate(Ease.InQuad, k));
            if (k >= 1f) release?.Invoke(this);
        }
    }

    /// <summary>
    /// Pooled damage numbers (UnityEngine.Pool.ObjectPool: no Instantiate/Destroy per hit, cached digit strings
    /// for 0..999 so showing a number does not allocate). Without a prefab a TextMesh number is built at runtime.
    /// Usage: DamageNumbers.Spawn(hitPoint, 12, crit: true).
    /// </summary>
    public sealed class DamageNumbers : MonoBehaviour
    {
        public DamageNumber prefab;
        public int defaultCapacity = 16;
        public int maxPooled = 64;
        [Tooltip("Spawns are skipped above this many visible numbers.")]
        public int maxActive = 48;
        public Color normalColor = Color.white;
        public Color critColor = new Color(1f, 0.85f, 0.2f, 1f);
        public Color healColor = new Color(0.4f, 1f, 0.4f, 1f);
        public float critScale = 1.4f;
        public Vector2 jitter = new Vector2(0.25f, 0.1f);
        public int sortingOrder = 100;

        public static DamageNumbers Main { get; private set; }
        public int CountActive => pool != null ? pool.CountActive : 0;

        ObjectPool<DamageNumber> pool;
        static string[] digits;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics() => Main = null;

        public static DamageNumber Spawn(Vector3 position, int value, bool crit = false)
        {
            if (Main == null)
            {
                if (!Application.isPlaying) return null;
                Main = new GameObject("[DamageNumbers]").AddComponent<DamageNumbers>();
            }
            return Main.Show(position, value, crit ? Main.critColor : (value < 0 ? Main.healColor : Main.normalColor),
                crit ? Main.critScale : 1f);
        }

        public DamageNumber Show(Vector3 position, int value, Color color, float scale = 1f)
        {
            pool ??= new ObjectPool<DamageNumber>(Create, n => n.gameObject.SetActive(true),
                n => n.gameObject.SetActive(false), n => { if (n != null) Destroy(n.gameObject); },
                Debug.isDebugBuild, defaultCapacity, maxPooled);
            if (pool.CountActive >= maxActive) return null;
            DamageNumber n = pool.Get();
            Vector3 p = position + new Vector3(UnityEngine.Random.Range(-jitter.x, jitter.x), UnityEngine.Random.Range(0f, jitter.y), 0f);
            n.Launch(p, ToText(Mathf.Abs(value)), color, scale);
            FeelLog.Log("DamageNumber", "value", value, "active", pool.CountActive, this);
            return n;
        }

        static string ToText(int v)
        {
            if (digits == null)
            {
                digits = new string[1000];
                for (int i = 0; i < digits.Length; i++) digits[i] = i.ToString();
            }
            return v < digits.Length ? digits[v] : v.ToString();
        }

        DamageNumber Create()
        {
            DamageNumber n = prefab != null ? Instantiate(prefab, transform) : BuildDefault();
            n.release = x => pool.Release(x);
            return n;
        }

        DamageNumber BuildDefault()
        {
            var go = new GameObject("DamageNumber");
            go.transform.SetParent(transform, false);
            var tm = go.AddComponent<TextMesh>();
            Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            tm.font = font;
            tm.fontSize = 64;
            tm.characterSize = 0.05f;
            tm.anchor = TextAnchor.MiddleCenter;
            tm.alignment = TextAlignment.Center;
            var mr = go.GetComponent<MeshRenderer>();
            if (font != null) mr.sharedMaterial = font.material;
            mr.sortingOrder = sortingOrder;
            var n = go.AddComponent<DamageNumber>();
            n.text = tm;
            return n;
        }

        void Awake()
        {
            if (Main == null) Main = this;
        }

        void OnDestroy()
        {
            if (Main == this) Main = null;
            pool?.Dispose();
        }
    }
}
