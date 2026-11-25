"""Shared helpers for the test suite. Standard library only: run with
`python3 -m unittest discover -s tests` (or pytest, if you prefer)."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_NAME = "american-business-playbook"
SKILL = os.path.join(REPO, "skills", SKILL_NAME)
SCRIPTS = os.path.join(SKILL, "scripts")
TOOLS = os.path.join(REPO, "tools")
FIXTURES = os.path.join(REPO, "tests", "fixtures")
ENTRY = os.path.join(SCRIPTS, "playbook.py")

sys.dont_write_bytecode = True
for path in (SCRIPTS, TOOLS):
    if path not in sys.path:
        sys.path.insert(0, path)

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
RLM = chr(0x200F)
ZWSP = chr(0x200B)


class _Untouchable(io.StringIO):
    """The stdin of a run that was given no input. Reading it would hang on a
    host that leaves the stream open, so the engine must never try."""

    def read(self, *args):
        raise AssertionError("the engine read stdin without being asked to (no --file - or --in -)")

    readline = read


def run(argv, stdin=None):
    """Run the command line in-process. Returns (exit_code, stdout, stderr)."""
    from abp import cli

    out, err = io.StringIO(), io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO(stdin) if stdin is not None else _Untouchable()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.stdin = saved
    return code, out.getvalue(), err.getvalue()


def run_json(argv, stdin=None):
    """Run a command with --format json and return (exit_code, parsed_output)."""
    code, out, _err = run(list(argv) + ["--format", "json"], stdin)
    return code, json.loads(out)


def facts(command, sheet, *extra):
    """Run a fact-sheet command and return its result dict."""
    code, payload = run_json([command, "--in", "-"] + list(extra), json.dumps(sheet))
    assert payload.get("ok"), payload
    return payload["result"]


def subprocess_run(args, stdin=None, entry=ENTRY, cwd=None):
    """Run the real entry point in a fresh interpreter."""
    proc = subprocess.run(
        [sys.executable, "-B", entry] + list(args),
        input=stdin, capture_output=True, text=True, encoding="utf-8", cwd=cwd, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


@contextlib.contextmanager
def skill_copy():
    """A throwaway copy of the skill folder, for tests that tamper with it."""
    base = tempfile.mkdtemp(prefix="abp-test-")
    target = os.path.join(base, SKILL_NAME)
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns("__pycache__"))
    try:
        yield target
    finally:
        shutil.rmtree(base, ignore_errors=True)


@contextlib.contextmanager
def repo_copy():
    """A throwaway copy of the whole repository, for tests that tamper with it."""
    base = tempfile.mkdtemp(prefix="abp-repo-")
    target = os.path.join(base, "repo")
    shutil.copytree(REPO, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.zip", "*.skill", "*.png"))
    try:
        yield target
    finally:
        shutil.rmtree(base, ignore_errors=True)


def read(*parts):
    with open(os.path.join(REPO, *parts), "r", encoding="utf-8") as handle:
        return handle.read()


TEXT_EXTENSIONS = (".py", ".md", ".json", ".yml", ".yaml", ".txt", ".sh", ".toml", ".cfg", ".cff", ".svg")
TEXT_NAMES = ("LICENSE", "NOTICE", "CODEOWNERS", ".gitignore", ".gitattributes")


def text_files(root, extensions=TEXT_EXTENSIONS):
    """Every text file under root, skipping VCS, caches and build output."""
    skip = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
    for folder, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in skip]
        for name in files:
            if name.endswith(extensions) or name in TEXT_NAMES:
                yield os.path.join(folder, name)
