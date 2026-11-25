"""The release package: what is in it, that it is reproducible, and that it works once unpacked."""

import hashlib
import os
import tempfile
import unittest
import zipfile

import _util
import package
from abp import seal


class PackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.files, cls.digest = package.build(cls.folder.name)
        cls.archive = os.path.join(cls.folder.name, _util.SKILL_NAME + ".zip")

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_tree_is_ready_to_package(self):
        self.assertEqual(package.problems(), [], "run: python3 tools/build.py")

    def test_both_names_hold_the_same_bytes(self):
        with open(self.archive, "rb") as handle:
            first = handle.read()
        with open(os.path.join(self.folder.name, _util.SKILL_NAME + ".skill"), "rb") as handle:
            second = handle.read()
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first).hexdigest(), self.digest)
        with open(os.path.join(self.folder.name, "SHA256SUMS"), "r", encoding="utf-8") as handle:
            lines = handle.read().strip().split("\n")
        self.assertEqual(lines, ["%s  %s.zip" % (self.digest, _util.SKILL_NAME), "%s  %s.skill" % (self.digest, _util.SKILL_NAME)])

    def test_the_build_is_reproducible(self):
        with tempfile.TemporaryDirectory() as again:
            _files, digest = package.build(again)
        self.assertEqual(digest, self.digest)

    def test_the_skill_folder_is_the_top_level_of_the_archive(self):
        """Claude looks for <skill-name>/SKILL.md inside an uploaded zip."""
        with zipfile.ZipFile(self.archive) as archive:
            names = archive.namelist()
        self.assertIn("%s/SKILL.md" % _util.SKILL_NAME, names)
        self.assertTrue(all(name.startswith(_util.SKILL_NAME + "/") for name in names))
        self.assertEqual(names, sorted(names))

    def test_the_archive_holds_the_sealed_files_and_nothing_else(self):
        with zipfile.ZipFile(self.archive) as archive:
            names = sorted(name[len(_util.SKILL_NAME) + 1:] for name in archive.namelist())
        self.assertEqual(names, sorted(seal.walk(_util.SKILL) + ["seal.json"]))
        for name in names:
            self.assertFalse(name.startswith(("tests/", "tools/", "evals/", ".")), name)
            self.assertNotIn("__pycache__", name)
            self.assertFalse(name.endswith((".pyc", "README.md")), name)

    def test_it_holds_no_absolute_paths_links_or_executables(self):
        with zipfile.ZipFile(self.archive) as archive:
            for info in archive.infolist():
                self.assertFalse(info.filename.startswith("/") or ".." in info.filename.split("/"), info.filename)
                self.assertEqual(info.external_attr >> 16, 0o644, info.filename)
                self.assertEqual(info.date_time, package.FIXED_TIME)

    def test_a_clean_extraction_passes_its_own_doctor_and_answers(self):
        with tempfile.TemporaryDirectory() as target:
            with zipfile.ZipFile(self.archive) as archive:
                archive.extractall(target)
            root = os.path.join(target, _util.SKILL_NAME)
            self.assertEqual(seal.verify(root)["status"], "ok")
            entry = os.path.join(root, "scripts", "playbook.py")
            code, out, err = _util.subprocess_run(["doctor", "--lang", "en"], entry=entry, cwd=target)
            self.assertEqual(code, 0, out + err)
            self.assertIn("All good.", out)
            self.assertIn("seal ok", out)
            sheet = '{"context": "sales", "today": "2026-11-24", "quotes": ["This is amazing!"], "next_step": {"exists": false}, "cost_to_them": []}'
            code, out, err = _util.subprocess_run(["decode", "--in", "-", "--lang", "en"], stdin=sheet, entry=entry, cwd=target)
            self.assertEqual(code, 0, err)
            self.assertIn("Verdict: Yellow", out)
            leftovers = [name for _folder, dirs, _files in os.walk(root) for name in dirs if name == "__pycache__"]
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
