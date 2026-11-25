using System.Collections.Generic;
using UnityEngine;

namespace GdwKit
{
    /// <summary>A minimal IMGUI console for DebugCommands. Backquote opens it. Disabled in release builds.</summary>
    public sealed class DebugConsole : MonoBehaviour
    {
        [SerializeField, Range(4, 40)] private int keepLines = 12;

        private readonly List<string> _lines = new List<string>();
        private readonly List<string> _history = new List<string>();
        private string _input = "";
        private bool _open;
        private bool _focus;

        private void Awake()
        {
            if (!Debug.isDebugBuild) enabled = false;
        }

        private void Update()
        {
            if (DebugInput.TogglePressed(DebugInput.Key.BackQuote))
            {
                _open = !_open;
                _focus = _open;
            }
        }

        private void OnGUI()
        {
            if (!_open) return;
            var e = Event.current;
            // Update toggles on the backquote key; keep its character out of the text field.
            if (e.type == EventType.KeyDown && (e.keyCode == KeyCode.BackQuote || e.character == '`')) { e.Use(); return; }
            if (e.type == EventType.KeyDown && (e.keyCode == KeyCode.Return || e.keyCode == KeyCode.KeypadEnter))
            {
                Submit();
                e.Use();
            }
            if (e.type == EventType.KeyDown && e.keyCode == KeyCode.UpArrow && _history.Count > 0)
            {
                _input = _history[_history.Count - 1];
                e.Use();
            }
            float h = 22f * (keepLines + 1) + 8f;
            GUILayout.BeginArea(new Rect(8, Screen.height - h - 8, Mathf.Min(Screen.width - 16, 720), h), GUI.skin.box);
            foreach (var l in _lines) GUILayout.Label(l);
            GUI.SetNextControlName("gdw-console");
            _input = GUILayout.TextField(_input);
            GUILayout.EndArea();
            if (_focus) { GUI.FocusControl("gdw-console"); _focus = false; }
        }

        private void Submit()
        {
            var line = _input.Trim();
            _input = "";
            if (line.Length == 0) return;
            _history.Add(line);
            Add("> " + line);
            foreach (var l in DebugCommands.Run(line).Split('\n')) Add(l);
        }

        private void Add(string line)
        {
            _lines.Add(line);
            while (_lines.Count > keepLines) _lines.RemoveAt(0);
        }
    }
}
