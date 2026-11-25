"""Meeting prep, the guard, simulation scenes and the debrief score."""

import copy
import unittest

import _util  # noqa: F401
from abp import meeting
from abp.core import PlaybookError, Receipt, load

READY = {
    "type": "sales",
    "goal_currency": "data_access",
    "goal": "three months of claims exports for a pilot",
    "the_ask": "Would you be open to sharing a sample export by Friday?",
}


def prep(**changes):
    data = copy.deepcopy(READY)
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return meeting.prep(data, "en")


class PrepIntakeTest(unittest.TestCase):
    def test_the_meeting_type_comes_first(self):
        result = meeting.prep({}, "en")
        self.assertEqual(result["status"], "needs_intake")
        self.assertIsNone(result["sheet"])
        self.assertEqual(result["ask_next"][0]["field"], "type")
        self.assertLessEqual(len(result["ask_next"]), 3)

    def test_goal_and_ask_are_required(self):
        result = meeting.prep({"type": "sales"}, "en")
        self.assertEqual(result["status"], "needs_intake")
        self.assertEqual([q["field"] for q in result["ask_next"]][:2], ["goal_currency", "the_ask"])

    def test_the_goal_must_be_a_commitment_currency(self):
        with self.assertRaises(PlaybookError):
            prep(goal_currency="good vibes")

    def test_type_aliases(self):
        self.assertEqual(prep(type="VC")["type"], "investor")
        self.assertEqual(prep(type="customer")["type"], "sales")
        self.assertEqual(prep(type="expert")["type"], "kol")


class PrepSheetTest(unittest.TestCase):
    def test_sales_sheet_carries_bant_and_mechanics(self):
        sheet = prep()["sheet"]
        self.assertEqual(sheet["bant"], "on")
        self.assertEqual([row["letter"] for row in sheet["bant_table"]], ["Budget", "Authority", "Need", "Timeline"])
        self.assertEqual(len(sheet["permission_lines"]), 3)
        self.assertIn("End a 30-minute meeting at 28", sheet["mechanics"][0])

    def test_timebox_follows_the_meeting_length(self):
        sheet = prep(meeting_minutes=45)["sheet"]
        self.assertEqual((sheet["timebox"]["minutes"], sheet["timebox"]["end_at"]), (45, 43))
        self.assertIn("45 minutes", sheet["timebox"]["opening"])

    def test_investor_sheet_has_no_bant_anywhere(self):
        """The single highest-damage failure the skill exists to prevent."""
        result = prep(type="investor")
        sheet = result["sheet"]
        self.assertEqual(sheet["bant"], "off")
        self.assertNotIn("bant_table", sheet)
        self.assertIn("Never run BANT on an investor", sheet["hard_rule"])
        brief = meeting.prep_brief(result, "en")
        for forbidden in ("Budget:", "Authority:", "How do initiatives like this usually get funded"):
            self.assertNotIn(forbidden, brief)
        self.assertEqual(len(sheet["may_ask"]), 5)
        self.assertEqual([row["row"] for row in sheet["soft_nos"]], ["too_early", "more_traction", "dont_lead", "discuss_partners", "who_else"])

    def test_every_question_a_founder_may_ask_an_investor_passes_the_guard(self):
        for item in load("meetings")["investor"]["may_ask"]:
            result = meeting.guard(item["q"], "investor", "en")
            self.assertEqual(result["status"], "pass", item["q"])
            self.assertEqual(result["violations"], [], item["q"])

    def test_investor_extras_depend_on_the_situation(self):
        ids = lambda **kw: [item["id"] for item in prep(type="investor", **kw)["sheet"]["advanced"]]
        self.assertEqual(ids(), ["process_signals"])
        self.assertIn("associate", ids(counterpart={"role": "Senior Associate"}))
        self.assertIn("second_meeting", ids(meeting_number=2))
        self.assertEqual(sorted(ids(live_thread=True)), ["momentum", "process_signals", "update_anatomy"])

    def test_kol_sheet_is_about_extraction_not_selling(self):
        sheet = prep(type="kol")["sheet"]
        self.assertEqual(len(sheet["extraction_bank"]), 6)
        self.assertIn("hard stuff", sheet["opening_line"])
        self.assertEqual(sheet["soft_nos"][0]["row"], "its_great")
        self.assertNotIn("bant_table", sheet)

    def test_small_talk_and_region(self):
        self.assertEqual(prep(city="New York")["sheet"]["small_talk"]["region"], "new_york")
        self.assertEqual(prep(city="Palo Alto")["sheet"]["small_talk"]["region"], "west_coast")
        self.assertEqual(prep(city="Austin")["sheet"]["small_talk"]["region"], "midwest_south")
        self.assertEqual(prep(city="Reykjavik")["sheet"]["small_talk"]["region"], "other")
        self.assertEqual(prep(city="Austin", region="new_york")["sheet"]["small_talk"]["region"], "new_york")
        talk = prep()["sheet"]["small_talk"]
        self.assertIn("politics", talk["forbidden"])
        self.assertIn("sports", talk["safe"])

    def test_unknown_region_is_stated_as_an_assumption(self):
        receipt = Receipt("prep")
        meeting.prep(copy.deepcopy(READY), "en", receipt)
        self.assertTrue(any("regional modifier" in note for note in receipt.assumptions))

    def test_recap_date_is_computed_when_date_and_place_are_known(self):
        sheet = prep(city="Chicago", meeting_date="2026-12-02")["sheet"]
        self.assertEqual((sheet["recap"]["date"], sheet["recap"]["zone"], sheet["recap"]["israel_time"]), ("2026-12-03", "CT", "17:30"))
        self.assertIsNone(prep()["sheet"]["recap"])

    def test_investor_prep_refers_to_dana_once(self):
        self.assertEqual(prep(type="investor")["bench"]["person"], "dana")
        self.assertIsNone(prep(type="investor", bench_used=2)["bench"])
        self.assertIsNone(prep()["bench"])

    def test_briefs_render_for_every_type_and_language(self):
        for kind in meeting.TYPES:
            for lang in ("he", "en"):
                data = dict(READY, type=kind, city="Boston", meeting_date="2026-12-02")
                text = meeting.prep_brief(meeting.prep(data, lang), lang)
                self.assertGreater(len(text.split("\n")), 10)
                self.assertNotIn(_util.EM_DASH, text)


