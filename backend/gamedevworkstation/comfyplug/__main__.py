"""Entry point for `python -m comfyplug ...` and `python path/to/comfyplug ...`."""
import os
import sys

if __package__:
    from .cli import main
else:
    # Run as a directory/script: drop this folder from sys.path (its image.py/audio.py would shadow things)
    # and make the parent importable so `comfyplug` resolves as a package.
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path = [p for p in sys.path if os.path.abspath(p or ".") != here]
    sys.path.insert(0, os.path.dirname(here))
    from comfyplug.cli import main

if __name__ == "__main__":
    sys.exit(main())
