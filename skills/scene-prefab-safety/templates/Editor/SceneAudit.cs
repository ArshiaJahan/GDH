// Harness.Safety.SceneAudit - reports missing scripts and missing object references in scenes and prefabs.
// Drop into any Editor folder (or keep the Harness.Safety.Editor.asmdef next to it). Unity 6000.3.
//
// Menu:      Tools/Harness/Safety/Audit Build Scenes + Prefabs
// Batchmode: Unity -batchmode -nographics -projectPath <P> -logFile <log>     (no -quit: the exit is deferred, see BatchExit)
//              -executeMethod Harness.Safety.SceneAudit.RunBatch [-auditScope build|all] [-auditReport <file.json>]
//            Exit 0 = clean, 1 = problems found, 2 = audit crashed. Log line: "SceneAudit RESULT: OK|FAIL ..."
//            With -quit it still works, but every failure becomes exit 1. scripts/scene_audit.sh runs it without -quit.
// MCP:       execute_code: return Harness.Safety.SceneAudit.RunToString("build");
//
// The audit never saves anything: scenes are opened read-only-in-practice and closed without saving,
// prefabs are loaded with LoadPrefabContents and unloaded without SaveAsPrefabAsset.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Harness.Safety
{
    public static class SceneAudit
    {
        [Serializable]
        public sealed class Issue
        {
            public string kind;      // MissingScript | MissingReference | MissingPrefabAsset
            public string asset;     // scene or prefab path
            public string objectPath;
            public string component;
            public string property;
            public override string ToString() =>
                $"{kind} {asset} :: {objectPath}" + (component != null ? $" [{component}]" : "") + (property != null ? $" .{property}" : "");
        }

        [Serializable]
        public sealed class Report
        {
            public string scope;
            public int scenes;
            public int prefabs;
            public int missingScripts;
            public int missingReferences;
            public int missingPrefabAssets;
            public List<Issue> issues = new List<Issue>();
            public bool Clean => missingScripts == 0 && missingReferences == 0 && missingPrefabAssets == 0;
            public string Summary =>
                $"{(Clean ? "OK" : "FAIL")} scope={scope} scenes={scenes} prefabs={prefabs} missingScripts={missingScripts} " +
                $"missingReferences={missingReferences} missingPrefabAssets={missingPrefabAssets}";
        }

        [MenuItem("Tools/Harness/Safety/Audit Build Scenes + Prefabs")]
        static void MenuBuild() => RunInteractive("build");

        [MenuItem("Tools/Harness/Safety/Audit All Scenes + Prefabs")]
        static void MenuAll() => RunInteractive("all");

        static void RunInteractive(string scope)
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            var setup = EditorSceneManager.GetSceneManagerSetup();
            try
            {
                var r = Run(scope);
                foreach (var i in r.issues) Debug.LogWarning("SceneAudit " + i);
                Debug.Log("SceneAudit RESULT: " + r.Summary);
            }
            finally
            {
                if (setup.Length > 0 && setup.All(s => !string.IsNullOrEmpty(s.path)))
                    EditorSceneManager.RestoreSceneManagerSetup(setup);
            }
        }

        /// <summary>For execute_code: runs the audit, restores the open scenes, returns the summary + issues.</summary>
        public static string RunToString(string scope = "build")
        {
            if (SceneManager.loadedSceneCount > 0)
                for (int i = 0; i < SceneManager.sceneCount; i++)
                    if (SceneManager.GetSceneAt(i).isDirty)
                        return "SceneAudit RESULT: FAIL dirty scene open (" + SceneManager.GetSceneAt(i).path + "); save it first";
            var setup = EditorSceneManager.GetSceneManagerSetup();
            try
            {
                var r = Run(scope);
                var sb = new StringBuilder("SceneAudit RESULT: " + r.Summary);
                foreach (var i in r.issues.Take(200)) sb.Append('\n').Append(i);
                return sb.ToString();
            }
            finally
            {
                if (setup.Length > 0 && setup.All(s => !string.IsNullOrEmpty(s.path)))
                    EditorSceneManager.RestoreSceneManagerSetup(setup);
            }
        }

        /// <summary>Batchmode entry point. Runs synchronously, then exits the editor with 0/1/2 one tick later (BatchExit).</summary>
        public static void RunBatch()
        {
            int code;
            try
            {
                var args = Environment.GetCommandLineArgs();
                string scope = Arg(args, "-auditScope") ?? "build";
                string reportPath = Arg(args, "-auditReport");
                var r = Run(scope);
                foreach (var i in r.issues) Debug.Log("SceneAudit ISSUE " + i);
                if (!string.IsNullOrEmpty(reportPath)) File.WriteAllText(reportPath, JsonUtility.ToJson(r, true));
                Debug.Log("SceneAudit RESULT: " + r.Summary);
                code = r.Clean ? 0 : 1;
            }
            catch (Exception e)
            {
                Debug.LogError("SceneAudit RESULT: FAIL crashed: " + e);
                code = 2;
            }
            BatchExit(code);
        }

        // ⚠ version-sensitive: on 6000.3.21f1 a synchronous EditorApplication.Exit inside -executeMethod at startup crashed
        // once during domain unload (exit 134). Defer it one editor tick and keep the code in SessionState so a domain
        // reload cannot drop it (same pattern as headless-ops' HarnessCli.Exit). With -quit: return (0) or throw (exit 1).
        // In an interactive editor (menu, execute_code) it does nothing.
        const string PendingExitKey = "Harness.Safety.PendingExit";

        static void BatchExit(int code)
        {
            if (!Application.isBatchMode) return;
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-quit") >= 0)
            {
                if (code != 0) throw new Exception("SceneAudit failed with code " + code);
                return;
            }
            SessionState.SetInt(PendingExitKey, code + 1);
            EditorApplication.delayCall += () => EditorApplication.Exit(code);
        }

        [InitializeOnLoadMethod]
        static void ExitAfterReload()
        {
            if (!Application.isBatchMode) return;
            int pending = SessionState.GetInt(PendingExitKey, 0);
            if (pending == 0) return;
            SessionState.EraseInt(PendingExitKey);
            EditorApplication.delayCall += () => EditorApplication.Exit(pending - 1);
        }

        /// <summary>scope: "build" = enabled scenes in Build Settings, "all" = every .unity under Assets/. Prefabs: all under Assets/.</summary>
        public static Report Run(string scope)
        {
            var report = new Report { scope = scope };
            IEnumerable<string> scenePaths = scope == "all"
                ? AssetDatabase.FindAssets("t:Scene", new[] { "Assets" }).Select(AssetDatabase.GUIDToAssetPath)
                : EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path);

            foreach (var path in scenePaths.Where(p => !string.IsNullOrEmpty(p) && File.Exists(p)).Distinct())
            {
                var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
                foreach (var root in scene.GetRootGameObjects()) AuditHierarchy(root, path, report);
                report.scenes++;
            }

            foreach (var guid in AssetDatabase.FindAssets("t:Prefab", new[] { "Assets" }))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (!path.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase)) continue; // skip models
                GameObject root = null;
                try
                {
                    root = PrefabUtility.LoadPrefabContents(path);
                    AuditHierarchy(root, path, report);
                    report.prefabs++;
                }
                catch (Exception e)
                {
                    report.issues.Add(new Issue { kind = "MissingPrefabAsset", asset = path, objectPath = "<load failed> " + e.Message });
                    report.missingPrefabAssets++;
                }
                finally
                {
                    if (root != null) PrefabUtility.UnloadPrefabContents(root);
                }
            }

            return report;
        }

        static void AuditHierarchy(GameObject root, string assetPath, Report report)
        {
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
            {
                var go = t.gameObject;
                string goPath = PathOf(t);

                int missing = GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(go);
                if (missing > 0)
                {
                    report.missingScripts += missing;
                    report.issues.Add(new Issue { kind = "MissingScript", asset = assetPath, objectPath = goPath, component = missing + " missing" });
                }

                if (PrefabUtility.IsPrefabAssetMissing(go) && PrefabUtility.IsOutermostPrefabInstanceRoot(go))
                {
                    report.missingPrefabAssets++;
                    report.issues.Add(new Issue { kind = "MissingPrefabAsset", asset = assetPath, objectPath = goPath });
                }

                foreach (var c in go.GetComponents<Component>())
                {
                    if (c == null) continue; // counted as missing script above
                    var so = new SerializedObject(c);
                    var it = so.GetIterator();
                    bool enterChildren = true;
                    while (it.Next(enterChildren))
                    {
                        enterChildren = it.propertyType != SerializedPropertyType.String; // skip char arrays
                        if (it.propertyType != SerializedPropertyType.ObjectReference) continue;
                        if (it.name == "m_Script" || it.name == "m_PrefabInstance" || it.name == "m_PrefabAsset" ||
                            it.name == "m_CorrespondingSourceObject") continue;
                        // A "Missing (Type)" reference keeps a non-zero instance ID while the object is gone.
                        if (it.objectReferenceValue == null && it.objectReferenceInstanceIDValue != 0)
                        {
                            report.missingReferences++;
                            report.issues.Add(new Issue
                            {
                                kind = "MissingReference", asset = assetPath, objectPath = goPath,
                                component = c.GetType().Name, property = it.propertyPath
                            });
                        }
                    }
                }
            }
        }

        static string PathOf(Transform t)
        {
            var sb = new StringBuilder(t.name);
            for (var p = t.parent; p != null; p = p.parent) sb.Insert(0, p.name + "/");
            return sb.ToString();
        }

        static string Arg(string[] args, string name)
        {
            int i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }
    }
}