class GuardTest(unittest.TestCase):
    def guards(self, text, audience):
        return [item["guard"] for item in meeting.guard(text, audience, "en")["violations"]]

    def test_bant_wording_fails_for_investors_only(self):
        for line in (
            "What is your budget for seed deals?",
            "Do you have budget for this?",
            "Who is the decision maker on your side?",
            "Who signs the check?",
            "Do you have the final authority?",
        ):
            self.assertEqual(self.guards(line, "investor"), ["bant_on_investor"], line)
            self.assertEqual(meeting.guard(line, "investor", "en")["status"], "fail")
            self.assertNotIn("bant_on_investor", self.guards(line, "sales"), line)

    def test_forbidden_small_talk_fails_everywhere(self):
        for line in ("So, who did you vote for?", "Are you married?", "How old are you?", "What's your salary there?", "Are you religious?"):
            for audience in meeting.TYPES:
                self.assertIn("forbidden_topics", self.guards(line, audience), line)

    def test_safe_small_talk_passes(self):
        for line in ("How was your weekend?", "Did you catch the game last night?", "Any food recommendations in Austin?"):
            self.assertEqual(self.guards(line, "sales"), [], line)

    def test_hypotheticals_fail_with_a_domain_expert(self):
        for line in ("Do you like it?", "Would you use this?", "Would you pay for it?"):
            self.assertIn("hypotheticals", self.guards(line, "kol"), line)
        self.assertEqual(self.guards("Walk me through the last time you dealt with this problem.", "kol"), [])

    def test_trashing_defending_and_false_scarcity_are_warnings(self):
        self.assertEqual(meeting.guard("Honestly their product is garbage.", "sales", "en")["violations"][0]["level"], "warn")
        self.assertIn("defending", self.guards("No, you don't understand how this works.", "kol"))
        self.assertIn("false_scarcity", self.guards("We're oversubscribed already.", "investor"))
        self.assertEqual(meeting.guard("We're oversubscribed already.", "investor", "en")["status"], "pass")

    def test_unknown_audience(self):
        with self.assertRaises(PlaybookError):
            meeting.guard("hello", "regulator")


class IsraelismsTest(unittest.TestCase):
    def ids(self, *lines):
        return [item["id"] for item in meeting.israelisms(list(lines))]

    def test_blunt_openers_are_caught_with_the_american_phrasing(self):
        found = meeting.israelisms(["Send me the contract today.", "Listen, it's very simple."])
        self.assertEqual([item["id"] for item in found], ["send_me", "listen", "its_simple"])
        self.assertTrue(all(item["american"] for item in found))
        self.assertEqual(found[0]["said"], "Send me the contract today.")

    def test_the_playbooks_own_questions_are_not_flagged(self):
        clean = [
            "What would you need to see in 6 months for this to be a strong yes?",
            "Tell me more about how you triage today.",
            "Would you be open to sharing a sample export?",
            "Could you send me the security questionnaire when you have a moment?",
            "If budget weren't an issue, would this be a priority?",
            "That's really helpful. Say more?",
        ]
        for line in clean:
            self.assertEqual(self.ids(line), [], line)

    def test_openers_only_count_at_the_start_of_a_sentence(self):
        self.assertEqual(self.ids("Thanks. Tell me the price."), ["tell_me"])
        self.assertEqual(self.ids("I will look into it and let you know."), [])


