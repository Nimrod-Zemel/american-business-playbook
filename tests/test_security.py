"""What the skill can touch. These tests are the claims in SECURITY.md, executable."""

import ast
import importlib.util
import marshal
import os
import subprocess
import sys
import unittest

import _util
import audit

MARKER = "PLANTED BYTECODE RAN"


class AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit.run()

    def test_the_self_audit_has_no_findings(self):
        self.assertEqual(self.report["findings"], [])
        self.assertTrue(self.report["ok"])

    def test_only_these_modules_are_imported(self):
        self.assertEqual(
            self.report["imports"],
            ["__future__", "abp", "argparse", "datetime", "difflib", "hashlib", "json", "os", "re", "sys"],
        )

    def test_no_network_process_or_dynamic_code_modules(self):
        forbidden = {
            "socket", "ssl", "http", "urllib", "requests", "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio",
            "subprocess", "multiprocessing", "ctypes", "pty", "signal", "shutil", "tempfile", "glob", "pathlib",
            "pickle", "marshal", "shelve", "importlib", "runpy", "code", "webbrowser", "zoneinfo", "random",
        }
        self.assertEqual(sorted(forbidden & set(self.report["imports"])), [])

    def test_no_environment_or_process_access_through_os(self):
        self.assertEqual(
            self.report["os_attributes"],
            ["O_WRONLY", "devnull", "dup2", "listdir", "open", "path", "sep", "walk"],
        )

    def test_the_only_file_write_is_the_calendar_export(self):
        self.assertEqual(self.report["write_sites"], ["scripts/abp/cli.py in _cmd_cadence()"])

    def test_urls_are_text_only_and_on_the_allowlist(self):
        self.assertEqual(
            sorted(self.report["urls"]),
            ["erinmeyer.com", "www.apache.org", "www.danlaunchpad.co.il", "www.momtestbook.com", "www.opm.gov"],
        )
        # The license's own address appears in the license text and nowhere else.
        self.assertEqual(sorted(set(self.report["urls"]["www.apache.org"])), ["LICENSE.txt"])

    def test_audit_catches_what_it_claims_to_catch(self):
        """The auditor itself is tested: each planted problem must be found."""
        planted = {
            "import socket\n": "imports socket",
            "import subprocess\nsubprocess.run(['ls'])\n": "imports subprocess",
            "import os\nos.system('ls')\n": "os.system",
            "import os\nkey = os.environ.get('API_KEY')\n": "os.environ",
            "eval('1+1')\n": "eval()",
            "open('/tmp/x', 'w').write('x')\n": "for writing",
            "from urllib import request\n": "imports urllib",
            "handle = open('notes.txt', mode='a')\n": "for writing",
        }
        with _util.skill_copy() as root:
            for index, (source, expected) in enumerate(planted.items()):
                path = os.path.join(root, "scripts", "abp", "planted_%d.py" % index)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(source)
                findings = audit.audit_python(path, "scripts/abp/planted_%d.py" % index)["findings"]
                self.assertTrue(any(expected in item for item in findings), "%r not caught: %s" % (source, findings))

    def test_audit_catches_hidden_characters_hooks_and_binaries(self):
        with _util.skill_copy() as root:
            with open(os.path.join(root, "references", "notes.md"), "w", encoding="utf-8") as handle:
                handle.write("looks harmless" + _util.RLM + "\n")
            os.makedirs(os.path.join(root, "hooks"))
            with open(os.path.join(root, "hooks", "hooks.json"), "w", encoding="utf-8") as handle:
                handle.write("{}")
            with open(os.path.join(root, "tool.bin"), "wb") as handle:
                handle.write(b"\x00\x01")
            with open(os.path.join(root, "references", "link.md"), "w", encoding="utf-8") as handle:
                handle.write("see https://evil.example.net/payload\n")
            findings = "\n".join(audit.run(root)["findings"])
            for expected in ("hidden or bidirectional", "hook, MCP or settings file", "unexpected file type", "evil.example.net"):
                self.assertIn(expected, findings)


