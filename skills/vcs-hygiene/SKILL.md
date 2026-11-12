---
name: vcs-hygiene
description: Sets up and audits git for Unity 6 (6000.3) projects - .gitignore, .gitattributes (LF, merge=unityyamlmerge, Git LFS for binaries), local LFS, the UnityYAMLMerge Smart Merge driver in repo config, Force Text + Visible Meta Files, and agent commit rules; vcs_check.py verifies. Use when setting up git, editing .gitignore/.gitattributes, adding LFS or smart merge, resolving a merge conflict in a scene/prefab/.meta, when the repo is too big, or when deciding what to commit.
---

# vcs-hygiene

Keep the repo small, mergeable and free of generated files, and make agents commit like careful humans.

Pinned: Unity 6000.3.21f1 (macOS), git ≥ 2.40, git-lfs 3.x, UnityYAMLMerge at `/Applications/Unity/Hub/Editor/<ver>/Unity.app/Contents/Helpers/UnityYAMLMerge`.
Tools: mostly shell (git) plus the scripts here. Unity-side fixes use MCP for Unity 10.3 tools (your client may prefix them, e.g. `mcp__UnityMCP__execute_code`); for tool parameters see unity-mcp-orchestrator. `<skills>` = the folder holding these skills.

## When to use / not to use
- Use at project creation (before the first commit), when adopting an existing repo, after a Unity editor upgrade (driver path changes), when a .unity/.prefab/.meta merge conflicts, when clones get slow/huge, and for every agent commit (conventions below).
- Not for repairing broken YAML or missing GUID references by hand (scene-prefab-safety), build output/versioning (build-ship), Unity Version Control/Plastic.

## Inputs
- Repo root (`git rev-parse --show-toplevel`) and Unity project root (folder with `ProjectSettings/`; may be a subfolder, e.g. `Game/`).
- Remote host and limits (GitHub: warns at 50 MB, rejects > 100 MB without LFS; LFS storage/bandwidth quotas), team size (solo vs shared: file locking).

## Files shipped
- `templates/Unity6.gitignore`: github/gitignore Unity template adapted for Unity 6 + Addressables build output (`/ServerData`, `Assets/StreamingAssets/aa*`, `*.bin` content state), Test Framework scenes, IDE (`.vs/ .idea/ .vscode/ *.csproj *.sln *.slnx`), macOS `.DS_Store`, `*.orig`, MCP screenshots (`Assets/Screenshots/`), profiler/perf captures.
- `templates/Unity6.gitattributes`: `* text=auto`; macros `unity-yaml` = `merge=unityyamlmerge eol=lf` for `*.unity *.prefab *.asset *.mat *.anim *.controller *.meta` (+ .spriteatlas(v2), .physicsMaterial2D, .preset, .mixer, …), `unity-json` (asmdef, inputactions, shadergraph) and `lfs` for images/PSD/Aseprite/audio/video/fonts/3D/archives/DLLs, size rationale in comments. Must be the repo's TOP-LEVEL .gitattributes (`[attr]` macros are ignored elsewhere).
- `scripts/setup_unityyamlmerge.sh`, `scripts/vcs_check.py`, `scripts/selftest_merge.sh` (below).

