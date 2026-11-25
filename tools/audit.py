#!/usr/bin/env python3
"""Static self-audit: what can this skill read, write, run and send?

    python3 tools/audit.py            human-readable report, exit 1 on a finding
    python3 tools/audit.py --json     the same as JSON
    python3 tools/audit.py --write    also refresh docs/AUDIT.md

It parses every Python file the skill ships (no execution) and inventories the
rest of the skill folder. The claims in SECURITY.md are exactly the checks
below; if one stops being true, this script and the test suite fail.

This is a capability inventory, not a malware scanner. Run a dedicated skill
scanner as well before installing any third-party skill, this one included.
"""

import argparse
import ast
import json
import os
import re
import sys

import _paths

ALLOWED_IMPORTS = {
    "__future__", "argparse", "datetime", "difflib", "hashlib", "json", "os", "re", "sys", "abp",
}
ALLOWED_OS = {
    "path", "walk", "listdir", "sep", "devnull", "dup2", "open", "O_WRONLY",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "input", "breakpoint"}
WRITE_MODES = set("wax+")
ALLOWED_WRITE_SITES = {("scripts/abp/cli.py", "_cmd_cadence")}
TEXT_EXTENSIONS = {".py", ".md", ".json", ".txt", ".yaml", ".yml"}
HIDDEN = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\u00ad]")
DASHES = re.compile("[\u2013\u2014]")
URL = re.compile(r"https?://[^\s\"'<>)\]]+")
SECRET = re.compile(r"(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
ALLOWED_URL_HOSTS = {
    "www.danlaunchpad.co.il", "www.opm.gov", "www.momtestbook.com", "erinmeyer.com",
    # The Apache License names its own address. LICENSE.txt is the only file that carries it.
    "www.apache.org",
}
HOOK_NAMES = {"hooks.json", ".mcp.json", ".lsp.json", "settings.json"}


def _function_of(tree, lineno):
    best = "<module>"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= lineno <= end:
                best = node.name
    return best


def audit_python(path, rel):
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=rel)
    findings, imports, writes, os_uses = [], set(), [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else None
            if name in FORBIDDEN_CALLS:
                findings.append("%s:%d calls %s()" % (rel, node.lineno, name))
            if name == "open":
                mode = "r"
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for keyword in node.keywords:
                    if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                        mode = str(keyword.value.value)
                if set(mode) & WRITE_MODES:
                    writes.append((rel, _function_of(tree, node.lineno), node.lineno))
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os":
                os_uses.add(node.attr)
    for name in sorted(imports - ALLOWED_IMPORTS):
        findings.append("%s imports %s (not on the allowlist)" % (rel, name))
    for attr in sorted(os_uses - ALLOWED_OS):
        findings.append("%s uses os.%s (not on the allowlist)" % (rel, attr))
    for site in writes:
        if (site[0], site[1]) not in ALLOWED_WRITE_SITES:
            findings.append("%s:%d opens a file for writing in %s()" % (site[0], site[2], site[1]))
    return {"imports": sorted(imports), "os": sorted(os_uses), "writes": writes, "findings": findings}


def run(root=None):
    root = root or _paths.SKILL
    report = {
        "skill": os.path.basename(root),
        "python_files": 0,
        "data_files": 0,
        "other_files": 0,
        "imports": set(),
        "os_attributes": set(),
        "write_sites": [],
        "urls": {},
        "findings": [],
    }
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if not name.startswith(".") and name != "__pycache__")
        for name in sorted(files):
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            ext = os.path.splitext(name)[1].lower()
            if name in HOOK_NAMES or rel.startswith("hooks/"):
                report["findings"].append("%s: hook, MCP or settings file inside the skill" % rel)
            if ext not in TEXT_EXTENSIONS:
                report["findings"].append("%s: unexpected file type" % rel)
                report["other_files"] += 1
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    text = handle.read()
            except UnicodeDecodeError:
                report["findings"].append("%s: not valid UTF-8 text" % rel)
                continue
            if HIDDEN.search(text):
                report["findings"].append("%s: hidden or bidirectional control characters" % rel)
            if DASHES.search(text):
                report["findings"].append("%s: em or en dash" % rel)
            if SECRET.search(text):
                report["findings"].append("%s: something that looks like a credential" % rel)
            for url in URL.findall(text):
                host = url.split("/")[2].lower()
                report["urls"].setdefault(host, set()).add(rel)
            if ext == ".py":
                report["python_files"] += 1
                result = audit_python(path, rel)
                report["imports"].update(result["imports"])
                report["os_attributes"].update(result["os"])
                report["write_sites"].extend("%s in %s()" % (site[0], site[1]) for site in result["writes"])
                report["findings"].extend(result["findings"])
            elif ext == ".json":
                report["data_files"] += 1
            else:
                report["other_files"] += 1
    for host in sorted(report["urls"]):
        if host not in ALLOWED_URL_HOSTS:
            report["findings"].append("URL host %s is not on the allowlist (%s)" % (host, ", ".join(sorted(report["urls"][host]))))
    report["imports"] = sorted(report["imports"])
    report["os_attributes"] = sorted(report["os_attributes"])
    report["urls"] = dict((host, sorted(files)) for host, files in sorted(report["urls"].items()))
    report["ok"] = not report["findings"]
    return report


def render(report):
    lines = [
        "# Self-audit: %s" % report["skill"],
        "",
        "Generated by `python3 tools/audit.py --write`. Static analysis only: nothing is executed.",
        "",
        "| Question | Answer |",
        "| --- | --- |",
        "| Does it use the network? | No. No networking module is imported (allowlist below). |",
        "| Does it start other programs? | No. No subprocess, no os.system, no eval or exec. |",
        "| Does it read environment variables or credentials? | No. |",
        "| Does it install hooks, MCP servers or settings? | No such file exists in the skill. |",
        "| Does it write files? | Only where the user asks: %s. |" % ("; ".join(report["write_sites"]) or "nowhere"),
        "| What does it read? | Its own `data/*.json` and `seal.json`, plus the draft or fact sheet you pass it. |",
        "",
        "## Inventory",
        "",
        "- Python files: %d" % report["python_files"],
        "- JSON files (rule tables, metadata, log, seal): %d" % report["data_files"],
        "- Other text files: %d" % report["other_files"],
        "- Imports (all standard library, plus the skill's own package `abp`): %s" % ", ".join("`%s`" % name for name in report["imports"]),
        "- `os` attributes used: %s" % ", ".join("`os.%s`" % name for name in report["os_attributes"]),
        "",
        "## URLs mentioned (text only, never fetched)",
        "",
    ]
    for host, files in report["urls"].items():
        lines.append("- `%s` in %s" % (host, ", ".join("`%s`" % name for name in files)))
    lines.extend(["", "## Findings", ""])
    if report["findings"]:
        lines.extend("- %s" % item for item in report["findings"])
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true", help="refresh docs/AUDIT.md")
    args = parser.parse_args()
    report = run()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report))
    if args.write:
        path = os.path.join(_paths.REPO, "docs", "AUDIT.md")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
