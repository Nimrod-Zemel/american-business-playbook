"""The meeting decoder: intake gate, phrase tables, the traffic-light verdict, the next move."""

import copy
import json
import unittest

import _util  # noqa: F401
from abp import decode
from abp.core import PlaybookError, Receipt

TODAY = "2026-11-24"
BASE = {
    "context": "sales",
    "today": TODAY,
    "meeting_date": "2026-11-17",
    "quotes": ["Thanks for the walkthrough."],
    "next_step": {"exists": False},
    "cost_to_them": [],
}


def sheet(**changes):
    out = copy.deepcopy(BASE)
    for key, value in changes.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def run(data, **kwargs):
    return decode.decode(data, "en", **kwargs)


def light(data, **kwargs):
    result = run(data, **kwargs)
    return result["verdict"]["light"], result["verdict"]["lean"]


class IntakeGateTest(unittest.TestCase):
    """Socratic before solutions: no verbatim words, no verdict."""

    def test_nothing_known_returns_three_questions_and_no_verdict(self):
        result = run({"context": "sales", "today": TODAY})
        self.assertEqual(result["status"], "needs_intake")
        self.assertIsNone(result["verdict"])
        self.assertEqual([q["field"] for q in result["ask_next"]], ["quotes", "next_step", "cost_to_them"])

    def test_never_more_than_three_questions_per_turn(self):
        for data in ({"context": "sales"}, {"context": "investor", "source": "transcript"}, {"context": "kol"}):
            self.assertLessEqual(len(run(data)["ask_next"]), 3)

    def test_each_missing_fact_blocks_the_verdict(self):
        for field in ("quotes", "next_step", "cost_to_them"):
            result = run(sheet(**{field: None}))
            self.assertEqual(result["status"], "needs_intake", field)
            self.assertEqual(result["ask_next"][0]["field"], field)

    def test_an_empty_cost_list_is_an_answer(self):
        self.assertEqual(run(sheet())["status"], "verdict")

    def test_voice_note_is_offered_only_for_the_long_question(self):
        asked = run({"context": "sales"})["ask_next"]
        self.assertEqual([("invite" in q) for q in asked], [True, False, False])

    def test_quotes_that_are_known_are_still_decoded_during_intake(self):
        result = run({"context": "sales", "quotes": ["Send me a deck and I'll take a look."]})
        self.assertEqual(result["status"], "needs_intake")
        self.assertEqual(result["decoded"][0]["row"], "send_deck")

    def test_a_buyers_question_is_not_asked_about_an_investor_or_an_expert(self):
        """Price, security and integration are what a customer asks. The fallback intake words it per context."""
        known = {"quotes": ["It's a bit early for us."], "next_step": {"exists": False}}
        asked = lambda context, lang="en": [item["question"] for item in decode.decode(dict(known, context=context), lang)["ask_next"] if item["field"] == "their_questions"][0]
        self.assertIn("price, security, or integration", asked("sales"))
        self.assertIn("a data room, references, cohort data", asked("investor"))
        self.assertNotIn("price", asked("investor"))
        self.assertNotIn("price", asked("kol"))
        self.assertIn("דאטה רום", asked("investor", "he"))

    def test_the_skipped_verdict_is_on_the_receipt(self):
        receipt = Receipt("decode")
        decode.decode({"context": "sales"}, "en", receipt)
        self.assertEqual(receipt.skipped[0]["check"], "verdict")

    def test_force_gives_a_provisional_verdict_on_a_paraphrase(self):
        result = run(sheet(quotes=None), force=True)
        self.assertEqual(result["status"], "provisional")
        self.assertIsNotNone(result["verdict"])
        self.assertIn("PROVISIONAL", decode.brief(result, "en"))

    def test_transcript_adds_one_clarifier_and_does_not_block(self):
        result = run(sheet(source="transcript"))
        self.assertEqual(result["status"], "verdict")
        self.assertEqual([q["field"] for q in result["ask_next"]][0], "decision_needed")
        answered = run(sheet(source="transcript", decision_needed="is this pipeline", their_questions=2))
        self.assertEqual(answered["ask_next"], [])


