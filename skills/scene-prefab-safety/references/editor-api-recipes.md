# Editor-API recipes (execute_code bodies / editor scripts)

Unity 6000.3. Each block is a valid `execute_code` method body (C# 6-compatible unless noted) or can go in an editor
script. `PrefabUtility.LoadPrefabContents`, `PrefabUtility.*` overrides API and `AssetDatabase.StartAssetEditing` are
confirmed on the 6000.3 docs; `EditorSceneManager.*` and `Undo.*` pages for 6000.3 were not fetched, but every block
below compiles on 6000.3.21f1, and SafeEdit's equivalents (EditPrefabAsset, CreateVariant, CreateInScene, EditScene,
EditSceneObject) ran in batchmode on the bench with only the intended files changing in `git status`.

If `SafeEdit.cs` is installed, prefer its one-liners (`Harness.Safety.SafeEdit.*`).

## 1. Edit a prefab asset in isolation
```csharp
var path = "Assets/Prefabs/Enemy.prefab";
var root = UnityEditor.PrefabUtility.LoadPrefabContents(path);
try {
    var hp = root.transform.Find("HealthBar");
    if (hp == null) return "HealthBar not found";
    hp.localPosition = new UnityEngine.Vector3(0, 1.2f, 0);
    bool ok;
    UnityEditor.PrefabUtility.SaveAsPrefabAsset(root, path, out ok);
    return ok ? "saved" : "SAVE FAILED";
} finally { UnityEditor.PrefabUtility.UnloadPrefabContents(root); }
```
Equivalent scope form (C# 8, Roslyn compiler): `using (var s = new PrefabUtility.EditPrefabContentsScope(path)) { s.prefabContentsRoot... }` saves on dispose.

## 2. Change a component on a scene object (undoable, keeps prefab overrides)
```csharp
var go = UnityEngine.GameObject.Find("Player");
var rb = go.GetComponent<UnityEngine.Rigidbody2D>();
UnityEditor.Undo.RecordObject(rb, "Set gravity");
rb.gravityScale = 0f;
if (UnityEditor.PrefabUtility.IsPartOfPrefabInstance(rb))
    UnityEditor.PrefabUtility.RecordPrefabInstancePropertyModifications(rb);
UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(go.scene);
UnityEditor.SceneManagement.EditorSceneManager.SaveScene(go.scene);
return "ok";
```
Serialized private fields: use `SerializedObject` instead of reflection; it records undo and overrides automatically:
```csharp
var so = new UnityEditor.SerializedObject(component);
so.FindProperty("maxHealth").intValue = 10;
so.ApplyModifiedProperties();   // undoable, marks dirty, records prefab override
```

## 3. Create objects and prefab instances
```csharp
var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/Enemy.prefab");
var inst = (UnityEngine.GameObject)UnityEditor.PrefabUtility.InstantiatePrefab(prefab);  // keeps the prefab link
UnityEditor.Undo.RegisterCreatedObjectUndo(inst, "Spawn enemy");
var col = UnityEditor.Undo.AddComponent<UnityEngine.CircleCollider2D>(inst);
UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(inst.scene);
UnityEditor.SceneManagement.EditorSceneManager.SaveScene(inst.scene);
return inst.name;
```
Delete with undo: `Undo.DestroyObjectImmediate(go)`. Re-parent with undo: `Undo.SetTransformParent(child, parent, "label")`.

## 4. Open, edit and save a scene that is not open
```csharp
for (int i = 0; i < UnityEngine.SceneManagement.SceneManager.sceneCount; i++)
    if (UnityEngine.SceneManagement.SceneManager.GetSceneAt(i).isDirty) return "dirty scene open: save first";
var scene = UnityEditor.SceneManagement.EditorSceneManager.OpenScene("Assets/Scenes/Level1.unity",
    UnityEditor.SceneManagement.OpenSceneMode.Single);
// ... edit ...
UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(scene);
return UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene) ? "saved" : "SAVE FAILED";
```
Additive: `OpenSceneMode.Additive`, then `EditorSceneManager.CloseScene(scene, true)` after saving.

## 5. Assets: move, rename, copy, delete (GUID-safe)
```csharp
var err = UnityEditor.AssetDatabase.ValidateMoveAsset("Assets/Old/a.png", "Assets/Art/Sprites/a.png");
if (!string.IsNullOrEmpty(err)) return err;
err = UnityEditor.AssetDatabase.MoveAsset("Assets/Old/a.png", "Assets/Art/Sprites/a.png"); // "" = success
// Rename in place (name without extension): AssetDatabase.RenameAsset(path, "newName")
// Duplicate with new GUID:                  AssetDatabase.CopyAsset(src, dst)  -> bool
// Delete:                                   AssetDatabase.DeleteAsset(path) or MoveAssetToTrash(path)
return string.IsNullOrEmpty(err) ? "moved" : err;
```
Bulk: wrap in `AssetDatabase.StartAssetEditing(); try { … } finally { AssetDatabase.StopAssetEditing(); }`. A missing
`StopAssetEditing` leaves the AssetDatabase unresponsive.

## 6. Report missing scripts in the open scene (read-only)
```csharp
var sb = new System.Text.StringBuilder();
foreach (var root in UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects())
    foreach (var t in root.GetComponentsInChildren<UnityEngine.Transform>(true)) {
        int n = UnityEditor.GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(t.gameObject);
        if (n > 0) sb.AppendLine(t.name + ": " + n);
    }
return sb.Length == 0 ? "none" : sb.ToString();
```
Full audit across scenes and prefabs: `Harness.Safety.SceneAudit.RunToString("build")`.

## 7. Find who references an asset (before deleting/moving)
```csharp
var target = UnityEditor.AssetDatabase.AssetPathToGUID("Assets/Art/Sprites/a.png");
var hits = new System.Collections.Generic.List<string>();
foreach (var p in UnityEditor.AssetDatabase.GetAllAssetPaths())
    if (p.StartsWith("Assets/") && System.Array.IndexOf(UnityEditor.AssetDatabase.GetDependencies(p, false),
        "Assets/Art/Sprites/a.png") >= 0) hits.Add(p);
return target + " used by: " + string.Join(", ", hits.ToArray());
```
