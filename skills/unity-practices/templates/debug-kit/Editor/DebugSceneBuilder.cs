#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace GdwKit.EditorTools
{
    /// <summary>
    /// Builds a small scene to reproduce one problem: camera, light, ground, the debug overlay and
    /// console, four spawn points, and the prefab under test. Saved under Assets/Scenes/Debug/ and
    /// never added to the build. Menu: Tools/Debug/Create Debug Scene (uses the selected prefab).
    /// Agents: DebugSceneBuilder.Create("PoolLeak", "Assets/Prefabs/Bullet.prefab") through MCP
    /// execute_code, or -executeMethod GdwKit.EditorTools.DebugSceneBuilder.CreateFromCommandLine
    /// -debugScene PoolLeak -debugPrefab Assets/Prefabs/Bullet.prefab. Prints RESULT: lines.
    /// </summary>
    public static class DebugSceneBuilder
    {
        public const string Folder = "Assets/Scenes/Debug";

        [MenuItem("Tools/Debug/Create Debug Scene")]
        private static void CreateFromMenu()
        {
            var selected = Selection.activeObject as GameObject;
            var prefabPath = selected ? AssetDatabase.GetAssetPath(selected) : "";
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            var name = selected ? selected.name : "Sandbox";
            var path = Create(name, prefabPath, allowDirty: true);
            if (path.StartsWith(Folder)) EditorGUIUtility.PingObject(AssetDatabase.LoadAssetAtPath<SceneAsset>(path));
        }

        public static void CreateFromCommandLine()
        {
            string name = "Sandbox", prefab = "";
            var args = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "-debugScene") name = args[i + 1];
                if (args[i] == "-debugPrefab") prefab = args[i + 1];
            }
            Create(name, prefab);
        }

        /// <summary>Returns the scene path, or a "RESULT: FAIL" message. Refuses while open scenes have unsaved changes.</summary>
        public static string Create(string name, string prefabPath = "", bool allowDirty = false, bool is2D = false)
        {
            for (int i = 0; i < SceneManager.sceneCount && !allowDirty; i++)
            {
                if (SceneManager.GetSceneAt(i).isDirty)
                    return Fail($"scene '{SceneManager.GetSceneAt(i).name}' has unsaved changes; save it first");
            }
            var safe = string.Concat(name.Split(Path.GetInvalidFileNameChars())).Replace(' ', '_');
            var path = $"{Folder}/Debug_{safe}.unity";
            if (File.Exists(path)) return Fail($"{path} exists; open it instead");

            var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            AddEnvironment(is2D);
            AddDebugObjects(is2D);

            if (!string.IsNullOrEmpty(prefabPath))
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                if (!prefab) return Fail($"no prefab at {prefabPath}");
                var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab, scene);
                instance.transform.position = Vector3.zero;
            }

            Directory.CreateDirectory(Folder);
            if (!EditorSceneManager.SaveScene(scene, path)) return Fail($"could not save {path}");
            Debug.Log($"RESULT: OK scene={path} (not in the build's scene list)");
            return path;
        }

        private static void AddEnvironment(bool is2D)
        {
            if (is2D)
            {
                var cam = Camera.main;
                if (cam) { cam.orthographic = true; cam.transform.position = new Vector3(0f, 0f, -10f); cam.transform.rotation = Quaternion.identity; }
                return;
            }
            var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "Ground";
            ground.transform.localScale = new Vector3(5f, 1f, 5f);
        }

        private static void AddDebugObjects(bool is2D)
        {
            var debug = new GameObject("Debug");
            debug.AddComponent<DebugOverlay>();
            debug.AddComponent<DebugConsole>();

            var spawns = new GameObject("SpawnPoints").transform;
            for (int i = 0; i < 4; i++)
            {
                var p = new GameObject($"Spawn_{i}").transform;
                p.SetParent(spawns, false);
                float a = i * Mathf.PI * 0.5f;
                p.localPosition = is2D ? new Vector3(Mathf.Cos(a) * 5f, Mathf.Sin(a) * 3f, 0f) : new Vector3(Mathf.Cos(a) * 8f, 0f, Mathf.Sin(a) * 8f);
            }
        }

        private static string Fail(string why)
        {
            var msg = $"RESULT: FAIL {why}";
            Debug.LogWarning(msg);
            return msg;
        }
    }
}
#endif