class PhraseTableTest(unittest.TestCase):
    def rows(self, quote, context="sales"):
        return [row["row"] for row in decode.match_quotes([quote], context, "en")["decoded"]]

    def test_the_sugar_coated_no_table(self):
        cases = {
            "This is really interesting!": "really_interesting",
            "Love it! Let's keep in touch.": "keep_in_touch",
            "Send me a deck and I'll take a look.": "send_deck",
            "You should definitely talk to our innovation team.": "talk_to_someone",
            "We don't have budget this quarter.": "no_budget",
            "Keep us posted!": "keep_posted",
            "Yes! And maybe you could also add SSO and reports.": "yes_and_features",
        }
        for quote, row in cases.items():
            self.assertIn(row, self.rows(quote), quote)

    def test_investor_speak_applies_only_to_investors(self):
        cases = {
            "It's a bit early for us.": "too_early",
            "Come back when you have more traction.": "more_traction",
            "We don't usually lead rounds at this stage.": "dont_lead",
            "Let me discuss with my partners.": "discuss_partners",
            "Who else are you talking to?": "who_else",
        }
        for quote, row in cases.items():
            self.assertIn(row, self.rows(quote, "investor"), quote)
            self.assertNotIn(row, self.rows(quote, "sales"), quote)

    def test_wording_variants_and_curly_apostrophes(self):
        curly = "We don" + chr(0x2019) + "t have the budget right now"
        self.assertIn("no_budget", self.rows(curly))
        self.assertIn("keep_posted", self.rows("definitely keep me in the loop"))
        self.assertIn("circle_back", self.rows("Let me circle back on that"))
        self.assertIn("loop_in_unnamed", self.rows("I'll loop in my colleague"))
        self.assertIn("reach_out_anytime", self.rows("Feel free to reach out anytime"))

    def test_moves_come_out_in_the_coaching_language_with_the_english_line_intact(self):
        result = decode.match_quotes(["We don't have budget this quarter."], "sales", "he")
        self.assertIn("If budget weren't an issue, would this be a priority?", result["decoded"][0]["move"])
        self.assertIn("לשאול", result["decoded"][0]["move"])

    def test_one_quote_two_rows_is_shown_once(self):
        result = decode.match_quotes(["It's a bit early for us. Keep us posted!"], "investor", "en")
        self.assertEqual(sorted(row["row"] for row in result["decoded"]), ["keep_posted", "too_early"])
        self.assertEqual([row["row"] for row in result["decoded"] if row["shown"]], ["too_early"])

    def test_compliment_calibration(self):
        levels = lambda quote: [item["level"] for item in decode.match_quotes([quote], "sales", "en")["compliments"]]
        self.assertEqual(levels("This is amazing!"), [5])
        self.assertEqual(levels("Great stuff."), [4])
        self.assertEqual(levels("Interesting."), [3])
        self.assertEqual(levels("I have a few thoughts on the onboarding."), [2])
        self.assertEqual(levels("How are you thinking about competition?"), [1])

    def test_lukewarm_words_count_only_when_they_stand_alone(self):
        long = "That is a good point about onboarding and we should look at it together next week"
        self.assertEqual(decode.match_quotes([long], "sales", "en")["compliments"], [])

    def test_lines_the_tables_do_not_know_are_reported_as_unmatched(self):
        result = decode.match_quotes(["Our fiscal year starts in February."], "sales", "en")
        self.assertEqual(result["unmatched"], ["Our fiscal year starts in February."])


