using UnityEngine;
using UnityEngine.SceneManagement;

namespace Harness.Arch
{
    /// <summary>
    /// Put in the Bootstrap scene (build index 0) next to SceneLoader and other persistent systems.
    /// Registers services, loads meta-progression, then loads the first content scene.
    /// In the editor, Game.Editor's "Play From Bootstrap" stores the scene you were editing; it is loaded instead.
    /// </summary>
    public sealed class Bootstrapper : MonoBehaviour
    {
        public const string EditedSceneKey = "Harness.Arch.EditedScene";

        [SerializeField] string firstContentScene = "MainMenu";

        async void Start()
        {
            var store = JsonSaveStore.CreateDefault();
            Services.Register(store);
            var load = store.TryLoad<MetaProgress>("meta", out var meta);
            if (!load.ok)
            {
                if (!load.missing) Debug.LogWarning("[Bootstrap] meta save not loaded: " + load.error);
                meta = new MetaProgress();
            }
            Services.Register(meta);

            string target = firstContentScene;
#if UNITY_EDITOR
            string edited = UnityEditor.SessionState.GetString(EditedSceneKey, "");
            if (!string.IsNullOrEmpty(edited) && edited != SceneManager.GetActiveScene().path)
                target = System.IO.Path.GetFileNameWithoutExtension(edited);
            UnityEditor.SessionState.EraseString(EditedSceneKey);
#endif
            try
            {
                await Services.Get<SceneLoader>().LoadContentAsync(target, destroyCancellationToken);
            }
            catch (System.OperationCanceledException) { }
        }
    }
}
