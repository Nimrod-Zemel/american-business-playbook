#!/usr/bin/env python3
"""One command after any edit: rebuild, audit, check credits and the guide, seal, test, package.

    python3 tools/build.py              references, audit, credits, guide, seal, tests
    python3 tools/build.py --package    the same, then dist/american-business-playbook.skill
    python3 tools/build.py --no-tests   skip the test run

Order matters: the references are generated from the rule tables, the seal
covers the references, and the package refuses an unsealed tree.
"""

import argparse
import json
import os
import sys
import unittest

import _paths
import audit
import build_refs
import guide
import notices
import package
from abp import seal


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package", action="store_true", help="also build the .skill package")
    parser.add_argument("--no-tests", action="store_true", help="skip the test suite")
    args = parser.parse_args()

    print("1/7 references")
    built = build_refs.build()
    for rel, text in built:
        path = os.path.join(_paths.REPO, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    print("    %d generated files written" % len(built))

    print("2/7 self-audit")
    report = audit.run()
    with open(os.path.join(_paths.REPO, "docs", "AUDIT.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(audit.render(report))
    if report["findings"]:
        for item in report["findings"]:
            print("    FINDING: %s" % item)
        return 1
    print("    no findings")

    print("3/7 credits")
    credits = notices.run()
    if credits["problems"]:
        for item in credits["problems"]:
            print("    GAP: %s" % item)
        return 1
    print("    %d sources, %d listed files, %d license texts" % (credits["sources"], credits["files"], credits["licenses"]))

    print("4/7 guide")
    copy = guide.render(guide.read(), guide.declared())
    with open(os.path.join(guide.GUIDE_DIR, guide.COPY), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(copy)
    checked = guide.run()
    if checked["problems"]:
        for item in checked["problems"]:
            print("    GAP: %s" % item)
        return 1
    print("    %d English lines of the guide, %d in the rule tables, %d are names" % (checked["lines"], checked["found"], checked["names"]))

    print("5/7 seal")
    manifest = seal.compute(_paths.SKILL)
    with open(os.path.join(_paths.SKILL, seal.SEAL_FILE), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("    %d files sealed, rules %s" % (len(manifest["files"]), seal.rules_digest(_paths.SKILL)))

    if args.no_tests:
        print("6/7 tests skipped")
    else:
        print("6/7 tests")
        suite = unittest.defaultTestLoader.discover(os.path.join(_paths.REPO, "tests"))
        result = unittest.TextTestRunner(verbosity=0).run(suite)
        if not result.wasSuccessful():
            return 1

    if args.package:
        print("7/7 package")
        return package.main()
    print("7/7 package skipped (pass --package)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
