#!/usr/bin/env python3
"""American Business Playbook: the engine's single entry point.

    python3 scripts/playbook.py <command> --help
    python3 scripts/playbook.py doctor

Standard library only (Python 3.9+). No network. No file writes, except the
calendar file you explicitly ask `cadence --ics PATH` to create.

The start-up order below is deliberate:

1. This folder comes off the import path, so a file planted here under a
   standard-library name (json.py, re.py) can never be imported.
2. The standard-library modules the engine uses are loaded, from the
   standard library.
3. Cached bytecode is switched off for the engine's own modules. The seal
   covers source files, and Python would otherwise run a __pycache__/*.pyc
   in place of the source it sits next to.
4. Only the seal checker is loaded, and the tree is verified before any other
   engine code runs.
5. The rest of the engine is imported, and this folder comes off the import
   path again.
"""

import sys

sys.dont_write_bytecode = True


def _folder_of(path):
    cut = max(path.rfind("/"), path.rfind("\\"))
    return path[:cut] if cut > 0 else "."


_HERE = _folder_of(__file__)
sys.path[:] = [entry for entry in sys.path if entry not in ("", ".", _HERE)]

import __future__  # noqa: E402,F401
import argparse  # noqa: E402,F401
import datetime  # noqa: E402,F401
import difflib  # noqa: E402,F401
import hashlib  # noqa: E402,F401
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402,F401


def _run():
    arguments = sys.argv[1:]
    # Bytecode lookups are sent beneath this file. A regular file has nothing
    # beneath it, so nothing can be planted there: every engine module is
    # compiled from the source the seal just checked.
    cache_setting = sys.pycache_prefix
    sys.pycache_prefix = os.path.join(os.path.abspath(__file__), "no-bytecode")
    sys.path.insert(0, _HERE)
    try:
        from abp import seal

        report = seal.verify(os.path.dirname(os.path.abspath(_HERE)))
        if report["status"] == "broken" and "--unsealed" not in arguments:
            payload = seal.refusal(report)
            if "json" in arguments and "--format" in arguments:
                sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            else:
                sys.stderr.write("SEAL BROKEN: %s\n%s\n" % (payload["message"], payload["hint"]))
            return seal.EXIT_SEAL
        from abp.cli import main
    finally:
        sys.path.remove(_HERE)
        sys.pycache_prefix = cache_setting
    return main(seal_report=report)


if __name__ == "__main__":
    try:
        code = _run()
        sys.stdout.flush()
    except BrokenPipeError:
        # The reader closed the pipe early (for example `| head`). Not an error.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    sys.exit(code)
