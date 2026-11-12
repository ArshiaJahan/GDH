---
name: scene-prefab-safety
description: Edits Unity 6 (6000.3) scenes, prefabs, prefab variants and asset files without breaking GUIDs, .meta files, prefab overrides or references - MCP-first call order, editor-API fallbacks (PrefabUtility, EditorSceneManager, Undo, AssetDatabase.MoveAsset), the YAML hand-edit procedure, a .meta/GUID checker and a missing-script/reference audit. Use when editing a scene or prefab, moving/renaming/duplicating/deleting assets, fixing "Missing (Mono Script)" or broken references, or before committing scene/prefab changes.
---

# scene-prefab-safety

Edit scenes, prefabs and assets through Unity's own APIs so GUIDs, overrides and references survive, and prove it afterwards.

Pinned: Unity 6000.3 LTS (tested 6000.3.21f1, macOS), MCP for Unity 10.3, Force Text serialization + Visible Meta Files (6000.3 defaults).
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. mcp__UnityMCP__read_console). For tool parameters see unity-mcp-orchestrator.

## When to use
- Any change to `.unity`, `.prefab`, `.asset`, `.mat` or other serialized assets; any move/rename/copy/delete of files under `Assets/`.
- Creating prefab variants or nested prefabs; applying or reverting overrides.
- Console shows "The referenced script on this Behaviour is missing", "Missing (…)" fields, or merge conflicts in scenes.

Not for: writing C# gameplay code (compile-fix-loop), import settings (asset-pipeline), git merge setup (vcs-hygiene), headless runners in general (headless-ops).

## Inputs
- Project root, the target scene/prefab/asset paths, and the intended change in one sentence.
- Whether an editor is open on the project (MCP route) or not (batchmode route via headless-ops).

## Procedure
1. **Pick the instance.** Read `mcpforunity://instances`, call `set_active_instance`, then read `mcpforunity://editor/state`; proceed only when `ready_for_tools` is true and `is_compiling` is false.
2. **Snapshot before.** Save open scenes first (`manage_scene(action="save")`) only if they hold the user's intended work; otherwise ask. Then record the baseline:
   ```bash
   git -C "$P" status --porcelain > /tmp/sps_before.txt; git -C "$P" diff --stat > /tmp/sps_before_stat.txt
   python3 <skill>/scripts/meta_check.py "$P"    # must already be RESULT: OK, or note pre-existing problems
   ```
   Files that were already dirty are the user's; never revert them.
3. **Dry-run where the tool supports it.** `manage_scriptable_object(action="modify", dry_run=true)` for SO patches; `manage_scene(action="validate")` (no `auto_repair`) reports missing scripts without changing anything; read the prefab first with `manage_prefabs(action="get_hierarchy")`.
4. **Edit with MCP tools, in this order of preference:**
   - Prefab asset contents: `manage_prefabs(action="modify_contents", prefab_path=…, target=…, component_properties|create_child|delete_child|components_to_add=…)`. Headless; saves the prefab itself.
   - Interactive prefab work: `manage_prefabs(open_prefab_stage)` → `manage_gameobject` / `manage_components` → `manage_prefabs(save_prefab_stage)` → `manage_prefabs(close_prefab_stage)`. Always close the stage.
   - Scene objects: `manage_scene(action="load", path=…)` → `manage_gameobject` / `manage_components` → `manage_scene(action="save")`.
   - Assets: `manage_asset(action="move"|"rename"|"duplicate"|"create_folder", path=…, destination=…)`.
   - Many edits: one `batch_execute(commands=[…], fail_fast=true)`.
