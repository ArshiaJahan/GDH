# Prefab, variant and nesting rules

Unity 6000.3. API names from https://docs.unity.com/en-us/engine/6000.3/script-reference/unityeditor/prefabutility.

## Which object to edit
| Change | Edit | Tool |
|---|---|---|
| Every instance should get it | the prefab asset | `manage_prefabs(modify_contents)` / `SafeEdit.EditPrefabAsset` |
| Only this placed object | the scene instance (becomes an override) | `manage_components(set_property)` / recipe 2 |
| A family of similar prefabs (enemy types) | a Prefab Variant of a base | `SafeEdit.CreateVariant` |
| A part reused inside many prefabs (health bar, shadow) | the nested prefab's own asset | `manage_prefabs(modify_contents)` on the inner prefab |

## Variants
- A variant stores only its overrides against the base. Edit the base for shared changes.
- Create in code: `InstantiatePrefab(base)` then `SaveAsPrefabAsset(instance, variantPath)` then destroy the temp
  instance. `SafeEdit.CreateVariant` does this and asserts `GetPrefabAssetType(result) == PrefabAssetType.Variant`
  (the docs do not state this explicitly, but it ran on the 6000.3.21f1 bench: the saved asset was a Variant and
  its scene instances passed SceneAudit).
- Check before editing: `PrefabUtility.IsPartOfVariantPrefab(obj)`, `GetCorrespondingObjectFromSource(obj)` gives the base object.
- Do not chain variants deeper than 2-3 levels; deep chains make override origin hard to read.
- Changing the base of an existing variant is not a supported edit; create a new variant and move references.

## Nesting
- Add a nested prefab with `manage_prefabs(modify_contents, create_child={"name":…, "source_prefab_path": "Assets/Prefabs/X.prefab"})`
  or, in code, `PrefabUtility.InstantiatePrefab(inner, parentTransformInsideLoadedContents)`.
- Never `Object.Instantiate` a prefab inside prefab contents; that copies the objects and drops the link.
- Edits to the inner prefab made while editing the outer one are overrides on the outer prefab, not changes to the inner asset.

## Overrides
- Inspect: `PrefabUtility.HasPrefabInstanceAnyOverrides(instanceRoot, false)`, `GetPropertyModifications`,
  `GetAddedComponents`, `GetRemovedComponents`, `GetAddedGameObjects`.
- Apply: `ApplyPrefabInstance(root, InteractionMode.UserAction)` (all) or `ApplyPropertyOverride(prop, assetPath, mode)` /
  `ApplyAddedComponent(component, assetPath, mode)` (one).
- Revert: `RevertPrefabInstance(root, InteractionMode.UserAction)`.
- Clean up overrides that point at removed properties: `PrefabUtility.RemoveUnusedOverrides(new[]{root}, InteractionMode.UserAction)`.
- Scripted change to an instance without `SerializedObject`: call `RecordPrefabInstancePropertyModifications(component)`
  after the change, or the value reverts on the next reload.
- Unpacking (`UnpackPrefabInstance`) is a last resort and needs the user's OK; it severs the link permanently.

## Prefab stage (interactive)
- `manage_prefabs(open_prefab_stage)` → edits via `manage_gameobject`/`manage_components` (they target the stage) →
  `save_prefab_stage` → `close_prefab_stage`. Read `mcpforunity://editor/prefab-stage` to confirm which prefab is open.
- Leaving a stage open blocks scene edits from targeting the scene; always close it.

## Missing prefab assets
- An instance whose source asset was deleted shows as a red "Missing Prefab". `PrefabUtility.IsPrefabAssetMissing(go)`
  detects it; SceneAudit reports it as `MissingPrefabAsset`. Fix by restoring the asset + `.meta` from git.
