#if HARNESS_INPUTSYSTEM
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;

namespace Harness.Verify
{
    /// <summary>
    /// Key backend for <see cref="ScriptedInput"/>: a virtual Input System keyboard. Pressed keys are sent as
    /// keyboard state events, so PlayerInput, InputActionAssets, project-wide actions and Keyboard.current all
    /// see them like real keys. Key names are Input System <see cref="Key"/> names (Space, A, LeftArrow, Enter...),
    /// case-insensitive, plus the aliases left/right/up/down/jump/esc.
    ///
    /// Only compiled when com.unity.inputsystem is installed (versionDefines in the asmdef). Delete this folder if
    /// the project uses only the legacy Input Manager. Editor and development builds only.
    /// </summary>
    public static class VirtualKeyboard
    {
        static Keyboard s_Keyboard;
        static readonly HashSet<Key> s_Down = new HashSet<Key>();
        static bool s_SettingsChanged;
        static InputSettings.BackgroundBehavior s_OldBackground;
#if UNITY_EDITOR
        static InputSettings.EditorInputBehaviorInPlayMode s_OldEditorBehavior;
#endif

#if UNITY_EDITOR || DEVELOPMENT_BUILD
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void Install()
        {
            s_Keyboard = null;
            s_Down.Clear();
            s_SettingsChanged = false;
            ScriptedInput.KeyHandler = Handle;
            Application.quitting -= Restore;
            Application.quitting += Restore;
        }
#endif

        /// <summary>The virtual device (added on first use).</summary>
        public static Keyboard Device
        {
            get
            {
                if (s_Keyboard == null || !s_Keyboard.added)
                {
                    // Injected input must reach the game even when the Game view/editor is not focused.
                    // InputSystem.settings may be the project's settings asset: remember and restore on quit.
                    var settings = InputSystem.settings;
                    if (!s_SettingsChanged)
                    {
                        s_OldBackground = settings.backgroundBehavior;
#if UNITY_EDITOR
                        s_OldEditorBehavior = settings.editorInputBehaviorInPlayMode;
#endif
                        s_SettingsChanged = true;
                    }
#if UNITY_EDITOR
                    settings.editorInputBehaviorInPlayMode =
                        InputSettings.EditorInputBehaviorInPlayMode.AllDeviceInputAlwaysGoesToGameView;
#endif
                    settings.backgroundBehavior = InputSettings.BackgroundBehavior.IgnoreFocus;
                    s_Keyboard = InputSystem.AddDevice<Keyboard>("HarnessVirtualKeyboard");
                }
                return s_Keyboard;
            }
        }

        /// <summary>Releases keys, removes the device and restores the Input System settings it changed.</summary>
        public static void Restore()
        {
            ReleaseAll();
            if (s_Keyboard != null && s_Keyboard.added) InputSystem.RemoveDevice(s_Keyboard);
            s_Keyboard = null;
            if (!s_SettingsChanged) return;
            var settings = InputSystem.settings;
            settings.backgroundBehavior = s_OldBackground;
#if UNITY_EDITOR
            settings.editorInputBehaviorInPlayMode = s_OldEditorBehavior;
#endif
            s_SettingsChanged = false;
        }

        public static bool Handle(string name, bool down)
        {
            Key key;
            if (!TryParse(name, out key)) return false;
            if (down) s_Down.Add(key);
            else s_Down.Remove(key);
            var keys = new Key[s_Down.Count];
            s_Down.CopyTo(keys);
            InputSystem.QueueStateEvent(Device, new KeyboardState(keys));
            return true;
        }

        public static void ReleaseAll()
        {
            s_Down.Clear();
            if (s_Keyboard != null && s_Keyboard.added) InputSystem.QueueStateEvent(s_Keyboard, new KeyboardState());
        }

        public static bool TryParse(string name, out Key key)
        {
            switch (name.ToLowerInvariant())
            {
                case "left": key = Key.LeftArrow; return true;
                case "right": key = Key.RightArrow; return true;
                case "up": key = Key.UpArrow; return true;
                case "down": key = Key.DownArrow; return true;
                case "jump": key = Key.Space; return true;
                case "esc": key = Key.Escape; return true;
            }
            return Enum.TryParse(name, true, out key) && key != Key.None;
        }
    }
}
#endif
