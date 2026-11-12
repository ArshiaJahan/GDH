#!/usr/bin/env python3
"""Final QC of trailer exports: the same as `trailer_edl.py qc`, under its own script name.

  trailer_qc.py <exports-dir|file> [--edl edl.json] [--beats B] [--platform P]

The app observes a script's last `RESULT:` line by the script's file name, so a workflow phase that must see a
passing QC (not any trailer_edl.py subcommand such as poster or export) waits for `trailer_qc`.
Python 3.9+ standard library only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trailer_edl  # noqa: E402


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["qc"]:  # tolerate `trailer_qc.py qc <dir> ...`
        args = args[1:]
    return trailer_edl.main(["qc"] + args)


if __name__ == "__main__":
    sys.exit(main())