class VerdictTest(unittest.TestCase):
    def test_compliments_with_no_step_are_yellow_leaning_red(self):
        """The guide's own example: no date, no data shared, 'amazing' only."""
        data = sheet(quotes=["This is amazing!", "Let's keep in touch."], their_questions=0)
        self.assertEqual(light(data), ("yellow", "red"))
        self.assertEqual(run(data)["verdict"]["rules_fired"], ["Y1"])

    def test_green_needs_a_signal_and_a_commitment(self):
        data = sheet(
            quotes=["What does pricing look like for 50 seats?"],
            next_step={"exists": True, "date": "2026-12-02", "proposed_by": "them", "what": "security review"},
            cost_to_them=[{"currency": "data_access", "evidence": "sent three months of claims exports"}],
        )
        result = run(data)
        self.assertEqual((result["verdict"]["light"], result["verdict"]["rules_fired"]), ("green", ["G1"]))
        self.assertIn("asked_pricing", [item["id"] for item in result["signals"]["green"]])

    def test_a_signal_without_commitment_is_yellow_leaning_green(self):
        data = sheet(quotes=["Could we do a reference call with one of your customers?"])
        self.assertEqual(light(data), ("yellow", "green"))

    def test_a_commitment_without_a_signal_is_not_green(self):
        data = sheet(cost_to_them=[{"currency": "intro", "evidence": "introduced us to their ops lead"}])
        self.assertEqual(light(data)[0], "yellow")

    def test_a_currency_they_paid_needs_evidence(self):
        """'They gave us data access', with nothing to show for it, is a hope and not a fact."""
        quotes = ["What does pricing look like for 50 seats?"]
        paid = sheet(quotes=quotes, cost_to_them=[{"currency": "data_access", "evidence": "sent three months of claims exports"}])
        self.assertEqual(light(paid)[0], "green")
        from abp.core import PlaybookError

        for blank in ("", "   "):
            with self.assertRaises(PlaybookError) as caught:
                run(sheet(quotes=quotes, cost_to_them=[{"currency": "data_access", "evidence": blank}]))
            self.assertIn("cost_to_them[0].evidence", caught.exception.message)

    def test_praise_alone_leans_red_even_when_they_asked_questions(self):
        self.assertEqual(light(sheet(quotes=["This is amazing!"], their_questions=3)), ("yellow", "red"))
        self.assertEqual(light(sheet(quotes=["Our fiscal year starts in February."], their_questions=3)), ("yellow", None))

    def test_a_date_only_on_the_founders_side_does_not_count(self):
        """'I told them I would send a proposal by Friday' costs them nothing."""
        data = sheet(
            quotes=["What does pricing look like?"],
            next_step={"exists": True, "date": "2026-11-27", "proposed_by": "founder", "what": "send proposal"},
        )
        result = run(data)
        self.assertEqual(result["verdict"]["light"], "yellow")
        self.assertTrue(result["verdict"]["one_sided_date"])
        self.assertFalse(result["verdict"]["dated_next_step"])
        accepted = copy.deepcopy(data)
        accepted["next_step"]["accepted_by_them"] = True
        self.assertEqual(light(accepted)[0], "green")

    def test_red_ghosting_after_three_unanswered_touches(self):
        self.assertEqual(light(sheet(touches_sent=3))[0], "red")
        self.assertEqual(light(sheet(touches_sent=2))[0], "yellow")

    def test_red_keep_us_posted_with_no_questions(self):
        data = sheet(quotes=["Sounds good, keep us posted!"], their_questions=0)
        self.assertEqual(light(data)[0], "red")
        data["their_questions"] = 4
        self.assertEqual(light(data)[0], "yellow")

    def test_red_feel_free_to_reach_out_anytime(self):
        self.assertEqual(light(sheet(quotes=["Feel free to reach out anytime."]))[0], "red")

    def test_red_reported_signal_needs_evidence(self):
        with_evidence = sheet(signals=[{"id": "refuses_concrete_step", "evidence": "declined a pilot and a data share twice"}])
        self.assertEqual(light(with_evidence)[0], "red")
        without = run(sheet(signals=[{"id": "refuses_concrete_step", "evidence": ""}]))
        self.assertEqual(without["verdict"]["light"], "yellow")
        self.assertEqual(without["claimed_without_evidence"], ["refuses_concrete_step"])

    def test_red_flag_plus_a_future_dated_step_is_a_conflict_not_red(self):
        data = sheet(
            quotes=["Feel free to reach out anytime."],
            next_step={"exists": True, "date": "2026-12-03", "proposed_by": "them"},
        )
        result = run(data)
        self.assertEqual((result["verdict"]["light"], result["verdict"]["rules_fired"]), ("yellow", ["R2"]))

    def test_a_yellow_older_than_14_days_forces_a_decision(self):
        fresh = run(sheet(meeting_date="2026-11-10"))
        self.assertFalse(fresh["verdict"]["forced_decision"])       # exactly 14 days
        stale = run(sheet(meeting_date="2026-11-09"))
        self.assertTrue(stale["verdict"]["forced_decision"])        # 15 days
        self.assertIn("Y14", stale["verdict"]["rules_fired"])
        self.assertEqual(stale["next_move"]["template"], "breakup")
        self.assertEqual(stale["next_move"]["alternative"], "archive")

    def test_named_people_cancel_the_unnamed_loop_in(self):
        quote = ["I'll loop in my colleague."]
        vague = run(sheet(quotes=quote))
        self.assertIn("loop_in_unnamed", [item["id"] for item in vague["signals"]["yellow"]])
        named = run(sheet(quotes=quote, signals=[{"id": "added_people", "evidence": "CISO Maria Lopez joins on 2 December"}]))
        self.assertNotIn("loop_in_unnamed", [item["id"] for item in named["signals"]["yellow"]])

    def test_fast_replies_are_a_signal(self):
        result = run(sheet(reply_latency_days=1))
        self.assertIn("fast_replies", [item["id"] for item in result["signals"]["green"]])
        self.assertNotIn("fast_replies", [item["id"] for item in run(sheet(reply_latency_days=5))["signals"]["green"]])


