#!/usr/bin/env bash
# `make live`: the real desktop window, running straight from this checkout.
#   - Vite dev server on :5173: UI edits appear in the window instantly (hot reload)
#   - the Tauri shell in dev mode, which starts the backend with `uv run workspace`
#     from this repo (WORKSPACE_DEV_BACKEND); backend edits apply when you restart `make live`
# Quit the window or press Ctrl-C to stop everything.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
export PATH="/opt/homebrew/bin:$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

command -v cargo >/dev/null || { echo "live: Rust is missing (https://rustup.rs)"; exit 1; }
command -v uv >/dev/null || { echo "live: uv is missing (curl -LsSf https://astral.sh/uv/install.sh | sh)"; exit 1; }
[[ -d frontend/node_modules ]] || (cd frontend && npm ci --no-audit --no-fund)
uv sync --quiet --group dev --extra agent-sdk

if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "live: port 5173 is busy (is \`make ui\` running?). Stop it first."; exit 1
fi

(cd frontend && exec npm run dev) &
VITE_PID=$!
trap 'kill "$VITE_PID" 2>/dev/null || true' EXIT INT TERM

export WORKSPACE_DEV_BACKEND="$ROOT"
# The dev window loads the UI from the Vite server (http://localhost:5173), which needs its
# own websocket and inline scripts for hot reload, so the app's CSP is dropped in dev only
# (a JSON merge patch: null removes the key). Release builds keep the CSP.
npx --prefix frontend tauri dev --config '{"app":{"security":{"csp":null}}}'
