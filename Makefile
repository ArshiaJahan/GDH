.PHONY: dev backend frontend ui live test test-live app app-test release install version clean

# Development: backend on :8765 serving the built UI, opened in your browser.
dev: frontend
	uv run gamedevworkstation

backend:
	uv run gamedevworkstation --no-browser

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

# macOS app: dist/GameDevWorkstation.app + dist/GameDevWorkstation.dmg
app:
	./scripts/build_mac.sh

app-test: app
	uv run python scripts/app_test.py

# Next version into the updates folder (~/GameDevWorkstationUpdates); the running app offers it.
# make release [BUMP=patch|minor|major | VERSION=x.y.z] [NOTES="…" | NOTES_FILE=path]
release:
	./scripts/release.sh

# Copy a built app to /Applications (quit GameDevWorkstation first). APP=path picks another build.
APP ?= dist/GameDevWorkstation.app
install:
	@test -d "$(APP)" || { echo "No app at $(APP). Run make app (or make release) first."; exit 1; }
	@if pgrep -f "/Applications/[G]ameDevWorkstation.app/Contents/MacOS/" >/dev/null; then echo "Quit GameDevWorkstation first."; exit 1; fi
	rm -rf /Applications/.GameDevWorkstation.app.installing
	ditto "$(APP)" /Applications/.GameDevWorkstation.app.installing
	rm -rf /Applications/GameDevWorkstation.app
	mv /Applications/.GameDevWorkstation.app.installing /Applications/GameDevWorkstation.app
	xattr -cr /Applications/GameDevWorkstation.app
	@echo "Installed $$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' /Applications/GameDevWorkstation.app/Contents/Info.plist) to /Applications/GameDevWorkstation.app"

version:
	@python3 scripts/version.py show

clean:
	rm -rf build dist frontend/dist src-tauri/target src-tauri/resources/backend