class SceneTest(unittest.TestCase):
    def test_same_seed_same_scene(self):
        for kind in meeting.TYPES:
            self.assertEqual(meeting.scene(kind, seed="abc"), meeting.scene(kind, seed="abc"))

    def test_every_scene_injects_a_sugar_coated_no_and_a_vague_deferral(self):
        for kind in meeting.TYPES:
            for seed in range(40):
                slots = [item["slot"] for item in meeting.scene(kind, seed=seed)["inject"]]
                self.assertIn("sugar_coated_no", slots)
                self.assertIn("vague_deferral", slots)

    def test_seeds_give_variety(self):
        for kind in ("sales", "investor"):
            plans = set(tuple(item["row"] for item in meeting.scene(kind, seed=seed)["inject"]) for seed in range(40))
            self.assertGreaterEqual(len(plans), 3, kind)

    def test_characters(self):
        self.assertEqual(meeting.scene("sales", seed=1)["character"]["name"], "Michael")
        self.assertEqual(meeting.scene("investor", seed=1)["character"]["name"], "Jennifer")
        self.assertEqual(meeting.scene("kol", seed=1)["character"]["name"], "Dr. Alan Park")
        self.assertEqual(meeting.scene("investor", seed=1)["bant"], "off")

    def test_the_investor_scene_always_probes_for_who_else(self):
        probes = [item for item in meeting.scene("investor", seed=7)["inject"] if item["slot"] == "probe"]
        self.assertEqual([item["row"] for item in probes], ["who_else"])
        self.assertFalse(probes[0]["scored"])

    def test_the_card_tells_the_model_how_to_debrief(self):
        card = meeting.scene("sales", seed="s1", lang="en")
        self.assertEqual(card["debrief_with"]["seed"], "s1")
        self.assertEqual(card["debrief_with"]["injected"], [item["row"] for item in card["inject"]])
        text = meeting.scene_brief(card, "en")
        self.assertIn("English only", text)
        self.assertIn("STOP", text)
        self.assertIn("do not hold it hostage to intake", text)

    def test_unknown_type_is_refused(self):
        with self.assertRaises(PlaybookError):
            meeting.scene("regulator")


def transcript(kind, seed, founder_replies, outcome="vague"):
    """Build a transcript in which the American delivers every injected line in order."""
    card = meeting.scene(kind, seed=seed)
    turns = []
    for item, reply in zip(card["inject"], founder_replies):
        turns.append({"who": "american", "text": item["line"]})
        turns.append({"who": "founder", "text": reply})
    return {"type": kind, "seed": str(seed), "turns": turns, "outcome": {"result": outcome}}