class InvestorTest(unittest.TestCase):
    def data(self, **changes):
        return sheet(context="investor", **changes)

    def test_soft_pass_is_nurture_and_gets_the_bar_extraction_reply(self):
        result = run(self.data(quotes=["It's a bit early for us, but keep us posted!"], their_questions=2))
        self.assertEqual(result["verdict"]["light"], "yellow")
        self.assertEqual(result["fund_status"]["status"], "nurture")
        self.assertEqual(result["next_move"]["template"], "bar_extraction")
        self.assertEqual(result["next_move"]["then"]["template"], "investor_update")
        self.assertIsNone(result["permission_line"])
        self.assertEqual(result["extraction_questions"], [])

    def test_in_process_needs_a_scheduled_interaction_or_open_diligence(self):
        scheduled = run(self.data(next_step={"exists": True, "date": "2026-12-01", "proposed_by": "them"}))
        self.assertEqual(scheduled["fund_status"]["status"], "in_process")
        diligence = run(self.data(signals=[{"id": "open_diligence_request", "evidence": "asked for the data room on 20 November"}]))
        self.assertEqual(diligence["fund_status"]["status"], "in_process")
        self.assertEqual(run(self.data())["fund_status"]["status"], "nurture")

    def test_sales_only_hints_do_not_leak_into_investor_verdicts(self):
        result = run(self.data(quotes=["What's your pricing model?"]))
        self.assertEqual(result["signals"]["green"], [])

    def test_an_offered_intro_is_a_positive_signal(self):
        result = run(self.data(quotes=["Let me introduce you to one of our portfolio founders."]))
        self.assertIn("intro_to_portfolio_or_fund", [item["id"] for item in result["signals"]["green"]])

    def test_investor_threads_end_with_a_referral_to_dana(self):
        self.assertEqual(run(self.data())["bench"]["person"], "dana")
        self.assertIsNone(run(self.data(bench_used=2))["bench"])


class KolTest(unittest.TestCase):
    def test_compliments_only_is_polite_feedback_and_arms_the_founder(self):
        result = run(sheet(context="kol", quotes=["It's great! Love it."]))
        self.assertEqual(result["verdict"]["feedback"], "polite")
        self.assertEqual(len(result["extraction_questions"]), 3)
        self.assertIsNone(result["verdict"]["light"])

    def test_criticism_is_real_feedback(self):
        result = run(sheet(context="kol", quotes=["I have a few thoughts on the workflow."]))
        self.assertEqual(result["verdict"]["feedback"], "real")
        self.assertEqual(result["extraction_questions"], [])


