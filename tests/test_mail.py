"""The email linter and the template renderer."""

import unittest

import _util
from abp import mail
from abp.core import PlaybookError, load

GOOD = """Subject: Cutting claims processing time at Acme

Hi Michael,

Sarah Cohen mentioned you're rebuilding the claims workflow at Acme.

We help mid-size insurers cut claims processing time - already live with two carriers.

Would Tuesday or Thursday work for a 20-minute call? No worries if not.

Best,
Dana
"""

SAMPLE_VALUES = {
    "first_name": "Michael", "connector": "Sarah", "subject_outcome": "faster claims triage",
    "trigger": "you're rebuilding the claims workflow", "icp": "mid-size insurers",
    "outcome": "cut claims processing time", "proof": "we're live with two carriers",
    "their_plan": "your Q1 plans", "founder": "Dana", "event": "InsureTech Connect", "topic": "claims triage",
    "their_pain": "manual claims triage", "their_words": "too many handoffs", "startup": "ClaimLoop",
    "company": "Acme", "name": "Maria", "pain_metric": "triage time", "number": "a third",
    "agreed": "A short pilot scoped to auto-triage", "next_step": "the pilot", "promised": "the pilot one-pager",
    "promised_when": "tomorrow", "fresh_reason": "a new benchmark on claims automation",
    "link": "the benchmark page", "timeframe": "this quarter", "development": "Pilot went live",
    "new_fact": "our pilot with a regional carrier went live", "their_initiative": "claims backlog",
    "month": "November", "headline": "second paid pilot", "shipped": "auto-triage for commercial lines",
    "sold": "second paid pilot signed", "learned": "procurement takes longer than we planned",
    "ask": "an intro to a head of claims at a mid-size carrier", "the_thing": "the intro to Maria",
    "talk_or_post": "talk", "detail": "the point about first notice of loss", "their_tz": "ET",
    "scheduling_link": "the link in my signature", "relevance": "Sarah thought our triage work fits your backlog project",
}


def checks(result):
    return [item["check"] for item in result["errors"] + result["warnings"]]


def lint(text, kind="cold", **kwargs):
    return mail.lint(text, kind, lang="en", **kwargs)


def variant(old, new, base=GOOD):
    assert old in base, old
    return base.replace(old, new)


class CleanEmailTest(unittest.TestCase):
    def test_a_good_cold_email_is_clean(self):
        result = lint(GOOD)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(checks(result), [])
        self.assertEqual((result["stats"]["sentences"], result["stats"]["asks"]), (4, 1))

    def test_the_guides_own_cold_example_is_clean(self):
        example = [t for t in load("templates")["templates"] if t["id"] == "cold"][0]["example"]
        self.assertEqual(lint(example)["status"], "pass")

    def test_same_input_same_output(self):
        self.assertEqual(lint(GOOD), lint(GOOD))


