#!/usr/bin/env bash
# Builds the next version of the app into the updates folder (~/GameDevWorkstationUpdates by default).
# The running app notices it within ~30 s and offers "Install & restart".
#
#   make release                     # patch bump: 0.1.0 -> 0.1.1
#   make release BUMP=minor          # or major
#   make release VERSION=1.0.0       # exact version
#   make release NOTES="Fixed X"     # or NOTES_FILE=path; default: commits since the last tag
#   KEEP_BUILD=1                     # keep the staging build in build/release-<version>
#   FORCE=1                          # replace an existing <dir>/<version>
#   RELEASE_BUILD=cmd                # build command (default scripts/build_mac.sh); it gets
#                                    # GDW_DIST_DIR and must leave GameDevWorkstation.app there
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
export PATH="/opt/homebrew/bin:$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

BUMP="${BUMP:-patch}"
WANT="${VERSION:-}"
PY=(uv run --quiet --frozen python)  # --frozen: never re-lock uv.lock behind the release commit's back

# rm -rf that survives Finder writing .DS_Store into a folder while it is being deleted.
rm_tree() {
  local i
  for i in 1 2 3 4 5; do
    rm -rf "$@" 2>/dev/null && return 0
    sleep 1
  done
  rm -rf "$@"
}

die() { echo "release: $*" >&2; exit 1; }
[[ "$(uname -s)" == "Darwin" ]] || die "builds the macOS app; run it on your Mac."
command -v uv >/dev/null || die "uv is missing (curl -LsSf https://astral.sh/uv/install.sh | sh)"

# 1. Clean tree only: a release must be exactly a commit.
if [[ -n "$(git status --porcelain)" ]]; then
  git status --short
  die "the working tree has uncommitted changes; commit or stash them first."
fi

CURRENT="$("${PY[@]}" scripts/version.py show)"
UPDATES_DIR="$("${PY[@]}" scripts/release_tool.py dir)"
PREV_TAG="$(git describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || true)"

# 2. Notes (before the version commit, so it isn't listed).
NOTES_TMP="$(mktemp -t gamedevworkstation-notes)"
trap 'rm -f "$NOTES_TMP"' EXIT
if [[ -n "${NOTES_FILE:-}" ]]; then
  cp "$NOTES_FILE" "$NOTES_TMP"
elif [[ -n "${NOTES:-}" ]]; then
  printf '%s\n' "$NOTES" > "$NOTES_TMP"
elif [[ -n "$PREV_TAG" ]]; then
  git log --no-merges --pretty='- %s' "$PREV_TAG..HEAD" | grep -v '^- Release v' > "$NOTES_TMP" || true
else
  git log --no-merges --pretty='- %s' -n 20 > "$NOTES_TMP"
fi
[[ -s "$NOTES_TMP" ]] || echo "- Rebuild of $CURRENT" > "$NOTES_TMP"

# 3. Version bump + commit.
if [[ -n "$WANT" ]]; then
  NEW="${WANT#v}"
else
  NEW="$("${PY[@]}" scripts/version.py next "$BUMP")"
fi
git rev-parse -q --verify "refs/tags/v$NEW" >/dev/null && die "tag v$NEW already exists; pick another version (VERSION=x.y.z)."
[[ -e "$UPDATES_DIR/$NEW" && -z "${FORCE:-}" ]] && die "$UPDATES_DIR/$NEW already exists (FORCE=1 replaces it)."
"${PY[@]}" scripts/version.py set "$NEW" >/dev/null
echo "==> GameDevWorkstation $CURRENT -> $NEW"
if [[ -n "$(git status --porcelain)" ]]; then
  git commit -q -a -m "Release v$NEW"
  echo "    committed: Release v$NEW"
fi

# 4. Build into a staging folder, never over an app that may be running.
STAGING="$ROOT/build/release-$NEW"
rm_tree "$STAGING"
mkdir -p "$STAGING"
if ! GDW_DIST_DIR="$STAGING" GDW_SKIP_DMG=1 ${RELEASE_BUILD:-./scripts/build_mac.sh}; then
  echo
  die "the build failed. The commit 'Release v$NEW' is in place but untagged; fix the build and run
         make release VERSION=$NEW
       (or drop the commit with: git reset --hard HEAD~1)."
fi
APP="$STAGING/GameDevWorkstation.app"

# 5. Verify.
echo "==> Verifying"
codesign --verify --deep --strict "$APP" || die "the signature of $APP doesn't verify."
BUILT="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
[[ "$BUILT" == "$NEW" ]] || die "the app says it's $BUILT, expected $NEW."
echo "    signature OK, version $BUILT"

# 6. Publish: copy, release.json, then latest.json last (the app only looks at latest.json).
echo "==> Publishing to $UPDATES_DIR/$NEW"
"${PY[@]}" scripts/release_tool.py publish --version "$NEW" --app "$APP" --notes-file "$NOTES_TMP" \
  --commit "$(git rev-parse --short HEAD)" ${FORCE:+--force} >/dev/null

# 7. Tag, prune, tidy.
git tag -a "v$NEW" -F "$NOTES_TMP"
PRUNED="$("${PY[@]}" scripts/release_tool.py prune)"
# Tidying is best effort: the release is already published and tagged.
[[ -n "${KEEP_BUILD:-}" ]] || rm_tree "$STAGING" || echo "    note: couldn't remove $STAGING (delete it by hand)"

echo
echo "Released GameDevWorkstation $NEW"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "  note: the build changed tracked files (commit or discard them before the next release):"
  git status --short | sed 's/^/    /'
fi
echo "  app:     $UPDATES_DIR/$NEW/GameDevWorkstation.app"
echo "  tag:     v$NEW"
echo "  folder:  $PRUNED"
echo "  notes:"
sed 's/^/    /' "$NOTES_TMP"
echo
echo "The running app shows \"Update v$NEW ready\" within about 30 seconds (Settings -> About & updates -> Check now"
echo "to look right away). First time, or if the installed app predates updates, install it once by hand:"
echo "  make install APP=\"$UPDATES_DIR/$NEW/GameDevWorkstation.app\""
