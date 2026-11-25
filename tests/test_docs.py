"""What the documents say must be what the code does.

Covers the Agent Skills format rules, the Skills IL conventions, parity between
the English and Hebrew instructions, and every place where a document names a
command, a flag, a file, a count or a version.
"""

import json
import os
import re
import struct
import unittest

import _util
import audit
import build_refs
from abp import __version__, cli, mail
from abp.core import load

SKILL_MD = _util.read("skills", _util.SKILL_NAME, "SKILL.md")
SKILL_HE = _util.read("skills", _util.SKILL_NAME, "SKILL_HE.md")
HIDDEN = [
    0x00AD, 0x061C, 0x180E, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2060, 0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF,
]
LONG_DASHES = [0x2012, 0x2013, 0x2014, 0x2015]


def front_matter(text):
    """A small reader for the `key: value` and folded-block front matter used here."""
    assert text.startswith("---\n"), "file must start with ---"
    end = text.index("\n---\n", 4)
    block, body = text[4:end], text[end + 5:]
    fields, key = {}, None
    for line in block.split("\n"):
        if line and not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            value = value.strip()
            fields[key] = "" if value in (">-", ">", "|", "|-") else value
        elif key is not None and line.strip():
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields, body


def code_spans(text):
    return set(re.findall(r"`([^`\n]+)`", text))


def flags_in(text):
    return set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", text))


def all_flags():
    parser = cli._parser()
    sub = [action for action in parser._actions if hasattr(action, "choices") and isinstance(action.choices, dict)][0]
    found = set()
    for name, child in sub.choices.items():
        for action in child._actions:
            found.update(option for option in action.option_strings if option.startswith("--"))
    return found | {"--version", "--help"}


