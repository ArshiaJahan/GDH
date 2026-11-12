# PyInstaller spec for the GameDevWorkstation backend: --onedir, arm64 on the M4 Air.
# Build: uv run pyinstaller packaging/gamedevworkstation.spec --noconfirm --distpath build/pyinstaller
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
datas = collect_data_files("gamedevworkstation") + [(os.path.join(ROOT, "skills"), "skills")]
binaries = []
hiddenimports = (
    collect_submodules("gamedevworkstation")  # features are imported by name at startup
    + collect_submodules("uvicorn")
    + collect_submodules("apscheduler")
    + ["keyring.backends.macOS", "keyring.backends.fail", "ptyprocess"]
)
for pkg in ("anthropic", "openai", "elevenlabs", "mcp", "httpx2", "pypdf", "claude_agent_sdk"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass  # optional packages (claude_agent_sdk) may be absent

a = Analysis(
    [os.path.join(SPECPATH, "backend_entry.py")],
    pathex=[os.path.join(ROOT, "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "PIL", "numpy", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="gamedevworkstation-backend",
    console=True,
    target_arch="arm64" if sys.platform == "darwin" else None,
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="backend")
