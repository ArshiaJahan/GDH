# Unity merge conflicts and the UnityYAMLMerge driver

Contents: 1. How the pieces fit · 2. Driver vs mergetool · 3. Resolving real conflicts · 4. .meta and GUID conflicts · 5. Testing the driver · 6. Verified evidence

## 1. How the pieces fit
- `.gitattributes` assigns `merge=unityyamlmerge` to Unity YAML files (via the `unity-yaml` macro).
- git looks up `merge.unityyamlmerge.driver` in its config (local > global > system). If no driver is defined, git silently falls back to its normal text merge, so the attribute alone does nothing.
- `setup_unityyamlmerge.sh` writes the driver into the LOCAL repo config. Config is per clone, so run it in every clone and after every editor upgrade.

## 2. Driver vs mergetool
| | Driver (automatic) | Mergetool (manual) |
|---|---|---|
| When | during `git merge`/`rebase`/`cherry-pick`, for files with the attribute | `git mergetool --tool=unityyamlmerge <file>` after a conflict |
| Config | `merge.unityyamlmerge.driver = '<UYM>' merge -h -p --force --fallback none %O %B %A %A` | `mergetool.unityyamlmerge.cmd = '<UYM>' merge -p "$BASE" "$REMOTE" "$LOCAL" "$MERGED"` (Unity manual form), `trustExitCode = false` |
| Arguments | `%O` base, `%B` other branch (UnityYAMLMerge "left/theirs"), `%A` ours ("right/mine") and the result file | same order with git's mergetool variables |
UnityYAMLMerge flags (from its usage text, 6000.3.21f1): `-h` headless (no dialogs), `-p` premerge, `--force` merge unknown extensions (git's temp files are `.merge_file_XXXX`), `--fallback none` no external fallback tool, `-l/-r` resolve conflicts with left/right. Rules and fallback spec files: `Unity.app/Contents/Resources/UnityYAMLMerge/{mergerules.txt,mergespecfile.txt}`.
[UNVERIFIED] the mergetool form was not exercised in tests (interactive); the driver form was.

## 3. Resolving real conflicts
Real conflict = both sides changed the same property (e.g. the same object's `m_Name`). With `--fallback none` git reports it as a normal conflict (exit 1, file in `git ls-files -u`).
1. Identify what each side changed: `git log --oneline --merge -- <file>`, `git diff <base>..ours -- <file>`, `git diff <base>..theirs -- <file>`.
2. Prefer: keep one side (`git checkout --ours <file>` or `--theirs`), `git add <file>`, then re-apply the other side's change in the editor (scene-prefab-safety procedure) and commit.
3. Or run `git mergetool --tool=unityyamlmerge <file>` (opens the fallback GUI tool only if one is configured in mergespecfile.txt).
4. Never commit YAML with `<<<<<<<` markers; never hand-merge object blocks unless following scene-prefab-safety's YAML rules (fileIDs, GUIDs, component lists).
5. After resolving: open the scene/prefab in Unity (or a batchmode load) and check the console for missing-reference errors before committing.
Prevention: small commits, one person per scene at a time (or split scenes into additive scenes/prefabs), prefabs for anything shared.

## 4. .meta and GUID conflicts
- Both sides added the same asset path with different GUIDs: keep the GUID that existing references use (`grep -rl "guid: <guid>" Assets ProjectSettings`), delete the other side's meta version, let Unity reimport.
- Importer settings conflicts (texture import, compression): pick one side, re-apply the setting in the importer (asset-pipeline).
- Missing .meta after merge = Unity generates a NEW GUID and breaks references: always commit .meta files with their assets.

## 5. Testing the driver
- `bash <skills>/vcs-hygiene/scripts/selftest_merge.sh [--project <unity-root>] [--dir <new-empty-dir>]`: builds a throwaway repo (isolated `GIT_CONFIG_GLOBAL`), two branches change adjacent lines of one Transform (plain text merge conflicts), merges with `GIT_TRACE`, expects UnityYAMLMerge in the trace and a clean merge with both changes, then checks that a same-property change still conflicts. Never deletes anything; each run uses a new directory.
- In a real repo: `GIT_TRACE=1 git merge <branch> 2>&1 | grep UnityYAMLMerge` shows the driver call.

## 6. Verified evidence (6000.3.21f1, git 2.54, git-lfs 3.8, 2026-11-06)
Scratch repo with the full templates + LFS + setup script, two branches editing `m_LocalPosition` vs `m_LocalScale` of one prefab (text merge: 1 conflict):
```
trace: run_command: ''/Applications/Unity/Hub/Editor/6000.3.21f1/Unity.app/Contents/Helpers/UnityYAMLMerge'' merge -h -p --force --fallback none .merge_file_zpRKlT .merge_file_Vv1h8s .merge_file_kOXlj0 .merge_file_kOXlj0
Merge made by the 'ort' strategy.   → m_LocalPosition: {x: 5 …}  m_LocalScale: {x: 2 …}
```
Same-property change on both sides: git exit 1, file listed in `git ls-files -u`, no GUI opened.