class DebriefTest(unittest.TestCase):
    def perfect_sales(self, seed="p1"):
        card = meeting.scene("sales", seed=seed)
        replies = []
        for item in card["inject"]:
            replies.append({
                "really_interesting": "Glad it resonates. Would Tuesday or Thursday work for a 20-minute follow-up with your data lead?",
                "keep_in_touch": "Happy to. What would need to change for this to become relevant?",
                "send_deck": "I'll send a one-pager today. Would Thursday at 10am work to walk through it?",
                "loop_in_unnamed": "Great. Who should I include, and would Tuesday work for a quick call with them?",
                "no_budget": "Understood. If budget weren't an issue, would this be a priority?",
            }[item["row"]])
        return transcript("sales", seed, replies, "dated_step")

    def test_a_founder_who_counters_everything_and_lands_a_date_scores_ten(self):
        for seed in ("p1", "p2", "p3", "p4", "p5", "p6"):
            data = self.perfect_sales(seed)
            data["turns"].append({"who": "founder", "text": "Should I close this out on my end, or would Thursday at 10am work?"})
            result = meeting.debrief(data, "en")
            self.assertEqual(result["score"], 10.0, (seed, result["breakdown"], result["signals_missed"]))
            self.assertEqual(result["signals_missed"], [])
            self.assertTrue(result["dated_next_step"])
            self.assertEqual(result["israelisms"], [])

    def test_a_founder_who_misses_everything_scores_low_and_gets_the_decoding_drill(self):
        data = transcript("sales", "p1", ["Great, thanks!", "Perfect, talk soon."], "vague")
        result = meeting.debrief(data, "en")
        self.assertLess(result["score"], 4.0)
        self.assertEqual(len(result["signals_missed"]), 2)
        self.assertFalse(result["dated_next_step"])
        self.assertEqual(result["drill"]["dimension"], "decoded")
        self.assertTrue(result["signals_missed"][0]["move"])

    def test_bant_on_an_investor_costs_points_and_sets_the_drill(self):
        data = transcript("investor", "i1", [
            "What is your budget for seed deals?",
            "If a strong lead came in, would you consider following? What would you need to see for a strong yes?",
            "We are mid-process with several funds.",
        ])
        result = meeting.debrief(data, "en")
        self.assertIn("bant_on_investor", [item["guard"] for item in result["violations"]])
        self.assertEqual(result["drill"]["dimension"], "discipline")
        discipline = [item for item in result["breakdown"] if item["dimension"] == "discipline"][0]
        self.assertEqual(discipline["points"], 1.0)
        self.assertEqual(result["bench"]["person"], "dana")

    def test_slipping_into_hebrew_is_counted(self):
        data = transcript("sales", "p1", ["רגע, מה אמרת?", "Would Thursday at 10am work?"])
        self.assertEqual(meeting.debrief(data, "en")["hebrew_slips"], 1)

    def test_a_claimed_outcome_needs_evidence_in_the_transcript(self):
        """The model played the American; its say-so alone earns half."""
        outcome = lambda result: [item for item in result["breakdown"] if item["dimension"] == "outcome"][0]["points"]
        claimed = transcript("sales", "p1", ["Sounds great.", "Thanks so much."], "dated_step")
        self.assertEqual(outcome(meeting.debrief(claimed, "en")), 1.5)
        self.assertFalse(meeting.debrief(claimed, "en")["dated_next_step"])
        real = transcript("sales", "p1", ["Sounds great.", "Would Thursday at 10am work?"], "dated_step")
        self.assertEqual(outcome(meeting.debrief(real, "en")), 3.0)
        asked = transcript("sales", "p1", ["Sounds great.", "Would Thursday at 10am work?"], "vague")
        self.assertEqual(outcome(meeting.debrief(asked, "en")), 1.0)

    def test_a_clean_no_counts_as_much_as_a_dated_step(self):
        data = transcript("sales", "p1", [
            "It sounds like this may not be a priority right now, and that's completely fine. If it's a no, I'd appreciate you telling me.",
            "Understood, thanks for the straight answer.",
        ], "clean_no")
        result = meeting.debrief(data, "en")
        self.assertEqual([item for item in result["breakdown"] if item["dimension"] == "outcome"][0]["points"], 3.0)

    def test_lines_that_were_never_delivered_are_not_scored(self):
        receipt = Receipt("debrief")
        data = {"type": "sales", "seed": "p1", "turns": [
            {"who": "american", "text": "Hello there."},
            {"who": "founder", "text": "Would Thursday at 10am work for a follow-up?"},
        ], "outcome": {"result": "dated_step"}}
        result = meeting.debrief(data, "en", receipt)
        self.assertEqual(len(result["not_delivered"]), 2)
        self.assertIsNone([item for item in result["breakdown"] if item["dimension"] == "decoded"][0]["points"])
        self.assertIn("decoded", [item["check"] for item in receipt.skipped])
        # Rescaled over the 7 points that could be assessed: outcome 3 + discipline 2 + register 1 of 7.
        self.assertEqual(result["score"], 8.6)

    def test_scores_are_stable_and_bounded(self):
        for seed in range(25):
            for kind in meeting.TYPES:
                data = transcript(kind, seed, ["Sounds good.", "Listen, send me the contract.", "We're oversubscribed."])
                first, second = meeting.debrief(copy.deepcopy(data), "en"), meeting.debrief(copy.deepcopy(data), "en")
                self.assertEqual(first, second)
                self.assertTrue(1.0 <= first["score"] <= 10.0)

    def test_an_empty_founder_side_is_an_error(self):
        with self.assertRaises(PlaybookError):
            meeting.debrief({"type": "sales", "turns": [{"who": "american", "text": "Hello"}]}, "en")

    def test_brief_lists_score_missed_signals_israelisms_and_one_drill(self):
        data = transcript("sales", "p1", ["Listen, it's very simple.", "Send me your answer."], "vague")
        text = meeting.debrief_brief(meeting.debrief(data, "he"), "he")
        for needle in ("ציון כיול", "סיגנלים שפוספסו", "ישראליזמים", "תרגול אחד"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
