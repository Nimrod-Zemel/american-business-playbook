#!/usr/bin/env python3
# THIRD-PARTY: anthropic-skills (idea only). The .skill name and the one-folder
# layout of the package follow skill-creator's scripts/package_skill.py by
# Anthropic. The writer below is this project's. See THIRD_PARTY_NOTICES.md.
"""Build the release package: dist/american-business-playbook.zip (and .skill)

    python3 tools/package.py

The package is a zip of the skill folder. It is written twice, byte for byte
the same, under two names: .zip is what Claude's "Upload a skill" asks for,
.skill is what skill tooling produces. The build is reproducible: files are
added in sorted order, uncompressed, with a fixed timestamp and fixed header
fields, so the same tree gives the same bytes and the same sha256 on any
machine and any supported Python. Anyone can rebuild a release from its tag
and compare. It refuses to package a tree whose seal is missing or broken,
whose generated files are stale, that fails the self-audit, or whose credits
do not match the tree.
"""

import hashlib
import os
import sys
import zipfile

import _paths
import audit
import build_refs
import guide
import notices
from abp import __version__, seal

FIXED_TIME = (2026, 1, 1, 0, 0, 0)
NAMES = ("%s.zip" % _paths.SKILL_NAME, "%s.skill" % _paths.SKILL_NAME)


def problems():
    """Reasons this tree must not be packaged. Empty when it is ready."""
    out = []
    report = seal.verify(_paths.SKILL)
    if report["status"] != "ok":
        out.append("the seal is %s. Run: python3 tools/build.py" % report["status"])
    stale = build_refs.stale()
    if stale:
        out.append("generated files are stale (%s). Run: python3 tools/build.py" % ", ".join(stale))
    for item in audit.run()["findings"]:
        out.append("self-audit finding: %s" % item)
    for item in notices.run()["problems"]:
        out.append("credits: %s" % item)
    for item in guide.run()["problems"]:
        out.append("guide: %s" % item)
    return out


def build(dist):
    """Write the package into `dist` under both names. Returns (files, sha256)."""
    os.makedirs(dist, exist_ok=True)
    files = sorted(seal.walk(_paths.SKILL) + [seal.SEAL_FILE])
    first = os.path.join(dist, NAMES[0])
    # Stored, not deflated: compressed bytes differ between zlib builds.
    with zipfile.ZipFile(first, "w", zipfile.ZIP_STORED) as archive:
        for rel in files:
            info = zipfile.ZipInfo("%s/%s" % (_paths.SKILL_NAME, rel), date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            with open(os.path.join(_paths.SKILL, *rel.split("/")), "rb") as handle:
                archive.writestr(info, handle.read())
    with open(first, "rb") as handle:
        payload = handle.read()
    with open(os.path.join(dist, NAMES[1]), "wb") as handle:
        handle.write(payload)
    digest = hashlib.sha256(payload).hexdigest()
    with open(os.path.join(dist, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as handle:
        for name in NAMES:
            handle.write("%s  %s\n" % (digest, name))
    return files, digest


def main():
    found = problems()
    if found:
        print("Refusing to package:")
        for item in found:
            print("  - %s" % item)
        return 1
    dist = os.path.join(_paths.REPO, "dist")
    files, digest = build(dist)
    print("Packaged %d files, version %s" % (len(files), __version__))
    for name in NAMES:
        print("  dist/%s" % name)
    print("  sha256 %s (both files are the same bytes)" % digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
