# Git LFS for Unity projects

Contents: 1. Why and what · 2. Setup (new repo) · 3. Adopting an existing repo · 4. History migration (approval required) · 5. Locking · 6. Checks and troubleshooting

## 1. Why and what
- git stores every version of every file in full in each clone; compressed binaries (PNG, OGG, MP4, FBX, PSD) do not delta-compress, so ten edits of a 5 MB PSD = 50 MB in every clone forever. LFS stores a ~130-byte pointer in git and the content on the LFS server, downloaded on checkout only for the versions you need.
- Rule used by the template: LFS by EXTENSION for binary source and media (predictable; even small pixel-art PNGs, so nobody has to judge size per file). Text-serialized Unity assets (.unity, .prefab, .asset, .mat, .anim, .controller, .meta) stay in git so they diff and merge (Force Text).
- vcs_check also flags any non-LFS blob above `--max-blob-kb` (default 1024 KB) regardless of extension (e.g. a huge .asset or an unlisted binary type).
- Host limits: GitHub warns at 50 MB and rejects files over 100 MB without LFS; LFS has storage and bandwidth quotas per account (check the plan before committing many large videos/audio stems).
- Template LFS groups: 2D art sources/images (aseprite, ase, psd, psb, kra, png, jpg, tga, tif, exr, hdr, gif, webp, bmp), 3D (fbx, blend, obj, dae, max, ma, mb…), audio (wav, ogg, mp3, flac, aif, it/mod/s3m/xm, bank), video (mp4, mov, webm, avi…), fonts (ttf, otf, woff, woff2), archives/libraries/executables (zip, 7z, dll, so, dylib, a, apk, exe, pdf, unitypackage), `LightingData.asset` binary.

## 2. Setup (new repo)
```bash
git lfs version                       # missing → ask the user: brew install git-lfs
git lfs install --local               # hooks + filter config for THIS repo only
cp <skills>/vcs-hygiene/templates/Unity6.gitattributes .gitattributes   # repo root
git add .gitattributes && git add -A && git commit -m "chore(vcs): gitattributes with LFS"
git lfs ls-files                      # every image/audio/font now listed
```
`git lfs track "*.ext"` appends a line `*.ext filter=lfs diff=lfs merge=lfs -text` to .gitattributes; the template's `lfs` macro is the same thing. Add project-specific types the same way (e.g. `*.spine`, `*.fmod`).

## 3. Adopting an existing repo (no history rewrite)
```bash
git lfs install --local
cp <skills>/vcs-hygiene/templates/Unity6.gitattributes .gitattributes   # merge with the existing file
git add --renormalize .               # re-runs the clean filter: matching files become LFS pointers
git commit -m "chore(vcs): move binary assets to LFS from here on"
python3 <skills>/vcs-hygiene/scripts/vcs_check.py --project <unity-root>   # blobs PASS; history may WARN
```
Verified in a scratch repo: a 1.6 MB PNG committed raw became an LFS pointer after renormalize; vcs_check went from 7 FAILs to `RESULT: OK` with one `history` WARN (the old raw blob).

## 4. History migration (needs the user's explicit approval)
Only if the history is a real problem (clone size, push rejected for > 100 MB). It rewrites every commit hash; collaborators must re-clone; open PRs break.
1. Explain the consequences and get a yes. Work on a fresh clone or after a backup (`git bundle create ../backup.bundle --all`).
2. `git lfs migrate info --everything --top=20` (report sizes by extension, read-only).
3. `git lfs migrate import --everything --include="*.png,*.psd,*.wav,*.ogg,*.mp4,*.fbx,*.ttf"` (match the .gitattributes LFS list).
4. Verify: `git lfs ls-files`, vcs_check (no `history` WARN), the project opens in Unity.
5. The USER force-pushes (`git push --force-with-lease --all`, then tags) after telling collaborators. Agents never force-push.

## 5. Locking (teams)
- Binary files cannot merge. For shared art/audio, mark them lockable: `*.psd lfs lockable` style (`git lfs track --lockable "*.psd"`), then `git lfs lock Assets/Art/hero.psd` before editing and `git lfs unlock` after pushing. Requires host support (GitHub, GitLab do).
- Do not lock .unity/.prefab: they merge with UnityYAMLMerge.

## 6. Checks and troubleshooting
- `git check-attr -a -- Assets/Art/hero.png` → `filter: lfs`, `diff: lfs`, `merge: lfs`, `text: unset`.
- `git lfs status`, `git lfs ls-files -s` (sizes).
- Pointer committed but content missing on another machine: `git lfs pull`.
- File shows as modified right after clone: line-ending or LFS filter mismatch → `git lfs install --local` on that clone, then `git add --renormalize .` and inspect the diff.
- `Encountered N files that should have been pointers`: someone committed without LFS installed → renormalize and commit.
