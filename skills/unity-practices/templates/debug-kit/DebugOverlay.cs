using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using Unity.Profiling;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace GdwKit
{
    /// <summary>
    /// FPS, frame time, GC allocated this frame, and watched values, drawn with IMGUI (no UI setup).
    /// F1 toggles it. Disabled in release builds. Add watches from anywhere:
    /// DebugOverlay.Watch("enemies", count); calls are compiled out of release builds.
    /// </summary>
    public sealed class DebugOverlay : MonoBehaviour
    {
        [SerializeField] private bool visible = true;
        [SerializeField, Range(0.1f, 2f)] private float refreshSeconds = 0.25f;
        [SerializeField, Range(10, 40)] private int fontSize = 14;

        private static readonly Dictionary<string, string> _watches = new Dictionary<string, string>();
        private readonly StringBuilder _sb = new StringBuilder(512);
        private ProfilerRecorder _gcAlloc;
        private ProfilerRecorder _mainThread;
        private float _nextRefresh;
        private int _frames;
        private float _elapsed;
        private string _text = "";
        private GUIStyle _style;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetStatics() => _watches.Clear();

        [Conditional("UNITY_EDITOR"), Conditional("DEVELOPMENT_BUILD")]
        public static void Watch(string key, object value) => _watches[key] = value?.ToString() ?? "null";

        [Conditional("UNITY_EDITOR"), Conditional("DEVELOPMENT_BUILD")]
        public static void Unwatch(string key) => _watches.Remove(key);

        private void Awake()
        {
            if (!Debug.isDebugBuild) enabled = false;
        }

        private void OnEnable()
        {
            _gcAlloc = ProfilerRecorder.StartNew(ProfilerCategory.Memory, "GC Allocated In Frame");
            _mainThread = ProfilerRecorder.StartNew(ProfilerCategory.Internal, "Main Thread", 15);
        }

        private void OnDisable()
        {
            _gcAlloc.Dispose();
            _mainThread.Dispose();
        }

        private void Update()
        {
            if (DebugInput.TogglePressed(DebugInput.Key.F1)) visible = !visible;
            _frames++;
            _elapsed += Time.unscaledDeltaTime;
            if (Time.unscaledTime < _nextRefresh) return;
            _nextRefresh = Time.unscaledTime + refreshSeconds;
            Rebuild();
        }

        private void Rebuild()
        {
            _sb.Clear();
            float fps = _elapsed > 0f ? _frames / _elapsed : 0f;
            _sb.Append("FPS ").Append(fps.ToString("0")).Append("  ").Append((1000f / Mathf.Max(fps, 0.01f)).ToString("0.0")).Append(" ms");
            if (_mainThread.Valid && _mainThread.Count > 0)
                _sb.Append("  main ").Append((_mainThread.LastValue * 1e-6).ToString("0.0")).Append(" ms");
            if (_gcAlloc.Valid)
                _sb.Append("\nGC alloc/frame ").Append(_gcAlloc.LastValue).Append(" B");
            foreach (var kv in _watches) _sb.Append('\n').Append(kv.Key).Append(": ").Append(kv.Value);
            _text = _sb.ToString();
            _frames = 0;
            _elapsed = 0f;
        }

        private void OnGUI()
        {
            if (!visible) return;
            if (_style == null)
                _style = new GUIStyle(GUI.skin.box) { fontSize = fontSize, alignment = TextAnchor.UpperLeft, richText = false };
            var size = _style.CalcSize(new GUIContent(_text));
            GUI.Box(new Rect(8, 8, size.x + 12, size.y + 8), _text, _style);
        }
    }

    /// <summary>Key checks that work with the Input System, the old Input Manager, or both.</summary>
    public static class DebugInput
    {
        public enum Key { F1, BackQuote, Return, Escape, UpArrow }

        public static bool TogglePressed(Key key)
        {
#if ENABLE_INPUT_SYSTEM
            var kb = UnityEngine.InputSystem.Keyboard.current;
            if (kb == null) return false;
            switch (key)
            {
                case Key.F1: return kb.f1Key.wasPressedThisFrame;
                case Key.BackQuote: return kb.backquoteKey.wasPressedThisFrame;
                case Key.Return: return kb.enterKey.wasPressedThisFrame || kb.numpadEnterKey.wasPressedThisFrame;
                case Key.Escape: return kb.escapeKey.wasPressedThisFrame;
                case Key.UpArrow: return kb.upArrowKey.wasPressedThisFrame;
            }
            return false;
#elif ENABLE_LEGACY_INPUT_MANAGER
            switch (key)
            {
                case Key.F1: return Input.GetKeyDown(KeyCode.F1);
                case Key.BackQuote: return Input.GetKeyDown(KeyCode.BackQuote);
                case Key.Return: return Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter);
                case Key.Escape: return Input.GetKeyDown(KeyCode.Escape);
                case Key.UpArrow: return Input.GetKeyDown(KeyCode.UpArrow);
            }
            return false;
#else
            return false;
#endif
        }
    }
}
