#!/usr/bin/env python3
"""Do the tests notice when a rule is broken? Break rules on purpose and see.

    python3 tools/mutation_check.py            run every mutation (several minutes)
    python3 tools/mutation_check.py --list     show the mutations and exit

For each mutation the script copies the repository to a temporary folder,
changes one rule there, regenerates the references and the seal (so that only
a behavior test can notice), runs the test suite and reports whether a test
failed. A passing suite on a broken rule is a hole in the tests.

Not part of CI: it runs the whole suite once per mutation. Run it before a
release that touches the engine.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import _paths

S = "skills/%s" % _paths.SKILL_NAME

# (what is broken, file, text to find, replacement)
MUTATIONS = [
    ("ghosting threshold 3 -> 5", S + "/data/signals.json", '"ghosting_touches": {"value": 3', '"ghosting_touches": {"value": 5'),
    ("yellow max age 14 -> 30 days", S + "/data/signals.json", '"yellow_max_age_days": {"value": 14', '"yellow_max_age_days": {"value": 30'),
    ("fast reply 2 -> 5 days", S + "/data/signals.json", '"fast_reply_days": {"value": 2', '"fast_reply_days": {"value": 5'),
    ("intake asks 5 questions per turn", S + "/data/signals.json", '"max_questions_per_turn": 3', '"max_questions_per_turn": 5'),
    ("cold email max sentences 5 -> 8", S + "/data/email.json", '"cold": {"max_sentences": 5', '"cold": {"max_sentences": 8'),
    ("cold email max words 130 -> 200", S + "/data/email.json", '"cold": {"max_sentences": 5, "max_words": 130', '"cold": {"max_sentences": 5, "max_words": 200'),
    ("unverified number back to a warning", S + "/data/email.json", '"unverified_number": {"level": "error"', '"unverified_number": {"level": "warn"'),
    ("intro late after 48h, not 24h", S + "/data/intro.json", '"reply_late_hours": {"value": 24', '"reply_late_hours": {"value": 48'),
    ("minimum gap between touches 2 -> 1", S + "/data/cadence.json", '"min_gap_days": 2', '"min_gap_days": 1'),
    ("value touch window day 3-4 -> 5-6", S + "/data/cadence.json", '"window_days": [3, 4]', '"window_days": [5, 6]'),
    ("send window Tue-Thu -> Mon-Wed", S + "/data/cadence.json", '"weekdays": [1, 2, 3]', '"weekdays": [0, 1, 2]'),
    ("debrief weight: decoding 3 -> 2", S + "/data/meetings.json", '"decoded": 3.0', '"decoded": 2.0'),
    ("BANT on an investor is only a warning", S + "/data/meetings.json", '"audience": ["investor"],\n      "level": "error"', '"audience": ["investor"],\n      "level": "warn"'),
    ("bench budget 2 -> 5", S + "/data/bench.json", '"max_nudges_per_session": 2', '"max_nudges_per_session": 5'),
    ("US DST starts first Sunday of March", S + "/scripts/abp/clock.py", "nth_weekday(year, 3, SUNDAY, 2), nth_weekday(year, 11, SUNDAY, 1)", "nth_weekday(year, 3, SUNDAY, 1), nth_weekday(year, 11, SUNDAY, 1)"),
    ("Israel DST starts on the Sunday", S + "/scripts/abp/clock.py", "last_weekday(year, 3, SUNDAY) - dt.timedelta(days=2)", "last_weekday(year, 3, SUNDAY) - dt.timedelta(days=0)"),
    ("late slot in Israel from 23:00", S + "/scripts/abp/clock.py", "LATE_HOUR_ISRAEL = 21", "LATE_HOUR_ISRAEL = 23"),
    ("stale cadence note kept after respacing", S + "/scripts/abp/clock.py", 'picked[index][2] = _note("respaced", lang, days=cfg["min_gap_days"])', 'picked[index][2] = picked[index][2] + "; " + _note("respaced", lang, days=cfg["min_gap_days"])'),
    ("a founder's own date counts as commitment", S + "/scripts/abp/decode.py", 'return step.get("proposed_by") == "them" or step.get("accepted_by_them") is True', "return True"),
    ("Green without commitment", S + "/scripts/abp/decode.py", 'elif lights["green"] and commitment:', 'elif lights["green"]:'),
    ("Red even with a dated step ahead", S + "/scripts/abp/decode.py", 'if lights["red"] and not future:', 'if lights["red"]:'),
    ("leaning Red no longer needs praise-only", S + "/scripts/abp/decode.py", "(zero_questions or soft_no or only_praise)", "(zero_questions or soft_no)"),
    ("Yellow forced at exactly 14 days", S + "/scripts/abp/decode.py", 'age > table["thresholds"]["yellow_max_age_days"]["value"]', 'age >= table["thresholds"]["yellow_max_age_days"]["value"]'),
    ("re-entry after 30 days, not 10", S + "/scripts/abp/decode.py", "RE_ENTRY_AFTER_DAYS = 10", "RE_ENTRY_AFTER_DAYS = 30"),
    ("quoted questions count as asks", S + "/scripts/abp/mail.py", 'bare = QUOTED.sub(" ", sentence)\n            if "?" not in bare', 'bare = sentence\n            if "?" not in bare'),
    ("either-or inside a quote closes an open ask", S + "/scripts/abp/mail.py", 'bare = norm(QUOTED.sub(" ", sentence))', "bare = norm(sentence)"),
    ("abbreviations match inside words again", S + "/scripts/abp/mail.py", 'r"(?<![A-Za-z])" + re.escape(abbr)', "re.escape(abbr)"),
    ("phrase gap 5 words -> 0", S + "/scripts/abp/phrases.py", "GAP_MAX = 5", "GAP_MAX = 0"),
    ("unknown fact-sheet fields accepted", S + "/scripts/abp/schema.py", '_fail(("%s.%s" % (path, key)).lstrip("."), "unknown field", hint)', "pass"),
    ("seal verify always ok", S + "/scripts/abp/seal.py", 'status = "ok" if not (changed or missing or unlisted) else "broken"', 'status = "ok"'),
    ("seal ignores planted files", S + "/scripts/abp/seal.py", 'if rel not in listed and (rel.split("/")[0] in GUARDED_DIRS or rel.endswith(".py"))', "if False"),
    ("bytecode switch removed", S + "/scripts/playbook.py", 'sys.pycache_prefix = os.path.join(os.path.abspath(__file__), "no-bytecode")', "pass"),
    ("script folder left on the import path", S + "/scripts/playbook.py", 'sys.path[:] = [entry for entry in sys.path if entry not in ("", ".", _HERE)]', "pass"),
    ("interview asks 5 questions per turn", S + "/data/interview.json", '"max_questions_per_turn": 3', '"max_questions_per_turn": 5'),
    ("interview: the date of a next step is no longer a must", S + "/data/interview.json", '"id": "next_step_date", "dimension": "next", "level": {"decode": 1}', '"id": "next_step_date", "dimension": "next", "level": {"decode": 2}'),
    ("interview: an open must no longer holds the run", S + "/scripts/abp/interview.py", 'elif musts_open:\n        status = "ask"', 'elif False:\n        status = "ask"'),
    ("interview: refinements are asked before musts", S + "/scripts/abp/interview.py", 'open_now.sort(key=lambda question: (\n        level[question["id"]],', 'open_now.sort(key=lambda question: (\n        -level[question["id"]],'),
    ("interview: a question is asked where it does not apply", S + "/scripts/abp/interview.py", 'return all(_holds(condition, answers) for condition in question.get("when", []))', "return True"),
    ("interview: a draft no longer eases a must", S + "/scripts/abp/interview.py", 'if ease and level < ease["to"] and all(', 'if False and level < ease["to"] and all('),
    ("interview: a line given twice is decoded twice", S + "/scripts/abp/interview.py", 'target.extend(item for item in feed.get("value", value) if item not in target)', 'target.extend(feed.get("value", value))'),
    ("interview: the printed lines lose the founder's language", S + "/scripts/abp/interview.py", "if lang != DEFAULT_LANG:", "if False:"),
    ("interview: a founder's answer is not one shell word", S + "/scripts/abp/interview.py", "return text if SAFE_WORD.match(text) else", "return text if True else"),
    ("interview: an early stop decodes nothing", S + "/scripts/abp/interview.py", 'first["partial"] = True', 'first["partial"] = False'),
    ("interview: their words may be empty", S + "/scripts/abp/interview.py", '(field == "quotes" and not sheet[field])', '(field == "quotes" and False)'),
    ("interview: what the founder says is not the source", S + "/scripts/abp/interview.py", 'source.extend(line for line in _lines(value) if line not in source)', "pass"),
    ("a political aside counts as a soft no in a scene", S + "/scripts/abp/meeting.py", 'NOT_SOFT_NOS = ("politics", "social_default")', 'NOT_SOFT_NOS = ("social_default",)'),
    ("joining a political remark goes unnoticed", S + "/scripts/abp/meeting.py", 'elif hits:\n                entry["outcome"] = "joined"', 'elif False:\n                entry["outcome"] = "joined"'),
    ("the guide check accepts a line no table has", "tools/guide.py", 'if row["status"] == "missing":', "if False:"),
    # The fact-sheet validator already rejects a currency with blank evidence,
    # so dropping the judge's own filter changes nothing a caller can observe.
    ("a currency counts without evidence", S + "/scripts/abp/decode.py", 'paid = [item for item in facts.get("cost_to_them", []) if item["evidence"].strip()]', 'paid = list(facts.get("cost_to_them", []))'),
]
EQUIVALENT = {"a currency counts without evidence"}
SELF_CHECK = "MutationListTest"


def _run(args, cwd):
    return subprocess.run([sys.executable, "-B"] + args, cwd=cwd, capture_output=True, text=True, timeout=900)


def check(name, rel, old, new):
    """Apply one mutation to a copy of the repository. Returns 'caught', 'missed' or 'stale'."""
    base = tempfile.mkdtemp(prefix="abp-mutation-")
    try:
        work = os.path.join(base, "repo")
        shutil.copytree(_paths.REPO, work, ignore=shutil.ignore_patterns("__pycache__", ".git", "*.skill", "*.zip", "SHA256SUMS"))
        path = os.path.join(work, *rel.split("/"))
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if old not in text:
            return "stale", "the text to replace is no longer in %s" % rel
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.replace(old, new, 1))
        _run(["tools/build_refs.py"], work)
        _run(["tools/audit.py", "--write"], work)
        _run(["tools/seal.py", "--write"], work)
        proc = _run(["-m", "unittest", "discover", "-s", "tests"], work)
        # One test checks that this list still matches the source. It fails in
        # every mutated copy by construction, so it proves nothing here.
        failing = [
            line for line in proc.stderr.split("\n")
            if line.startswith(("FAIL:", "ERROR:")) and "(" in line and SELF_CHECK not in line
        ]
        if not failing:
            return "missed", "no behavior test failed"
        modules = sorted(set(line.split("(")[1].split(".")[0] for line in failing))
        return "caught", "%d failing in %s" % (len(failing), ", ".join(modules))
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="show the mutations and exit")
    args = parser.parse_args()
    if args.list:
        for name, rel, _old, _new in MUTATIONS:
            print("%-48s %s%s" % (name, rel, "  (equivalent)" if name in EQUIVALENT else ""))
        return 0
    if _run(["-m", "unittest", "discover", "-s", "tests"], _paths.REPO).returncode != 0:
        print("The suite fails before any mutation. Fix that first: python3 tools/build.py")
        return 1
    holes = 0
    for name, rel, old, new in MUTATIONS:
        outcome, detail = check(name, rel, old, new)
        if outcome == "missed" and name in EQUIVALENT:
            outcome = "same"
        if outcome in ("missed", "stale"):
            holes += 1
        print("%-7s %-48s %s" % (outcome.upper(), name, detail))
    print("%d mutations, %d holes." % (len(MUTATIONS), holes))
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
