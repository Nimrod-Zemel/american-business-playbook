"""The guide is the source: the tables must say what it says, and the check must bite."""

import html
import json
import os
import re
import unittest

import _util
import guide
from abp import decode, mail, meeting
from abp.core import load

TODAY = "2026-11-24"


class GuideIsTheSourceTest(unittest.TestCase):
    def test_the_guide_the_reading_copy_and_the_tables_agree(self):
        report = guide.run()
        self.assertEqual(report["problems"], [])
        self.assertGreater(report["lines"], 100)
        self.assertEqual(report["found"] + report["names"], report["lines"])

    def test_only_two_quoted_strings_are_names_and_not_lines(self):
        self.assertEqual(sorted(guide.NOT_LINES), ["Americanize My Email", "The American Meeting"])

    def test_the_tables_declare_the_guide_they_implement(self):
        meta = load("coach")["guide"]
        self.assertEqual(meta["sha256"], guide.sha256())
        self.assertEqual(meta["version"], "V2")
        blocks = guide.read()
        last = [block["text"] for block in blocks if block["kind"] != "table" and block["text"]][-1]
        self.assertIn("V2, Last Update: 23/09/2026", last)
        self.assertIn(meta["authors"], last)

    def test_the_reading_copy_says_every_word_of_the_word_file(self):
        """Markup aside, the generated copy is the guide, word for word and in order."""
        text = _util.read("docs", "guide", guide.COPY)
        body = text.split('<div dir="rtl">', 1)[1]
        said = []
        # Fenced boxes are the guide's English, verbatim. Everything else carries Markdown to strip.
        for index, part in enumerate(re.split(r"```text\n(.*?)```", body, flags=re.S)):
            if index % 2:
                said.extend(part.split())
                continue
            part = re.sub(r"<[^>]+>", " ", part)
            part = re.sub(r"(?m)^\|( --- \|)+$", " ", part)
            part = re.sub(r"(?m)^(#{2,3}|-|>) ", " ", part)
            part = re.sub(r"(?m)^>$", " ", part)
            part = part.replace("\\|", "\x00").replace("|", " ").replace("\x00", "|").replace("\\*", "*").replace("\\_", "_")
            said.extend(html.unescape(part).split())
        self.assertEqual(said, guide.words(guide.read()))

    def test_english_boxes_stay_left_to_right(self):
        text = _util.read("docs", "guide", guide.COPY)
        outside = re.sub(r'<div dir="rtl">.*?</div>', "", text, flags=re.S)
        fences = re.findall(r"```text\n.*?```", text, re.S)
        self.assertGreaterEqual(len(fences), 8)
        for fence in fences:
            self.assertIn(fence, outside)
            self.assertIsNone(guide.HEBREW.search(fence))
        self.assertEqual(text.count('<div dir="rtl">'), text.count("</div>"))

    def test_the_guide_folder_explains_itself_in_both_languages(self):
        note = _util.read("docs", "guide", "README.md")
        for needle in ("All rights reserved", "python3 tools/guide.py", '<a id="hebrew"></a>', "כל הזכויות שמורות"):
            self.assertIn(needle, note)
        tables = set(re.findall(r"`([a-z]+\.json)`", note))
        on_disk = set(os.listdir(os.path.join(_util.SKILL, "data")))
        self.assertTrue(tables <= on_disk, tables - on_disk)
        self.assertGreaterEqual(len(tables), 8)


class CheckBitesTest(unittest.TestCase):
    def test_a_rule_dropped_from_a_table_is_reported(self):
        with _util.repo_copy() as root:
            path = os.path.join(root, "skills", _util.SKILL_NAME, "data", "decoder.json")
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text.replace("never a dull moment here", "what a week"))
            problems = guide.run(root)["problems"]
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("never a dull moment", problems[0])

    def test_a_new_guide_with_the_old_declaration_is_reported(self):
        with _util.repo_copy() as root:
            path = os.path.join(root, "docs", "guide", guide.DOCX)
            with open(path, "rb") as handle:
                data = handle.read()
            with open(path, "wb") as handle:
                handle.write(data + b"\n")
            problems = guide.run(root)["problems"]
        self.assertTrue(any("still names V2" in item for item in problems), problems)

    def test_a_hand_edited_reading_copy_is_reported(self):
        with _util.repo_copy() as root:
            with open(os.path.join(root, "docs", "guide", guide.COPY), "a", encoding="utf-8") as handle:
                handle.write("\nOne more rule.\n")
            problems = guide.run(root)["problems"]
        self.assertTrue(any("is stale" in item for item in problems), problems)


