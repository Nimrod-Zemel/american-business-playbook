"""The phrase-pattern syntax that every rule table is written in."""

import unittest

import _util  # noqa: F401
from abp.core import PlaybookError
from abp.phrases import PhraseSet, compile_phrase, merged, norm


class NormalizeTest(unittest.TestCase):
    def test_lowercases_and_drops_punctuation(self):
        self.assertEqual(norm("Keep us POSTED!!"), "keep us posted")

    def test_drops_straight_and_curly_apostrophes(self):
        curly = "don" + chr(0x2019) + "t"
        self.assertEqual(norm("don't"), "dont")
        self.assertEqual(norm(curly), "dont")

    def test_hyphens_become_spaces(self):
        self.assertEqual(norm("a 20-minute call, one-pager"), "a 20 minute call one pager")

    def test_keeps_hebrew_words(self):
        self.assertEqual(norm("תמחור, ומודל עסקי!"), "תמחור ומודל עסקי")

    def test_is_idempotent(self):
        for text in ("It's a bit early for us. Keep us posted!", "Let's  stay   in-touch"):
            self.assertEqual(norm(norm(text)), norm(text))


class PatternTest(unittest.TestCase):
    def hit(self, pattern, text):
        return bool(compile_phrase(pattern).search(norm(text)))

    def test_plain_phrase_matches_whole_words_only(self):
        self.assertTrue(self.hit("keep in touch", "Let's keep in touch."))
        self.assertFalse(self.hit("keep in touch", "keep in touching distance"))
        self.assertFalse(self.hit("asap", "asapx"))

    def test_alternatives_in_one_position(self):
        for text in ("Keep us posted", "keep me updated", "Keep me posted!"):
            self.assertTrue(self.hit("keep us|me posted|updated", text), text)
        self.assertFalse(self.hit("keep us|me posted|updated", "keep them posted"))

    def test_optional_word(self):
        self.assertTrue(self.hit("that's ?really interesting", "That's interesting"))
        self.assertTrue(self.hit("that's ?really interesting", "that's really interesting"))
        self.assertFalse(self.hit("that's ?really interesting", "that's not interesting"))

    def test_trailing_optional_word(self):
        self.assertTrue(self.hit("circle back ?soon", "let me circle back"))
        self.assertTrue(self.hit("circle back ?soon", "let me circle back soon"))

    def test_gap_allows_up_to_five_words(self):
        self.assertTrue(self.hit("send ... deck", "send me the deck"))
        self.assertTrue(self.hit("send ... deck", "send deck"))
        self.assertTrue(self.hit("send ... deck", "send one two three four five deck"))
        self.assertFalse(self.hit("send ... deck", "send one two three four five six deck"))

    def test_prefix_star(self):
        for text in ("integrate", "integration", "Does it integrate with SAP?"):
            self.assertTrue(self.hit("integrat*", text), text)
        self.assertFalse(self.hit("integrat*", "disintegrate"))

    def test_apostrophes_in_patterns_are_normalized_too(self):
        self.assertTrue(self.hit("don't have budget", "We dont have budget"))
        self.assertTrue(self.hit("don't have budget", "We don't have budget"))

    def test_raw_regex_escape_hatch(self):
        self.assertTrue(self.hit(r"re:\bq[1-4]\b", "reconnect in Q2"))
        self.assertFalse(self.hit(r"re:\bq[1-4]\b", "reconnect in Q7"))

    def test_bad_patterns_are_rejected(self):
        for bad in ("", "... deck", "send ...", "?maybe later", "one-pager", "a (b) c", "re:(unclosed"):
            with self.assertRaises(PlaybookError, msg=bad):
                compile_phrase(bad)


class PhraseSetTest(unittest.TestCase):
    def test_hits_are_ordered_and_deduplicated(self):
        phrases = PhraseSet(["asap", "please advise", "i need you to"])
        text = "I need you to reply ASAP. Please advise, ASAP."
        self.assertEqual(phrases.hits(text), ["i need you to", "asap", "please advise"])

    def test_longest_match_wins_on_overlap(self):
        phrases = PhraseSet(["checking in", "just checking in"])
        self.assertEqual(phrases.hits("Just checking in on this"), ["just checking in"])

    def test_starts_only_matches_at_the_beginning(self):
        phrases = PhraseSet(["send me", "tell me"])
        self.assertEqual(phrases.starts("Send me your availability"), "send me")
        self.assertIsNone(phrases.starts("Could you send me the file"))

    def test_any(self):
        phrases = PhraseSet(["no worries", "happy to"])
        self.assertTrue(phrases.any("Happy to work around your calendar"))
        self.assertFalse(phrases.any("Call me"))

    def test_merged_flattens_origin_lists(self):
        self.assertEqual(merged({"playbook": ["a"], "extension": ["b"]}), ["a", "b"])
        self.assertEqual(merged(["a", "b"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
