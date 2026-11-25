"""Credit is part of the build: every borrowed file is recorded, and the check bites."""

import hashlib
import os
import re
import unittest

import _util
import notices

# The license texts are kept byte for byte as their owners publish them.
LICENSE_TEXTS = {
    "Apache-2.0-anthropic.txt": "bc6b3af2f331cbc7fb0da1344efb2cbe5877a31498b4d70dbc7000f3405a1362",
    "Apache-2.0-lool-ventures.txt": "92547f7f9a3c9dcb2c10ad183f05f2f2f0bf6e2bb2648205907b1d770c3cec93",
    "MIT-garry-tan.txt": "e56fbb5b3d95756f3fa1cfefa24732ec79f18ece1ad08a4e79e00df57e8b198c",
    "MIT-skills-il.txt": "cdbc9963ca21a7c9230c10889ed04e5e5d4a5ca0f4708699f3919e6f4c960c2c",
    "MIT-yaniv-golan.txt": "cd34da18ee9a9502eeb5210d323b1e0ea3f9c440eab3af43ca520185ed8ab041",
}
MARK = notices.WORD + ": "


def problems(root):
    return notices.run(root)["problems"]


class CreditsHoldTest(unittest.TestCase):
    def test_the_notices_match_the_tree(self):
        report = notices.run()
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["sources"], 5)
        self.assertEqual(report["licenses"], len(LICENSE_TEXTS))
        self.assertGreater(report["files"], 10)

    def test_every_source_has_a_holder_a_link_a_full_commit_and_a_license_text(self):
        sources, found = notices.parse(_util.read(notices.NOTICES))
        self.assertEqual(found, [])
        self.assertEqual(sorted(sources), ["anthropic-skills", "founder-skills", "gstack", "proof-engine", "skills-il"])
        for name, entry in sources.items():
            self.assertRegex(entry["source"], r"^https://github\.com/[\w.-]+/[\w.-]+$", name)
            self.assertRegex(entry["commit"], r"^[0-9a-f]{40}$", name)
            self.assertTrue(entry["copyright"].startswith("Copyright "), name)
            self.assertIn(entry["copyright"], _util.read(*entry["license_text"].split("/")), name)

    def test_license_texts_are_the_published_bytes(self):
        folder = os.path.join(_util.REPO, "licenses")
        self.assertEqual(sorted(os.listdir(folder)), sorted(LICENSE_TEXTS))
        for name, expected in LICENSE_TEXTS.items():
            with open(os.path.join(folder, name), "rb") as handle:
                self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), expected, name)

    def test_the_adapted_module_says_so_in_its_own_header(self):
        """Apache-2.0, section 4(b): a modified file carries a prominent notice that it was changed."""
        header = _util.read("skills", _util.SKILL_NAME, "scripts", "abp", "seal.py").split('"""')[0]
        for needle in (MARK + "founder-skills", "script_hashes.py", "Copyright 2026 lool ventures", "Apache License, Version 2.0", "Changed for this skill"):
            self.assertIn(needle, header)

    def test_the_package_carries_its_license_and_credits(self):
        from abp import seal

        sealed = seal.read(_util.SKILL)["files"]
        for name in ("LICENSE.txt", "NOTICE.txt"):
            self.assertIn(name, sealed)
        notice = _util.read("NOTICE")
        for needle in ("Copyright 2026 Nimrod Zemel", "Copyright 2026 lool ventures", "Skills IL", "THIRD_PARTY_NOTICES.md"):
            self.assertIn(needle, notice)
        # No address in the notice: every URL inside the package is on the audit's short allowlist.
        self.assertNotRegex(notice, r"https?://")

    def test_the_build_and_ci_run_the_check(self):
        self.assertIn("notices.run()", _util.read("tools", "build.py"))
        self.assertIn("tools/notices.py", _util.read(".github", "workflows", "ci.yml"))