# THIRD-PARTY: skills-il. AgentSkillsFormatTest and HebrewCompanionTest write the
# nine checks of Skills IL's scripts/validate-skill.sh again as unit tests, and
# reuse three of its regular expressions (the name pattern, the when-to-use
# pattern, the secret pattern). MIT License. See THIRD_PARTY_NOTICES.md.
class AgentSkillsFormatTest(unittest.TestCase):
    """agentskills.io format rules, plus the Skills IL validator's nine checks."""

    def setUp(self):
        self.fields, self.body = front_matter(SKILL_MD)

    def test_front_matter_has_only_allowed_keys(self):
        self.assertEqual(sorted(self.fields), ["allowed-tools", "compatibility", "description", "license", "name"])
        self.assertNotIn("metadata", self.fields, "Skills IL: metadata lives in metadata.json, not in the front matter")

    def test_name_matches_the_folder_and_the_naming_rules(self):
        name = self.fields["name"]
        self.assertEqual(name, _util.SKILL_NAME)
        self.assertEqual(name, os.path.basename(_util.SKILL))
        self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(name), 64)
        self.assertNotIn("claude", name)
        self.assertNotIn("anthropic", name)

    def test_description_says_what_and_when(self):
        description = self.fields["description"]
        # The spec allows 1024. The Skills IL validator gates at 1023, because one host rejects exactly 1024.
        self.assertLessEqual(len(description), 1023)
        self.assertGreater(len(description), 200)
        self.assertRegex(description.lower(), r"use when|use for|use if|when user|when the user")
        self.assertIn("Do NOT use for", description)

    def test_no_angle_brackets_in_front_matter(self):
        block = SKILL_MD[: SKILL_MD.index("\n---\n", 4)]
        self.assertNotIn("<", block)
        self.assertNotIn(">", block.replace(">-", ""))

    def test_compatibility_and_license(self):
        self.assertTrue(1 <= len(self.fields["compatibility"]) <= 500)
        self.assertEqual(self.fields["license"], "Apache-2.0")

    def test_allowed_tools_grant_python_read_and_write_and_nothing_else(self):
        """Python runs the engine, Read opens the bundled references, Write saves a draft to lint."""
        self.assertEqual(self.fields["allowed-tools"], "Bash(python3:*) Bash(python:*) Read Write")
        for instruction in ("`references/manual-mode.md`", "save it, run `lint"):
            self.assertIn(instruction, SKILL_MD, "the instructions no longer need the tool this grants")

    def test_no_secret_patterns_in_the_skill_folder(self):
        """The Skills IL validator's ninth check, with its pattern."""
        pattern = re.compile(r"""(sk-[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16}|ghp_[a-zA-Z0-9]{36}|password:\s*[^\s]+|secret_key|api_key\s*=\s*["'][^\s]+)""")
        for path in _util.text_files(_util.SKILL):
            with open(path, "r", encoding="utf-8") as handle:
                self.assertIsNone(pattern.search(handle.read()), os.path.relpath(path, _util.REPO))

    def test_size_limits(self):
        self.assertLess(SKILL_MD.count("\n"), 500, "keep SKILL.md under 500 lines")
        self.assertLess(len(self.body.split()), 5000, "keep the body under 5,000 words")

    def test_no_readme_inside_the_skill_folder(self):
        for folder, _dirs, files in os.walk(_util.SKILL):
            self.assertNotIn("README.md", files, folder)

    def test_required_sections_are_present(self):
        for heading in ("## Overview", "## Examples", "## Bundled Resources", "## Reference Links", "## Gotchas", "## Troubleshooting"):
            self.assertIn("\n%s\n" % heading, SKILL_MD)
        self.assertGreaterEqual(len(re.findall(r"^### Example \d", SKILL_MD, re.M)), 2)

    def test_references_are_one_level_deep_and_all_exist(self):
        mentioned = set(re.findall(r"`(references/[\w.-]+)`", SKILL_MD))
        on_disk = set("references/" + name for name in os.listdir(os.path.join(_util.SKILL, "references")))
        self.assertEqual(mentioned, on_disk)

    def test_front_matter_reads_the_same_with_a_real_yaml_parser(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed (it is optional)")
        for text in (SKILL_MD, SKILL_HE):
            parsed = yaml.safe_load(text[4: text.index("\n---\n", 4)])
            self.assertEqual(sorted(parsed), sorted(self.fields))
            for key in ("name", "license", "allowed-tools"):
                self.assertEqual(parsed[key], self.fields[key])
            self.assertEqual(" ".join(parsed["description"].split()), self.fields["description"])


class HebrewCompanionTest(unittest.TestCase):
    """SKILL_HE.md mirrors SKILL.md: same structure, same commands, same code."""

    def test_same_front_matter(self):
        self.assertEqual(front_matter(SKILL_HE)[0], front_matter(SKILL_MD)[0])

    def test_same_heading_structure(self):
        levels = lambda text: [len(mark) for mark in re.findall(r"^(#+) ", text, re.M)]
        self.assertEqual(levels(SKILL_HE), levels(SKILL_MD))

    def test_same_commands_flags_paths_and_literals(self):
        self.assertEqual(code_spans(SKILL_HE), code_spans(SKILL_MD))

    def test_same_code_blocks(self):
        blocks = lambda text: re.findall(r"```.*?```", text, re.S)
        self.assertEqual(blocks(SKILL_HE), blocks(SKILL_MD))

    def test_same_number_of_steps_bullets_and_table_rows(self):
        for pattern in (r"^\d+\. ", r"^- ", r"^\|"):
            self.assertEqual(len(re.findall(pattern, SKILL_HE, re.M)), len(re.findall(pattern, SKILL_MD, re.M)), pattern)

    def test_the_hebrew_file_is_actually_hebrew(self):
        body = front_matter(SKILL_HE)[1]
        hebrew = sum(1 for char in body if 0x05D0 <= ord(char) <= 0x05EA)
        self.assertGreater(hebrew, 3000)

    def test_no_english_section_heading_is_left_in_the_hebrew_file(self):
        """An untranslated heading renders as-is on a Hebrew page. Headings inside code fences do not count."""
        outside_fences = re.sub(r"```.*?```", "", SKILL_HE, flags=re.S)
        left = re.findall(
            r"^#{2,3} (?:Examples|Troubleshooting|Instructions|Gotchas|Reference Links|Bundled Resources|Recommended MCP Servers|References|Scripts)[ \t]*$",
            outside_fences, re.M,
        )
        self.assertEqual(left, [])

    def test_the_hebrew_body_is_under_the_same_word_cap(self):
        self.assertLess(len(front_matter(SKILL_HE)[1].split()), 5000)


class InstructionsMatchEngineTest(unittest.TestCase):
    """Every command, flag, type and message the model is told about is real."""

    def test_every_engine_command_is_documented(self):
        spans = code_spans(SKILL_MD)
        for name, _help in cli.COMMANDS:
            self.assertTrue(any(span == name or span.startswith(name + " ") for span in spans), "SKILL.md never names `%s`" % name)

    def test_every_command_the_instructions_name_exists(self):
        known = set(name for name, _help in cli.COMMANDS)
        named = set(re.findall(r"playbook\.py ([a-z][a-z-]*)", SKILL_MD))
        named.update(span.split()[0] for span in code_spans(SKILL_MD) if re.match(r"^[a-z][a-z-]* --", span))
        self.assertEqual(sorted(named - known), [])
        self.assertGreaterEqual(len(named), 8)

    def test_every_flag_the_instructions_name_exists(self):
        # `tools/seal.py --write` is the maintainer's tool in the repository, not an engine flag.
        engine_text = re.sub(r"`tools/[^`]*`", "", SKILL_MD)
        self.assertEqual(sorted(flags_in(engine_text) - all_flags()), [])
        self.assertGreaterEqual(len(flags_in(engine_text)), 10)
        self.assertNotIn("--write", all_flags(), "the shipped engine must have no way to reseal itself")

    def test_the_list_of_email_types_is_the_engines(self):
        line = [row for row in SKILL_MD.split("\n") if row.startswith("Types: ")][0]
        self.assertEqual(sorted(re.findall(r"`([a-z_]+)`", line)), mail.types())

    def test_the_command_list_in_bundled_resources_is_the_engines(self):
        line = [row for row in SKILL_MD.split("\n") if row.startswith("- `scripts/playbook.py`")][0]
        listed = re.findall(r"`([a-z-]+)`", line.split("The engine:")[1].split(". ")[0])
        self.assertEqual(listed, [name for name, _help in cli.COMMANDS])

    def test_the_heredoc_example_runs_as_written(self):
        block = re.search(r"```bash\n(.*?)```", SKILL_MD, re.S).group(1)
        lines = [line.strip() for line in block.strip().split("\n")]
        self.assertEqual(lines[0], "python3 scripts/playbook.py interview --in - <<'JSON'")
        self.assertEqual(lines[2], "JSON")
        code, payload = _util.run_json(["interview", "--in", "-"], lines[1])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        # The example is a first telling: two facts in, and the engine asks for the rest before anything runs.
        self.assertEqual(payload["result"]["status"], "ask")
        self.assertFalse(payload["result"]["can_run"])
        self.assertEqual([item["id"] for item in payload["result"]["ask_next"]][:2], ["next_step_exists", "cost_to_them"])
        self.assertEqual([item["level"] for item in payload["result"]["ask_next"]], [1, 1, 2])

    def test_the_instructions_name_the_interviews_own_words(self):
        """Statuses, depths and input fields in SKILL.md are the engine's, so the model never guesses a name."""
        from abp import interview
        for text in (SKILL_MD, SKILL_HE):
            for status in ("ask", "run_and_ask", "ready"):
                self.assertIn("| `%s` |" % status, text)
            for depth in ("quick", "deep"):
                self.assertIn('"depth": "%s"' % depth, text)
                self.assertIn(depth, interview.DEPTHS)
            for field in ("stop", "skipped", "depth", "mode", "answers"):
                self.assertIn(field, interview.SPEC)
            self.assertIn('"stop": true', text)
            self.assertIn("`skipped`", text)
            for mode in interview.MODES:
                self.assertIn("`%s`" % mode, text)
        statuses = set()
        for answers, extra in (({}, {}), ({"context": "sales", "quotes": ["Hi"], "next_step_exists": False, "cost_to_them": []}, {}), ({}, {"stop": True})):
            statuses.add(interview.plan(dict({"mode": "decode", "answers": answers}, **extra), "en")["status"])
        self.assertEqual(statuses, {"ask", "run_and_ask", "ready"})

    def test_the_stamp_wording_is_the_engines(self):
        stamp = load("coach")["stamp"]
        self.assertTrue(stamp["verified"]["en"].startswith("[verified by code"))
        self.assertTrue(stamp["verified"]["he"].startswith("[נבדק בקוד"))
        self.assertIn("NOT VERIFIED BY CODE", stamp["not_verified"]["en"])
        for text in (SKILL_MD, SKILL_HE):
            for needle in ("[verified by code", "[נבדק בקוד", "NOT VERIFIED BY CODE"):
                self.assertIn(needle, text)

    def test_troubleshooting_quotes_real_error_messages(self):
        _code, _out, err = _util.run(["decode", "--json", '{"context": "sales", "qoutes": []}'])
        self.assertIn("unknown field", err)
        _code, _out, err = _util.run(["decode", "--json", '{"context": "retail"}'])
        self.assertIn("is not one of", err)
        _code, _out, err = _util.run(["send-time", "--tz", "Narnia"])
        self.assertIn("Unknown timezone or city", err)
        with _util.skill_copy() as root:
            with open(os.path.join(root, "data", "email.json"), "a", encoding="utf-8") as handle:
                handle.write(" ")
            _code, _out, err = _util.subprocess_run(["doctor"], entry=os.path.join(root, "scripts", "playbook.py"))
            self.assertIn("SEAL BROKEN", err)
        for needle in ("SEAL BROKEN", "unknown field", "is not one of", "Unknown timezone or city"):
            self.assertIn(needle, SKILL_MD)

    def test_the_three_worked_examples_give_what_they_promise(self):
        """Example 2 promises Yellow leaning Red and a recap; Example 3 promises BANT off."""
        sheet = {"context": "sales", "today": "2026-11-24", "quotes": ["This is amazing! We'll be in touch."], "next_step": {"exists": False}, "cost_to_them": [], "their_questions": 0}
        result = _util.facts("decode", sheet)
        self.assertEqual((result["verdict"]["light"], result["verdict"]["lean"]), ("yellow", "red"))
        self.assertEqual(result["next_move"]["template"], "recap")
        open_sheet = _util.facts("decode", {"context": "sales", "quotes": ["This is amazing!"]})
        self.assertEqual(open_sheet["status"], "needs_intake")
        prep = _util.facts("prep", {"type": "investor"})
        self.assertFalse(prep["bant"]["on"] if isinstance(prep.get("bant"), dict) else prep.get("bant_on", False))
        # Example 1: a pasted draft is not held back by questions. Example 2: one quote is not enough, and
        # with no step and nothing paid the decode line is printed and the interview goes on.
        pasted = _util.facts("interview", {"mode": "email", "answers": {"email_type": "cold", "draft_exists": "have_draft"}})
        self.assertEqual(pasted["status"], "run_and_ask")
        printed = [" ".join(item["argv"]) for item in pasted["handoff"] if not item["blocked_by"]]
        self.assertEqual(printed, ["lint --type cold --file draft.txt", "lint --type cold --file rewrite.txt --source source.txt"])
        located = _util.facts("interview", {"mode": "email", "answers": {"email_type": "cold", "draft_exists": "have_draft", "their_city": "ET"}})
        printed = [" ".join(item["argv"]) for item in located["handoff"] if not item["blocked_by"]]
        for line in ("lint --type cold --file draft.txt", "lint --type cold --file rewrite.txt --source source.txt", "send-time --tz ET"):
            self.assertIn(line, printed)
            self.assertIn("`%s`" % line, SKILL_MD)
        # Example 3: an investor meeting tomorrow is not enough to prepare for. The goal and the ask come first.
        tomorrow = _util.facts("interview", {"mode": "prep", "answers": {"context": "investor"}})
        self.assertEqual((tomorrow["status"], [item["id"] for item in tomorrow["open_musts"]]), ("ask", ["goal_currency", "the_ask"]))
        ready = _util.facts("interview", {"mode": "prep", "answers": {"context": "investor", "goal_currency": "calendar_time", "the_ask": "a partner meeting"}})
        self.assertEqual(ready["handoff"][0]["sheet"]["type"], "investor")
        one_quote = _util.facts("interview", {"mode": "decode", "answers": {"context": "sales", "quotes": ["This is amazing! We'll be in touch."]}})
        self.assertEqual(one_quote["status"], "ask")
        self.assertEqual([item["id"] for item in one_quote["open_musts"]], ["next_step_exists", "cost_to_them"])
        answered = _util.facts("interview", {"mode": "decode", "answers": {"context": "sales", "quotes": ["This is amazing! We'll be in touch."], "next_step_exists": False, "cost_to_them": []}})
        self.assertEqual(answered["status"], "run_and_ask")
        self.assertEqual(answered["handoff"][0]["argv"], ["decode", "--in", "-"])

    def test_a_lookup_needs_no_interview_and_start_now_is_a_stop(self):
        """Two places where asking first would be the wrong reflex, said in the instructions and true in the engine."""
        self.assertIn("A lookup needs none: `send-time`, `cadence`, `template` and `bench` answer directly.", SKILL_MD)
        from abp import interview
        for command in ("send-time", "cadence", "template", "bench"):
            self.assertIn(command, [name for name, _help in cli.COMMANDS])
        self.assertNotIn("template", [name for names in interview.MODE_COMMANDS.values() for name in names])
        self.assertIn('If the founder says "start now", that is a stop: pass `"stop": true`', SKILL_MD)
        started = _util.facts("interview", {"mode": "scene", "stop": True, "answers": {"context": "sales"}})
        self.assertEqual((started["status"], started["ask_next"], started["can_run"]), ("ready", [], True))
        self.assertEqual(started["handoff"][0]["argv"], ["scene", "--type", "sales"])


class VersionTest(unittest.TestCase):
    def test_one_version_everywhere(self):
        meta = json.loads(_util.read("skills", _util.SKILL_NAME, "metadata.json"))
        plugin = json.loads(_util.read(".claude-plugin", "plugin.json"))
        log = json.loads(_util.read("skills", _util.SKILL_NAME, "optimization-log.json"))
        first = re.search(r"^## \[(\d+\.\d+\.\d+)\]", _util.read("CHANGELOG.md"), re.M).group(1)
        self.assertEqual(
            {"engine": __version__, "metadata": meta["version"], "plugin": plugin["version"], "changelog": first, "log": log["cycles"][-1]["version"]},
            dict.fromkeys(("engine", "metadata", "plugin", "changelog", "log"), __version__),
        )
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_the_citation_file_names_this_version_and_its_release_date(self):
        citation = _util.read("CITATION.cff")
        released = re.search(r"^## \[%s\] - (\d{4}-\d{2}-\d{2})$" % re.escape(__version__), _util.read("CHANGELOG.md"), re.M).group(1)
        self.assertIn("\nversion: %s\n" % __version__, citation)
        self.assertIn("\ndate-released: %s\n" % released, citation)
        self.assertIn("\nlicense: Apache-2.0\n", citation)
        self.assertIn("\ncff-version: 1.2.0\n", citation)
        for key in ("message", "type", "title", "authors", "repository-code"):
            self.assertRegex(citation, r"(?m)^%s:" % key)

    def test_the_earlier_optimization_cycle_is_kept(self):
        log = json.loads(_util.read("skills", _util.SKILL_NAME, "optimization-log.json"))
        self.assertEqual([cycle["version"] for cycle in log["cycles"]], ["1.1.0", "2.0.0"])

    def test_metadata_follows_the_skills_il_shape(self):
        meta = json.loads(_util.read("skills", _util.SKILL_NAME, "metadata.json"))
        self.assertEqual(sorted(meta), ["author", "category", "display_description", "display_name", "supported_agents", "tags", "version"])
        self.assertEqual(len(meta["tags"]["he"]), len(meta["tags"]["en"]))
        self.assertTrue(all(tag.strip() for tag in meta["tags"]["he"] + meta["tags"]["en"]))
        for key in ("display_name", "display_description"):
            self.assertEqual(sorted(meta[key]), ["en", "he"])


class GeneratedFilesTest(unittest.TestCase):
    def test_nothing_generated_is_stale(self):
        self.assertEqual(build_refs.stale(), [], "run: python3 tools/build.py")

    def test_the_audit_report_is_current(self):
        self.assertEqual(_util.read("docs", "AUDIT.md"), audit.render(audit.run()), "run: python3 tools/build.py")

    def test_readme_demo_blocks_are_what_a_sealed_install_prints(self):
        """The generator fakes nothing: the real entry point gives the same text."""
        sheet = json.dumps(build_refs.EX_DECODE_FULL)
        code, out, err = _util.subprocess_run(["decode", "--in", "-", "--lang", "en"], stdin=sheet)
        self.assertEqual(code, 0, err)
        self.assertIn(out.rstrip("\n"), _util.read("README.md"))
        code, out, err = _util.subprocess_run(["decode", "--in", "-"], stdin=sheet)
        self.assertEqual(code, 0, err)
        self.assertIn("```text\n%s\n```" % out.rstrip("\n"), _util.read("README.md"), "the Hebrew block is not the engine's Hebrew output")

    def test_every_demo_marker_is_filled(self):
        text = _util.read("README.md")
        blocks = re.findall(r"<!-- demo:([a-z:-]+) -->\n(.*?)<!-- /demo -->", text, re.S)
        self.assertEqual([name for name, _body in blocks], ["interview-open", "decode-verdict", "decode-verdict:he:output"])
        for name, body in blocks:
            opening = "```text\n" if name.endswith(":output") else "```console\n$ python3 scripts/playbook.py "
            self.assertTrue(body.startswith(opening), name)
            self.assertTrue(body.rstrip("\n").endswith("```"), name)

    def test_stamps_quoted_in_prose_carry_the_current_rules_fingerprint(self):
        from abp import seal

        current = seal.rules_digest(_util.SKILL)
        for parts in (("README.md",), ("docs", "ARCHITECTURE.md")):
            quoted = set(re.findall(r"\| rules ([0-9a-f]{12}) \|", _util.read(*parts)))
            self.assertEqual(quoted, {current}, "/".join(parts))

    def test_examples_cover_every_command_but_schema_and_doctor(self):
        text = _util.read("docs", "EXAMPLES.md")
        for name, _help in cli.COMMANDS:
            if name not in ("schema", "doctor"):
                self.assertIn("$ python3 scripts/playbook.py %s " % name, text, name)


class CountsTest(unittest.TestCase):
    """Numbers quoted in prose are checked, so the prose cannot rot."""

    def test_command_and_table_counts(self):
        commands = len(cli.COMMANDS)
        tables = len([name for name in os.listdir(os.path.join(_util.SKILL, "data")) if name.endswith(".json")])
        templates = len(load("templates")["templates"])
        readme = _util.read("README.md")
        self.assertIn("%d commands" % commands, readme)
        self.assertIn("%d commands" % commands, _util.read("docs", "ARCHITECTURE.md"))
        self.assertIn("%d rule tables" % tables, _util.read("docs", "ARCHITECTURE.md"))
        self.assertIn("%d email templates" % templates, readme)
        self.assertIn("%d תבניות מייל" % templates, readme)

    def test_numbers_the_readme_promises_a_founder(self):
        readme = _util.read("README.md")
        english, hebrew = readme.split('<a id="hebrew"></a>')
        rows = load("decoder")["rows"]
        political = len([row for row in rows if row["table"] == "politics"])
        polite = len(rows) - political
        self.assertIn("Decodes %d polite American lines" % polite, english)
        self.assertIn("Knows the %d political asides" % political, english)
        self.assertIn("מפענח %d משפטים אמריקאיים" % polite, hebrew)
        self.assertIn("את %d האמירות הפוליטיות" % political, hebrew)
        bank = load("interview")
        questions, areas = len(bank["questions"]), len(bank["dimensions"])
        self.assertIn("a bank of %d questions in %d areas" % (questions, areas), english)
        self.assertIn("from a bank of %d questions" % questions, english)
        self.assertIn("picks from %d written questions" % questions, english)
        self.assertIn("בנק של %d שאלות ב-%d תחומים" % (questions, areas), hebrew)
        self.assertIn("מתוך בנק של %d שאלות" % questions, hebrew)
        self.assertIn("מתוך %d שאלות כתובות" % questions, hebrew)
        section = english.split("\n### The Interview\n")[1].split("\n### ")[0]
        for item in bank["dimensions"]:
            self.assertIn(item["label"]["en"].lower(), section, item["id"])
            self.assertIn(item["label"]["he"], hebrew, item["id"])
        self.assertEqual(bank["max_questions_per_turn"], 3)
        self.assertIn("Asks at most three a turn", section)
        self.assertIn("עד שלוש שאלות בסבב", hebrew)
        touches = load("cadence")["touches"]
        self.assertEqual(len(touches), 5)
        self.assertIn("five touches over about 90 days", readme)
        self.assertIn("חמש נגיעות על פני כ-90 יום", readme)
        self.assertTrue(touches[-1]["window_days"][0] <= 90 <= touches[-1]["window_days"][1])
        self.assertEqual(load("signals")["intake"]["max_questions_per_turn"], 3)
        self.assertIn("Up to three short questions", readme)
        self.assertIn("עד שלוש שאלות קצרות", readme)
        self.assertEqual(sorted(load("meetings")["types"]), ["investor", "kol", "sales"])

    def test_the_changelog_table_quotes_current_numbers(self):
        """The 2.0.0 comparison table is measured, not remembered."""
        changelog = _util.read("CHANGELOG.md")
        scripts = os.path.join(_util.SKILL, "scripts")
        lines = 0
        for path in _util.text_files(scripts, (".py",)):
            with open(path, "r", encoding="utf-8") as handle:
                lines += handle.read().count("\n")
        body = front_matter(SKILL_MD)[1]
        suite = unittest.defaultTestLoader.discover(os.path.join(_util.REPO, "tests"))
        doctor = _util.run_json(["doctor"])[1]["result"]["checks"]
        patterns = [re.search(r"(\d+) phrase patterns", item["check"]) for item in doctor]
        patterns = [match.group(1) for match in patterns if match][0]
        checks = len(set(re.findall(r'\bran\("([a-z_]+)"\)', _util.read("skills", _util.SKILL_NAME, "scripts", "abp", "mail.py"))))
        for claim in (
            "%d commands, %s lines, standard library only" % (len(cli.COMMANDS), format(lines, ",")),
            "`SKILL.md` (%s words)" % format(len(body.split()), ","),
            "%d JSON rule tables, %s phrase patterns" % (len([name for name in os.listdir(os.path.join(_util.SKILL, "data")) if name.endswith(".json")]), patterns),
            "`interview`, from a bank of %d questions" % len(load("interview")["questions"]),
            "A bank of %d questions in %d areas" % (len(load("interview")["questions"]), len(load("interview")["dimensions"])),
            "%d model-level eval cases" % len([name for name in os.listdir(os.path.join(_util.REPO, "evals")) if os.path.isdir(os.path.join(_util.REPO, "evals", name))]),
            "%d unit tests" % suite.countTestCases(),
            "%d checks that can raise %d distinct findings" % (checks, len(load("email")["messages"])),
        ):
            self.assertIn(claim, changelog)

    def test_python_versions_named_in_the_docs_are_the_ones_ci_runs(self):
        matrix = re.search(r'python: \[(.*?)\]', _util.read(".github", "workflows", "ci.yml")).group(1)
        versions = re.findall(r'"(3\.\d+)"', matrix)
        self.assertEqual(versions[0], "3.9")
        claim = "Python %s to %s" % (versions[0], versions[-1])
        for parts in (("README.md",), ("CONTRIBUTING.md",)):
            self.assertIn(claim, _util.read(*parts))


class RepositoryHygieneTest(unittest.TestCase):
    def files(self):
        return list(_util.text_files(_util.REPO))

    def test_no_long_dashes_anywhere(self):
        for path in self.files():
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            for code in LONG_DASHES:
                self.assertNotIn(chr(code), text, "%s contains U+%04X" % (os.path.relpath(path, _util.REPO), code))

    def test_no_hidden_or_bidirectional_control_characters(self):
        for path in self.files():
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            for code in HIDDEN:
                self.assertNotIn(chr(code), text, "%s contains U+%04X" % (os.path.relpath(path, _util.REPO), code))

    def test_text_files_use_unix_line_endings_and_end_with_a_newline(self):
        for path in self.files():
            with open(path, "rb") as handle:
                data = handle.read()
            rel = os.path.relpath(path, _util.REPO)
            self.assertNotIn(b"\r", data, rel)
            # Fixtures and the third-party license texts are kept byte for byte as they were found.
            if data and not rel.startswith((os.path.join("tests", "fixtures"), "licenses" + os.sep)):
                self.assertTrue(data.endswith(b"\n"), rel)

    def test_every_json_file_parses(self):
        found = [path for path in _util.text_files(_util.REPO, (".json",)) if path.endswith(".json")]
        self.assertGreater(len(found), 12)
        for path in found:
            with open(path, "r", encoding="utf-8") as handle:
                json.load(handle)

    def test_relative_links_point_at_files_that_exist(self):
        checked = 0
        for path in _util.text_files(_util.REPO, (".md",)):
            rel_dir = os.path.dirname(path)
            if os.sep + "evals" + os.sep in path:
                continue
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
                if re.match(r"^[a-z]+:", target):
                    continue
                self.assertTrue(os.path.exists(os.path.join(rel_dir, target)), "%s links to missing %s" % (os.path.relpath(path, _util.REPO), target))
                checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_required_repository_files(self):
        for parts in (
            ("README.md",), ("LICENSE",), ("NOTICE",), ("THIRD_PARTY_NOTICES.md",), ("CITATION.cff",),
            ("SECURITY.md",), ("CHANGELOG.md",), ("CONTRIBUTING.md",), (".gitignore",), (".gitattributes",),
            ("docs", "ARCHITECTURE.md"), ("docs", "ASSUMPTIONS.md"), ("docs", "AUDIT.md"), ("docs", "EXAMPLES.md"),
            ("docs", "RELEASING.md"), ("dist", "GEMINI-GEM.md"),
            ("docs", "guide", "README.md"), ("docs", "guide", "The-American-Playbook-V2.docx"), ("docs", "guide", "the-american-playbook-v2.md"),
            (".github", "workflows", "ci.yml"), (".github", "workflows", "release.yml"), (".github", "dependabot.yml"),
            (".github", "CODEOWNERS"), (".github", "PULL_REQUEST_TEMPLATE.md"),
            (".github", "ISSUE_TEMPLATE", "config.yml"), (".github", "ISSUE_TEMPLATE", "bug.yml"),
            (".github", "ISSUE_TEMPLATE", "rule-feels-wrong.yml"),
            ("assets", "header.png"), ("assets", "social-preview.png"),
        ):
            self.assertTrue(os.path.isfile(os.path.join(_util.REPO, *parts)), "/".join(parts))
        # One README in two languages replaced the separate Hebrew files.
        for parts in (("README.he.md",), ("docs", "PUBLISHING.he.md")):
            self.assertFalse(os.path.exists(os.path.join(_util.REPO, *parts)), "/".join(parts))

    def test_the_project_license_is_apache_2(self):
        license_text = _util.read("LICENSE")
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0, January 2004", license_text)
        self.assertIn("Copyright 2026 Nimrod Zemel", license_text)
        self.assertNotIn("[yyyy]", license_text)
        self.assertIn("Copyright 2026 Nimrod Zemel", _util.read("NOTICE"))
        self.assertIn("license-Apache%202.0", _util.read("README.md"))
        for text in (_util.read("README.md"), _util.read("CONTRIBUTING.md")):
            self.assertNotRegex(text, r"\bMIT license\b|\bMIT License\b")

    def test_english_first_then_hebrew_in_one_file(self):
        """Hebrew lives after the English, inside right-to-left blocks, in the same file."""
        for parts in (("README.md",), ("docs", "RELEASING.md")):
            name = "/".join(parts)
            text = _util.read(*parts)
            self.assertEqual(text.count('<a id="hebrew"></a>'), 1, name)
            english, hebrew = text.split('<a id="hebrew"></a>')
            is_hebrew = lambda line: any(0x05D0 <= ord(char) <= 0x05EA for char in line)
            for line in english.split("\n"):
                if is_hebrew(line):
                    self.assertIn("(#hebrew)", line, "%s has Hebrew above the Hebrew section: %s" % (name, line[:60]))
            self.assertGreater(len(english), len(hebrew), name)
            self.assertGreater(sum(1 for char in hebrew if 0x05D0 <= ord(char) <= 0x05EA), 800, name)
            self.assertEqual(text.count('<div dir="rtl">'), text.count("</div>"), name)
            self.assertNotIn('<div dir="rtl">', english, name)
            # Outside the right-to-left blocks nothing is Hebrew: commands stay left-to-right.
            outside = re.sub(r'<div dir="rtl">.*?</div>', "", hebrew, flags=re.S)
            self.assertFalse(is_hebrew(outside), "%s: Hebrew text outside a right-to-left block" % name)
            # Inside them, a fenced block is allowed only when it is Hebrew output.
            for block in re.findall(r'<div dir="rtl">(.*?)</div>', hebrew, re.S):
                for fence in re.findall(r"```.*?```", block, re.S):
                    self.assertTrue(is_hebrew(fence), "%s: a left-to-right code block sits inside a right-to-left block" % name)
                # Markdown inside an HTML block needs a blank line after the opening tag.
                self.assertTrue(block.startswith("\n\n"), name)

    def test_the_readme_is_written_for_a_founder(self):
        readme = _util.read("README.md")
        english = readme.split('<a id="hebrew"></a>')[0]
        order = ["## What it does", "## Getting started", "### What to expect on your first run", "## How it works",
                 "## Privacy and trust", "## Honest limits", "## Troubleshooting", "## Development",
                 "## Acknowledgments", "## Contact", "## License"]
        places = [english.index("\n%s\n" % heading) for heading in order]
        self.assertEqual(places, sorted(places))
        self.assertLess(english.index("\n### The Interview\n"), english.index("\n### Email Doctor\n"), "every mode starts with the interview, and so does the page")
        for mode in ("### The Interview", "### Email Doctor", "### Meeting Decoder", "### Prep and Simulation"):
            block = english.split("\n%s\n" % mode)[1].split("\n### ")[0]
            for label in ("**What it does:**", "**What to provide:**", "**What you get back:**", "**Example prompts:**"):
                self.assertIn(label, block, "%s lacks %s" % (mode, label))
        # The first screen is for the founder: the engineering comes after the install steps.
        self.assertLess(english.index("## Getting started"), english.index("python3 "))
        for anchor in re.findall(r"\]\(#([a-z0-9-]+)\)", readme):
            heading_slugs = [re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-") for heading in re.findall(r"^#+ (.+)$", readme, re.M)]
            self.assertTrue(anchor in heading_slugs or '<a id="%s"></a>' % anchor in readme, "README links to #%s, which is not there" % anchor)

    def test_images_the_readme_shows_exist(self):
        readme = _util.read("README.md")
        shown = re.findall(r'(?:src|srcset)="([^"]+)"', readme)
        self.assertGreaterEqual(len(shown), 13)
        for target in shown:
            self.assertTrue(os.path.isfile(os.path.join(_util.REPO, *target.split("/"))), target)
        sizes = {}
        for name in os.listdir(os.path.join(_util.REPO, "assets")):
            if name.endswith(".png"):
                self.assertTrue(os.path.isfile(os.path.join(_util.REPO, "assets", "src", name[:-4] + ".svg")), "%s has no SVG source" % name)
                with open(os.path.join(_util.REPO, "assets", name), "rb") as handle:
                    data = handle.read(24)
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", name)
                sizes[name] = struct.unpack(">II", data[16:24])
        self.assertEqual(sizes["header.png"], (1600, 640))
        # The size GitHub asks for a repository's social preview.
        self.assertEqual(sizes["social-preview.png"], (1280, 640))
        for name in ("the-interview", "email-doctor", "meeting-decoder", "prep-and-simulation"):
            self.assertEqual(sizes[name + ".png"], sizes[name + "-light.png"], name)
            self.assertEqual(sizes[name + ".png"], sizes["email-doctor.png"], name)

    def test_acknowledgments_thank_the_same_sources_in_both_languages(self):
        """The credits policy: the README thanks, by name and with a link, the sources its author chose.

        Both languages thank the same ones. The complete record of what came from
        where is THIRD_PARTY_NOTICES.md, which tools/notices.py checks.
        """
        readme = _util.read("README.md")
        section = readme.split("\n## Acknowledgments\n")[1].split("\n## ")[0]
        hebrew = readme.split("\n### תודות\n")[1].split("\n### ")[0]
        thanked = re.compile(r"^- \*\*\[([^\]]+)\]\((https?://[^)\s]+)\)", re.M)
        english_credits = sorted(thanked.findall(section))
        self.assertGreaterEqual(len(english_credits), 1)
        self.assertEqual(
            english_credits,
            sorted(thanked.findall(hebrew)),
            "the Hebrew credits do not thank the same sources as the English ones",
        )
        for text in (section, hebrew):
            self.assertIn("(THIRD_PARTY_NOTICES.md)", text)
        notices = _util.read("THIRD_PARTY_NOTICES.md")
        sources = re.findall(r"^- Source: (https://github\.com/[\w.-]+/[\w.-]+)", notices, re.M)
        self.assertGreaterEqual(len(sources), 5)


class ManifestTest(unittest.TestCase):
    def test_plugin_manifest(self):
        plugin = json.loads(_util.read(".claude-plugin", "plugin.json"))
        self.assertEqual(plugin["name"], _util.SKILL_NAME)
        self.assertEqual(plugin["license"], "Apache-2.0")
        self.assertEqual(plugin["author"]["name"], "Nimrod Zemel")
        self.assertTrue(plugin["description"])
        for key in ("hooks", "mcpServers", "commands", "agents"):
            self.assertNotIn(key, plugin)

    def test_marketplace_manifest_lists_this_plugin(self):
        market = json.loads(_util.read(".claude-plugin", "marketplace.json"))
        self.assertEqual(market["name"], "venture-engineer")
        self.assertEqual([(item["name"], item["source"]) for item in market["plugins"]], [(_util.SKILL_NAME, "./")])
        self.assertIn("american-business-playbook@%s" % market["name"], _util.read("README.md"))

    def test_icon_is_a_square_png_of_the_accepted_size(self):
        with open(os.path.join(_util.REPO, ".claude-plugin", "icon.png"), "rb") as handle:
            data = handle.read()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual(width, height)
        self.assertTrue(512 <= width <= 2048)
        self.assertLess(len(data), 2 * 1024 * 1024)

    def test_the_skill_sits_where_plugins_and_hosts_look_for_it(self):
        self.assertTrue(os.path.isfile(os.path.join(_util.REPO, "skills", _util.SKILL_NAME, "SKILL.md")))
        self.assertFalse(os.path.exists(os.path.join(_util.REPO, "SKILL.md")))


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.ci = _util.read(".github", "workflows", "ci.yml")
        self.release = _util.read(".github", "workflows", "release.yml")

    def test_every_action_is_pinned_to_a_full_commit(self):
        uses = re.findall(r"uses: (\S+)", self.ci + self.release)
        self.assertGreaterEqual(len(uses), 5)
        for item in uses:
            self.assertRegex(item, r"^actions/[a-z-]+@[0-9a-f]{40}$", item)
        # Pins that are never refreshed rot, so Dependabot watches them.
        dependabot = _util.read(".github", "dependabot.yml")
        self.assertIn("package-ecosystem: github-actions", dependabot)

    def test_least_privilege(self):
        for text in (self.ci, self.release):
            self.assertIn("\npermissions:\n  contents: read\n", text)
            self.assertNotIn("pull_request_target", text)
            self.assertNotIn("secrets.", text)
            self.assertEqual(text.count("uses: actions/checkout@"), text.count("persist-credentials: false"))
        self.assertNotIn("id-token", self.ci)
        self.assertNotIn("contents: write", self.ci)

    def test_ci_runs_every_gate(self):
        for command in (
            "python -B -m unittest discover -s tests", "tools/seal.py --check", "tools/build_refs.py --check",
            "tools/audit.py", "tools/notices.py", "tools/guide.py", "playbook.py doctor",
        ):
            self.assertIn(command, self.ci)
        # The build runs the same gates locally, in the order that makes each one meaningful.
        build = _util.read("tools", "build.py")
        steps = re.findall(r'print\("(\d)/7 ([a-z-]+)', build)
        self.assertEqual([name for _number, name in steps if name != "package"][:6], ["references", "self-audit", "credits", "guide", "seal", "tests"])
        for gate in ("audit.run()", "notices.run()", "guide.run()"):
            self.assertIn(gate, build)
            self.assertIn(gate, _util.read("tools", "package.py"), "a release must not be packaged past %s" % gate)

    def test_release_checks_the_tag_tests_packages_and_attests(self):
        for needle in ("The tag must match the engine version", "unittest discover", "tools/package.py", "attest-build-provenance", "gh release"):
            self.assertIn(needle, self.release)
        self.assertLess(self.release.index("unittest discover"), self.release.index("tools/package.py"))
        self.assertLess(self.release.index("tools/package.py"), self.release.index("attest-build-provenance"))


class MutationListTest(unittest.TestCase):
    """tools/mutation_check.py breaks rules on purpose. Its list must not rot."""

    def test_every_mutation_still_points_at_real_text(self):
        import mutation_check

        names = [item[0] for item in mutation_check.MUTATIONS]
        self.assertGreaterEqual(len(names), 30)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(mutation_check.EQUIVALENT <= set(names))
        for name, rel, old, new in mutation_check.MUTATIONS:
            self.assertIn(old, _util.read(*rel.split("/")), name)
            self.assertNotEqual(old, new, name)
        # The changelog quotes the size of this list. The count of caught ones is what the last full run printed.
        claim = "breaks %d rules one at a time and checks that a test fails. %d are caught." % (len(names), len(names) - len(mutation_check.EQUIVALENT))
        self.assertIn(claim, _util.read("CHANGELOG.md"))
        # The interview, the guide check and the politics rules are in the list, not only the older engine.
        for area in ("interview", "guide", "politic"):
            self.assertTrue([name for name in names if area in name], area)


class EvalCasesTest(unittest.TestCase):
    """The model-level cases are not run here (they cost money), but they must load."""

    ROOT = os.path.join(_util.REPO, "evals")
    RESERVED = {"results", "mocks", "node_modules", "files", "true", "false", "null"}

    def cases(self):
        return sorted(name for name in os.listdir(self.ROOT) if os.path.isdir(os.path.join(self.ROOT, name)) and name != "results")

    def test_there_are_cases_and_their_names_are_valid(self):
        names = self.cases()
        self.assertGreaterEqual(len(names), 6)
        for name in names:
            self.assertRegex(name, r"^[a-z][a-z0-9-]*$")
            self.assertNotIn(name, self.RESERVED)

    def test_every_case_has_a_prompt_a_description_and_graders(self):
        for name in self.cases():
            base = os.path.join(self.ROOT, name)
            with open(os.path.join(base, "prompt.md"), "r", encoding="utf-8") as handle:
                settings, prompt = front_matter(handle.read())
            self.assertEqual(sorted(settings), ["allowed_tools", "max_turns", "tags", "timeout_seconds"], name)
            self.assertTrue(prompt.strip(), name)
            with open(os.path.join(base, "case.yaml"), "r", encoding="utf-8") as handle:
                case = handle.read()
            self.assertTrue(case.startswith('schema_version: "1.1"\nname: %s\nexpected_outcome: |\n  ' % name), name)
            graders = sorted(os.listdir(os.path.join(base, "graders")))
            self.assertGreaterEqual(len(graders), 3, name)
            for index, grader in enumerate(graders, 1):
                self.assertRegex(grader, r"^%02d-[a-z0-9-]+\.md$" % index, name)
                with open(os.path.join(base, "graders", grader), "r", encoding="utf-8") as handle:
                    fields, statement = front_matter(handle.read())
                self.assertEqual(fields, {"type": "llm", "focus": "trace", "weight": "1"}, grader)
                self.assertGreater(len(statement.split()), 6, grader)

    def test_the_cases_cover_every_mode_and_one_case_where_the_skill_should_stay_out(self):
        names = " ".join(self.cases())
        for needle in ("email", "decode", "prep", "simulation", "cadence", "invented", "stays-out"):
            self.assertIn(needle, names)

    def test_dates_promised_by_the_cadence_case_are_what_the_engine_gives(self):
        touches = _util.run_json(["cadence", "--meeting-date", "2026-11-23", "--tz", "Chicago", "--today", "2026-11-24"])[1]["result"]["touches"]
        self.assertEqual([touch["date"] for touch in touches], ["2026-11-24", "2026-11-30", "2026-12-02", "2026-12-08", "2027-02-23"])
        self.assertEqual((touches[0]["local_time"], touches[0]["israel_time"]), ("09:30", "17:30"))


if __name__ == "__main__":
    unittest.main()