## Procedure (new or adopted repo)
1. **Look first.** `git status --short`, `git log --oneline -5`, `git lfs version`, `python3 <skills>/vcs-hygiene/scripts/vcs_check.py --project <unity-root>` → note FAIL/WARN lines. Uncommitted user work stays untouched: never stash, reset, clean or checkout over it; ask.
2. **.gitignore.** No file: copy `templates/Unity6.gitignore` to the Unity project root (anchored `/Library/` patterns are relative to the .gitignore's folder, so put it next to `ProjectSettings/`). Existing file: add the missing lines, keep the user's lines.
3. **.gitattributes.** Copy `templates/Unity6.gitattributes` to the REPO root (merge with an existing one; keep user rules, remove duplicates that conflict).
4. **Untrack generated files.** For each tracked path vcs_check names: `git rm -r --cached Library Temp Obj Logs UserSettings *.csproj *.sln` (only those that are tracked). Files stay on disk.
5. **Git LFS.** `git lfs install --local` (repo-only hooks/filters; never `--system`; if git-lfs is missing, ask the user to `brew install git-lfs`). The template already contains the patterns (equivalent to `git lfs track "*.png"` …). Then `git add --renormalize .` so files that match LFS patterns are stored as pointers from this commit on; `git lfs ls-files` lists them.
   ⚠ Existing history keeps the old raw blobs (vcs_check `history` WARN). Rewriting it (`git lfs migrate import --include="*.png,*.psd,…" --everything`) changes every commit hash and needs a force-push: only with the user's explicit approval, on a backup/clone, after telling collaborators. Read references/lfs.md first.
6. **Smart Merge driver.** `bash <skills>/vcs-hygiene/scripts/setup_unityyamlmerge.sh --project <unity-root>` → reads `ProjectSettings/ProjectVersion.txt`, finds `…/<ver>/Unity.app/Contents/Helpers/UnityYAMLMerge`, writes LOCAL config only (`merge.unityyamlmerge.{name,driver,recursive}`, `mergetool.unityyamlmerge.{cmd,trustExitCode}`, `mergetool.keepBackup`), idempotent (prints `set`/`unchanged` per key), ends with `RESULT: OK`. `--dry-run` previews, `--set-default-tool` also sets `merge.tool`. Driver: `'<UnityYAMLMerge>' merge -h -p --force --fallback none %O %B %A %A` (verified on 6000.3.21f1: headless, premerge, `--force` because git passes temp files without .prefab extensions, no GUI fallback so real conflicts become normal git conflicts). Every clone needs this step (git config is not versioned); re-run after an editor upgrade.
7. **Editor settings.** vcs_check `editor` reads `ProjectSettings/EditorSettings.asset` (`m_SerializationMode: 2` = Force Text) and `VersionControlSettings.asset` (`m_Mode: Visible Meta Files`); both are Unity 6 defaults. If wrong, with the editor open: `execute_code("UnityEditor.EditorSettings.serializationMode = UnityEditor.SerializationMode.ForceText; UnityEditor.VersionControlSettings.mode = \"Visible Meta Files\"; UnityEditor.AssetDatabase.SaveAssets(); return 1;")` (verified API on 6000.3.21f1). Switching to Force Text re-serializes every asset: commit that alone.
8. **Commit.** `git status --short` → review → `git add` the specific files → `git commit -m "chore(vcs): Unity 6 gitignore, gitattributes, LFS, smart merge"`. Run vcs_check again.

## Agent commit conventions
- One story/fix per commit; message `<ID>: <imperative summary>` (e.g. `M1-S02: add melee hit detection`) or `chore(vcs|deps|build): …`. Small, reviewable diffs.
- `git status --short` BEFORE editor operations (know what was dirty) and AFTER (catch scene/prefab/ProjectSettings churn you did not intend; revert only your own unintended changes, never the user's).
- Stage explicit paths, not `git add -A`, unless status was reviewed. Every new/moved asset is committed with its `.meta`; deleted assets with their `.meta` deleted.
- Never commit `Library/ Temp/ Obj/ Logs/ UserSettings/ Build(s)/`, `*.csproj/*.sln`, MemoryCaptures, crash dumps, secrets (API keys, signing identities, `.env`).
- Do not commit while Unity is compiling/importing (half-written .meta/.asset): check `mcpforunity://editor/state` (`is_compiling` false, `ready_for_tools` true) or that no batchmode run is active. Save scenes/prefabs (or discard) first.
- Never force-push, rewrite history, `git clean -fdx`, `git reset --hard`, or delete branches without the user's explicit approval. Do not change `--global`/`--system` git config.
- Large new binaries: check `git check-attr filter -- <file>` says `lfs` before committing.

## Merge conflicts (summary; details: references/merge-conflicts.md)
- With the driver configured, Unity YAML merges run through UnityYAMLMerge automatically; most "adjacent line" conflicts merge clean.
- Remaining real conflicts in .unity/.prefab: pick a side per file (`git checkout --ours|--theirs <file>`) and re-apply the other side's change in the editor (scene-prefab-safety), or `git mergetool --tool=unityyamlmerge <file>`. Never hand-edit merged YAML unless scene-prefab-safety's YAML rules are followed.
- `.meta` conflicts: never invent GUIDs; keep the GUID that other assets reference (`grep -r <guid> Assets`).
- LFS binaries cannot merge: choose a side; for shared art, use `git lfs lock` (references/lfs.md).

## Rules
- LOCAL repo config only; the scripts never write `--global`/`--system`. Tests run with `GIT_CONFIG_GLOBAL` pointed at a temp file.
- Templates are a baseline: merge with existing files, never delete user rules without asking.
- ⚠ version-sensitive: Unity 6 on macOS ships UnityYAMLMerge in `Contents/Helpers` (no `Contents/Tools`); Windows/Linux use `Editor/Data/Tools/`. The driver path embeds the editor version: upgrading Unity breaks merges until setup is re-run (vcs_check `driver` FAILs with "driver binary missing").
- ⚠ The `merge=unityyamlmerge` attribute does nothing without the driver in git config (the state found in this user's projects); vcs_check checks both.

## Failure handling
- `setup_unityyamlmerge.sh` `RESULT: FAIL UnityYAMLMerge-not-found`: the version in ProjectVersion.txt is not installed → install it via Unity Hub, or pass `UNITY_YAML_MERGE=<path>` from another installed 6000.x editor (tell the user).
- vcs_check `blobs` FAIL after renormalize: the file does not match an LFS pattern → add its extension to .gitattributes, `git add --renormalize <file>`.
- `lfs-install` FAIL: `git lfs install --local`; if `git lfs` is missing, ask the user to install it.
- Push rejected for large files: the blob is in history → stop; propose `git lfs migrate` to the user (step 5 warning).
- A merge produced broken references (pink/missing in the editor): `git merge --abort` if not committed; otherwise hand off to scene-prefab-safety.

## References
- references/lfs.md: read before LFS setup on an existing repo, history migration, locking, or LFS quota problems.
- references/merge-conflicts.md: read when a merge/rebase conflicts on Unity files or when testing the merge driver.

## Verify
- `python3 <skills>/vcs-hygiene/scripts/vcs_check.py --project <unity-root>` exits 0 and prints `RESULT: OK` (WARN lines allowed only for `history`/`meta`, each reported to the user).
- `bash <skills>/vcs-hygiene/scripts/selftest_merge.sh --project <unity-root>` exits 0, prints a `trace: run_command: '…/Contents/Helpers/UnityYAMLMerge' merge -h -p --force --fallback none …` line, `smart merge: CLEAN, both changes kept`, `real conflict: reported by git` and `RESULT: OK` (it uses its own scratch repo; nothing in the project changes).
- `git config --local --get merge.unityyamlmerge.driver` prints the driver; `git config --global --get merge.unityyamlmerge.driver` is unchanged by this skill.
- `git status --short` after the commit is empty (or only the user's pre-existing changes).
