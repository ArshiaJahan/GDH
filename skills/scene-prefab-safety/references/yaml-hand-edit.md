# Hand-editing Unity YAML (last resort)

Use only when the editor cannot do the change: unresolved merge conflict markers, a file that fails to load, or
re-pointing many references from one GUID to another after a lost `.meta`. For merges prefer UnityYAMLMerge
(see vcs-hygiene; macOS path `/Applications/Unity/Hub/Editor/<ver>/Unity.app/Contents/Helpers/UnityYAMLMerge`).

## Format facts
- Text assets start with `%YAML 1.1` and `%TAG !u! tag:unity3d.com,2011:`. Each object is a document
  `--- !u!<classID> &<fileID>` (e.g. `!u!1` GameObject, `!u!4` Transform, `!u!114` MonoBehaviour, `!u!1001` PrefabInstance).
- A reference is `{fileID: N, guid: G, type: T}`. `fileID` alone (no guid) = object in the same file.
  `type: 2` = asset in project, `type: 3` = object in an imported asset (scripts, sprites), `type: 0` = built-in.
- MonoBehaviour script link: `m_Script: {fileID: 11500000, guid: <script .meta guid>, type: 3}`.
- Sprite sub-asset fileIDs are stored in the texture's `.meta` (`internalID` / `nameFileIdTable`); single sprites use `21300000`.
- Built-in GUIDs: `0000000000000000e000000000000000` (extra resources), `0000000000000000f000000000000000` (default resources).
- With "Reduce version control noise" enabled, references are written on single lines; do not reflow.

## Procedure
1. **Close the editor** on this project (or confirm none is open: `pgrep -f "Unity.*-projectPath <P>"` prints nothing).
   Editing YAML under a running editor gets overwritten or half-reimported.
2. **Back up**: `cp -p "<file>" "/tmp/yaml-backup-$(date +%s)-$(basename "<file>")"` (the backup goes outside `Assets/`,
   so Unity never imports it). Also note `git -C <P> status --porcelain -- "<file>"`.
3. **Edit minimally** with an exact-text replace (the edit tool, or `python3` with a literal string replace). Never reformat,
   re-indent, sort or re-serialize the file through a YAML library: Unity's dialect (`!u!` tags, `stripped` documents,
   duplicate-ish keys) does not round-trip.
   - Re-point a GUID: replace `guid: OLD` with `guid: NEW` only inside `{fileID: …, guid: OLD, type: …}` references;
     keep `fileID` unless the target sub-object changed.
   - Conflict markers: keep one side's complete `--- !u!` documents; never mix lines from both sides inside one document.
   - Never change `&fileID` anchors or the `.meta` `guid:` line.
4. **Validate text**:
   - No conflict markers: `grep -nE '^(<<<<<<<|=======|>>>>>>>)' "<file>"` prints nothing.
   - Header intact: first line is `%YAML 1.1`.
   - `python3 <skill>/scripts/meta_check.py <P> --refs` prints `RESULT: OK` (every GUID resolves).
5. **Validate in Unity**: open the project (or run `scene_audit.sh <P> all`); the file loads without
   "Unable to parse" / "Unknown fileID" warnings in the log or `read_console`, and SceneAudit reports 0 issues.
6. **Re-save through Unity** (open the scene/prefab, `manage_scene(save)` / `SafeEdit.EditPrefabAsset` with a no-op edit)
   so the file is normalized by the serializer, then check `git diff` shows only the intended change.
7. If any step fails: restore the backup (`cp -p /tmp/yaml-backup-… "<file>"`) and report; do not iterate blindly.
