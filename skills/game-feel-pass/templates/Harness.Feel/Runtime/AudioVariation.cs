using UnityEngine;
using UnityEngine.Audio;

namespace Harness.Feel
{
    /// <summary>
    /// Plays one of several clips with random pitch/volume so repeated hits do not sound identical
    /// (pitch +-5..10% is the usual range). Owns a small round-robin set of AudioSources (voices), so changing
    /// pitch never affects a sound that is already playing and the number of overlapping copies is capped.
    /// Audio is not slowed by Time.timeScale, so hit-stop does not stretch it.
    /// </summary>
    public sealed class AudioVariation : MonoBehaviour
    {
        public AudioClip[] clips;
        public Vector2 pitchRange = new Vector2(0.92f, 1.08f);
        public Vector2 volumeRange = new Vector2(0.85f, 1f);
        [Range(1, 16)] public int voices = 4;
        [Tooltip("Ignore Play calls closer together than this (seconds, unscaled): ten enemies hit in one frame = one sound.")]
        public float minInterval = 0.03f;
        public bool avoidRepeat = true;
        public AudioMixerGroup output;
        [Range(0f, 1f)] public float spatialBlend;

        AudioSource[] sources;
        int nextVoice;
        int lastClip = -1;
        float lastPlayTime = float.NegativeInfinity;

        void Awake() => EnsureSources();

        void EnsureSources()
        {
            if (sources != null && sources.Length == voices) return;
            sources = new AudioSource[Mathf.Max(1, voices)];
            for (int i = 0; i < sources.Length; i++)
            {
                AudioSource s = gameObject.AddComponent<AudioSource>();
                s.playOnAwake = false;
                s.outputAudioMixerGroup = output;
                s.spatialBlend = spatialBlend;
                sources[i] = s;
            }
        }

        public void Play() => Play(1f);

        public void Play(float volumeScale)
        {
            if (clips == null || clips.Length == 0 || !isActiveAndEnabled) return;
            float now = Time.unscaledTime;
            if (now - lastPlayTime < minInterval) return;
            lastPlayTime = now;
            EnsureSources();
            int idx = Random.Range(0, clips.Length);
            if (avoidRepeat && clips.Length > 1 && idx == lastClip) idx = (idx + 1 + Random.Range(0, clips.Length - 1)) % clips.Length;
            lastClip = idx;
            AudioSource s = sources[nextVoice];
            nextVoice = (nextVoice + 1) % sources.Length;
            s.clip = clips[idx];
            s.pitch = Random.Range(pitchRange.x, pitchRange.y);
            s.volume = Random.Range(volumeRange.x, volumeRange.y) * volumeScale;
            s.Play();
            FeelLog.Log("Audio", "clip", idx, "pitch", s.pitch, this);
        }
    }
}
