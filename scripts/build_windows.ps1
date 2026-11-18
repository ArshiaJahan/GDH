# Build GameDevWorkstation for Windows (x64): the frozen backend (PyInstaller, onedir) inside the
# Tauri shell, packaged as an NSIS installer.
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#
# Needs: Node 20+, uv, Rust (MSVC toolchain) and the Visual Studio C++ build tools.
# Output: dist\GameDevWorkstation-<version>-x64-setup.exe and dist\backend\ (the frozen backend).
# Unsigned: Windows SmartScreen will warn on first run.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Root = (Get-Location).Path
$Dist = if ($env:GDW_DIST_DIR) { $env:GDW_DIST_DIR } else { Join-Path $Root "dist" }

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "Missing $cmd. $hint" }
}
Need node "Install Node 20 or newer from https://nodejs.org"
Need npm "npm comes with Node"
Need uv "Install uv: https://docs.astral.sh/uv/"
Need cargo "Install Rust: https://rustup.rs"
function Run([scriptblock]$block) {
    & $block
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}

Write-Host "==> Frontend"
Push-Location frontend
Run { npm ci --no-audit --no-fund }
Run { npm run build }
Pop-Location

Write-Host "==> Backend (PyInstaller, onedir)"
Run { uv sync --frozen --group dev --extra agent-sdk }
Run { uv run --frozen python scripts/version.py build-info } | Out-Null
Remove-Item -Recurse -Force build\pyinstaller\backend -ErrorAction SilentlyContinue
Run { uv run --frozen pyinstaller packaging/gamedevworkstation.spec --noconfirm --distpath build/pyinstaller --workpath build/pyi-work --log-level WARN }
Remove-Item -Recurse -Force src-tauri\resources\backend -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force src-tauri\resources | Out-Null
Copy-Item -Recurse build\pyinstaller\backend src-tauri\resources\backend
New-Item -ItemType File -Force src-tauri\resources\backend\.keep | Out-Null

Write-Host "==> Desktop shell (Tauri, NSIS installer)"
Run { npx --prefix frontend tauri build --bundles nsis }

$Version = (Get-Content VERSION -Raw).Trim()
New-Item -ItemType Directory -Force $Dist | Out-Null
$Setup = Get-ChildItem src-tauri\target\release\bundle\nsis\*.exe | Select-Object -First 1
if (-not $Setup) { throw "No NSIS installer was produced" }
Copy-Item $Setup.FullName (Join-Path $Dist "GameDevWorkstation-$Version-x64-setup.exe") -Force
Remove-Item -Recurse -Force (Join-Path $Dist "backend") -ErrorAction SilentlyContinue
Copy-Item -Recurse build\pyinstaller\backend (Join-Path $Dist "backend")
Write-Host "Built: $Dist\GameDevWorkstation-$Version-x64-setup.exe"
