// Harness.Safety.SafeEdit - editor-API helpers for scene/prefab/asset edits that keep Undo, prefab overrides
// and GUIDs intact. Use when the MCP tools (manage_prefabs/manage_gameobject/manage_components/manage_asset)
// cannot express the change. Callable from execute_code, editor scripts or -executeMethod. Unity 6000.3.
using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace Harness.Safety
{
    public static class SafeEdit
    {
        // ---------- Prefab assets (isolated, no scene involved) ----------

        /// <summary>Load prefab contents into an isolated scene, edit, save, unload. Never leaves the contents loaded.</summary>
        public static void EditPrefabAsset(string prefabPath, Action<GameObject> edit)
        {
            if (AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath) == null)
                throw new ArgumentException("No prefab at " + prefabPath);
            var root = PrefabUtility.LoadPrefabContents(prefabPath);
            try
            {
                edit(root);
                PrefabUtility.SaveAsPrefabAsset(root, prefabPath, out bool ok);
                if (!ok) throw new InvalidOperationException("SaveAsPrefabAsset failed for " + prefabPath);
            }
            finally
            {
                PrefabUtility.UnloadPrefabContents(root);
            }
        }

        /// <summary>Create a Prefab Variant of basePath at variantPath (keeps the link to the base).</summary>
        public static GameObject CreateVariant(string basePath, string variantPath, Action<GameObject> editInstance = null)
        {
            var basePrefab = AssetDatabase.LoadAssetAtPath<GameObject>(basePath);
            if (basePrefab == null) throw new ArgumentException("No prefab at " + basePath);
            if (AssetDatabase.LoadAssetAtPath<Object>(variantPath) != null)
                throw new InvalidOperationException("Refusing to overwrite " + variantPath);
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(basePrefab);
            try
            {
                editInstance?.Invoke(instance); // changes become overrides on the variant
                var variant = PrefabUtility.SaveAsPrefabAsset(instance, variantPath, out bool ok);
                if (!ok || PrefabUtility.GetPrefabAssetType(variant) != PrefabAssetType.Variant)
                    throw new InvalidOperationException("Variant creation failed for " + variantPath);
                return variant;
            }
            finally
            {
                Object.DestroyImmediate(instance);
            }
        }

        // ---------- Scene objects (undoable, marks the scene dirty) ----------

        /// <summary>Record, change, and register prefab-instance overrides for one object/component in an open scene.</summary>
        public static void EditSceneObject(Object target, string undoLabel, Action change)
        {
            Undo.RecordObject(target, undoLabel);
            change();
            if (PrefabUtility.IsPartOfPrefabInstance(target))
                PrefabUtility.RecordPrefabInstancePropertyModifications(target);
            var go = target is Component c ? c.gameObject : target as GameObject;
            if (go != null && go.scene.IsValid()) EditorSceneManager.MarkSceneDirty(go.scene);
            else EditorUtility.SetDirty(target); // assets (ScriptableObjects, materials)
        }

        /// <summary>Create a GameObject (or prefab instance when prefabPath is set) with Undo, in the active scene.</summary>
        public static GameObject CreateInScene(string name, Transform parent = null, string prefabPath = null)
        {
            GameObject go;
            if (!string.IsNullOrEmpty(prefabPath))
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                if (prefab == null) throw new ArgumentException("No prefab at " + prefabPath);
                go = (GameObject)PrefabUtility.InstantiatePrefab(prefab, parent != null ? parent.gameObject.scene : SceneManager.GetActiveScene());
                if (!string.IsNullOrEmpty(name)) go.name = name;
            }
            else go = new GameObject(name);
            Undo.RegisterCreatedObjectUndo(go, "Create " + go.name);
            if (parent != null) Undo.SetTransformParent(go.transform, parent, "Parent " + go.name);
            EditorSceneManager.MarkSceneDirty(go.scene);
            return go;
        }

        /// <summary>Add a component with Undo (use instead of AddComponent in editor code).</summary>
        public static T AddComponent<T>(GameObject go) where T : Component
        {
            var c = Undo.AddComponent<T>(go);
            EditorSceneManager.MarkSceneDirty(go.scene);
            return c;
        }

        /// <summary>Open a scene (single), run edit, save it. Refuses if the currently open scenes are dirty.</summary>
        public static void EditScene(string scenePath, Action<Scene> edit)
        {
            for (int i = 0; i < SceneManager.sceneCount; i++)
                if (SceneManager.GetSceneAt(i).isDirty)
                    throw new InvalidOperationException("Unsaved changes in " + SceneManager.GetSceneAt(i).path + "; save or discard first");
            var scene = EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single);
            edit(scene);
            EditorSceneManager.MarkSceneDirty(scene);
            if (!EditorSceneManager.SaveScene(scene)) throw new InvalidOperationException("SaveScene failed for " + scenePath);
        }

        /// <summary>Returns paths of loaded scenes with unsaved changes (empty list = safe).</summary>
        public static List<string> DirtyScenes()
        {
            var list = new List<string>();
            for (int i = 0; i < SceneManager.sceneCount; i++)
            {
                var s = SceneManager.GetSceneAt(i);
                if (s.isDirty) list.Add(string.IsNullOrEmpty(s.path) ? "<untitled>" : s.path);
            }
            return list;
        }

        // ---------- Assets (GUID-preserving) ----------

        /// <summary>Move/rename keeping the GUID (the .meta moves with it). Throws with Unity's reason on failure.</summary>
        public static void Move(string from, string to)
        {
            string err = AssetDatabase.ValidateMoveAsset(from, to);
            if (!string.IsNullOrEmpty(err)) throw new InvalidOperationException(err);
            err = AssetDatabase.MoveAsset(from, to);
            if (!string.IsNullOrEmpty(err)) throw new InvalidOperationException(err);
        }

        /// <summary>Duplicate with a NEW GUID (never copy a file together with its .meta).</summary>
        public static void Copy(string from, string to)
        {
            if (!AssetDatabase.CopyAsset(from, to)) throw new InvalidOperationException($"CopyAsset {from} -> {to} failed");
        }

        /// <summary>Batch many imports/moves into one refresh; always closed in finally.</summary>
        public static void Batch(Action work)
        {
            AssetDatabase.StartAssetEditing();
            try { work(); }
            finally { AssetDatabase.StopAssetEditing(); }
            AssetDatabase.SaveAssets();
        }
    }
}