class ParsingTest(unittest.TestCase):
    def test_subject_is_separated_from_the_body(self):
        parsed = mail.parse(GOOD, "cold")
        self.assertEqual(parsed["subject"], "Cutting claims processing time at Acme")
        self.assertNotIn("Subject", parsed["body"])

    def test_greeting_and_signature_are_not_counted(self):
        parsed = mail.parse(GOOD, "cold")
        self.assertEqual(len(parsed["sentences"]), 4)
        self.assertNotIn("Dana", " ".join(parsed["sentences"]))

    def test_greeting_on_the_same_line_as_content_keeps_the_content(self):
        """v1 dropped the whole line and reported 'no question found' on the guide's own template."""
        for opener in ("Hi Michael - ", "Hi Michael, ", "Hello Michael: "):
            parsed = mail.parse(opener + "is the pilot still on the table for Q1, or should I circle back next quarter?", "followup")
            self.assertEqual(len(parsed["sentences"]), 1, opener)
            self.assertEqual(len(parsed["questions"]), 1, opener)

    def test_greeting_variants(self):
        for greeting in ("Hi Michael,", "Hello,", "Hey there!", "Dear Dr. Park,", "Hi [First name],", "Good morning Michael,"):
            parsed = mail.parse(greeting + "\n\nWould Tuesday work? No worries if not.", "reply")
            self.assertIsNotNone(parsed["greeting"], greeting)
            self.assertEqual(len(parsed["sentences"]), 2, greeting)

    def test_a_first_line_that_is_not_a_greeting_is_kept(self):
        parsed = mail.parse("Hi-tech carriers lose days on triage. Would Tuesday work?", "reply")
        self.assertIsNone(parsed["greeting"])
        self.assertEqual(len(parsed["sentences"]), 2)

    def test_bullets_count_as_one_sentence_each(self):
        recap = "Hi Michael, thank you for the time today. Quick recap:\n- Triage takes too long\n- A pilot could prove value\n- Next step: intro to the data team by Friday\n\nI'll send the one-pager tomorrow. Anything I missed?"
        parsed = mail.parse(recap, "recap")
        self.assertEqual(len(parsed["sentences"]), 6)
        self.assertEqual(parsed["lead_ins"], ["Quick recap:"])
        self.assertEqual(len(parsed["questions"]), 1)

    def test_abbreviations_do_not_split_sentences(self):
        parsed = mail.parse("We work with U.S. carriers, e.g. two regional insurers. Would Tuesday work?", "reply")
        self.assertEqual(len(parsed["sentences"]), 2)

    def test_a_question_inside_a_quote_is_not_an_ask(self):
        """Documented v1 false positive: a quoted customer line counted as an extra ask."""
        text = 'Hi Michael,\n\nYour team asked "can this cut triage time?" in the demo. Would Tuesday work for a short call? No worries if not.'
        result = lint(text, "followup")
        self.assertEqual(result["stats"]["asks"], 1)
        self.assertNotIn("ask_many", checks(result))

    def test_pleasantry_questions_are_not_asks(self):
        parsed = mail.parse("Hi Michael,\n\nHow are you? Would Tuesday work for a call?", "cold")
        self.assertEqual(len(parsed["questions"]), 1)

    def test_forwardable_blurb_is_split_off(self):
        text = mail.render("forwardable")["text"]
        parsed = mail.parse(text, "intro")
        self.assertEqual(len(parsed["questions"]), 1)
        self.assertEqual(len(parsed["blurb_questions"]), 1)
        self.assertEqual(len(parsed["sentences"]) + len(parsed["blurb_sentences"]), 6)

    def test_windows_line_endings(self):
        self.assertEqual(lint(GOOD.replace("\n", "\r\n"))["stats"], lint(GOOD)["stats"])