class ModuleSixPoliticsTest(unittest.TestCase):
    """The guide's politics module, which the tables lacked until they were checked against V2."""

    SHEET = {"context": "sales", "today": TODAY, "quotes": ["This is amazing!"], "next_step": {"exists": False}, "cost_to_them": [], "their_questions": 0}

    def decoded(self, quote):
        sheet = dict(self.SHEET, quotes=self.SHEET["quotes"] + [quote])
        return decode.decode(sheet, "en")

    def test_political_lines_are_decoded_with_the_guides_move(self):
        cases = {
            "This administration is killing us with regulation.": ("administration_complaint", "Sounds like a real headache for the industry"),
            "What's your take on the election?": ("election_take", "Like baseball"),
            "How are things back in Israel? We've been worried.": ("israel_concern", "Thank you for asking"),
            "Come on, you must have a take!": ("pushed_for_opinion", "still a guest here"),
            "What do you think about the government?": ("israel_politics_question", "leave politics to the politicians"),
        }
        for quote, (row_id, move) in cases.items():
            rows = [row for row in self.decoded(quote)["decoded"] if row["quote"] == quote]
            self.assertEqual([row["row"] for row in rows], [row_id], quote)
            self.assertIn(move, rows[0]["move"], quote)
            self.assertEqual(rows[0]["table"], "politics")

    def test_a_political_line_never_moves_the_traffic_light(self):
        plain = decode.decode(dict(self.SHEET), "en")["verdict"]
        for quote in ("This administration is killing us with regulation.", "What's your take on the election?", "Let's grab coffee sometime!"):
            verdict = self.decoded(quote)["verdict"]
            self.assertEqual((verdict["light"], verdict["lean"]), (plain["light"], plain["lean"]), quote)

    def test_coffee_sometime_is_friendliness_and_a_dated_coffee_is_not(self):
        rows = self.decoded("Let's grab coffee sometime!")["decoded"]
        self.assertIn("coffee_sometime", [row["row"] for row in rows])
        rows = self.decoded("Let's grab coffee on Tuesday at 10.")["decoded"]
        self.assertNotIn("coffee_sometime", [row["row"] for row in rows])

    def test_political_rows_are_not_listed_as_soft_nos_in_a_prep_sheet(self):
        for kind in meeting.TYPES:
            listed = [row["row"] for row in meeting.soft_nos_for(kind, "en")]
            for row in load("decoder")["rows"]:
                if row["table"] in ("politics", "social_default"):
                    self.assertNotIn(row["id"], listed)

    def test_a_scene_drops_a_political_aside_only_when_asked(self):
        for kind in meeting.TYPES:
            plain = meeting.scene(kind, seed="s1", lang="en")
            with_aside = meeting.scene(kind, seed="s1", lang="en", politics=True)
            self.assertEqual(plain["inject"], with_aside["inject"][:len(plain["inject"])], "the same seed must keep its lines")
            extra = with_aside["inject"][len(plain["inject"]):]
            self.assertEqual([item["slot"] for item in extra], ["politics_aside"])
            self.assertEqual(extra[0]["row"], load("meetings")["politics"]["asides"][kind])
            self.assertNotIn("politics_aside", [item["slot"] for item in plain["inject"]])

    def debrief(self, reply):
        turns = [
            {"who": "american", "text": "This administration is killing us with regulation."},
            {"who": "founder", "text": reply},
            {"who": "american", "text": "Anyway. Send me a deck and I'll take a look."},
            {"who": "founder", "text": "Happy to send a one-pager today. Would Thursday at 10am work to walk through it?"},
        ]
        return meeting.debrief({"type": "sales", "turns": turns, "injected": ["send_deck"], "outcome": {"result": "dated_step"}}, "en")

    def test_joining_a_political_remark_costs_discipline(self):
        joined = self.debrief("Totally, tell me about it. Regulation is out of control.")
        bridged = self.debrief("Sounds like a real headache for the industry. Is that part of what's driving this project?")
        stayed = self.debrief("Understood. Shall we look at the pilot scope?")
        self.assertEqual([item["outcome"] for item in joined["politics"]], ["joined"])
        self.assertEqual([item["outcome"] for item in bridged["politics"]], ["bridged"])
        self.assertEqual([item["outcome"] for item in stayed["politics"]], ["stayed_out"])
        self.assertIn("joined_politics", [item["guard"] for item in joined["violations"]])
        self.assertNotIn("joined_politics", [item["guard"] for item in bridged["violations"]])
        self.assertLess(joined["score"], bridged["score"])
        self.assertEqual(bridged["score"], stayed["score"])
        self.assertEqual(joined["drill"]["dimension"], "discipline")
        self.assertIn("Politics came up", meeting.debrief_brief(joined, "en"))

    def test_a_transcript_without_politics_reports_none(self):
        result = meeting.debrief({"type": "sales", "turns": [{"who": "american", "text": "This is really interesting!"}, {"who": "founder", "text": "Thanks. Would Tuesday at 10 work?"}]}, "en")
        self.assertEqual(result["politics"], [])