class ImportPathTest(unittest.TestCase):
    """A file planted in scripts/ under a standard-library name must never run."""

    def test_the_entry_point_preloads_every_standard_module_the_engine_imports(self):
        with open(_util.ENTRY, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        preloaded = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                preloaded.update(alias.name for alias in node.names)
        needed = set(audit.run()["imports"]) - {"abp"}
        self.assertEqual(sorted(needed - preloaded), [])

    def test_planted_modules_do_not_execute_even_when_the_seal_is_waved_through(self):
        marker = "PLANTED CODE RAN"
        with _util.skill_copy() as root:
            for name in ("json", "re", "shutil", "gettext", "__future__", "datetime", "hashlib", "argparse", "difflib"):
                with open(os.path.join(root, "scripts", name + ".py"), "w", encoding="utf-8") as handle:
                    handle.write("print(%r)\nraise SystemExit(99)\n" % marker)
            entry = os.path.join(root, "scripts", "playbook.py")
            code, out, err = _util.subprocess_run(["doctor"], entry=entry)
            self.assertEqual(code, 3)
            self.assertNotIn(marker, out + err)
            self.assertIn("unlisted: scripts/__future__.py", err)
            for argv in (["lint", "--help", "--unsealed"], ["scene", "--type", "sales", "--seed", "1", "--unsealed"]):
                code, out, err = _util.subprocess_run(argv, entry=entry)
                self.assertEqual(code, 0, err)
                self.assertNotIn(marker, out + err)

    def test_works_from_inside_the_scripts_folder_too(self):
        code, out, err = _util.subprocess_run(["--version"], cwd=_util.SCRIPTS)
        self.assertEqual((code, out.strip()), (0, "american-business-playbook 2.0.0"), err)


class BytecodeTest(unittest.TestCase):
    """The seal covers source files. Left to its defaults, Python runs a cached
    __pycache__/*.pyc in place of the source next to it, so the engine never
    reads one for its own modules."""

    def plant(self, root, module):
        source = os.path.join(root, "scripts", "abp", module + ".py")
        stat = os.stat(source)
        code = compile("print(%r)\nraise SystemExit(99)\n" % MARKER, source, "exec")
        header = (
            importlib.util.MAGIC_NUMBER
            + (0).to_bytes(4, "little")
            + (int(stat.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little")
            + (stat.st_size & 0xFFFFFFFF).to_bytes(4, "little")
        )
        target = importlib.util.cache_from_source(source)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(header + marshal.dumps(code))

    def python(self, snippet, *args):
        # -B: these snippets import the engine directly and must not leave bytecode in the tree.
        return subprocess.run([sys.executable, "-I", "-B", "-c", snippet] + list(args), capture_output=True, text=True, timeout=60)

    def test_control_the_planted_file_runs_when_python_is_left_to_its_defaults(self):
        """Without this control the next test could pass for the wrong reason."""
        with _util.skill_copy() as root:
            self.plant(root, "core")
            proc = self.python("import sys; sys.path.insert(0, sys.argv[1]); import abp.core", os.path.join(root, "scripts"))
            self.assertIn(MARKER, proc.stdout)

    def test_planted_bytecode_never_runs_through_the_entry_point(self):
        with _util.skill_copy() as root:
            for module in ("__init__", "seal", "core", "cli", "decode", "mail", "phrases"):
                self.plant(root, module)
            entry = os.path.join(root, "scripts", "playbook.py")
            for argv in (["doctor", "--lang", "en"], ["bench", "--topic", "pricing"], ["--version"]):
                code, out, err = _util.subprocess_run(argv, entry=entry)
                self.assertEqual(code, 0, err)
                self.assertNotIn(MARKER, out + err)
            self.assertIn("All good.", _util.subprocess_run(["doctor", "--lang", "en"], entry=entry)[1])

    def test_every_engine_module_loads_while_bytecode_is_switched_off(self):
        """A module imported later, after start-up, would be read from the cache again."""
        snippet = (
            "import os, sys; sys.path.insert(0, sys.argv[1]); import abp.cli; "
            "names = [n[:-3] for n in os.listdir(os.path.join(sys.argv[1], 'abp')) if n.endswith('.py') and n != '__init__.py']; "
            "print(sorted(n for n in names if 'abp.' + n not in sys.modules))"
        )
        proc = self.python(snippet, _util.SCRIPTS)
        self.assertEqual(proc.stdout.strip(), "[]", proc.stderr)

    def test_the_tests_themselves_leave_no_bytecode_in_the_skill(self):
        for folder, dirs, _files in os.walk(_util.SKILL):
            self.assertNotIn("__pycache__", dirs, folder)

    def test_the_cache_setting_is_restored_for_the_rest_of_the_run(self):
        with open(_util.ENTRY, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("sys.pycache_prefix = os.path.join(os.path.abspath(__file__), \"no-bytecode\")", source)
        self.assertIn("sys.pycache_prefix = cache_setting", source)
        self.assertLess(source.index("sys.pycache_prefix = os.path.join"), source.index("from abp import seal"))


class SourceHygieneTest(unittest.TestCase):
    def test_every_script_parses_as_python_3_9(self):
        for path in _util.text_files(os.path.join(_util.SKILL, "scripts"), (".py",)):
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            try:
                ast.parse(source, filename=path, feature_version=(3, 9))
            except SyntaxError as exc:
                self.fail("%s is not valid Python 3.9: %s" % (path, exc))

    def test_engine_code_is_plain_ascii(self):
        """No look-alike or invisible characters can hide in code that is ASCII only.

        Every Hebrew word the engine prints lives in data/*.json, where it is
        text and never an identifier.
        """
        scripts = list(_util.text_files(os.path.join(_util.SKILL, "scripts"), (".py",)))
        self.assertGreaterEqual(len(scripts), 12)
        for path in scripts:
            with open(path, "rb") as handle:
                for number, line in enumerate(handle, 1):
                    self.assertTrue(line.isascii(), "%s:%d is not plain ASCII" % (os.path.relpath(path, _util.REPO), number))

    def test_no_credentials_or_personal_contact_details_anywhere(self):
        import re

        secret = re.compile(r"(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
        email = re.compile(r"[\w.+-]+@[\w-]+\.(?:com|co\.il|org|net|io|ac\.il)\b")
        allowed_emails = set()
        for path in _util.text_files(_util.REPO):
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            self.assertIsNone(secret.search(text), path)
            for found in email.findall(text):
                self.assertIn(found, allowed_emails, "%s contains the address %s" % (path, found))

    def test_the_skill_folder_has_no_hooks_servers_or_executables(self):
        present = set()
        for _folder, dirs, files in os.walk(_util.SKILL):
            present.update(dirs)
            present.update(files)
        for name in ("hooks", "hooks.json", ".mcp.json", ".lsp.json", "settings.json", "bin", "agents", "monitors"):
            self.assertNotIn(name, present)
        self.assertFalse(os.path.exists(os.path.join(_util.REPO, "bin")), "a top-level bin/ blocks installation in Claude apps")
        self.assertFalse(os.path.exists(os.path.join(_util.REPO, "hooks")))


if __name__ == "__main__":
    unittest.main()
