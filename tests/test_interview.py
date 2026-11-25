"""The question bank and the interview that walks a founder through it."""

import copy
import json
import re
import shlex
import unittest

import _util
from abp import cli, decode, interview, intro, mail, meeting
from abp.core import PlaybookError, Receipt, load

TODAY = "2026-11-24"
BANK = load("interview")
BY_ID = dict((question["id"], question) for question in BANK["questions"])


def plan(mode, answers=None, lang="en", **extra):
    data = {"mode": mode, "today": TODAY, "answers": answers or {}}
    data.update(extra)
    return interview.plan(data, lang)


def sample(question):
    """A valid answer for a question, by its kind."""
    kind = question["kind"]
    if kind == "text":
        return "Boston" if question["id"] == "their_city" else "a short answer"
    if kind == "choice":
        return question["choices"][0]
    if kind == "bool":
        return True
    if kind == "date":
        return "2026-12-08"
    if kind in ("int", "number"):
        return 1 if question["id"] != "meeting_minutes" else 30
    if kind == "quotes":
        return ["This is really interesting!"]
    if kind == "list":
        return [question["choices"][0]] if question.get("choices") else ["2 paid pilots with regional carriers"]
    if kind == "costs":
        return [{"currency": "calendar_time", "evidence": "a 45-minute call on 12 November"}]
    return [{"id": question["signals"][0], "evidence": "it happened on 12 November"}]


def answer_everything(mode, first=None):
    """Play a founder who answers every question the interview asks, at full depth."""
    answers = dict(first or {})
    turns = 0
    while True:
        result = plan(mode, answers, depth="deep")
        if not result["ask_next"]:
            return answers, result, turns
        for item in result["ask_next"]:
            answers[item["id"]] = sample(BY_ID[item["id"]])
        turns += 1
        assert turns < 60, "the interview does not end"