class RuleTest(unittest.TestCase):
    """One positive case per check; the clean email above is the negative case for all of them."""

    def assertFlags(self, text, check, kind="cold", level=None, **kwargs):
        result = lint(text, kind, **kwargs)
        self.assertIn(check, checks(result), "\n".join(item["message"] for item in result["errors"] + result["warnings"]))
        if level:
            found = [item for item in result["errors"] + result["warnings"] if item["check"] == check][0]
            self.assertEqual(found["level"], level)
        return result

    def test_too_many_sentences(self):
        long = variant("No worries if not.", "No worries if not. " + "We also do fraud detection. " * 3)
        result = self.assertFlags(long, "length_sentences", level="error")
        self.assertEqual(result["status"], "revise")

    def test_too_many_words(self):
        filler = " ".join(["really"] * 120)
        self.assertFlags(variant("already live", filler + " already live"), "length_words", level="error")

    def test_word_target_is_a_warning(self):
        filler = " ".join(["really"] * 88)
        result = self.assertFlags(variant("already live", filler + " already live"), "length_words_target", level="warn")
        self.assertTrue(120 < result["stats"]["words"] <= 130)
        self.assertNotIn("length_words", checks(result))

    def test_no_ask(self):
        self.assertFlags(variant("Would Tuesday or Thursday work for a 20-minute call?", "Happy to talk."), "ask_none", level="error")

    def test_two_questions(self):
        self.assertFlags(variant("No worries if not.", "Could you also intro me to your CTO? No worries if not."), "ask_many", level="error")

    def test_an_instruction_counts_as_an_ask(self):
        result = self.assertFlags(variant("No worries if not.", "Send me your availability. No worries if not."), "ask_many")
        self.assertEqual(result["stats"]["asks"], 2)
        self.assertIn("command_tone", checks(result))

    def test_open_ended_ask_is_a_warning(self):
        text = variant("Would Tuesday or Thursday work for a 20-minute call?", "What do you think about a call?")
        self.assertFlags(text, "ask_open", level="warn")

    def test_an_either_or_inside_a_quote_does_not_close_an_open_ask(self):
        text = variant("Would Tuesday or Thursday work for a 20-minute call?", 'What do you think about the "build or buy" question?')
        self.assertFlags(text, "ask_open", level="warn")

    def test_closed_asks_are_not_flagged_as_open(self):
        for ask in (
            "Would Tuesday or Thursday work for a 20-minute call?",
            "Worth a 20-minute call to see if this is relevant?",
            "That made me think of your backlog - worth restarting the conversation?",
            "Quick one: is the pilot still on the table, or should I circle back next quarter?",
            "Anything I missed?",
        ):
            result = lint(variant("Would Tuesday or Thursday work for a 20-minute call?", ask))
            self.assertNotIn("ask_open", checks(result), ask)

    def test_command_tone(self):
        for opener in ("Send me your availability.", "Please send me the file.", "Tell me when you are free.", "Let me know your availability."):
            text = variant("Would Tuesday or Thursday work for a 20-minute call?", opener + " Would Tuesday work?")
            self.assertFlags(text, "command_tone", level="error")

    def test_command_words_in_the_middle_of_a_sentence_are_fine(self):
        text = variant("No worries if not.", "Happy to send over anything you would like me to share. No worries if not.")
        self.assertNotIn("command_tone", checks(lint(text)))

    def test_pushy_phrases(self):
        for phrase in ("ASAP", "Please advise", "I need you to confirm", "kindly", "urgent"):
            text = variant("No worries if not.", "This is needed, %s. No worries if not." % phrase)
            self.assertFlags(text, "pushy", level="error")

    def test_pushy_matches_whole_words_only(self):
        self.assertNotIn("pushy", checks(lint(variant("already live", "already live with insurgent startups"))))

    def test_missing_softener(self):
        self.assertFlags(variant(" No worries if not.", "").replace("Would Tuesday or Thursday work for", "Is Tuesday good for"), "softener_missing", level="error")

    def test_checking_in(self):
        text = "Hi Michael - just checking in on the pilot. Would Tuesday work for a call? No worries if not."
        self.assertFlags(text, "checking_in", "followup", level="error")

    def test_hurt_tone(self):
        text = "Hi Michael - you never replied to my last note. Would Tuesday work for a call? No worries if not."
        self.assertFlags(text, "hurt_tone", "followup", level="error")

    def test_over_apology(self):
        text = "Hi Michael,\n\nSorry for the long silence. Would Tuesday work for a call? No worries if not."
        self.assertFlags(text, "over_apology", "followup", level="warn")

    def test_throat_clearing_opener(self):
        self.assertFlags(variant("Sarah Cohen mentioned", "I hope this email finds you well. Sarah Cohen mentioned").replace(" No worries if not.", ""), "bluf", level="warn")

    def test_formal_greeting(self):
        self.assertFlags(variant("Hi Michael,", "Dear Mr. Miller,"), "formal_greeting", level="warn")
        self.assertFlags(variant("Hi Michael,", "To whom it may concern,"), "formal_greeting")

    def test_subject_rules(self):
        self.assertFlags(variant("Cutting claims processing time at Acme", "Hello"), "subject_generic", level="warn")
        self.assertFlags(variant("Cutting claims processing time at Acme", "x" * 70), "subject_long", level="error")
        self.assertFlags(variant("Subject: Cutting claims processing time at Acme", "Subject:"), "subject_empty", level="error")
        self.assertFlags(variant("Subject: Cutting claims processing time at Acme\n\n", ""), "subject_missing", level="warn")

    def test_a_reply_needs_no_subject(self):
        result = lint("Hi Michael,\n\nCompletely understand. Thanks for the straight read.", "reply")
        self.assertNotIn("subject_missing", checks(result))

    def test_em_and_en_dashes(self):
        for dash in (_util.EM_DASH, _util.EN_DASH):
            self.assertFlags(variant("time - already", "time %s already" % dash), "typography_dash", level="error")

    def test_hidden_characters(self):
        for char in (_util.RLM, _util.ZWSP):
            result = self.assertFlags(variant("No worries if not.", "No worries if not." + char), "hidden_chars", level="error")
            self.assertEqual(result["status"], "revise")

    def test_hebrew_in_an_english_deliverable(self):
        self.assertFlags(variant("No worries if not.", "No worries if not. תודה"), "hebrew_in_english", level="error")

    def test_leftover_brackets_are_missing_facts(self):
        result = self.assertFlags(variant("two carriers", "[number] carriers"), "placeholder_left", level="error")
        self.assertEqual(result["missing_facts"], ["[number]"])

    def test_deck_on_first_contact(self):
        self.assertFlags(variant("No worries if not.", "Attached is our deck. No worries if not."), "deck_attached", level="warn")

    def test_long_paragraph(self):
        block = "We do triage. We do routing. We do fraud. We do intake."
        self.assertFlags(variant("We help mid-size insurers cut claims processing time - already live with two carriers.", block), "paragraph_long", level="warn")

    def test_directive_wording_but_not_the_strong_yes_question(self):
        self.assertFlags(variant("No worries if not.", "You need to see this. No worries if not."), "directive", level="warn")
        bar = mail.render("bar_extraction", {"first_name": "Jennifer", "founder": "Dana"})["text"]
        self.assertEqual(checks(lint(bar, "reply")), [])

    def test_unknown_type_and_empty_draft_are_errors(self):
        with self.assertRaises(PlaybookError):
            lint(GOOD, "newsletter")
        with self.assertRaises(PlaybookError):
            lint("   \n")


