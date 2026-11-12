.PHONY: dev backend frontend ui live test test-live app app-test release install version clean

# Development: backend on :8765 serving the built UI, opened in your browser.
dev: frontend
	uv run workspace

backend:
	uv run workspace --no-browser

# Hot-reloading UI on :5173 (run `make backend` in another terminal).
ui:
	cd frontend && npm run dev

# The desktop window running from this checkout, with hot reload for UI edits.
live:
	./scripts/live.sh

frontend:
	cd frontend && npm install --no-audit --no-fund && npm run build

test:
	uv run pytest -q
	cd frontend && npx tsc -b && npx vitest run

test-live:
	uv run pytest -q -m live

# macOS app: dist/Workspace.app + dist/Workspace.dmg
app:
	./scripts/build_mac.sh

app-test: app
	uv run python scripts/app_test.py

# Next version into the updates folder (~/WorkspaceUpdates); the running app offers it.
# make release [BUMP=patch|minor|major | VERSION=x.y.z] [NOTES="…" | NOTES_FILE=path]
release:
	./scripts/release.sh

# Copy a built app to /Applications (quit Workspace first). APP=path picks another build.
APP ?= dist/Workspace.app
install:
	@test -d "$(APP)" || { echo "No app at $(APP). Run make app (or make release) first."; exit 1; }
	@if pgrep -f "/Applications/[W]orkspace.app/Contents/MacOS/" >/dev/null; then echo "Quit Workspace first."; exit 1; fi
	rm -rf /Applications/.Workspace.app.installing
	ditto "$(APP)" /Applications/.Workspace.app.installing
	rm -rf /Applications/Workspace.app
	mv /Applications/.Workspace.app.installing /Applications/Workspace.app
	xattr -cr /Applications/Workspace.app
	@echo "Installed $$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' /Applications/Workspace.app/Contents/Info.plist) to /Applications/Workspace.app"

version:
	@python3 scripts/version.py show

clean:
	rm -rf build dist frontend/dist src-tauri/target src-tauri/resources/backend