class BankTest(unittest.TestCase):
    def test_the_bank_has_no_gaps(self):
        self.assertEqual(interview.check_bank(), [])

    def test_the_banks_own_check_catches_a_question_that_could_never_be_asked(self):
        """A typo in a condition does not raise an error. It silently hides a question, so the bank checks itself."""
        by_id = dict(BY_ID)
        bad = lambda conditions: interview._bad_conditions("q", conditions, by_id)
        self.assertEqual(bad([{"q": "email_type", "is": "recap"}, {"q": "meeting_number", "min": 2}, {"q": "next_step_exists", "is": True}, {"q": "traction_truth", "answered": True}]), [])
        self.assertIn("can never be 'recapp'", bad([{"q": "email_type", "is": "recapp"}])[0])
        self.assertIn("can never be 'cold call'", bad([{"q": "email_type", "in": ["cold", "cold call"]}])[0])
        self.assertIn("is not a question", bad([{"q": "email_kind", "is": "cold"}])[0])
        self.assertIn("a minimum needs a number", bad([{"q": "email_type", "min": 2}])[0])
        self.assertIn("tests nothing", bad([{"q": "email_type"}])[0])
        self.assertIn("is yes or no", bad([{"q": "next_step_exists", "is": "yes"}])[0])
        # Every question of the bank can be reached by some set of answers in at least one of its modes.
        for question in BANK["questions"]:
            for condition in question.get("when", []):
                self.assertEqual(interview._bad_conditions(question["id"], [condition], by_id), [])

    def test_a_question_about_last_time_waits_for_a_second_meeting(self):
        first = plan("prep", {"context": "sales", "goal_currency": "calendar_time", "the_ask": "a pilot", "meeting_number": 1}, depth="deep")
        second = plan("prep", {"context": "sales", "goal_currency": "calendar_time", "the_ask": "a pilot", "meeting_number": 2}, depth="deep")
        self.assertNotIn("promised_last_time", first["waiting"] + [item["id"] for item in first["ask_next"]])
        self.assertIn("promised_last_time", second["waiting"] + [item["id"] for item in second["ask_next"]])

    def test_a_cold_email_is_not_asked_about_a_meeting_that_never_happened(self):
        def all_asked(kind):
            answers, asked = {"email_type": kind, "draft_exists": "from_scratch"}, []
            while True:
                result = plan("email", answers, depth="deep")
                if not result["ask_next"]:
                    return asked
                for item in result["ask_next"]:
                    asked.append(item["id"])
                    answers[item["id"]] = sample(BY_ID[item["id"]])
        cold, followup = all_asked("cold"), all_asked("followup")
        for name in ("meeting_date", "touches_done", "stage_now", "fresh_value", "agreed_items"):
            self.assertNotIn(name, cold, name)
        for name in ("meeting_date", "touches_done", "stage_now", "fresh_value"):
            self.assertIn(name, followup, name)
        for name in ("why_them_now", "company_one_liner", "proof_points", "the_one_ask"):
            self.assertIn(name, cold, name)

    def test_the_musts_are_exactly_these(self):
        """A must delays every founder, and a missing must lets an answer out early. Changing the list is a decision, so it is pinned."""
        musts = dict((mode, [question["id"] for question in BANK["questions"] if question["level"].get(mode) == 1]) for mode in interview.MODES)
        self.assertEqual(musts, {
            "email": ["email_type", "draft_exists", "their_city", "the_one_ask", "proof_points", "fresh_value", "their_last_message",
                      "agreed_items", "event_context", "update_lines", "thanks_for"],
            "decode": ["context", "quotes", "next_step_exists", "next_step_date", "next_step_proposed_by", "next_step_accepted", "cost_to_them"],
            "prep": ["context", "goal_currency", "the_ask"],
            "scene": ["context"],
            "intro": ["intro_stage", "forwardable_attached", "hours_since_intro", "replied", "hours_since_meeting", "loop_closed", "both_agreed"],
        })
        # Of those, only these are asked of everyone. The rest open on an answer.
        always = dict((mode, [question["id"] for question in BANK["questions"] if question["level"].get(mode) == 1 and (not question.get("when") or mode in question.get("when_not_in_modes", []))]) for mode in interview.MODES)
        self.assertEqual(always, {
            "email": ["email_type", "draft_exists", "their_city"],
            "decode": ["context", "quotes", "next_step_exists", "cost_to_them"],
            "prep": ["context", "goal_currency", "the_ask"],
            "scene": ["context"],
            "intro": ["intro_stage"],
        })

    def test_a_next_step_counts_only_with_its_date_its_owner_and_their_yes(self):
        """Each of the three is a must on its own. Leave any one out and no verdict runs."""
        full = {"context": "sales", "quotes": ["Sounds good."], "cost_to_them": [], "next_step_exists": True,
                "next_step_date": "2026-12-08", "next_step_proposed_by": "them", "next_step_accepted": True}
        self.assertEqual(plan("decode", full)["status"], "run_and_ask")
        for name in ("next_step_date", "next_step_proposed_by", "next_step_accepted"):
            partial = dict(full)
            del partial[name]
            for depth in interview.DEPTHS:
                result = plan("decode", partial, depth=depth)
                self.assertEqual(result["status"], "ask", "%s at %s" % (name, depth))
                self.assertEqual([item["id"] for item in result["open_musts"]], [name])
        # The same goes for an intro: each stage has the one fact its check cannot run without.
        for stage, needed in (("asking", ["forwardable_attached"]), ("received", ["hours_since_intro", "replied"]),
                              ("after_meeting", ["hours_since_meeting", "loop_closed"]), ("connecting", ["both_agreed"])):
            self.assertEqual([item["id"] for item in plan("intro", {"intro_stage": stage})["open_musts"]], needed, stage)

    def test_the_bank_is_broad(self):
        self.assertGreaterEqual(len(BANK["questions"]), 110)
        per_dimension = {}
        for question in BANK["questions"]:
            per_dimension[question["dimension"]] = per_dimension.get(question["dimension"], 0) + 1
        self.assertEqual(sorted(per_dimension), sorted(item["id"] for item in BANK["dimensions"]))
        for name, count in per_dimension.items():
            self.assertGreaterEqual(count, 5, name)
        for mode in interview.MODES:
            musts = [question for question in BANK["questions"] if question["level"].get(mode) == 1]
            self.assertGreaterEqual(len(musts), 1, mode)
        # Depth is where the breadth lives: the fast path stays short.
        for mode, most in (("decode", 7), ("prep", 3), ("scene", 1)):
            self.assertLessEqual(len([question for question in BANK["questions"] if question["level"].get(mode) == 1]), most, mode)

    def test_every_kind_of_email_in_the_guide_has_a_question_of_its_own(self):
        """A recap, an update, a thank-you and a conference follow-up each need a fact no other email needs."""
        own = {}
        for question in BANK["questions"]:
            for condition in question.get("when", []):
                if condition["q"] == "email_type":
                    for kind in [condition["is"]] if "is" in condition else condition["in"]:
                        own.setdefault(kind, []).append(question["id"])
        for kind, needs in (("recap", "agreed_items"), ("conference", "event_context"), ("investor_update", "update_lines"),
                            ("thank_you", "thanks_for"), ("followup", "fresh_value"), ("reply", "their_last_message"),
                            ("scheduling", "scheduling_link"), ("cold", "why_them_now"), ("linkedin", "why_them_now")):
            self.assertIn(needs, own.get(kind, []), kind)
        for kind in own:
            self.assertIn(kind, mail.types())

    def test_reasons_draw_on_every_module_of_the_guide(self):
        cited = set(question["guide_module"] for question in BANK["questions"] if "guide_module" in question)
        self.assertEqual(cited, set(range(1, 9)))

    def test_every_question_has_its_reason_in_both_languages(self):
        for question in BANK["questions"]:
            for field in ("ask", "why"):
                self.assertTrue(question[field]["en"].strip() and question[field]["he"].strip(), question["id"])
                self.assertTrue(any(0x05D0 <= ord(char) <= 0x05EA for char in question[field]["he"]), question["id"])
            self.assertTrue(question["ask"]["en"].rstrip().endswith(("?", ".")), question["id"])

    def test_choices_are_the_engines_own_lists(self):
        self.assertEqual(sorted(BY_ID["email_type"]["choices"]), mail.types())
        self.assertEqual(BY_ID["touches_done"]["choices"], list(decode.TOUCHES))
        self.assertEqual(BY_ID["intro_stage"]["choices"], list(intro.STAGES))
        self.assertEqual(BY_ID["context"]["choices"], list(decode.CONTEXTS))
        self.assertEqual(BY_ID["goal_currency"]["choices"], [item["id"] for item in load("decoder")["currencies"]])
        self.assertEqual(BY_ID["quotes_source"]["choices"], decode.SPEC["source"]["values"])
        self.assertEqual(BY_ID["next_step_proposed_by"]["choices"], decode.SPEC["next_step"]["props"]["proposed_by"]["values"])

    def test_every_argument_a_question_feeds_is_a_real_flag(self):
        parser = cli._parser()
        sub = [action for action in parser._actions if isinstance(getattr(action, "choices", None), dict)][0]
        for question in BANK["questions"]:
            for feed in question["feeds"]:
                flag = feed.get("arg") or feed.get("flag")
                if flag:
                    flags = [option for action in sub.choices[feed["command"]]._actions for option in action.option_strings]
                    self.assertIn(flag, flags, question["id"])
        for command, config in interview.ARGS.items():
            flags = [option for action in sub.choices[command]._actions for option in action.option_strings]
            for flag in config["needs"]:
                self.assertIn(flag, flags)

    def test_the_interview_probes_every_green_signal_of_the_traffic_light(self):
        """A founder forgets to mention exactly the facts that would make a lead Green."""
        for context in decode.CONTEXTS:
            probed = set()
            for question in BANK["questions"]:
                if context in question.get("contexts", []):
                    probed.update(question.get("signals", []))
            for signal in decode.signal_ids(context)["green"]:
                self.assertIn(signal, probed, "%s: no question asks about %s" % (context, signal))

    def test_the_interview_asks_for_bad_news_as_hard_as_for_good_news(self):
        """Every Yellow and Red signal is reachable: asked about by name, or raised by the decoder from what the interview collects."""
        named = re.findall(r'"([^"]+)"', BY_ID["deferral_lines"]["ask"]["en"])
        self.assertEqual(len(named), 4)
        for context in ("sales", "investor"):
            probed = set()
            for question in BANK["questions"]:
                if context in question.get("contexts", []):
                    probed.update(question.get("signals", []))
            answers = {"context": context, "quotes": ["This is amazing!"], "next_step_exists": False, "cost_to_them": [],
                       "deferral_lines": named, "touches_sent": 4, "their_questions": 0}
            verdict = decode.decode(plan("decode", answers)["handoff"][0]["sheet"], "en")
            raised = set(item["id"] for light in ("yellow", "red") for item in verdict["signals"][light])
            ids = decode.signal_ids(context)
            for signal in ids["yellow"] + ids["red"]:
                self.assertIn(signal, probed | raised, "%s: nothing in the interview can surface %s" % (context, signal))
            # The four lines the question names are lines the decoder knows.
            self.assertEqual(verdict["unmatched_quotes"], [], context)

    def test_the_musts_of_each_mode_cover_the_gate_of_its_command(self):
        """When the interview says the musts are in, the command it hands off to does not ask again."""
        fed = {}
        for question in BANK["questions"]:
            for feed in question["feeds"]:
                if "path" in feed:
                    fed.setdefault(feed["command"], set()).add((feed["path"].split(".")[0], min(question["level"].values())))
        for item in load("signals")["intake"]["questions"]:
            if item["required_for_verdict"]:
                self.assertIn((item["field"], 1), fed["decode"])
        for item in load("meetings")["prep_intake"]["questions"]:
            if item["required"]:
                self.assertIn((item["field"], 1), fed["prep"])
        self.assertIn(("stage", 1), fed["intro"])

    def test_lead_lists_name_real_questions_of_that_mode(self):
        for mode, names in BANK["lead"].items():
            if mode.startswith("_"):
                continue
            self.assertEqual(len(names), len(set(names)), mode)
            for name in names:
                self.assertIn(mode, BY_ID[name]["level"], "%s leads in %s but does not serve it" % (name, mode))