class CheckBitesTest(unittest.TestCase):
    """Each gap is planted in a copy of the repository and must be reported."""

    def test_a_marked_file_that_is_not_listed(self):
        with _util.repo_copy() as root:
            with open(os.path.join(root, "tools", "borrowed.py"), "w", encoding="utf-8") as handle:
                handle.write("# %sfounder-skills. Copied from somewhere.\n" % MARK)
            found = problems(root)
        self.assertEqual(len(found), 1, found)
        self.assertIn("tools/borrowed.py", found[0])
        self.assertIn("does not list it", found[0])

    def test_a_marker_for_a_source_nobody_recorded(self):
        with _util.repo_copy() as root:
            with open(os.path.join(root, "docs", "borrowed.md"), "w", encoding="utf-8") as handle:
                handle.write("<!-- %ssomebody-else. A table. -->\n# Notes\n" % MARK)
            found = problems(root)
        self.assertEqual(len(found), 1, found)
        self.assertIn("somebody-else", found[0])

    def test_a_listed_file_that_lost_its_marker(self):
        with _util.repo_copy() as root:
            path = os.path.join(root, "tools", "seal.py")
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text.replace(MARK + "founder-skills", "Adapted from founder-skills"))
            found = problems(root)
        self.assertEqual(len(found), 1, found)
        self.assertIn("tools/seal.py is listed under founder-skills but carries no", found[0])

    def test_a_listed_file_that_is_gone(self):
        with _util.repo_copy() as root:
            os.remove(os.path.join(root, "CITATION.cff"))
            found = problems(root)
        self.assertTrue(any("CITATION.cff, which does not exist" in item for item in found), found)

    def test_a_shortened_commit(self):
        with _util.repo_copy() as root:
            path = os.path.join(root, notices.NOTICES)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text.replace("`4394a02363d6fb1acc6115927bc04ee26b78e860`", "`4394a023`"))
            found = problems(root)
        self.assertTrue(any("gstack" in item and "no commit line" in item for item in found), found)

    def test_a_license_text_nobody_claims_and_one_that_was_swapped(self):
        with _util.repo_copy() as root:
            with open(os.path.join(root, "licenses", "Extra.txt"), "w", encoding="utf-8") as handle:
                handle.write("Some license.\n")
            with open(os.path.join(root, "licenses", "MIT-garry-tan.txt"), "w", encoding="utf-8") as handle:
                handle.write("MIT License\n\nCopyright (c) 2026 Somebody Else\n")
            found = problems(root)
        self.assertTrue(any("licenses/Extra.txt belongs to no source" in item for item in found), found)
        self.assertTrue(any("MIT-garry-tan.txt does not state 'Copyright (c) 2026 Garry Tan'" in item for item in found), found)

    def test_a_missing_license_text(self):
        with _util.repo_copy() as root:
            os.remove(os.path.join(root, "licenses", "MIT-skills-il.txt"))
            found = problems(root)
        self.assertTrue(any("licenses/MIT-skills-il.txt is missing" in item for item in found), found)

    def test_the_copy_inside_the_package_must_match(self):
        with _util.repo_copy() as root:
            with open(os.path.join(root, "skills", _util.SKILL_NAME, "NOTICE.txt"), "a", encoding="utf-8") as handle:
                handle.write("One more line.\n")
            os.remove(os.path.join(root, "skills", _util.SKILL_NAME, "LICENSE.txt"))
            found = problems(root)
        self.assertEqual(len(found), 2, found)
        self.assertTrue(all("is missing or differs from" in item for item in found), found)

    def test_a_section_that_lists_files_without_naming_its_marker(self):
        with _util.repo_copy() as root:
            path = os.path.join(root, notices.NOTICES)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("\n## Somebody, Copyright 2026 Somebody, MIT License\n\nDerived, modified:\n\n- `README.md`: a paragraph.\n")
            found = problems(root)
        self.assertTrue(any("lists files but has no Marker line" in item for item in found), found)

    def test_the_marker_is_only_read_from_comment_lines(self):
        """Prose that explains the marker must not count as one, or the docs could never describe it."""
        self.assertEqual(notices.MARKER.findall("1. Put a line that starts with `%sname`.\n" % MARK), [])
        self.assertEqual(notices.MARKER.findall("- Marker: `%sgstack`\n" % MARK), [])
        self.assertEqual(notices.MARKER.findall("# %sgstack. The format.\n" % MARK), ["gstack"])
        self.assertEqual(notices.MARKER.findall("<!-- %sfounder-skills (page structure). -->\n" % MARK), ["founder-skills"])
        marked = notices.marked_files(_util.REPO)
        self.assertNotIn("tools/notices.py", marked)
        self.assertNotIn("tests/test_notices.py", marked)
        self.assertNotIn("CONTRIBUTING.md", marked)


if __name__ == "__main__":
    unittest.main()
