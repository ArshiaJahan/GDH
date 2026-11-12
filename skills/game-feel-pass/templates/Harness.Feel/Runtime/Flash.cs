using System.Collections;
using UnityEngine;

namespace Harness.Feel
{
    /// <summary>
    /// Hit flash for sprites. Two paths, chosen per renderer when mode = Auto:
    /// PropertyBlock: the material's shader has float <c>_FlashAmount</c> (0..1) and color <c>_FlashColor</c>
    ///   (e.g. the shipped "Harness/SpriteFlashUnlit" shader, or a Sprite Shader Graph that lerps the colour to
    ///   _FlashColor by _FlashAmount, keeping alpha). Gives a true WHITE flash; set per renderer through a
    ///   MaterialPropertyBlock, so the material asset is never modified. The block is cleared afterwards
    ///   (renderers with a property block are not SRP-batched while it is set).
    /// Tint: any SpriteRenderer, no shader needed. SpriteRenderer.color MULTIPLIES the texture, so it can only
    ///   darken/colour (default red tint); a white flash needs the PropertyBlock path.
    /// FeelSettings.ReduceFlashing: one weaker flash (no blinking).
    /// </summary>
    public sealed class Flash : MonoBehaviour
    {
        public enum Mode { Auto, PropertyBlock, Tint }

        [Tooltip("Empty = all SpriteRenderers in children (found on first Play).")]
        public Renderer[] renderers;
        public Mode mode = Mode.Auto;
        [Tooltip("PropertyBlock path colour (white = classic hit flash).")]
        public Color flashColor = Color.white;
        [Tooltip("Tint path colour (multiplied with the sprite).")]
        public Color tintColor = new Color(1f, 0.3f, 0.3f, 1f);
        public float duration = 0.08f;
        [Min(1)] public int blinks = 1;
        public bool unscaledTime = true;

        public static readonly int FlashAmountId = Shader.PropertyToID("_FlashAmount");
        public static readonly int FlashColorId = Shader.PropertyToID("_FlashColor");

        MaterialPropertyBlock block;
        Color[] baseColors;
        bool[] useBlock;
        Coroutine running;

        public void Play() => Play(duration);

        public void Play(float seconds)
        {
            if (!isActiveAndEnabled) return;
            Init();
            if (running != null) { StopCoroutine(running); Apply(0f); }
            bool reduced = FeelSettings.ReduceFlashing;
            float amount = reduced ? FeelSettings.ReducedFlashAmount : 1f;
            int count = reduced ? 1 : Mathf.Max(1, blinks);
            running = StartCoroutine(Run(amount, Mathf.Max(0.01f, seconds), count));
            if (FeelLog.Enabled)
                FeelLog.Log("Flash", "mode=" + (useBlock.Length > 0 && useBlock[0] ? "block" : "tint") +
                                     " renderers=" + renderers.Length + " amount=" + FeelLog.F(amount), this);
            else FeelLog.Log("Flash", null, this);
        }

        IEnumerator Run(float amount, float seconds, int count)
        {
            for (int i = 0; i < count; i++)
            {
                Apply(amount);
                yield return Wait(seconds);
                Apply(0f);
                if (i < count - 1) yield return Wait(seconds);
            }
            running = null;
        }

        object Wait(float seconds) =>
            unscaledTime ? (object)new WaitForSecondsRealtime(seconds) : new WaitForSeconds(seconds);

        void Init()
        {
            if (renderers == null || renderers.Length == 0)
                renderers = GetComponentsInChildren<SpriteRenderer>(true);
            if (useBlock != null && useBlock.Length == renderers.Length) return;
            block ??= new MaterialPropertyBlock();
            baseColors = new Color[renderers.Length];
            useBlock = new bool[renderers.Length];
            for (int i = 0; i < renderers.Length; i++)
            {
                Renderer r = renderers[i];
                if (r == null) continue;
                bool hasProps = r.sharedMaterial != null && r.sharedMaterial.HasProperty(FlashAmountId);
                useBlock[i] = mode == Mode.PropertyBlock || (mode == Mode.Auto && hasProps);
                if (r is SpriteRenderer sr) baseColors[i] = sr.color;
            }
        }

        void Apply(float amount)
        {
            for (int i = 0; i < renderers.Length; i++)
            {
                Renderer r = renderers[i];
                if (r == null) continue;
                if (useBlock[i])
                {
                    if (amount <= 0f) { r.SetPropertyBlock(null); continue; }
                    r.GetPropertyBlock(block);
                    block.SetFloat(FlashAmountId, amount);
                    block.SetColor(FlashColorId, flashColor);
                    r.SetPropertyBlock(block);
                }
                else if (r is SpriteRenderer sr)
                {
                    sr.color = amount <= 0f ? baseColors[i] : Color.Lerp(baseColors[i], tintColor, amount);
                }
            }
        }

        void OnDisable()
        {
            if (running != null) { running = null; }
            if (useBlock != null) Apply(0f);
        }
    }
}