class FlowTest(unittest.TestCase):
    def test_an_empty_case_asks_three_musts_and_runs_nothing(self):
        result = plan("decode")
        self.assertEqual(result["status"], "ask")
        self.assertFalse(result["can_run"])
        self.assertEqual([item["id"] for item in result["ask_next"]], ["context", "quotes", "next_step_exists"])
        self.assertTrue(all(item["level"] == 1 for item in result["ask_next"]))
        self.assertEqual(result["handoff"][0]["blocked_by"], ["context", "quotes", "next_step", "cost_to_them"])
        self.assertEqual(result["picture"]["known"], 0)

    def test_the_questions_still_waiting_are_named_so_nothing_already_said_is_asked_again(self):
        result = plan("decode", {"context": "sales", "quotes": ["This is amazing!"], "next_step_exists": False, "cost_to_them": []})
        asked = [item["id"] for item in result["ask_next"]]
        self.assertEqual(len(result["waiting"]), result["remaining"]["at_this_depth"])
        self.assertFalse(set(asked) & set(result["waiting"]))
        self.assertIn("their_city", result["waiting"])
        brief = interview.plan_brief(result, "en")
        self.assertIn("If the founder already answered one, record it now and do not ask it: ", brief)
        self.assertIn(", ".join(result["waiting"]), brief)
        # Recording one of them takes it off the list without it ever being asked.
        again = plan("decode", {"context": "sales", "quotes": ["This is amazing!"], "next_step_exists": False, "cost_to_them": [], "their_city": "Boston"})
        self.assertNotIn("their_city", again["waiting"] + [item["id"] for item in again["ask_next"]])
        self.assertEqual(plan("decode", {"context": "sales"}, stop=True)["waiting"], [])

    def test_never_more_than_three_questions_a_turn_in_any_mode_or_depth(self):
        self.assertEqual(BANK["max_questions_per_turn"], 3)
        for mode in interview.MODES:
            for depth in interview.DEPTHS:
                self.assertLessEqual(len(plan(mode, depth=depth)["ask_next"]), 3)

    def test_musts_come_before_refinements_and_refinements_before_depth(self):
        for mode in interview.MODES:
            answers, seen = {}, []
            while True:
                result = plan(mode, answers, depth="deep")
                if not result["ask_next"]:
                    break
                for item in result["ask_next"]:
                    seen.append(item["id"])
                    answers[item["id"]] = sample(BY_ID[item["id"]])
                levels = [item["level"] for item in result["ask_next"]]
                self.assertEqual(levels, sorted(levels), "%s: within a turn, a must is never asked after a refinement" % mode)
                # While a must is open the turn starts with it, and nothing is declared runnable.
                self.assertEqual(result["status"] == "ask", levels[0] == 1, mode)
            self.assertTrue(seen)

    def test_once_the_musts_are_in_the_command_can_run_while_the_interview_goes_on(self):
        musts = {"context": "sales", "quotes": ["This is amazing! Let's keep in touch."], "next_step_exists": False, "cost_to_them": []}
        result = plan("decode", musts)
        self.assertEqual(result["status"], "run_and_ask")
        self.assertTrue(result["can_run"])
        self.assertEqual(len(result["ask_next"]), 3)
        self.assertTrue(all(item["level"] == 2 for item in result["ask_next"]))
        verdict = decode.decode(result["handoff"][0]["sheet"], "en")
        self.assertEqual(verdict["status"], "verdict")
        self.assertEqual((verdict["verdict"]["light"], verdict["verdict"]["lean"]), ("yellow", "red"))

    def test_the_questions_that_move_the_verdict_lead_the_second_round(self):
        musts = {"context": "sales", "quotes": ["This is amazing!"], "next_step_exists": False, "cost_to_them": []}
        self.assertEqual([item["id"] for item in plan("decode", musts)["ask_next"]], ["their_questions", "deferral_lines", "after_purchase"])
        musts["context"] = "investor"
        self.assertEqual([item["id"] for item in plan("decode", musts)["ask_next"]], ["their_questions", "deferral_lines", "diligence_asks"])

    def test_an_email_is_asked_only_what_its_kind_needs(self):
        def scratch(kind):
            result = plan("email", {"email_type": kind, "draft_exists": "from_scratch"}, depth="quick")
            return [item["id"] for item in result["open_musts"]]
        self.assertEqual(scratch("breakup"), ["their_city"])
        self.assertEqual(scratch("scheduling"), ["their_city"])
        self.assertEqual(scratch("recap"), ["agreed_items", "their_city"])
        self.assertEqual(scratch("cold"), ["the_one_ask", "proof_points", "their_city"])
        self.assertEqual(scratch("followup"), ["the_one_ask", "fresh_value", "their_city"])
        self.assertEqual(scratch("reply"), ["the_one_ask", "their_last_message", "their_city"])
        self.assertEqual(scratch("conference"), ["the_one_ask", "event_context", "proof_points", "their_city"])
        self.assertEqual(scratch("investor_update"), ["update_lines", "their_city"])
        self.assertEqual(scratch("thank_you"), ["thanks_for", "their_city"])
        # The first round never waits for the kind: it asks for it.
        self.assertEqual([item["id"] for item in plan("email")["ask_next"]], ["email_type", "draft_exists", "their_city"])

    def test_a_draft_answers_for_the_ask_and_the_proof(self):
        """A founder who pasted a draft gets the rewrite. The questions the draft already answers come after, not before."""
        for kind, own in (("cold", ["the_one_ask", "proof_points"]), ("recap", ["agreed_items"]), ("followup", ["the_one_ask", "fresh_value"]),
                          ("reply", ["the_one_ask", "their_last_message"]), ("thank_you", ["thanks_for"]), ("investor_update", ["update_lines"])):
            scratch = plan("email", {"email_type": kind, "draft_exists": "from_scratch", "their_city": "Boston"})
            self.assertEqual(scratch["status"], "ask", kind)
            self.assertEqual([item["id"] for item in scratch["open_musts"]], own, kind)
            draft = plan("email", {"email_type": kind, "draft_exists": "have_draft"})
            self.assertEqual(draft["status"], "run_and_ask", kind)
            self.assertEqual(draft["open_musts"], [], kind)
            self.assertIn("their_city", [item["id"] for item in draft["ask_next"]] + draft["waiting"], "the send time still needs the place, after the rewrite")
            asked = dict((item["id"], item["level"]) for item in plan("email", {"email_type": kind, "draft_exists": "have_draft", "their_city": "Boston"}, depth="deep")["ask_next"])
            later = [question["id"] for question in BANK["questions"] if "eases" in question]
            self.assertEqual(sorted(later), sorted(["their_city", "the_one_ask", "proof_points", "fresh_value", "their_last_message", "agreed_items", "event_context", "update_lines", "thanks_for"]))
            for name in own:
                self.assertEqual(asked.get(name, 2), 2, "%s: %s is still asked, as a refinement" % (kind, name))
        self.assertEqual(interview.level_of(BY_ID["the_one_ask"], "email", {"draft_exists": "have_draft"}), 2)
        self.assertEqual(interview.level_of(BY_ID["the_one_ask"], "email", {"draft_exists": "from_scratch"}), 1)
        self.assertEqual(interview.level_of(BY_ID["proof_points"], "prep", {"draft_exists": "have_draft"}), 2)

    def test_a_follow_up_question_opens_only_when_its_answer_calls_for_it(self):
        base = {"context": "sales", "quotes": ["Great stuff."], "cost_to_them": []}
        without = plan("decode", dict(base, next_step_exists=False), depth="deep")
        with_step = plan("decode", dict(base, next_step_exists=True), depth="deep")
        opened = set(item["id"] for item in with_step["ask_next"]) - set(item["id"] for item in without["ask_next"])
        self.assertEqual(opened, {"next_step_date", "next_step_proposed_by", "next_step_accepted"})
        self.assertEqual(with_step["status"], "ask", "a step without a date and an owner is still a must")
        self.assertFalse(any(item["id"] == "fresh_value" for item in plan("email", {"email_type": "cold"})["ask_next"]))
        self.assertIn("fresh_value", [item["id"] for item in plan("email", {"email_type": "followup"})["ask_next"]])

    def test_context_questions_stay_with_their_context(self):
        for context, own in (("sales", "after_purchase"), ("investor", "diligence_asks"), ("kol", "real_feedback")):
            answers, _result, _turns = answer_everything("decode", {"context": context})
            self.assertIn(own, answers)
            for other in ("after_purchase", "diligence_asks", "real_feedback"):
                if other != own:
                    self.assertNotIn(other, answers, "%s was asked in a %s case" % (other, context))

    def test_same_case_same_questions(self):
        answers = {"context": "investor", "quotes": ["It's a bit early for us. Keep us posted!"]}
        self.assertEqual(plan("decode", answers), plan("decode", copy.deepcopy(answers)))

    def test_depth_decides_how_far_the_interview_goes(self):
        counts = {}
        for depth in interview.DEPTHS:
            answers = {"context": "sales"}
            turns = 0
            while True:
                result = plan("prep", answers, depth=depth)
                if not result["ask_next"]:
                    break
                for item in result["ask_next"]:
                    answers[item["id"]] = sample(BY_ID[item["id"]])
                turns += 1
            counts[depth] = len(answers)
            self.assertEqual(result["status"], "ready")
        self.assertLess(counts["quick"], counts["standard"])
        self.assertLess(counts["standard"], counts["deep"])
        self.assertEqual(counts["quick"], 3)

    def test_the_founder_can_stop_and_the_gaps_are_named(self):
        receipt = Receipt("interview")
        result = interview.plan({"mode": "decode", "answers": {"context": "sales", "quotes": ["Love it!"]}, "stop": True}, "en", receipt)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["ask_next"], [])
        self.assertFalse(result["can_run"])
        self.assertEqual([item["id"] for item in result["open_musts"]], ["next_step_exists", "cost_to_them"])
        skipped = [item["check"] for item in receipt.as_dict()["checks_skipped"]]
        self.assertEqual(skipped, ["decode", "interview_complete"])
        brief = interview.plan_brief(result, "en")
        self.assertIn("Stopped by the founder", brief)
        self.assertIn("It gives no verdict without: next_step, cost_to_them", brief)

    def test_a_founder_who_stops_early_still_gets_the_lines_decoded(self):
        """Stopping is the founder's right. What can honestly be said with half a picture is still said."""
        result = plan("decode", {"context": "investor", "quotes": ["It's a bit early for us. Keep us posted!"], "next_step_exists": False}, stop=True)
        first = result["handoff"][0]
        self.assertTrue(first["partial"])
        self.assertEqual(first["blocked_by"], ["cost_to_them"])
        self.assertFalse(result["can_run"])
        brief = interview.plan_brief(result, "en")
        self.assertIn("Run this for the decoding of their lines. It gives no verdict without: cost_to_them:", brief)
        self.assertIn("playbook.py decode --lang en --in - <<'JSON'", brief)
        out = decode.decode(first["sheet"], "en")
        self.assertEqual(out["status"], "needs_intake")
        self.assertIsNone(out["verdict"])
        self.assertTrue(out["decoded"], "the lines are decoded even though no verdict is given")
        # Without their words, or without knowing who they are, there is nothing to decode.
        for answers in ({"context": "sales"}, {"quotes": ["Love it!"]}):
            self.assertNotIn("partial", plan("decode", answers, stop=True)["handoff"][0])
        # While the interview is still going, nothing runs on half a picture.
        self.assertNotIn("partial", plan("decode", {"context": "sales", "quotes": ["Love it!"]})["handoff"][0])
        self.assertNotIn("playbook.py decode", interview.plan_brief(plan("decode", {"context": "sales", "quotes": ["Love it!"]}), "en"))

    def test_a_skipped_question_is_not_asked_again_and_is_shown_as_skipped(self):
        result = plan("decode", {"context": "sales"}, skipped=["quotes"])
        self.assertNotIn("quotes", [item["id"] for item in result["ask_next"]])
        said = [item for item in result["picture"]["dimensions"] if item["id"] == "said"][0]
        self.assertEqual(said["skipped"], ["quotes"])
        self.assertIn("quotes", result["handoff"][0]["blocked_by"])

    def test_none_is_an_answer(self):
        result = plan("decode", {"context": "sales", "quotes": ["Love it!"], "next_step_exists": True, "next_step_date": None, "next_step_proposed_by": "founder", "next_step_accepted": False, "cost_to_them": None})
        self.assertEqual(result["status"], "run_and_ask")
        sheet = result["handoff"][0]["sheet"]
        self.assertEqual(sheet["cost_to_them"], [])
        self.assertNotIn("date", sheet["next_step"])
        self.assertEqual(decode.decode(sheet, "en")["status"], "verdict")
        # It cost them nothing: an answer. They said nothing: not an answer, there is nothing to decode.
        wordless = plan("decode", {"context": "sales", "quotes": None, "next_step_exists": False, "cost_to_them": None})
        self.assertEqual(wordless["handoff"][0]["blocked_by"], ["quotes"])
        self.assertFalse(wordless["can_run"])