5. **Fallback: editor API** when a tool cannot express the change. Use `execute_code` with the calls below, or drop `templates/Editor/SafeEdit.cs` into an `Editor` folder and call its helpers. Recipes: [references/editor-api-recipes.md](references/editor-api-recipes.md) (read when writing execute_code or an editor script).
   - Prefab asset: `PrefabUtility.LoadPrefabContents(path)` → edit → `SaveAsPrefabAsset(root, path)` → `UnloadPrefabContents(root)` in `finally` (or `SafeEdit.EditPrefabAsset`).
   - Scene object: `Undo.RecordObject(obj, label)` → change → `PrefabUtility.RecordPrefabInstancePropertyModifications(obj)` if it is a prefab instance → `EditorSceneManager.MarkSceneDirty(scene)` → `EditorSceneManager.SaveScene(scene)`.
   - New objects: `Undo.RegisterCreatedObjectUndo(go, label)`; components via `Undo.AddComponent<T>`; prefab instances via `PrefabUtility.InstantiatePrefab` (never `Object.Instantiate`, which breaks the prefab link).
   - Asset edits (SO, material): `Undo.RecordObject` → change → `EditorUtility.SetDirty(asset)` → `AssetDatabase.SaveAssets()`.
   - Bulk asset operations: wrap in `AssetDatabase.StartAssetEditing()` / `StopAssetEditing()` inside try/finally (`SafeEdit.Batch`).
6. **YAML hand-edit only if unavoidable** (merge conflict, editor cannot open the file, mass GUID re-point). Follow [references/yaml-hand-edit.md](references/yaml-hand-edit.md) exactly: close the editor, back up, edit, validate, reopen.
7. **Save and verify** (section Verify). Then compare `git status --porcelain` with `/tmp/sps_before.txt`; every new entry must be an intended file.

## Rules
- **Layer, don't replace:** when replacing a system, prefab or scene, build the new one beside the old, verify parity with play-verify, then remove the old in a separate step with user approval. Use the harness's `replace-system` workflow when available.

