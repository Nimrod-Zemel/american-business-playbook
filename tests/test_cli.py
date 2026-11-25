"""The command line as the model uses it: commands, exit codes, receipts, errors."""

import json
import os
import tempfile
import unittest

import _util
from _util import run, run_json
from abp import cli, mail
from abp.core import load

GOOD = "Subject: Cutting claims time at Acme\n\nHi Michael,\n\nWe help insurers cut claims time - live with two carriers.\n\nWould Tuesday or Thursday work for a 20-minute call? No worries if not.\n\nBest,\nDana\n"
BAD = "Dear Sir,\n\nSend me your availability ASAP. Can we talk? Can you intro me to your CTO?\n"


class CommandSurfaceTest(unittest.TestCase):
    def test_fourteen_commands_and_the_interview_comes_first(self):
        self.assertEqual(
            [name for name, _help in cli.COMMANDS],
            ["interview", "lint", "template", "send-time", "cadence", "decode", "prep", "guard", "scene", "debrief", "intro", "bench", "schema", "doctor"],
        )

    def test_no_command_prints_help_and_exits_2(self):
        code, out, _err = run([])
        self.assertEqual(code, 2)
        self.assertIn("usage: playbook.py", out)

    def test_every_command_has_help(self):
        for name, _help in cli.COMMANDS:
            code, out, _err = run([name, "--help"])
            self.assertEqual(code, 0, name)
            self.assertIn("usage: playbook.py %s" % name, out)

    def test_version(self):
        code, out, _err = run(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("american-business-playbook 2.0.0", out)


class ExitCodeTest(unittest.TestCase):
    def test_lint_clean_is_0_and_revise_is_1(self):
        self.assertEqual(run(["lint", "--type", "cold", "--file", "-"], GOOD)[0], 0)
        self.assertEqual(run(["lint", "--type", "cold", "--file", "-"], BAD)[0], 1)

    def test_guard_pass_is_0_and_fail_is_1(self):
        self.assertEqual(run(["guard", "--audience", "investor", "--file", "-"], "What does your process look like from here?")[0], 0)
        self.assertEqual(run(["guard", "--audience", "investor", "--file", "-"], "What is your budget?")[0], 1)

    def test_needs_intake_is_a_normal_answer_not_an_error(self):
        self.assertEqual(run(["decode", "--json", '{"context": "sales"}'])[0], 0)
        self.assertEqual(run(["prep", "--json", "{}"])[0], 0)

    def test_bad_input_is_2_with_a_hint(self):
        cases = [
            (["decode", "--json", "{not json"], None),
            (["decode", "--json", '{"context": "sales", "qoutes": []}'], None),
            (["decode"], None),
            (["decode", "--json", ""], None),
            (["lint", "--type", "cold"], None),
            (["guard", "--audience", "sales"], None),
            (["cadence", "--meeting-date", "9999-12-30"], None),
            (["cadence", "--meeting-date", "0001-01-01"], None),
            (["send-time", "--tz", "ET", "--now", "1850-06-01T10:00"], None),
            (["lint", "--type", "cold", "--file", "/nonexistent/draft.txt"], None),
            (["send-time", "--tz", "Narnia"], None),
            (["cadence", "--meeting-date", "10/08/2026"], None),
            (["cadence", "--meeting-date", "2026-08-10", "--sent", "recap,telepathy"], None),
            (["template", "--id", "newsletter"], None),
            (["template", "--id", "cold", "--set", "mood=great"], None),
            (["bench"], None),
        ]
        for argv, stdin in cases:
            code, _out, err = run(argv, stdin)
            self.assertEqual(code, 2, argv)
            self.assertIn("Error:", err, argv)

    def test_errors_are_json_when_json_was_asked_for(self):
        code, out, _err = run(["send-time", "--tz", "Narnia", "--format", "json"])
        payload = json.loads(out)
        self.assertEqual((code, payload["ok"], payload["error"]), (2, False, "unknown_zone"))
        self.assertIn("hint", payload)


class NoHangTest(unittest.TestCase):
    """A run that was given nothing must say so at once, not wait on stdin."""

    def test_missing_input_fails_fast_even_when_stdin_is_left_open(self):
        import subprocess
        import sys

        for argv in (["lint", "--type", "cold"], ["guard", "--audience", "sales"], ["decode"], ["prep"], ["debrief"], ["intro"], ["decode", "--json", ""]):
            proc = subprocess.Popen(
                [sys.executable, "-B", _util.ENTRY] + argv,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                code = proc.wait(timeout=30)  # stdin stays open and silent the whole time
            finally:
                proc.stdin.close()
                proc.stdout.close()
                err = proc.stderr.read().decode("utf-8")
                proc.stderr.close()
            self.assertEqual(code, 2, argv)
            self.assertIn("Error:", err, argv)

    def test_a_dash_reads_stdin(self):
        self.assertEqual(run(["lint", "--type", "cold", "--file", "-"], GOOD)[0], 0)
        self.assertEqual(run(["decode", "--in", "-"], '{"context": "sales"}')[0], 0)


class ReceiptTest(unittest.TestCase):
    """Every answer says what produced it and what was not checked."""

    def test_json_output_carries_a_receipt(self):
        code, payload = run_json(["lint", "--type", "cold", "--file", "-"], GOOD)
        receipt = payload["receipt"]
        self.assertEqual(receipt["engine"], "american-business-playbook 2.0.0")
        self.assertEqual(receipt["command"], "lint")
        self.assertRegex(receipt["rules"], r"^[0-9a-f]{12}$")
        self.assertEqual(receipt["seal"], "ok")
        self.assertIn("one_ask", receipt["checks_run"])
        self.assertEqual([item["check"] for item in receipt["checks_skipped"]], ["numbers_vs_source"])

    def test_brief_ends_with_the_stamp_in_the_coaching_language(self):
        _code, out, _err = run(["lint", "--type", "cold", "--file", "-", "--lang", "en"], GOOD)
        self.assertTrue(out.strip().split("\n")[-1].startswith("[verified by code: american-business-playbook 2.0.0 | rules "))
        _code, out, _err = run(["lint", "--type", "cold", "--file", "-"], GOOD)
        last = out.strip().split("\n")[-1]
        self.assertTrue(last.startswith("[נבדק בקוד: american-business-playbook 2.0.0"), last)

    def test_the_stamp_names_what_was_not_checked(self):
        _code, out, _err = run(["lint", "--type", "cold", "--file", "-", "--lang", "en"], GOOD)
        self.assertIn("not checked: numbers_vs_source", out.strip().split("\n")[-1])
        _code, out, _err = run(["decode", "--lang", "en", "--json", '{"context": "sales"}'])
        self.assertIn("not checked: verdict", out.strip().split("\n")[-1])

    def test_assumptions_are_printed(self):
        _code, out, _err = run(["send-time", "--tz", "Boston", "--now", "2026-11-24T14:16", "--lang", "en"])
        self.assertIn('Assumptions: timezone ET assumed from "Boston"', out)

    def test_every_stamp_and_brief_is_free_of_dashes(self):
        outputs = [
            run(["lint", "--type", "cold", "--file", "-"], BAD)[1],
            run(["send-time", "--tz", "PT", "--now", "2026-11-24T14:16"])[1],
            run(["cadence", "--meeting-date", "2026-11-20", "--tz", "CT", "--today", "2026-11-24"])[1],
            run(["scene", "--type", "kol", "--seed", "1"])[1],
            run(["bench", "--topic", "pricing"])[1],
            run(["template", "--list"])[1],
        ]
        for text in outputs:
            self.assertNotIn(_util.EM_DASH, text)
            self.assertNotIn(_util.EN_DASH, text)


class CommandBehaviorTest(unittest.TestCase):
    def test_lint_with_source_file(self):
        with tempfile.TemporaryDirectory() as folder:
            draft, rewrite = os.path.join(folder, "draft.txt"), os.path.join(folder, "rewrite.txt")
            with open(draft, "w", encoding="utf-8") as handle:
                handle.write("We work with two carriers. Send me your availability. Can we talk?")
            with open(rewrite, "w", encoding="utf-8") as handle:
                handle.write(GOOD.replace("two carriers", "two carriers and 14 pilots"))
            code, payload = run_json(["lint", "--type", "cold", "--file", rewrite, "--source", draft])
        self.assertEqual(code, 1, "a figure the founder never gave must stop the email")
        self.assertEqual(payload["result"]["unverified_numbers"], ["14"])
        self.assertIn("unverified_number", [item["check"] for item in payload["result"]["errors"]])
        self.assertEqual(payload["result"]["before"]["asks"], 2)
        self.assertEqual(payload["receipt"]["checks_skipped"], [])

    def test_send_time_today(self):
        code, payload = run_json(["send-time", "--tz", "ET", "--now", "2026-11-24T14:16"])
        self.assertEqual(code, 0)
        first = payload["result"]["slots"][0]
        self.assertEqual((first["date"], first["local_time"], first["israel_time"]), ("2026-12-01", "09:30", "16:30"))
        self.assertEqual(payload["result"]["skipped"][0]["name"], "Thanksgiving week")

    def test_cadence_and_calendar_export(self):
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, "touches.ics")
            code, payload = run_json(["cadence", "--meeting-date", "2026-08-10", "--tz", "ET", "--ics", target])
            self.assertEqual(code, 0)
            self.assertEqual([t["date"] for t in payload["result"]["touches"]], ["2026-08-11", "2026-08-13", "2026-08-18", "2026-08-25", "2026-11-10"])
            with open(target, "r", encoding="utf-8", newline="") as handle:
                self.assertEqual(handle.read().count("BEGIN:VEVENT"), 5)
            self.assertIn("ics_export", payload["receipt"]["checks_run"])

    def test_template_list_and_render(self):
        _code, payload = run_json(["template", "--list"])
        self.assertEqual([t["id"] for t in payload["result"]["templates"]], mail.template_ids())
        code, payload = run_json(["template", "--id", "breakup", "--set", "first_name=Michael"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["result"]["missing"], [])
        self.assertEqual(payload["result"]["lint"]["status"], "pass")

    def test_scheduling_template_gets_real_dates_only_with_a_zone(self):
        _code, payload = run_json(["template", "--id", "scheduling", "--tz", "ET", "--now", "2026-11-24T14:16"])
        self.assertIn("- Tue Dec 1, 9:00-11:00", payload["result"]["text"])
        self.assertNotIn("[date]", payload["result"]["text"])
        _code, payload = run_json(["template", "--id", "scheduling"])
        self.assertIn("[date]", payload["result"]["text"])
        self.assertIn("scheduling_dates", [item["check"] for item in payload["receipt"]["checks_skipped"]])

    def test_scene_then_debrief_round_trip(self):
        _code, payload = run_json(["scene", "--type", "sales", "--seed", "rt-1"])
        card = payload["result"]
        turns = []
        for item in card["inject"]:
            turns.append({"who": "american", "text": item["line"]})
            turns.append({"who": "founder", "text": "Would Thursday at 10am work for a quick follow-up?"})
        sheet = dict(card["debrief_with"], turns=turns, outcome={"result": "dated_step"})
        code, payload = run_json(["debrief", "--in", "-"], json.dumps(sheet))
        self.assertEqual(code, 0)
        self.assertTrue(1 <= payload["result"]["score"] <= 10)
        self.assertEqual(payload["result"]["not_delivered"], [])

    def test_fact_sheet_from_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "facts.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"stage": "received", "hours_since_intro": 30, "replied": False}, handle)
            code, payload = run_json(["intro", "--in", path])
        self.assertEqual((code, payload["result"]["status"]), (0, "act"))

    def test_decode_force_flag(self):
        sheet = json.dumps({"context": "sales", "next_step": {"exists": False}, "cost_to_them": []})
        _code, payload = run_json(["decode", "--in", "-"], sheet)
        self.assertEqual(payload["result"]["status"], "needs_intake")
        _code, payload = run_json(["decode", "--in", "-", "--force"], sheet)
        self.assertEqual(payload["result"]["status"], "provisional")


class SchemaTest(unittest.TestCase):
    """The documented example for every fact sheet must actually run."""

    def test_every_schema_example_runs_through_its_command(self):
        for name, (_spec, example) in cli.FACT_COMMANDS.items():
            code, payload = run_json([name, "--in", "-"], json.dumps(example))
            self.assertEqual(code, 0, name)
            self.assertTrue(payload["ok"], name)

    def test_schema_output_lists_fields_signals_and_an_example(self):
        code, out, _err = run(["schema", "decode"])
        self.assertEqual(code, 0)
        for needle in ("context: sales | investor | kol (required)", "accepted_by_them", "sales/green: added_people", "Example:"):
            self.assertIn(needle, out)

    def test_examples_use_only_known_fields(self):
        from abp.schema import validate

        for name, (spec, example) in cli.FACT_COMMANDS.items():
            validate(example, spec)


class DoctorTest(unittest.TestCase):
    def test_doctor_passes_on_a_sealed_tree(self):
        code, payload = run_json(["doctor"])
        failing = [item["check"] for item in payload["result"]["checks"] if not item["ok"]]
        self.assertEqual(failing, [])
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(payload["result"]["checks"]), 9)


class EntryPointTest(unittest.TestCase):
    """The real script in a fresh interpreter, the way an agent runs it."""

    def test_runs_from_any_working_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            code, out, err = _util.subprocess_run(["doctor", "--lang", "en"], cwd=folder)
        self.assertEqual(code, 0, out + err)
        self.assertIn("All good.", out)

    def test_heredoc_style_stdin_with_apostrophes(self):
        sheet = json.dumps({"context": "investor", "quotes": ["It's a bit early for us. Keep us posted!"], "next_step": {"exists": False}, "cost_to_them": [], "today": "2026-11-24"})
        code, out, err = _util.subprocess_run(["decode", "--in", "-", "--lang", "en"], stdin=sheet)
        self.assertEqual(code, 0, err)
        self.assertIn("Bar-extraction reply", out)

    def test_hebrew_output_survives_the_pipe(self):
        code, out, err = _util.subprocess_run(["bench", "--topic", "תמחור"])
        self.assertEqual(code, 0, err)
        self.assertIn("נמרוד", out)

    def test_leaves_no_bytecode_behind(self):
        _util.subprocess_run(["doctor"])
        for folder, dirs, _files in os.walk(_util.SKILL):
            self.assertNotIn("__pycache__", dirs, folder)


class LabelsTest(unittest.TestCase):
    def test_every_label_the_code_asks_for_exists(self):
        import re

        used = set()
        for name in ("cli.py", "decode.py", "meeting.py", "intro.py"):
            source = _util.read("skills", _util.SKILL_NAME, "scripts", "abp", name)
            used.update(re.findall(r"""(?:\b_lab|\blab|label\("coach",)\(?\s*"([a-z_]+)\"""", source))
        labels = set(load("coach")["labels"]) | set(load("meetings")["debrief"]["labels"])
        missing = sorted(key for key in used if key not in labels and not key.endswith("_"))
        self.assertEqual(missing, [])
        self.assertGreater(len(used), 40)
        for status in ("sent", "overdue", "due_today", "upcoming", "planned"):
            self.assertIn("status_" + status, labels)


if __name__ == "__main__":
    unittest.main()