class PictureTest(unittest.TestCase):
    def test_the_picture_counts_what_is_known_by_dimension(self):
        result = plan("decode", {"context": "sales", "quotes": ["Love it!"]})
        picture = result["picture"]
        self.assertEqual(picture["known"], 2)
        self.assertEqual(sum(item["known"] for item in picture["dimensions"]), 2)
        self.assertEqual(sum(item["of"] for item in picture["dimensions"]), picture["of"])
        self.assertTrue(0 < picture["completeness"] < 1)
        missing = [name for item in picture["dimensions"] for name in item["missing_musts"]]
        self.assertEqual(sorted(missing), ["cost_to_them", "next_step_exists"])

    def test_musts_weigh_more_than_depth(self):
        weights = BANK["weights"]
        self.assertGreater(weights["1"], weights["2"])
        self.assertGreater(weights["2"], weights["3"])
        only_must = plan("prep", {"context": "sales"}, depth="deep")["picture"]["completeness"]
        only_depth = plan("prep", {"competitor": "Acme"}, depth="deep")["picture"]["completeness"]
        self.assertGreater(only_must, only_depth)

    def test_a_full_interview_ends_complete_in_every_mode(self):
        for mode in interview.MODES:
            _answers, result, turns = answer_everything(mode, {"context": "sales"} if mode != "intro" else None)
            self.assertEqual(result["status"], "ready", mode)
            self.assertEqual(result["picture"]["completeness"], 1.0, mode)
            self.assertEqual(result["picture"]["known"], result["picture"]["of"], mode)
            self.assertGreaterEqual(turns, 2, mode)

    def test_the_guides_cautions_fire_on_the_answers_that_call_for_them(self):
        fired = lambda mode, answers: [item["id"] for item in plan(mode, answers)["cautions"]]
        self.assertEqual(fired("email", {"attachment": "deck"}), ["deck_in_first_email"])
        self.assertEqual(fired("email", {"attachment": "one_pager"}), [])
        self.assertEqual(fired("decode", {"how_met": "warm_intro"}), ["warm_intro_protocol"])
        self.assertEqual(fired("decode", {"politics_came_up": "yes_took_a_side"}), ["took_a_political_side"])
        self.assertEqual(fired("decode", {"politics_came_up": "yes_stayed_out"}), [])
        one_sided = {"next_step_exists": True, "next_step_proposed_by": "founder", "next_step_accepted": False}
        self.assertEqual(fired("decode", one_sided), ["one_sided_date"])
        self.assertEqual(fired("decode", dict(one_sided, next_step_accepted=True)), [])
        self.assertEqual(fired("email", {"urgency": "must_go_today", "email_type": "recap"}), [], "a recap never waits")
        self.assertEqual(fired("email", {"urgency": "must_go_today", "email_type": "cold"}), ["outside_the_window"])
        self.assertEqual(fired("intro", {"intro_stage": "asking", "connector_strength": "loose_contact"}), ["loose_connector"])
        self.assertEqual(fired("intro", {"intro_stage": "asking", "connector_strength": "worked_together"}), [])
        self.assertEqual(fired("decode", {"context": "sales", "who_talked": "mostly_me"}), ["talked_the_whole_time"])
        self.assertEqual(fired("decode", {"context": "sales", "who_talked": "even"}), [])