### GUID and .meta integrity
- Never delete, regenerate or hand-write a `.meta`. Its `guid:` is the identity every reference uses.
- Move/rename only with `manage_asset(move|rename)`, `AssetDatabase.MoveAsset` / `RenameAsset`, or the Project window. Never `mv` in the shell: it bypasses the AssetDatabase, a file that arrives without its `.meta` gets a new GUID (every reference breaks), and with the editor open the importer can see the file before the `.meta`.
- If a shell move is truly unavoidable (editor closed), move the file AND its `.meta` together in one step, and folders with their folder `.meta`; then run `meta_check.py --refs`.
- Duplicate only with `manage_asset(action="duplicate")` or `AssetDatabase.CopyAsset`. Never `cp` a file with its `.meta`: that creates a duplicate GUID and Unity reassigns one at random.
- Replacing an asset's content (e.g. placeholder art → final art): overwrite the bytes of the existing file at the same path and keep its `.meta`; references stay intact.
- Delete with `manage_asset(action="delete")` / `AssetDatabase.DeleteAsset` (or `MoveAssetToTrash`) after confirming nothing references it (`meta_check.py --refs` after the delete, or the editor's "Find References in Scene").
- Folders need `.meta` too. Create them with `manage_asset(action="create_folder")` or `AssetDatabase.CreateFolder`.

### Scenes
- One scene edit session at a time. Never leave a scene dirty: end every task with `manage_scene(action="save")` or `EditorSceneManager.SaveScene`.
- Do not open another scene (`OpenSceneMode.Single`) while the current one is dirty; that discards or prompts. Check `SafeEdit.DirtyScenes()` or `scene.isDirty` first.
- Do not edit scenes during Play mode; changes are lost on stop. Check `mcpforunity://editor/state` first.
- Additive editing (`manage_scene(load, additive=true)`): save each scene you touched, then `close_scene`.

### Prefabs, variants, nesting
- Change shared structure on the prefab asset, per-instance values as overrides on the instance. Do not unpack prefabs to "fix" something.
- Variants inherit from their base: edit the base for changes all variants need, the variant for differences only. Do not re-parent a variant onto a different base; create a new variant.
- Nested prefabs: edit the inner prefab in its own asset; an edit made through the outer prefab becomes an override on the outer one.
- After scripted instance changes always call `PrefabUtility.RecordPrefabInstancePropertyModifications`, or the change is lost on reload.
- Apply overrides deliberately (`PrefabUtility.ApplyPrefabInstance` / `ApplyPropertyOverride`); review `HasPrefabInstanceAnyOverrides` first. Clean stale overrides with `PrefabUtility.RemoveUnusedOverrides`.
- Details and variant creation code: [references/prefab-rules.md](references/prefab-rules.md) (read when creating variants, nesting prefabs or applying overrides).

### Missing scripts and references
- Do not auto-remove missing scripts (`manage_scene(validate, auto_repair=true)`, `GameObjectUtility.RemoveMonoBehavioursWithMissingScript`) until you know why the script is missing. Usual causes: a compile error (fix with compile-fix-loop, then re-audit), a renamed class or file (restore the name, or move the file with its `.meta`), or a deleted `.meta` (restore it from git).
- A missing reference after a move means the GUID changed. Restore the original `.meta` from git rather than re-linking by hand.

## Failure handling / stop conditions
- `meta_check.py` reports `duplicate_guid` or `missing_meta` you did not cause: stop and report; do not "fix" by deleting metas.
- `SaveAsPrefabAsset` returns `success=false`, or SceneAudit shows new issues after your edit: undo your change (`manage_editor(action="undo")` or restore the file with `git restore <file>` only if it was clean in `/tmp/sps_before.txt`), then report.
- MCP connection drops mid-edit (domain reload): wait for `ready_for_tools`, re-read the hierarchy, and check whether the edit landed before retrying. Never apply the same edit twice blindly.
- The editor holds the project and you need batchmode: stop; use the MCP route or ask the user to close the editor.

## Scripts and templates
- `scripts/meta_check.py [project] [--refs] [--strict] [--json]`: missing/orphan/bad `.meta`, duplicate GUIDs, and with `--refs` YAML references to GUIDs that exist nowhere (project, `Library/PackageCache`, built-in `0000000000000000e/f/d000000000000000`). Exit 0 clean, 1 problems, 2 setup error.
- `templates/Editor/SceneAudit.cs` (`Harness.Safety.SceneAudit`): opens enabled Build Settings scenes (or all) and every prefab, reports missing scripts (`GameObjectUtility.GetMonoBehavioursWithMissingScriptCount`), missing references (`objectReferenceValue == null && objectReferenceInstanceIDValue != 0`) and missing prefab assets. Menu `Tools/Harness/Safety/…`, `execute_code` via `RunToString`, batchmode via `RunBatch`.
- `templates/Editor/SafeEdit.cs` (`Harness.Safety.SafeEdit`): `EditPrefabAsset`, `CreateVariant`, `EditSceneObject`, `CreateInScene`, `AddComponent<T>`, `EditScene`, `DirtyScenes`, `Move`, `Copy`, `Batch`.
- `templates/Editor/Harness.Safety.Editor.asmdef`: optional, editor-only assembly for both files.
- `scripts/scene_audit.sh <project> [build|all] [timeout]`: SceneAudit in batchmode (project must be closed).

Install: copy `templates/Editor/` to `Assets/Harness/Safety/Editor/` with `manage_asset`, or with `cp` (new files, Unity creates the metas), then wait for compilation (`mcpforunity://editor/state`) and `read_console(types=["error"])`.

## Verify
Run all four; each must pass.
1. **GUID integrity**: `python3 <skill>/scripts/meta_check.py "$P" --refs` prints `RESULT: OK` and exits 0. If `Library/PackageCache` is missing it prints WARN lines; open the project once and re-run.
2. **No missing scripts/references**:
   - Editor open: `execute_code(action="execute", code="return Harness.Safety.SceneAudit.RunToString(\"build\");")` returns `SceneAudit RESULT: OK … missingScripts=0 missingReferences=0 missingPrefabAssets=0`.
   - Editor closed: `bash <skill>/scripts/scene_audit.sh "$P" build` exits 0 and its last line starts with `RESULT: OK`.
   - Use `all` instead of `build` when you touched scenes that are not in Build Settings.
3. **Nothing dirty**: `execute_code(code="return string.Join(\",\", Harness.Safety.SafeEdit.DirtyScenes());")` returns an empty string. Without SafeEdit, check `UnityEngine.SceneManagement.SceneManager.GetSceneAt(i).isDirty` for each loaded scene. `read_console(types=["error"])` shows no new errors.
4. **Only intended files changed**: `git -C "$P" status --porcelain` minus `/tmp/sps_before.txt` lists only files you meant to touch, each `.unity/.prefab/.asset` change comes with no unexpected `.meta` add/delete, and `git -C "$P" diff --stat` shows no surprise files (e.g. `ProjectSettings/*`, unrelated scenes).
