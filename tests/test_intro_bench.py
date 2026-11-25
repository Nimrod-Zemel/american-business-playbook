"""The intro protocol checklist and bench routing."""

import unittest

import _util  # noqa: F401
from abp import intro
from abp.core import PlaybookError, load


def check(**facts):
    return intro.intro(facts, "en")


def rules(result):
    return dict((item["rule"], item["ok"]) for item in result["items"])


class IntroTest(unittest.TestCase):
    def test_asking_without_a_forwardable_email(self):
        result = check(stage="asking", forwardable_attached=False, gave_before=True)
        self.assertEqual(rules(result), {"double_opt_in": False, "give_first": True})
        self.assertEqual(result["templates"], ["forwardable"])
        self.assertEqual(result["status"], "act")

    def test_asking_done_right(self):
        result = check(stage="asking", forwardable_attached=True, gave_before=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["templates"], [])

    def test_favor_balance(self):
        self.assertFalse(rules(check(stage="asking", forwardable_attached=True, gave_before=False))["give_first"])
        unknown = check(stage="asking", forwardable_attached=True)
        self.assertIsNone(rules(unknown)["give_first"])
        self.assertEqual(unknown["unknown"], ["gave_before"])

    def test_reply_speed_is_hours_not_days(self):
        late = check(stage="received", hours_since_intro=30, replied=False)
        self.assertFalse(rules(late)["speed"])
        self.assertIn("Late", late["items"][0]["text"])
        self.assertIn("intro_reply_bcc", late["templates"])
        pending = check(stage="received", hours_since_intro=3, replied=False)
        self.assertIn("Reply now", pending["items"][0]["text"])
        on_time = check(stage="received", hours_since_intro=3, replied=True, moved_to_bcc=True)
        self.assertEqual(on_time["status"], "ok")

    def test_bcc_protocol(self):
        result = check(stage="received", hours_since_intro=2, replied=True, moved_to_bcc=False)
        self.assertFalse(rules(result)["bcc"])
        self.assertEqual(result["templates"], ["intro_reply_bcc"])

    def test_closing_the_loop(self):
        open_loop = check(stage="after_meeting", connector="Sarah", loop_closed=False)
        self.assertIn("Sarah", open_loop["items"][0]["text"])
        self.assertEqual(open_loop["templates"], ["loop_close", "thank_you"])
        self.assertEqual(check(stage="after_meeting", loop_closed=True)["status"], "ok")

    def test_connecting_others_needs_both_to_agree(self):
        self.assertFalse(rules(check(stage="connecting", both_agreed=False))["double_opt_in"])
        self.assertTrue(rules(check(stage="connecting", both_agreed=True))["double_opt_in"])

    def test_all_five_rules_travel_with_every_answer(self):
        result = check(stage="asking", forwardable_attached=True, gave_before=True)
        self.assertEqual([rule["id"] for rule in result["rules"]], ["double_opt_in", "speed", "bcc", "close_loop", "give_first"])

    def test_stage_is_required_and_validated(self):
        with self.assertRaises(PlaybookError):
            intro.intro({}, "en")
        with self.assertRaises(PlaybookError):
            check(stage="ghosting")

    def test_brief_in_both_languages(self):
        for lang in ("he", "en"):
            text = intro.intro_brief(intro.intro({"stage": "received", "hours_since_intro": 30, "replied": False}, lang), lang)
            self.assertIn("intro_reply_bcc", text)


class BenchTest(unittest.TestCase):
    def test_every_row_of_the_routing_table_routes_to_its_person(self):
        for row in load("bench")["routing"]:
            for topic in row["topic"].split(","):
                result = intro.route(topic.strip(), lang="en")
                self.assertEqual(result["person"], row["person"], topic)

    def test_hebrew_topics(self):
        cases = {"תמחור ומודל עסקי": "nimrod", "גיוס מקרן אמריקאית": "dana", "פיבוט": "eyal", "שיווק וקהילה": "einat", "אבטיפוס": "erez"}
        for topic, person in cases.items():
            self.assertEqual(intro.route(topic)["person"], person, topic)

    def test_flags(self):
        self.assertEqual(intro.route(flag="investor_thread")["person"], "dana")
        self.assertEqual(intro.route(flag="strategic_fork")["person"], "eyal")

    def test_a_nudge_is_a_question_or_a_referral_never_a_quote(self):
        result = intro.route("pricing", lang="en")
        self.assertEqual(sorted(result["allowed_forms"]), ["question", "referral"])
        self.assertIn("What would Nimrod ask here?", result["allowed_forms"]["question"])
        self.assertTrue(any("NEVER invent" in rule for rule in result["rules"]))

    def test_hebrew_nudge_forms_agree_in_gender(self):
        self.assertIn("הייתה שואלת", intro.route("investors")["allowed_forms"]["question"])
        self.assertIn("היה שואל", intro.route("pricing")["allowed_forms"]["question"])

    def test_two_nudges_per_session(self):
        self.assertEqual(intro.route("pricing", used=0)["budget_left"], 1)
        self.assertEqual(intro.route("pricing", used=1)["budget_left"], 0)
        spent = intro.route("pricing", used=2)
        self.assertIsNone(spent["person"])
        self.assertIn("used up", intro.route("pricing", used=2, lang="en")["message"])

    def test_no_owner_and_no_topic(self):
        self.assertIsNone(intro.route("quantum gravity", lang="en")["person"])
        with self.assertRaises(PlaybookError):
            intro.route()


if __name__ == "__main__":
    unittest.main()