class HandoffTest(unittest.TestCase):
    def test_a_full_interview_gives_every_command_a_sheet_it_accepts(self):
        for context in decode.CONTEXTS:
            answers, result, _turns = answer_everything("decode", {"context": context})
            out = decode.decode(result["handoff"][0]["sheet"], "en")
            self.assertEqual(out["status"], "verdict", context)
            given = [item["id"] for item in result["handoff"][0]["sheet"].get("signals", [])]
            self.assertTrue(given, "%s: the probes must reach the fact sheet" % context)
            self.assertTrue(set(given) <= set(item for group in decode.signal_ids(context).values() for item in group))

            answers, result, _turns = answer_everything("prep", {"context": context})
            sheet = meeting.prep(result["handoff"][0]["sheet"], "en")
            self.assertEqual(sheet["status"], "ready", context)
            self.assertEqual(result["handoff"][1]["argv"], ["guard", "--lang", "en", "--audience", context, "--file", "talk.txt"])
        for stage in intro.STAGES:
            _answers, result, _turns = answer_everything("intro", {"intro_stage": stage})
            intro.intro(result["handoff"][0]["sheet"], "en")

    def test_the_email_handoff_names_the_type_the_zone_and_the_cadence(self):
        answers = {
            "email_type": "followup", "their_city": "Chicago", "meeting_date": "2026-11-17", "touches_done": ["recap", "value"],
            "proof_points": ["2 paid pilots", "triage time down 31%"],
        }
        handoff = dict((item["command"], item) for item in plan("email", answers, lang="he")["handoff"])
        self.assertEqual(handoff["lint"]["argv"], ["lint", "--type", "followup", "--file", "rewrite.txt", "--source", "source.txt"])
        self.assertEqual(handoff["lint"]["source_lines"], ["2 paid pilots", "triage time down 31%"])
        self.assertEqual(handoff["send-time"]["argv"], ["send-time", "--tz", "Chicago"])
        self.assertEqual(handoff["cadence"]["argv"], ["cadence", "--tz", "Chicago", "--meeting-date", "2026-11-17", "--sent", "recap,value", "--today", TODAY])
        for item in handoff.values():
            self.assertEqual(item["blocked_by"], [])
            code, _out, err = _util.run([part for part in item["argv"] if part not in ("--file", "rewrite.txt", "--source", "source.txt")] if item["command"] != "lint" else ["lint", "--type", "followup", "--file", "-"], stdin="Hi Michael,\n\nWould Tuesday work?\n")
            self.assertIn(code, (0, 1), err)
        # No date given for today: the cadence is still offered, and says on its own which day it assumed.
        undated = interview.plan({"mode": "email", "answers": answers}, "he")["handoff"]
        self.assertNotIn("--today", [item for item in undated if item["command"] == "cadence"][0]["argv"])

    def test_a_draft_is_measured_first_and_is_part_of_the_source(self):
        with_draft = plan("email", {"email_type": "cold", "draft_exists": "have_draft", "their_city": "Boston"}, lang="he")
        lints = [item for item in with_draft["handoff"] if item["command"] == "lint"]
        self.assertEqual([item["argv"] for item in lints], [
            ["lint", "--type", "cold", "--file", "draft.txt"],
            ["lint", "--type", "cold", "--file", "rewrite.txt", "--source", "source.txt"],
        ])
        self.assertEqual([item["after"] for item in lints], ["draft", "rewrite"])
        brief = interview.plan_brief(plan("email", {"email_type": "cold", "draft_exists": "have_draft", "their_city": "Boston"}), "en")
        measure = brief.index("Save the founder's draft as draft.txt and measure it before you rewrite:")
        check = brief.index("After you write the email, save it as rewrite.txt and check it:")
        self.assertLess(measure, check)
        self.assertIn("source.txt is the founder's own material: here, a copy of the draft.", brief)
        both = interview.plan_brief(plan("email", {"email_type": "cold", "draft_exists": "have_draft", "their_city": "Boston", "proof_points": ["2 paid pilots"]}), "en")
        self.assertIn("source.txt is the founder's own material: the draft, followed by these lines.", both)
        self.assertIn("  2 paid pilots", both)
        scratch = plan("email", {"email_type": "breakup", "draft_exists": "from_scratch", "their_city": "Boston"}, lang="he")
        lints = [item for item in scratch["handoff"] if item["command"] == "lint"]
        self.assertEqual([item["argv"] for item in lints], [["lint", "--type", "breakup", "--file", "rewrite.txt"]], "nothing to compare figures with, so no source is named")

    def test_a_command_without_its_facts_is_not_offered(self):
        handoff = dict((item["command"], item) for item in plan("email", {"email_type": "cold"})["handoff"])
        self.assertEqual(handoff["send-time"]["blocked_by"], ["--tz"])
        self.assertEqual(handoff["cadence"]["blocked_by"], ["--meeting-date"])
        brief = interview.plan_brief(plan("email", {"email_type": "cold", "draft_exists": "have_draft", "the_one_ask": "a call", "proof_points": [], "their_city": "Boston"}), "en")
        self.assertIn("send-time --lang en --tz Boston", brief)
        self.assertNotIn("playbook.py cadence", brief)

    def test_a_command_that_does_not_belong_to_the_case_is_not_announced_as_missing(self):
        """A cold email has no meeting, so no cadence. Saying "not enough yet for cadence" would send the model asking for one."""
        cold = plan("email", {"email_type": "cold", "draft_exists": "have_draft"})
        self.assertEqual(cold["status"], "run_and_ask")
        by_command = dict((item["command"], item) for item in cold["handoff"])
        self.assertTrue(by_command["cadence"]["out_of_scope"])
        self.assertNotIn("out_of_scope", by_command["send-time"], "the place is still asked, so the send time is only not yet")
        brief = interview.plan_brief(cold, "en")
        self.assertNotIn("cadence", brief)
        self.assertIn("not enough yet for send-time: --tz", brief)
        followup = plan("email", {"email_type": "followup", "draft_exists": "from_scratch", "the_one_ask": "a call", "fresh_value": "a new customer", "their_city": "Boston"})
        self.assertNotIn("out_of_scope", dict((item["command"], item) for item in followup["handoff"])["cadence"])
        self.assertIn("not enough yet for cadence: --meeting-date", interview.plan_brief(followup, "en"))

    def test_a_scene_takes_its_region_from_the_city_and_politics_from_the_focus(self):
        argv = plan("scene", {"context": "investor", "their_city": "San Francisco", "practice_focus": "politics"}, lang="he")["handoff"][0]["argv"]
        self.assertEqual(argv, ["scene", "--type", "investor", "--region", "west_coast", "--politics"])
        argv = plan("scene", {"context": "sales", "their_city": "Nowhere Special", "practice_focus": "soft_nos"}, lang="he")["handoff"][0]["argv"]
        self.assertEqual(argv, ["scene", "--type", "sales"])

    def test_the_printed_lines_carry_the_founders_language(self):
        """The lines are run as printed. A founder who writes English must not get the next answer in Hebrew."""
        answers = {"context": "sales", "quotes": ["Let's keep in touch."], "next_step_exists": False, "cost_to_them": []}
        english, hebrew = plan("decode", answers, lang="en"), plan("decode", answers, lang="he")
        self.assertEqual(english["handoff"][0]["argv"], ["decode", "--lang", "en", "--in", "-"])
        self.assertEqual(hebrew["handoff"][0]["argv"], ["decode", "--in", "-"])
        self.assertIn("playbook.py decode --lang en --in - <<'JSON'", interview.plan_brief(english, "en"))
        self.assertIn("playbook.py decode --in - <<'JSON'", interview.plan_brief(hebrew, "he"))
        for mode in interview.MODES:
            for item in plan(mode, lang="en")["handoff"]:
                self.assertEqual(item["argv"][:3], [item["command"], "--lang", "en"], mode)
        code, out, err = _util.run(english["handoff"][0]["argv"], stdin=json.dumps(english["handoff"][0]["sheet"]))
        self.assertEqual(code, 0, err)
        self.assertIn("Verdict:", out)

    def test_a_hostile_answer_stays_one_shell_word(self):
        """The printed command is pasted into a shell. Nothing a founder says may become a second command."""
        for city in ("New York", "Boston; rm -rf ~", "$(whoami)", "it's `here`", "a\nb && c"):
            result = plan("email", {"email_type": "cold", "their_city": city}, lang="he")
            brief = interview.plan_brief(dict(result, status="ready"), "en")
            line = [row for row in brief.split("\n") if "send-time" in row][0]
            one_line = " ".join(city.split())
            self.assertEqual(shlex.split(line)[-2:], ["--tz", one_line])
            argv = [item for item in result["handoff"] if item["command"] == "send-time"][0]["argv"]
            self.assertEqual(argv, ["send-time", "--tz", one_line])
        self.assertEqual(interview._word("Chicago"), "Chicago")
        self.assertEqual(shlex.split(interview._word("it's; here")), ["it's; here"])

    def test_a_fact_sheet_is_printed_on_one_line_so_the_heredoc_cannot_be_closed_early(self):
        result = plan("decode", {"context": "sales", "quotes": ["line one\nJSON\nrm -rf ~"], "next_step_exists": False, "cost_to_them": []})
        lines = interview.plan_brief(result, "en").split("\n")
        opening = [index for index, line in enumerate(lines) if line.endswith("<<'JSON'")][0]
        self.assertEqual(lines[opening + 2], "JSON")
        self.assertEqual(lines.count("JSON"), 1)

    def test_what_the_founder_says_is_the_source_the_figures_are_checked_against(self):
        answers = {
            "email_type": "followup", "their_city": "Boston", "draft_exists": "from_scratch",
            "the_one_ask": "a 20-minute call next week",
            "fresh_value": "Triage time is down 31% at Lakeside Mutual.\nWe signed a second carrier.",
        }
        lint = dict((item["command"], item) for item in plan("email", answers, lang="he")["handoff"])["lint"]
        self.assertEqual(lint["argv"], ["lint", "--type", "followup", "--file", "rewrite.txt", "--source", "source.txt"])
        self.assertEqual(lint["source_lines"], ["a 20-minute call next week", "Triage time is down 31% at Lakeside Mutual.", "We signed a second carrier."])
        source = "\n".join(lint["source_lines"])
        honest = "Hi Michael,\n\nTriage time is now down 31% at Lakeside Mutual. Would a 20-minute call next week work? No worries if not.\n\nBest,\nDana\n"
        inflated = honest.replace("31%", "45%")
        flagged = lambda text: [item["check"] for item in mail.lint(text, "followup", source, "en")["errors"]]
        self.assertNotIn("unverified_number", flagged(honest))
        self.assertIn("unverified_number", flagged(inflated))
        brief = interview.plan_brief(plan("email", answers), "en")
        self.assertIn("source.txt is the founder's own material. Save these lines as source.txt.", brief)
        self.assertIn("  Triage time is down 31% at Lakeside Mutual.", brief)

    def test_a_line_given_twice_is_one_line_and_the_answers_stay_as_given(self):
        answers = {"context": "sales", "quotes": ["This is amazing!"], "next_step_exists": False, "cost_to_them": [],
                   "deferral_lines": ["Keep us posted!", "This is amazing!"], "pushback": ["Keep us posted!", "Have you considered a pilot?"]}
        before = copy.deepcopy(answers)
        result = plan("decode", answers)
        self.assertEqual(result["handoff"][0]["sheet"]["quotes"], ["This is amazing!", "Keep us posted!", "Have you considered a pilot?"])
        self.assertEqual(answers, before)
        self.assertEqual(result["answers"]["quotes"], ["This is amazing!"])

    def test_a_pasted_talk_track_is_handed_to_the_guard(self):
        talk = "Thanks for making the time.\nWhat is your budget for this year?\nWho signs off on a deal like this?"
        result = plan("prep", {"context": "investor", "goal_currency": "calendar_time", "the_ask": "a partner meeting", "talk_track": talk})
        guard = dict((item["command"], item) for item in result["handoff"])["guard"]
        self.assertEqual(guard["talk_lines"], talk.split("\n"))
        brief = interview.plan_brief(result, "en")
        self.assertIn("Save the founder's text below as talk.txt, then run:", brief)
        self.assertIn("talk.txt:\n  Thanks for making the time.", brief)
        report = meeting.guard("\n".join(guard["talk_lines"]), "investor", "en")
        self.assertTrue(report["violations"], "BANT aimed at an investor is what the guard is for")
        without = plan("prep", {"context": "investor", "goal_currency": "calendar_time", "the_ask": "a partner meeting"})
        self.assertNotIn("talk_lines", dict((item["command"], item) for item in without["handoff"])["guard"])
        self.assertIn("When the founder has a talk track", interview.plan_brief(without, "en"))

    def test_what_code_does_not_judge_is_handed_to_the_model_as_context(self):
        result = plan("decode", {"context": "sales", "their_role": "VP Operations", "how_it_ended": "He said he would think about it."})
        notes = dict((item["id"], item["value"]) for item in result["context_notes"])
        self.assertEqual(notes, {"their_role": "VP Operations", "how_it_ended": "He said he would think about it."})
        self.assertNotIn("context", notes, "a fact that reached the fact sheet is not repeated as a note")


