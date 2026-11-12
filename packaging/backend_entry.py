"""PyInstaller entry point for the bundled backend (the Tauri app launches this)."""
import multiprocessing

from workspace.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