class TypeSpecificTest(unittest.TestCase):
    def test_breakup_allows_no_question(self):
        text = mail.render("breakup", {"first_name": "Michael"})["text"]
        self.assertEqual(lint(text, "breakup")["status"], "pass")

    def test_breakup_rejects_two_questions(self):
        text = "Hi Michael, I'll assume the timing isn't right. Should I close this out? Or reconnect in Q2? No hard feelings."
        self.assertIn("ask_many_soft", checks(lint(text, "breakup")))

    def test_investor_update_needs_its_sections_and_exactly_one_ask(self):
        good = mail.render("investor_update", {k: SAMPLE_VALUES[k] for k in ("first_name", "startup", "month", "headline", "shipped", "sold", "learned", "ask", "founder")})["text"]
        self.assertEqual(lint(good, "investor_update")["status"], "pass")
        missing = good.replace("Learned: procurement takes longer than we planned\n", "")
        self.assertIn("update_sections", checks(lint(missing, "investor_update")))
        two = good + "\nAsk: also a candidate for head of sales"
        self.assertIn("update_ask", checks(lint(two, "investor_update")))

    def test_investor_update_word_limit(self):
        good = mail.render("investor_update", {k: SAMPLE_VALUES[k] for k in ("first_name", "startup", "month", "headline", "shipped", "sold", "learned", "ask", "founder")})["text"]
        long = good.replace("auto-triage for commercial lines", " ".join(["feature"] * 260))
        self.assertIn("length_words", checks(lint(long, "investor_update")))

    def test_linkedin_note_limit_counts_the_greeting(self):
        ok = "Hi Michael - enjoyed your talk on claims triage. Building in the same space at ClaimLoop; would love to connect."
        self.assertEqual(lint(ok, "linkedin")["status"], "pass")
        self.assertIn("linkedin_long", checks(lint(ok + " " + "x" * 200, "linkedin")))
        self.assertIn("linkedin_pitch", checks(lint(ok + " Can I book a demo?", "linkedin")))

    def test_forwardable_blurb_may_carry_only_one_question(self):
        text = mail.render("forwardable")["text"] + " Worth a call?"
        self.assertIn("blurb_questions", checks(lint(text, "intro")))


class SentenceBoundaryTest(unittest.TestCase):
    def count(self, body):
        return len(mail.parse("Hi Michael,\n\n%s\n\nBest,\nDana\n" % body, "cold")["sentences"])

    def test_a_quoted_question_inside_a_sentence_does_not_end_it(self):
        self.assertEqual(self.count('Sarah said "is this a priority for Q1?" when we spoke. Would Tuesday work?'), 2)
        self.assertEqual(self.count("She wrote (see the note!) and then called. Would Tuesday work?"), 2)

    def test_a_quote_that_ends_a_sentence_still_ends_it(self):
        self.assertEqual(self.count('Sarah said "this is a priority." Then she booked a call. Would Tuesday work?'), 3)

    def test_abbreviations_do_not_swallow_ordinary_words(self):
        """'ms.' is an abbreviation; 'claims.' and 'teams.' are the ends of sentences."""
        self.assertEqual(self.count("We speed up claims. We work with two teams. This is our best. Would Tuesday work?"), 4)
        self.assertEqual(self.count("We are first. No. That is not a typo. Would Tuesday work?"), 4)

    def test_real_abbreviations_do_not_end_a_sentence(self):
        self.assertEqual(self.count("Dr. Smith and Ms. Lee from Acme Inc. joined, e.g. for the demo. Would 10 a.m. ET work?"), 2)

    def test_lowercase_writing_is_still_counted(self):
        """Quick lowercase English is common in drafts; it must not slip under the length limit."""
        self.assertEqual(self.count("we are a startup. we do ai for claims. we have two carriers. can we talk?"), 4)