class InputTest(unittest.TestCase):
    def test_an_unknown_question_id_is_an_error_with_a_suggestion(self):
        with self.assertRaises(PlaybookError) as caught:
            plan("decode", {"qoutes": ["x"]})
        self.assertIn("Did you mean 'quotes'?", caught.exception.hint)
        with self.assertRaises(PlaybookError):
            plan("decode", {}, skipped=["no_such_question"])

    def test_an_answer_of_the_wrong_shape_is_an_error(self):
        bad = [
            {"next_step_exists": "yes"}, {"context": "retail"}, {"quotes": "one line"}, {"their_questions": -1},
            {"cost_to_them": [{"currency": "goodwill", "evidence": "x"}]}, {"cost_to_them": [{"currency": "money"}]},
            {"after_purchase": [{"id": "ghosting", "evidence": "x"}]}, {"meeting_date": "17/11/2026"}, {"touches_done": ["letter"]},
        ]
        for answers in bad:
            with self.assertRaises(PlaybookError, msg=str(answers)):
                plan("decode", answers)

    def test_mode_is_required_and_has_everyday_names(self):
        with self.assertRaises(PlaybookError):
            interview.plan({"answers": {}}, "en")
        self.assertEqual(interview.plan({"mode": "meeting"}, "en")["mode"], "decode")
        self.assertEqual(interview.plan({"mode": "simulation"}, "en")["mode"], "scene")

    def test_the_command_line(self):
        code, payload = _util.run_json(["interview", "--in", "-"], '{"mode": "decode", "answers": {"context": "sales"}}')
        self.assertEqual(code, 0)
        self.assertEqual(payload["result"]["status"], "ask")
        self.assertIn("question_bank", payload["receipt"]["checks_run"])
        code, out, _err = _util.run(["interview", "--in", "-"], '{"mode": "decode"}')
        self.assertIn("מה הם אמרו", out)
        self.assertIn("[נבדק בקוד", out.strip().split("\n")[-1])
        code, out, _err = _util.run(["schema", "interview"])
        for question in BANK["questions"]:
            self.assertIn("  %s (" % question["id"], out)
        code, payload = _util.run_json(["interview", "--in", "-"], '{"mode": "decode", "answers": {"qoutes": []}}')
        self.assertEqual((code, payload["error"]), (2, "unknown_question"))

    def test_the_example_in_the_schema_runs(self):
        result = interview.plan(copy.deepcopy(interview.EXAMPLE), "en")
        self.assertEqual(result["status"], "ask")
        self.assertEqual(result["ask_next"][0]["id"], "cost_to_them")
        self.assertEqual([item["level"] for item in result["ask_next"]], [1, 2, 2], "one must is left, so the turn is filled with refinements")


if __name__ == "__main__":
    unittest.main()