class ModuleFiveAndEightTest(unittest.TestCase):
    PREP = {"type": "sales", "goal_currency": "calendar_time", "the_ask": "Would Thursday at 10 work?", "city": "Austin", "meeting_minutes": 30}

    def test_the_frame_line_is_the_guides_for_a_thirty_minute_meeting(self):
        frame = load("meetings")["conduct"]["frame"]
        self.assertEqual(frame["template"].format(minutes=30), frame["said"])
        sheet = meeting.prep(dict(self.PREP), "en")["sheet"]
        self.assertEqual(sheet["timebox"]["opening"], frame["said"])
        sheet = meeting.prep(dict(self.PREP, meeting_minutes=45), "en")["sheet"]
        self.assertIn("we have 45 minutes", sheet["timebox"]["opening"])
        self.assertEqual(sheet["timebox"]["end_at"], 43)

    def test_the_prep_sheet_carries_the_hard_stop_the_bridge_line_and_the_politics_rule(self):
        brief = meeting.prep_brief(meeting.prep(dict(self.PREP), "en"), "en")
        for needle in (
            "I want to be respectful of your time", "First time in Austin - any recommendations?", "Great, thanks! How about you?",
            "Do not initiate, do not join, do not correct", "Is it part of what's driving this project?",
            "Do not interrupt", "two or three minutes early", "Do not offer tomorrow", "never behind your champion's back",
        ):
            self.assertIn(needle, brief)
        for kind in ("investor", "kol"):
            sheet = meeting.prep(dict(self.PREP, type=kind), "en")["sheet"]
            self.assertIsNone(sheet["timebox"]["opening"], "the workflow frame is a sales opening")
            self.assertTrue(sheet["timebox"]["hard_stop"])

    def test_small_talk_lists_follow_the_guide(self):
        talk = load("meetings")["small_talk"]
        self.assertIn("career", talk["safe"])
        self.assertTrue(any("Israel" in item for item in talk["forbidden"]))
        self.assertEqual(len(talk["safe"]), len(talk["safe_he"]))
        self.assertEqual(len(talk["forbidden"]), len(talk["forbidden_he"]))


class ModuleThreeExamplesTest(unittest.TestCase):
    """The guide's own lines, run through the linter."""

    def lint(self, line, kind="cold"):
        draft = "Subject: Claims triage pilot\n\nHi Michael,\n\n%s\n\nBest,\nDana\n" % line
        return mail.lint(draft, kind, lang="en")

    def codes(self, result):
        return [item["check"] for item in result["errors"] + result["warnings"]]

    def test_the_lines_to_avoid_are_flagged(self):
        examples = load("email")["examples"]
        flagged = {"Send me your feedback.": "command_tone", "I want to schedule a call.": "directive", "You must understand that...": "directive"}
        self.assertEqual(sorted(flagged), sorted(examples["avoid"]))
        for line, code in flagged.items():
            self.assertIn(code, self.codes(self.lint(line)), line)

    def test_the_lines_to_use_count_as_softeners(self):
        for line in load("email")["examples"]["use"]:
            result = self.lint("We help mid-size insurers cut claims triage time. %s" % line.replace("...", " for a short call?"))
            self.assertNotIn("softener_missing", self.codes(result), line)
        bare = self.lint("We help mid-size insurers cut claims triage time. Can we talk on Tuesday?")
        self.assertIn("softener_missing", self.codes(bare), "the control: a line with no softener is flagged")

    def test_the_hurt_line_is_flagged_and_the_closed_ask_is_one_ask(self):
        examples = load("email")["examples"]
        self.assertIn("hurt_tone", self.codes(self.lint(examples["hurt"], "followup")))
        result = self.lint("We help mid-size insurers cut claims triage time. %s" % examples["closed_ask"])
        self.assertEqual(result["stats"]["asks"], 1)
        self.assertNotIn("ask_open", self.codes(result))


if __name__ == "__main__":
    unittest.main()