class NextMoveTest(unittest.TestCase):
    def move(self, **changes):
        return run(sheet(tz="ET", **changes))["next_move"]

    def test_follows_the_cadence(self):
        self.assertEqual(self.move(meeting_date="2026-11-23")["touch"], "recap")
        self.assertEqual(self.move(touches_done=["recap"])["touch"], "value")
        self.assertEqual(self.move(touches_done=["recap", "value"])["touch"], "second_angle")
        self.assertEqual(self.move(touches_done=["recap", "value", "second_angle"])["touch"], "breakup")
        self.assertEqual(self.move(touches_done=["recap", "value", "second_angle", "breakup"])["touch"], "nurture")

    def test_names_the_touch_after_this_one(self):
        move = self.move(meeting_date="2026-11-23")
        self.assertEqual(move["then"]["touch"], "value")

    def test_founder_who_went_silent_gets_the_re_entry_template(self):
        move = self.move(meeting_date="2026-11-12")
        self.assertEqual((move["template"], move["why"]), ("re_entry", "founder_went_silent"))

    def test_red_prescribes_the_breakup_then_nurture(self):
        self.assertEqual(self.move(touches_sent=3)["template"], "breakup")
        self.assertEqual(self.move(touches_sent=3, touches_done=["recap", "value", "second_angle", "breakup"])["touch"], "nurture")

    def test_green_prescribes_the_recap_then_holds(self):
        green = dict(
            quotes=["What does pricing look like for 50 seats?"],
            next_step={"exists": True, "date": "2026-12-02", "proposed_by": "them"},
        )
        self.assertEqual(self.move(**green)["touch"], "recap")
        self.assertIsNone(self.move(touches_done=["recap"], **green)["touch"])

    def test_send_date_is_on_both_clocks_and_skips_holidays(self):
        move = self.move(touches_done=["recap"])              # value touch was due 20-21 Nov, today is 24 Nov
        self.assertEqual(move["send"]["date"], "2026-12-01")  # Thanksgiving week is skipped
        self.assertEqual((move["send"]["local_time"], move["send"]["israel_time"]), ("09:30", "16:30"))

    def test_without_a_zone_the_send_date_is_declared_skipped(self):
        receipt = Receipt("decode")
        result = decode.decode(sheet(), "en", receipt)
        self.assertIsNone(result["next_move"]["send"])
        self.assertIn("send_date", [item["check"] for item in receipt.skipped])

    def test_yellow_carries_a_permission_to_say_no_line(self):
        self.assertIn("close this out", run(sheet())["permission_line"])

    def test_one_push_per_verdict(self):
        self.assertTrue(run(sheet())["push"])
        resisting = run(sheet(flags=["founder_resists_verdict"]))
        self.assertIn("what did it cost them", resisting["push"])


class BenchTest(unittest.TestCase):
    def test_flags_route_to_the_right_person(self):
        self.assertEqual(run(sheet(flags=["pricing_raised_without_model"]))["bench"]["person"], "nimrod")
        self.assertEqual(run(sheet(flags=["strategic_fork"]))["bench"]["person"], "eyal")
        self.assertIsNone(run(sheet())["bench"])

    def test_the_session_budget_is_respected(self):
        self.assertIsNone(run(sheet(flags=["strategic_fork"], bench_used=2))["bench"])


class InputValidationTest(unittest.TestCase):
    def test_unknown_fields_are_rejected_with_a_suggestion(self):
        with self.assertRaises(PlaybookError) as caught:
            run(sheet(qoutes=["typo"]))
        self.assertIn("quotes", caught.exception.hint)

    def test_unknown_values_are_rejected(self):
        for bad in (
            sheet(context="government"),
            sheet(next_step={"exists": "yes"}),
            sheet(cost_to_them=[{"currency": "goodwill", "evidence": "x"}]),
            sheet(meeting_date="17/11/2026"),
            sheet(their_questions=-1),
            sheet(signals=[{"id": "vibes", "evidence": "felt great"}]),
        ):
            with self.assertRaises(PlaybookError):
                run(bad)

    def test_friendly_aliases(self):
        self.assertEqual(run(sheet(context="VC"))["context"], "investor")
        self.assertEqual(run(sheet(context="customer"))["context"], "sales")


