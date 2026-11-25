#!/usr/bin/env python3
"""Check the credits: THIRD_PARTY_NOTICES.md against the tree.

    python3 tools/notices.py            exit 1 and name every gap
    python3 tools/notices.py --root DIR check another checkout

Credit that exists only as a good intention rots. This check makes it a build
failure to borrow from a source without recording it:

  * a file that carries a marker line (a comment starting with the marker
    word and the source's short name) must be listed under that source,
  * a file listed as derived or as an idea must exist and carry its marker,
  * every source names its holder, license, link and full commit, and points
    at a license text under licenses/ that states the same copyright line,
  * every file under licenses/ belongs to a source,
  * the project's own LICENSE and NOTICE are in place, and the copies that
    travel inside the skill package are the same bytes.
"""

import argparse
import glob
import os
import re
import sys

import _paths

NOTICES = "THIRD_PARTY_NOTICES.md"
WORD = "THIRD-PARTY"
MARKER = re.compile(r"^\s*(?:#|<!--|//)\s*" + WORD + r": ([a-z0-9][a-z0-9-]*)", re.M)
FIELD = {
    "source": re.compile(r"^- Source: (https://\S+)", re.M),
    "commit": re.compile(r"^- Commit: `([0-9a-f]{40})`", re.M),
    "license_text": re.compile(r"^- License text: `(licenses/[\w.-]+)`", re.M),
    "marker": re.compile(r"^- Marker: `" + WORD + r": ([a-z0-9][a-z0-9-]*)`", re.M),
}
KINDS = {
    "Derived, modified:": "derived",
    "Ideas, not text:": "ideas",
    "No header:": "no_header",
    "Unmodified copy:": "copy",
}
NEEDS_MARKER = ("derived", "ideas")
TEXT_EXTENSIONS = (".py", ".md", ".json", ".yml", ".yaml", ".txt", ".cff", ".toml", ".cfg", ".sh", ".svg")
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "licenses"}
OWN = (("LICENSE", "LICENSE.txt"), ("NOTICE", "NOTICE.txt"))


def sections(text):
    """Split the notices into (heading, body) pairs, one per level-two heading."""
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    return [(parts[index].strip(), parts[index + 1]) for index in range(1, len(parts), 2)]


def listed_paths(body):
    """(kind, path or glob) for every file a section lists."""
    out, kind = [], None
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped in KINDS:
            kind = KINDS[stripped]
        elif stripped.startswith("- ") and kind is not None:
            subject = stripped[2:].split(": ", 1)[0]
            for path in re.findall(r"`([^`]+)`", subject):
                out.append((kind, path))
        elif stripped and not stripped.startswith("- "):
            kind = None
    return out


def parse(text):
    """The sources the notices describe, keyed by marker name."""
    sources, problems = {}, []
    for heading, body in sections(text):
        match = FIELD["marker"].search(body)
        if not match:
            if any(label in body for label in KINDS):
                problems.append("section %r lists files but has no Marker line" % heading)
            continue
        entry = {"heading": heading, "files": listed_paths(body)}
        for name, pattern in FIELD.items():
            found = pattern.search(body)
            if found:
                entry[name] = found.group(1)
            else:
                problems.append("%s: no %s line (or it is malformed)" % (heading, name.replace("_", " ")))
        if ", Copyright " not in heading or heading.count(", ") < 2:
            problems.append("%s: the heading must read 'name, Copyright holder, license'" % heading)
        else:
            entry["copyright"] = heading.split(", ", 1)[1].rsplit(", ", 1)[0]
        if entry["marker"] in sources:
            problems.append("marker %s is used by two sections" % entry["marker"])
        sources[entry["marker"]] = entry
    return sources, problems


def marked_files(root):
    """{relative path: set of marker names} for every text file that carries a marker line."""
    found = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS)
        for name in sorted(files):
            if not name.endswith(TEXT_EXTENSIONS):
                continue
            path = os.path.join(folder, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            names = set(MARKER.findall(text))
            if names:
                found[os.path.relpath(path, root).replace(os.sep, "/")] = names
    return found


def _same_bytes(first, second):
    try:
        with open(first, "rb") as one, open(second, "rb") as two:
            return one.read() == two.read()
    except OSError:
        return False


def run(root=None):
    """Every gap between the notices and the tree. An empty list means the credits hold."""
    root = root or _paths.REPO
    try:
        with open(os.path.join(root, NOTICES), "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return {"problems": ["%s is missing" % NOTICES], "sources": 0, "files": 0, "licenses": 0}
    sources, problems = parse(text)
    marked = marked_files(root)
    files_checked = 0

    for name, entry in sorted(sources.items()):
        listed = set()
        for kind, pattern in entry["files"]:
            matches = sorted(glob.glob(os.path.join(root, *pattern.split("/"))))
            if not matches:
                problems.append("%s lists %s, which does not exist" % (name, pattern))
            for path in matches:
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                listed.add(rel)
                files_checked += 1
                if kind in NEEDS_MARKER and name not in marked.get(rel, set()):
                    problems.append("%s is listed under %s but carries no '%s: %s' line" % (rel, name, WORD, name))
        for rel, names in sorted(marked.items()):
            if name in names and rel not in listed:
                problems.append("%s carries '%s: %s' but %s does not list it" % (rel, WORD, name, NOTICES))
        license_rel = entry.get("license_text")
        if license_rel:
            try:
                with open(os.path.join(root, *license_rel.split("/")), "r", encoding="utf-8") as handle:
                    license_text = handle.read()
            except OSError:
                problems.append("%s: %s is missing" % (name, license_rel))
            else:
                if entry.get("copyright") and entry["copyright"] not in license_text:
                    problems.append("%s: %s does not state '%s'" % (name, license_rel, entry["copyright"]))

    for rel, names in sorted(marked.items()):
        for name in sorted(names - set(sources)):
            problems.append("%s carries '%s: %s', a source %s does not describe" % (rel, WORD, name, NOTICES))

    referenced = set(entry.get("license_text") for entry in sources.values())
    license_dir = os.path.join(root, "licenses")
    on_disk = sorted(os.listdir(license_dir)) if os.path.isdir(license_dir) else []
    for name in on_disk:
        if "licenses/%s" % name not in referenced:
            problems.append("licenses/%s belongs to no source in %s" % (name, NOTICES))

    skill = os.path.join(root, "skills", _paths.SKILL_NAME)
    for own, shipped in OWN:
        if not os.path.isfile(os.path.join(root, own)):
            problems.append("%s is missing" % own)
        elif not _same_bytes(os.path.join(root, own), os.path.join(skill, shipped)):
            problems.append("skills/%s/%s is missing or differs from %s" % (_paths.SKILL_NAME, shipped, own))
    return {"problems": problems, "sources": len(sources), "files": files_checked, "licenses": len(on_disk)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=_paths.REPO, help="repository to check (default: this one)")
    args = parser.parse_args()
    report = run(args.root)
    for item in report["problems"]:
        print("GAP: %s" % item)
    if report["problems"]:
        print("Credits are incomplete. Fix %s or the marker lines." % NOTICES)
        return 1
    print("Credits OK: %d sources, %d listed files, %d license texts." % (report["sources"], report["files"], report["licenses"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