class NumbersTest(unittest.TestCase):
    SOURCE = "We cut claims processing time by about 40 percent for 2 carriers and raised $1.5M."

    def unverified(self, sentence):
        draft = GOOD.replace("We help mid-size insurers cut claims processing time - already live with two carriers.", sentence)
        return lint(draft, source=self.SOURCE)["unverified_numbers"]

    def test_figures_from_the_source_are_verified_in_any_notation(self):
        self.assertEqual(self.unverified("We cut processing time by 40% for 2 carriers after raising $1.5 million."), [])
        self.assertEqual(self.unverified("We raised 1,500,000 dollars."), [])

    def test_an_invented_figure_is_flagged(self):
        self.assertEqual(self.unverified("We cut processing time by 40% and run 12 pilots."), ["12"])
        self.assertEqual(self.unverified("We cut processing time by 55%."), ["55%"])
        self.assertEqual(self.unverified("We raised $3M."), ["$3m"])

    def test_an_invented_figure_stops_the_email(self):
        draft = GOOD.replace("already live with two carriers", "already live with 12 carriers")
        result = lint(draft, source=self.SOURCE)
        self.assertEqual(result["status"], "revise")
        self.assertIn("unverified_number", [item["check"] for item in result["errors"]])
        self.assertEqual(lint(GOOD, source=self.SOURCE)["status"], "pass")

    def test_meeting_lengths_times_dates_and_years_are_not_claims(self):
        clean = "Since 2023 we cut time by 40%. Free on Dec 3 at 9:30 am or on the 4th for 20 minutes?"
        self.assertEqual(self.unverified(clean), [])

    def test_without_a_source_the_check_is_declared_skipped(self):
        from abp.core import Receipt

        receipt = Receipt("lint")
        result = mail.lint(GOOD, "cold", lang="en", receipt=receipt)
        self.assertEqual(result["unverified_numbers"], [])
        self.assertIn("numbers_vs_source", [item["check"] for item in receipt.skipped])

    def test_before_and_after_numbers(self):
        draft = "Dear Sir, I hope you are well. We are a startup. Send me your availability. Can we talk? Can you intro me to your CTO?"
        result = lint(GOOD, source=draft)
        self.assertEqual(result["before"], {"sentences": 5, "words": 23, "asks": 3})


class TemplateTest(unittest.TestCase):
    def test_unfilled_slots_stay_as_brackets_and_are_reported(self):
        rendered = mail.render("cold", {"first_name": "Michael"})
        self.assertIn("Hi Michael,", rendered["text"])
        self.assertIn("[ICP]", rendered["missing"])
        self.assertNotIn("first_name", rendered["open_slots"])
        self.assertEqual(lint(rendered["text"])["errors"][0]["check"], "placeholder_left")

    def test_unknown_template_or_slot_is_an_error(self):
        with self.assertRaises(PlaybookError):
            mail.render("newsletter")
        with self.assertRaises(PlaybookError):
            mail.render("cold", {"mood": "great"})

    def test_a_slot_can_fill_several_brackets(self):
        rendered = mail.render("forwardable", {"company": "Acme"})
        self.assertIn("Quick intro request - [Startup] x Acme", rendered["text"])
        self.assertIn("at Acme?", rendered["text"])

    def test_every_template_is_clean_under_its_own_rules_once_filled(self):
        """v1's linter flagged the guide's own breakup, recap, second-angle and bar-extraction templates."""
        from abp import clock

        slots = clock.scheduling_slots(clock.parse_now("2026-11-24T14:16"), "ET")
        for template in load("templates")["templates"]:
            values = dict((key, SAMPLE_VALUES[key]) for key in template["slots"])
            if template["id"] == "intro_reply_bcc":
                values["ask"] = "Would Tuesday or Thursday work for a 20-minute call?"
            rendered = mail.render(template["id"], values, slots if template.get("computed") else None)
            self.assertEqual(rendered["missing"], [], template["id"])
            result = lint(rendered["text"], template["type"])
            self.assertEqual(result["status"], "pass", "%s: %s" % (template["id"], [item["message"] for item in result["errors"]]))
            self.assertEqual(result["warnings"], [], "%s: %s" % (template["id"], [item["message"] for item in result["warnings"]]))

    def test_briefs_are_free_of_dashes_in_both_languages(self):
        for lang in ("he", "en"):
            text = mail.lint_brief(mail.lint("Dear Sir, send me your availability ASAP. Can we talk? Can you help?", "cold", lang=lang), lang)
            self.assertNotIn(_util.EM_DASH, text)
            self.assertNotIn(_util.EN_DASH, text)
            self.assertIn("command_tone", text)


if __name__ == "__main__":
    unittest.main()
