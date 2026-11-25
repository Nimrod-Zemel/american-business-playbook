#!/usr/bin/env python3
# THIRD-PARTY: founder-skills. The --write / --check / --root command line follows
# founder-skills/scripts/script_hashes.py (Copyright 2026 lool ventures, Apache
# License 2.0), written again around abp.seal. See THIRD_PARTY_NOTICES.md.
"""Write or check the skill's integrity seal (skills/<skill>/seal.json).

    python3 tools/seal.py --write     after any edit to the skill's files
    python3 tools/seal.py --check     exit 1 and name what differs

The engine itself only ever checks the seal. Writing lives here, outside the
shipped skill, so that an installed copy has no command that reseals itself.
"""

import argparse
import json
import os
import sys

import _paths  # noqa: F401  (sets sys.path)
from abp import seal


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="regenerate seal.json")
    group.add_argument("--check", action="store_true", help="verify the tree against seal.json")
    parser.add_argument("--root", default=_paths.SKILL, help="skill folder (default: this repository's skill)")
    args = parser.parse_args()

    if args.write:
        manifest = seal.compute(args.root)
        path = os.path.join(args.root, seal.SEAL_FILE)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print("Sealed %d files -> %s" % (len(manifest["files"]), os.path.relpath(path, _paths.REPO)))
        print("Rules fingerprint: %s" % seal.rules_digest(args.root))
        return 0

    report = seal.verify(args.root)
    if report["status"] == "ok":
        print("Seal OK (%d files)." % len(seal.read(args.root)["files"]))
        return 0
    if report["status"] == "absent":
        print("No seal.json. Run: python3 tools/seal.py --write")
        return 1
    for key in ("changed", "missing", "unlisted"):
        for rel in report[key]:
            print("%-9s %s" % (key, rel))
    print("Seal BROKEN. If the edits are intended, run: python3 tools/seal.py --write")
    return 1


if __name__ == "__main__":
    sys.exit(main())