class DeterminismTest(unittest.TestCase):
    """The reason the engine exists: the same facts always get the same verdict."""

    def generate(self, seed):
        import hashlib

        def pick(slot, options):
            digest = hashlib.sha256(("%d|%s" % (seed, slot)).encode()).hexdigest()
            return options[int(digest[:8], 16) % len(options)]

        quotes_pool = [
            "This is really interesting!", "Love it! Let's keep in touch.", "Send me a deck and I'll take a look.",
            "We don't have budget this quarter.", "Keep us posted!", "This is amazing!", "Great stuff.",
            "What does pricing look like?", "Feel free to reach out anytime.", "Let me circle back.",
            "Are you SOC 2 compliant?", "Our fiscal year starts in February.",
        ]
        data = sheet(
            context=pick("context", ["sales", "investor"]),
            quotes=[pick("q%d" % index, quotes_pool) for index in range(1 + seed % 3)],
            their_questions=pick("questions", [0, 1, 5]),
            touches_sent=pick("touches", [0, 0, 1, 3]),
            meeting_date=pick("date", ["2026-11-23", "2026-11-17", "2026-11-02"]),
        )
        step = pick("step", ["none", "theirs", "founder"])
        if step == "theirs":
            data["next_step"] = {"exists": True, "date": "2026-12-02", "proposed_by": "them"}
        elif step == "founder":
            data["next_step"] = {"exists": True, "date": "2026-12-02", "proposed_by": "founder"}
        if pick("cost", [False, True]):
            data["cost_to_them"] = [{"currency": "data_access", "evidence": "shared exports"}]
        return data

    def test_same_fact_sheet_same_json_every_time(self):
        for seed in range(60):
            data = self.generate(seed)
            first = json.dumps(run(copy.deepcopy(data)), sort_keys=True, default=str)
            second = json.dumps(run(copy.deepcopy(data)), sort_keys=True, default=str)
            self.assertEqual(first, second, seed)

    def test_no_evidence_never_produces_green(self):
        for seed in range(200):
            data = self.generate(seed)
            data["next_step"] = {"exists": False}
            data["cost_to_them"] = []
            self.assertNotEqual(run(data)["verdict"]["light"], "green", data)

    def test_praise_never_improves_a_verdict(self):
        order = {"red": 0, "yellow": 1, "green": 2}
        for seed in range(200):
            data = self.generate(seed)
            before = order[run(copy.deepcopy(data))["verdict"]["light"]]
            data["quotes"] = data["quotes"] + ["This is amazing!", "Awesome, love it.", "Great stuff."]
            after = order[run(data)["verdict"]["light"]]
            self.assertLessEqual(after, before, data)

    def test_a_red_flag_never_improves_a_verdict(self):
        order = {"red": 0, "yellow": 1, "green": 2}
        for seed in range(200):
            data = self.generate(seed)
            before = order[run(copy.deepcopy(data))["verdict"]["light"]]
            data["quotes"] = data["quotes"] + ["Feel free to reach out anytime."]
            after = order[run(data)["verdict"]["light"]]
            self.assertLessEqual(after, before, data)

    def test_briefs_render_in_both_languages(self):
        for seed in range(30):
            result_he = decode.decode(self.generate(seed), "he")
            result_en = decode.decode(self.generate(seed), "en")
            self.assertEqual(result_he["verdict"]["light"], result_en["verdict"]["light"])
            for text in (decode.brief(result_he, "he"), decode.brief(result_en, "en")):
                self.assertNotIn(_util.EM_DASH, text)
                self.assertNotIn(_util.EN_DASH, text)


if __name__ == "__main__":
    unittest.main()
