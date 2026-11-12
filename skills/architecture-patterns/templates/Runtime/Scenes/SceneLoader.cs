using System;
using System.Threading;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Harness.Arch
{
    /// <summary>Implement on a loading-screen MonoBehaviour in the Bootstrap scene and assign it to SceneLoader.</summary>
    public interface ILoadingScreen
    {
        Awaitable ShowAsync();
        void SetProgress(float progress01);
        Awaitable HideAsync();
    }

    /// <summary>
    /// Lives in the Bootstrap scene (never unloaded). Keeps exactly one "content" scene loaded additively on top
    /// (MainMenu, Run, Hub...). Uses Unity 6 Awaitable; every scene must be in Build Profiles / Build Settings.
    /// </summary>
    public sealed class SceneLoader : MonoBehaviour
    {
        [SerializeField, Tooltip("Component implementing ILoadingScreen (optional)")]
        MonoBehaviour loadingScreen;

        public static SceneLoader Instance { get; private set; }
        public string CurrentContentScene { get; private set; }
        public bool IsLoading { get; private set; }
        public event Action<string> ContentSceneLoaded;

        void Awake()
        {
            if (Instance != null && Instance != this) { Destroy(gameObject); return; }
            Instance = this;
            Services.Register(this);
        }

        void OnDestroy()
        {
            if (Instance == this) { Instance = null; Services.Unregister(this); }
        }

        /// <summary>Unload the current content scene, load sceneName additively, make it active.</summary>
        public async Awaitable LoadContentAsync(string sceneName, CancellationToken token = default)
        {
            if (IsLoading) throw new InvalidOperationException("SceneLoader is already loading");
            if (!Application.CanStreamedLevelBeLoaded(sceneName))
                throw new ArgumentException($"Scene '{sceneName}' is not in the build scene list");
            IsLoading = true;
            var screen = loadingScreen as ILoadingScreen;
            try
            {
                if (screen != null) await screen.ShowAsync();
                screen?.SetProgress(0f);

                if (!string.IsNullOrEmpty(CurrentContentScene) && SceneManager.GetSceneByName(CurrentContentScene).isLoaded)
                {
                    var unload = SceneManager.UnloadSceneAsync(CurrentContentScene);
                    if (unload != null) await unload;
                    CurrentContentScene = null;
                }

                var op = SceneManager.LoadSceneAsync(sceneName, LoadSceneMode.Additive);
                while (!op.isDone)
                {
                    screen?.SetProgress(Mathf.Clamp01(op.progress / 0.9f));
                    await Awaitable.NextFrameAsync(token);
                }

                var scene = SceneManager.GetSceneByName(sceneName);
                SceneManager.SetActiveScene(scene); // new objects + lighting go to the content scene
                CurrentContentScene = sceneName;
                await Resources.UnloadUnusedAssets();
                screen?.SetProgress(1f);
                ContentSceneLoaded?.Invoke(sceneName);
            }
            finally
            {
                IsLoading = false;
                if (screen != null) await screen.HideAsync();
            }
        }
    }
}
