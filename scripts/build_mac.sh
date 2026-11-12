#!/usr/bin/env bash
# Builds dist/Workspace.app and dist/Workspace.dmg for Apple Silicon, ad-hoc signed.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
# Output folder (default dist/). scripts/release.sh builds into a staging folder instead and
# sets WORKSPACE_SKIP_DMG=1.
DIST="${WORKSPACE_DIST_DIR:-$ROOT/dist}"
TARGET=aarch64-apple-darwin

# rm -rf that survives Finder writing .DS_Store into a folder while it is being deleted.
rm_tree() {
  local i
  for i in 1 2 3 4 5; do
    rm -rf "$@" 2>/dev/null && return 0
    sleep 1
  done
  rm -rf "$@"
}

# GUI-launched shells and fresh terminals may miss Homebrew/cargo paths.
export PATH="/opt/homebrew/bin:$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

echo "==> Checking prerequisites"
missing=()
[[ "$(uname -s)" == "Darwin" ]] || { echo "This script builds the macOS app; run it on your Mac."; exit 1; }
xcode-select -p >/dev/null 2>&1 || missing+=("Xcode Command Line Tools — run: xcode-select --install")
command -v cargo >/dev/null 2>&1 || missing+=("Rust — run: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")
if command -v node >/dev/null 2>&1; then
  node -e 'process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)' || missing+=("Node 20 or newer (you have $(node -v)) — run: brew install node")
else
  missing+=("Node 20+ — run: brew install node")
fi
command -v npm >/dev/null 2>&1 || missing+=("npm (comes with Node) — run: brew install node")
command -v uv >/dev/null 2>&1 || missing+=("uv — run: curl -LsSf https://astral.sh/uv/install.sh | sh")
command -v git >/dev/null 2>&1 || missing+=("git — run: xcode-select --install")
if (( ${#missing[@]} )); then
  echo "Missing:"; printf '  • %s\n' "${missing[@]}"; exit 1
fi
if command -v rustup >/dev/null 2>&1 && ! rustup target list --installed | grep -q "$TARGET"; then
  echo "    adding Rust target $TARGET"; rustup target add "$TARGET"
fi
command -v codex >/dev/null 2>&1 && echo "    Codex CLI: found" || echo "    Codex CLI: not installed (optional; the Codex CLI harness will show as unavailable)"
[[ "$(uname -m)" == "arm64" ]] || echo "    note: building on $(uname -m); the app targets $TARGET"

echo "==> Frontend"
# npm ci deletes node_modules first; Finder/Spotlight writing into it can make that fail once (ENOTEMPTY).
( cd frontend && { npm ci --no-audit --no-fund || { sleep 2; npm ci --no-audit --no-fund; }; } && npm run build )

echo "==> Backend (PyInstaller, arm64, onedir)"
uv sync --group dev --extra agent-sdk
uv run python scripts/version.py build-info >/dev/null  # version, commit, build time for About
rm_tree build/pyinstaller/backend  # PyInstaller's own clean-up fails if Finder touches the folder
uv run pyinstaller packaging/workspace.spec --noconfirm --distpath build/pyinstaller --workpath build/pyi-work --log-level WARN
rm_tree src-tauri/resources/backend
mkdir -p src-tauri/resources
cp -R build/pyinstaller/backend src-tauri/resources/backend
touch src-tauri/resources/backend/.keep  # tracked placeholder; the rm above deletes it

echo "==> Desktop shell (Tauri)"
( cd "$ROOT" && npx --prefix frontend tauri build --target "$TARGET" --bundles app )

BUNDLE="src-tauri/target/$TARGET/release/bundle"
rm_tree "$DIST/Workspace.app" "$DIST/Workspace.dmg"
mkdir -p "$DIST"
cp -R "$BUNDLE/macos/Workspace.app" "$DIST/Workspace.app"

echo "==> Signing (ad-hoc)"
xattr -cr "$DIST/Workspace.app"
codesign --force --deep --sign - "$DIST/Workspace.app"
codesign --verify --deep --strict "$DIST/Workspace.app" && echo "    signature OK"

if [[ -n "${WORKSPACE_SKIP_DMG:-}" ]]; then echo; echo "Built: $DIST/Workspace.app"; exit 0; fi

echo "==> Disk image (from the signed app)"
STAGE="$(mktemp -d)"
cp -R "$DIST/Workspace.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname Workspace -srcfolder "$STAGE" -ov -format UDZO "$DIST/Workspace.dmg" >/dev/null
rm -rf "$STAGE"

echo
echo "Built: $DIST/Workspace.app"
echo "       $DIST/Workspace.dmg"
