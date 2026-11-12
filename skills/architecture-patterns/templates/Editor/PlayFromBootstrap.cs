using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Harness.Arch.Editor
{
    /// <summary>
    /// Toggle "Tools/Harness/Arch/Play From Bootstrap": Play always starts in the Bootstrap scene (build index 0),
    /// and Bootstrapper then loads the scene you were editing instead of its first content scene.
    /// </summary>
    [InitializeOnLoad]
    public static class PlayFromBootstrap
    {
        const string MenuPath = "Tools/Harness/Arch/Play From Bootstrap";
        const string PrefKey = "Harness.Arch.PlayFromBootstrap";

        static PlayFromBootstrap()
        {
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
            EditorApplication.delayCall += Apply;
        }

        [MenuItem(MenuPath)]
        static void Toggle()
        {
            EditorPrefs.SetBool(PrefKey, !EditorPrefs.GetBool(PrefKey, false));
            Apply();
        }

        [MenuItem(MenuPath, true)]
        static bool ToggleValidate()
        {
            Menu.SetChecked(MenuPath, EditorPrefs.GetBool(PrefKey, false));
            return true;
        }

        static void Apply()
        {
            bool on = EditorPrefs.GetBool(PrefKey, false);
            var scenes = EditorBuildSettings.scenes;
            SceneAsset bootstrap = null;
            if (on && scenes.Length > 0) bootstrap = AssetDatabase.LoadAssetAtPath<SceneAsset>(scenes[0].path);
            EditorSceneManager.playModeStartScene = bootstrap;
        }

        static void OnPlayModeChanged(PlayModeStateChange change)
        {
            if (change != PlayModeStateChange.ExitingEditMode || EditorSceneManager.playModeStartScene == null) return;
            var active = EditorSceneManager.GetActiveScene().path;
            SessionState.SetString(Bootstrapper.EditedSceneKey, active ?? "");
            Debug.Log("[PlayFromBootstrap] starting from Bootstrap, content scene: " + active);
        }
    }
}
