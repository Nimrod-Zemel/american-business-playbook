# THIRD-PARTY: founder-skills. Adapted from founder-skills/scripts/script_hashes.py,
# Copyright 2026 lool ventures, licensed under the Apache License, Version 2.0.
# Kept: the manifest shape, sha256 over bytes with CRLF folded to LF, hashing a
# Markdown file by the body after its front matter, the walk that skips dot and
# double-underscore folders, and counting an unlisted .py file as a difference.
# Changed for this skill: it seals every shipped file, the check runs before the
# engine loads and stops it, there is no tolerance threshold, an unlisted file
# under scripts/ or data/ breaks the seal, the rule-table fingerprint and the
# refusal message are new, and the manifest writer lives outside the shipped
# skill. Record: NOTICE.txt, and THIRD_PARTY_NOTICES.md in the source repository.
"""The integrity seal: seal.json lists a sha256 for every file the skill ships.

Like the strip on a medicine bottle, the seal does not prove who made the
skill; it proves nobody opened it since it was sealed. Every run of the
engine recomputes the hashes and refuses to answer when:

  * a listed file changed or is missing, or
  * a file the seal does not list appears under scripts/ or data/
    (a planted scripts/json.py would be imported before the standard
    library's, and a planted data file could change the rules).

Limits, stated plainly: whoever can edit a file can also re-run
tools/seal.py --write, and whoever can rewrite this checker (or playbook.py,
which calls it before loading anything else) can defeat it. The seal catches
partial edits, planted files, and edits an agent makes mid-session. Against a
modified copy of the whole repository the answer is the signed provenance
attestation on the GitHub release, not this file.

Hashing rules: bytes with CRLF folded to LF, so a Windows checkout hashes the
same. For SKILL.md and SKILL_HE.md only the body after the front matter is
hashed, because installers are known to rewrite front matter.
"""

from __future__ import annotations

import hashlib
import json
import os

SEAL_FILE = "seal.json"
EXIT_SEAL = 3
SCHEMA = 1
ALGORITHM = "sha256"
BODY_ONLY = ("SKILL.md", "SKILL_HE.md")
GUARDED_DIRS = ("scripts", "data")


def _skip_dir(name):
    return name.startswith(".") or name.startswith("__")


def _skip_file(name):
    return name.startswith(".") or name.endswith((".pyc", ".pyo"))


def body_after_front_matter(data):
    """Bytes after a leading --- front matter block, or everything when there is none."""
    lines = data.split(b"\n")
    if not lines or lines[0].strip() != b"---":
        return data
    for index in range(1, len(lines)):
        if lines[index].strip() == b"---":
            return b"\n".join(lines[index + 1:])
    return data


def digest(path, body_only=False):
    """sha256 of a file with CRLF folded to LF, or None when it cannot be read."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    data = data.replace(b"\r\n", b"\n")
    if body_only:
        data = body_after_front_matter(data)
    return hashlib.sha256(data).hexdigest()


def walk(root):
    """Every sealable file under root, as sorted POSIX-style relative paths."""
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if not _skip_dir(name))
        for name in sorted(files):
            if _skip_file(name):
                continue
            rel = os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")
            if rel == SEAL_FILE:
                continue
            found.append(rel)
    return sorted(found)


def compute(root):
    """The manifest for the tree at root."""
    files = {}
    for rel in walk(root):
        files[rel] = digest(os.path.join(root, rel), body_only=rel in BODY_ONLY)
    return {
        "schema": SCHEMA,
        "algorithm": ALGORITHM,
        "line_endings": "crlf-as-lf",
        "body_only": list(BODY_ONLY),
        "files": files,
    }


def read(root):
    path = os.path.join(root, SEAL_FILE)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        return None
    return manifest


def verify(root):
    """Compare the tree at root with its seal.

    Returns a dict with status "ok", "absent" or "broken", and for "broken"
    the lists that explain it: changed, missing, unlisted.
    """
    manifest = read(root)
    if manifest is None:
        return {"status": "absent", "changed": [], "missing": [], "unlisted": []}
    listed = manifest["files"]
    changed, missing = [], []
    for rel in sorted(listed):
        actual = digest(os.path.join(root, *rel.split("/")), body_only=rel in BODY_ONLY)
        if actual is None:
            missing.append(rel)
        elif actual != listed[rel]:
            changed.append(rel)
    unlisted = [
        rel
        for rel in walk(root)
        if rel not in listed and (rel.split("/")[0] in GUARDED_DIRS or rel.endswith(".py"))
    ]
    status = "ok" if not (changed or missing or unlisted) else "broken"
    return {"status": status, "changed": changed, "missing": missing, "unlisted": unlisted}


def explain(report):
    """One line naming every file that breaks the seal."""
    parts = []
    for key in ("changed", "missing", "unlisted"):
        if report.get(key):
            parts.append("%s: %s" % (key, ", ".join(report[key])))
    return "; ".join(parts)


def refusal(report):
    """What the engine says instead of an answer when the seal is broken."""
    return {
        "ok": False,
        "error": "seal_broken",
        "message": "The skill's files do not match its integrity seal (%s)." % explain(report),
        "hint": (
            "Do not work around this. Tell the user the skill was modified since it was sealed. "
            "Reinstall from the release, or pass --unsealed to run anyway with the answer stamped as unsealed."
        ),
    }


def rules_digest(root):
    """A short fingerprint of the rule tables in use, printed in every receipt."""
    hasher = hashlib.sha256()
    data_dir = os.path.join(root, "data")
    try:
        names = sorted(name for name in os.listdir(data_dir) if name.endswith(".json"))
    except OSError:
        return "unknown"
    for name in names:
        hasher.update(name.encode("utf-8"))
        hasher.update((digest(os.path.join(data_dir, name)) or "").encode("ascii"))
    return hasher.hexdigest()[:12]
