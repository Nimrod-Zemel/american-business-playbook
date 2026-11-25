"""The rule tables check themselves: every row must recognize its own example."""

import json
import os
import re
import unittest

import _util
from abp import cli, decode, mail, meeting
from abp.core import load
from abp.phrases import PhraseSet, merged, norm

DATA = os.path.join(_util.SKILL, "data")
TABLES = ["bench", "cadence", "coach", "decoder", "email", "interview", "intro", "meetings", "signals", "templates"]
BRACKET = re.compile(r"\[[^\[\]\n]{1,120}\]")


def walk(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            for item in walk(value, "%s.%s" % (path, key)):
                yield item
    elif isinstance(node, list):
        for index, value in enumerate(node):
            for item in walk(value, "%s[%d]" % (path, index)):
                yield item
    else:
        yield path, node


class FilesTest(unittest.TestCase):
    def test_every_table_is_valid_json_and_listed(self):
        on_disk = sorted(name[:-5] for name in os.listdir(DATA) if name.endswith(".json"))
        self.assertEqual(on_disk, TABLES)
        for name in TABLES:
            with open(os.path.join(DATA, name + ".json"), "r", encoding="utf-8") as handle:
                self.assertIsInstance(json.load(handle), dict, name)

    def test_every_table_explains_itself(self):
        for name in TABLES:
            self.assertIn("_about", load(name), name)

    def test_every_bilingual_node_has_both_languages(self):
        for name in TABLES:
            for path, _value in walk(load(name)):
                if path.endswith(".he"):
                    english = path[:-3] + ".en"
                    self.assertIn(english, dict(walk(load(name))), "%s: %s has no English twin" % (name, path))
            paths = dict(walk(load(name)))
            for path in paths:
                if path.endswith(".en") and not path.endswith("label.en"):
                    twin = path[:-3] + ".he"
                    alt = [path[:-3] + ".he_m", path[:-3] + ".he_f"]
                    self.assertTrue(twin in paths or all(item in paths for item in alt), "%s: %s has no Hebrew twin" % (name, path))

    def test_origin_tags_are_known(self):
        for name in TABLES:
            for path, value in walk(load(name)):
                if path.endswith("origin") or path.endswith("_origin"):
                    self.assertIn(value, ("playbook", "extension"), "%s%s" % (name, path))

    def test_all_phrase_patterns_compile(self):
        self.assertGreater(cli._compile_all(), 400)


class DecoderTest(unittest.TestCase):
    def setUp(self):
        self.data = load("decoder")

    def test_row_ids_are_unique(self):
        ids = [row["id"] for row in self.data["rows"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_guides_eight_and_six_rows_are_all_present(self):
        tables = [row["table"] for row in self.data["rows"]]
        self.assertEqual(tables.count("sugar_coated_no"), 8)
        self.assertEqual(tables.count("investor_speak"), 6)
        self.assertEqual(len(self.data["compliments"]["levels"]), 5)
        self.assertEqual(len(self.data["permission_to_say_no"]["lines"]), 3)

    def test_every_row_matches_its_own_wording_and_examples(self):
        for row in self.data["rows"]:
            if not row["patterns"]:
                continue
            phrases = PhraseSet(row["patterns"])
            samples = list(row["examples"])
            if row["id"] != "offers_intro":
                samples.append(row["said"])
            samples.append(row.get("scene_line", row["said"]) if row["id"] != "offers_intro" else row["examples"][0])
            for sample in samples:
                self.assertTrue(phrases.any(sample), "%s does not match %r" % (row["id"], sample))

    def test_every_green_hint_matches_its_examples(self):
        for hint in self.data["green_hints"]:
            phrases = PhraseSet(hint["patterns"])
            for sample in hint["examples"]:
                self.assertTrue(phrases.any(sample), "%s does not match %r" % (hint["id"], sample))

    def test_plain_business_sentences_match_nothing(self):
        for sample in self.data["non_examples"]:
            for context in decode.CONTEXTS:
                matched = decode.match_quotes([sample], context, "en")
                self.assertEqual(matched["decoded"], [], sample)
                self.assertEqual(matched["hints"], [], sample)
                self.assertEqual(matched["unmatched"], [sample])

    def test_permission_lines_are_recognized_by_their_markers(self):
        markers = PhraseSet(self.data["permission_to_say_no"]["markers"])
        for line in self.data["permission_to_say_no"]["lines"]:
            self.assertTrue(markers.any(line), line)

    def test_every_counter_move_is_recognized_in_the_tables_own_move(self):
        """The move the table recommends must count as a counter when the founder says it."""
        for row in self.data["rows"]:
            quoted = re.findall(r'"([^"]+)"', row["move"]["en"])
            if not quoted or not row["counter"]:
                continue
            self.assertTrue(meeting._countered(row, [quoted[0]]), "%s: %r is not recognized as its own counter-move" % (row["id"], quoted[0]))

    def test_rows_have_text_in_both_languages(self):
        for row in self.data["rows"]:
            for field in ("means", "move"):
                self.assertTrue(row[field]["en"].strip() and row[field]["he"].strip(), row["id"])


class SignalsTest(unittest.TestCase):
    def test_signal_ids_are_unique_per_context(self):
        for context in decode.CONTEXTS:
            ids = decode.signal_ids(context)
            flat = ids["green"] + ids["yellow"] + ids["red"]
            self.assertEqual(len(flat), len(set(flat)), context)

    def test_the_guides_traffic_light_is_complete(self):
        sales = decode.signal_ids("sales")
        self.assertEqual((len(sales["green"]), len(sales["yellow"]), len(sales["red"])), (7, 3, 4))

    def test_rows_that_suggest_a_signal_point_at_a_real_one(self):
        for row in load("decoder")["rows"]:
            target = row.get("suggests_signal")
            if target:
                found = any(target in sum(decode.signal_ids(context).values(), []) for context in row["contexts"])
                self.assertTrue(found, "%s suggests unknown signal %s" % (row["id"], target))

    def test_green_hints_are_real_sales_signals(self):
        for hint in load("decoder")["green_hints"]:
            self.assertIn(hint["id"], decode.signal_ids("sales")["green"])

    def test_intake_asks_at_most_three_questions(self):
        intake = load("signals")["intake"]
        self.assertEqual(intake["max_questions_per_turn"], 3)
        self.assertEqual(sum(1 for q in intake["questions"] if q["required_for_verdict"]), 3)


class EmailTablesTest(unittest.TestCase):
    def test_v1_limits_are_preserved(self):
        types = load("email")["types"]
        expected = {"cold": (5, 130), "followup": (5, 130), "intro": (6, 150), "recap": (8, 170), "breakup": (6, 140), "reply": (7, 160)}
        for name, (sentences, words) in expected.items():
            self.assertEqual((types[name]["max_sentences"], types[name]["max_words"]), (sentences, words), name)

    def test_v1_phrase_lists_are_preserved(self):
        email = load("email")
        self.assertEqual(len(email["pushy"]["playbook"]), 10)
        self.assertEqual(len(email["command_openers"]["playbook"]), 8)
        # Ten from the 1.1.0 linter, and "any chance", which the guide itself lists under Use.
        self.assertEqual(len(merged(email["softeners"]["request"]["playbook"]) + merged(email["softeners"]["release"]["playbook"])), 11)

    def test_every_message_has_a_level_and_two_languages(self):
        for key, message in load("email")["messages"].items():
            self.assertIn(message["level"], ("error", "warn"), key)
            self.assertTrue(message["en"] and message["he"], key)


class TemplatesTest(unittest.TestCase):
    def setUp(self):
        self.templates = load("templates")["templates"]

    def test_fifteen_templates_in_twelve_guide_groups(self):
        self.assertEqual(len(self.templates), 15)
        self.assertEqual(sorted(set(t["group"] for t in self.templates if t["group"])), list(range(1, 13)))

    def test_template_types_are_lint_types(self):
        for template in self.templates:
            self.assertIn(template["type"], mail.types(), template["id"])

    def test_every_slot_label_appears_in_its_template(self):
        for template in self.templates:
            text = template.get("subject", "") + "\n" + template["body"]
            for key, labels in template["slots"].items():
                for label in ([labels] if isinstance(labels, str) else labels):
                    self.assertIn(label, text, "%s: slot %s" % (template["id"], key))

    def test_every_bracket_in_a_template_has_a_slot(self):
        for template in self.templates:
            text = template.get("subject", "") + "\n" + template["body"]
            known = []
            for labels in template["slots"].values():
                known.extend([labels] if isinstance(labels, str) else labels)
            for bracket in BRACKET.findall(text):
                if template.get("computed") and bracket == "[date]":
                    continue
                self.assertIn(bracket, known, "%s: %s has no slot" % (template["id"], bracket))

    def test_templates_never_ship_invented_figures(self):
        """Rule 7: a rendered template may not carry a metric the founder did not supply."""
        allowed = {20.0, 6.0}
        for template in self.templates:
            for value, shown in mail.numbers_in(mail._plain_for_numbers(template["body"])):
                if template["id"] == "scheduling":
                    continue
                self.assertIn(value, allowed, "%s carries the figure %s" % (template["id"], shown))


class MeetingsTablesTest(unittest.TestCase):
    def setUp(self):
        self.meetings = load("meetings")

    def test_three_meeting_types_and_only_sales_runs_bant(self):
        types = self.meetings["types"]
        self.assertEqual(sorted(types), ["investor", "kol", "sales"])
        self.assertEqual([name for name, spec in types.items() if spec["bant"] == "on"], ["sales"])

    def test_guide_content_counts(self):
        self.assertEqual(len(self.meetings["sales"]["bant"]), 4)
        self.assertEqual(len(self.meetings["investor"]["may_ask"]), 5)
        self.assertEqual(len(self.meetings["investor"]["advanced"]), 5)
        self.assertEqual(len(self.meetings["kol"]["extraction_bank"]), 6)
        self.assertEqual(len(self.meetings["characters"]), 3)

    def test_characters_inject_rows_that_exist_and_can_be_detected(self):
        for name, character in self.meetings["characters"].items():
            for row_id in character["sugar"] + character["deferral"] + character.get("probes", []):
                row = meeting._row(row_id)
                line = row.get("scene_line", row["said"])
                self.assertTrue(PhraseSet(row["patterns"]).any(line), "%s: %s cannot detect its own line" % (name, row_id))

    def test_debrief_weights_sum_to_ten(self):
        weights = self.meetings["debrief"]["weights"]
        total = sum(value for key, value in weights.items() if not key.startswith("_"))
        self.assertEqual(total, 10.0)
        for key in weights:
            if not key.startswith("_"):
                self.assertIn(key, self.meetings["debrief"]["drills"])
                self.assertIn(key, self.meetings["debrief"]["dimension_labels"])

    def test_guard_messages_name_what_was_hit(self):
        for key, rule in self.meetings["guards"].items():
            self.assertIn("{hits}", rule["message"]["en"], key)
            self.assertIn("{hits}", rule["message"]["he"], key)
            self.assertTrue(set(rule["audience"]) <= set(meeting.TYPES), key)

    def test_region_aliases_do_not_collide(self):
        seen = {}
        for region, spec in self.meetings["regions"].items():
            for alias in spec["aliases"]:
                self.assertNotIn(alias, seen, "%s is in both %s and %s" % (alias, seen.get(alias), region))
                seen[alias] = region


class CadenceTablesTest(unittest.TestCase):
    def test_touch_templates_exist(self):
        for touch in load("cadence")["touches"]:
            self.assertIn(touch["template"], mail.template_ids(), touch["id"])

    def test_city_table_points_at_known_zones(self):
        cadence = load("cadence")
        for city, zone in cadence["cities"].items():
            if not city.startswith("_"):
                self.assertIn(zone, cadence["zones"], city)
                self.assertEqual(city, norm(city), "city keys must be normalized: %r" % city)
        for alias, zone in cadence["zone_aliases"].items():
            self.assertIn(zone, cadence["zones"], alias)

    def test_weekday_names_run_monday_to_sunday_in_both_languages(self):
        names = load("cadence")["weekday_names"]
        self.assertEqual(sorted(names), ["en", "he"])
        self.assertEqual(names["en"], ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
        self.assertEqual(len(names["he"]), 7)
        self.assertEqual(len(set(names["he"])), 7)

    def test_every_next_move_the_engine_can_prescribe_has_its_text(self):
        """decode.py names a reason by id; the words for it live in the table."""
        with open(os.path.join(DATA, "..", "scripts", "abp", "decode.py"), "r", encoding="utf-8") as handle:
            source = handle.read()
        used = set(re.findall(r'why="([a-z_]+)"', source)) | set(re.findall(r'"why": "([a-z_]+)"', source))
        table = load("cadence")["next_moves"]
        self.assertEqual(sorted(used), sorted(table))
        self.assertGreaterEqual(len(used), 7)
        for key, node in table.items():
            self.assertTrue(node["en"].strip() and node["he"].strip(), key)

    def test_touches_outside_the_cadence_are_named_in_both_languages(self):
        names = load("cadence")["off_cadence_touches"]
        self.assertEqual(sorted(names), ["bar_extraction_reply", "investor_update"])
        for key, node in names.items():
            self.assertTrue(node["en"].strip() and node["he"].strip(), key)
        label = load("signals")["investor"]["process"]["open_diligence_label"]
        self.assertTrue(label["en"].strip() and label["he"].strip())


class BenchTablesTest(unittest.TestCase):
    def test_routing_points_at_real_people(self):
        bench = load("bench")
        people = [person["id"] for person in bench["people"]]
        self.assertEqual(len(people), 5)
        for row in bench["routing"]:
            self.assertIn(row["person"], people)

    def test_no_contact_details_in_the_bench(self):
        raw = _util.read("skills", _util.SKILL_NAME, "data", "bench.json")
        self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", raw), "an email address is in bench.json")
        self.assertIsNone(re.search(r"(?<!\d)(?:\+972|05\d)[\d -]{7,}", raw), "a phone number is in bench.json")

    def test_intro_rules_reference_real_templates(self):
        for rule in load("intro")["rules"]:
            if rule["template"]:
                self.assertIn(rule["template"], mail.template_ids())


if __name__ == "__main__":
    unittest.main()
