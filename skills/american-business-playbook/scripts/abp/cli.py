"""Command line for the engine. One entry point, one sub-command per job."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, clock, decode, interview, intro, mail, meeting, seal
from .core import (
    EXIT_OK, EXIT_REVISE, EXIT_SEAL, EXIT_USAGE, LANGS, SKILL_ROOT,
    PlaybookError, Receipt, fmt, israel_today, load, parse_date, stamp_line, tr,
)
from .phrases import PhraseSet, merged
from .schema import describe, parse_json

COMMANDS = [
    ("interview", "What to ask the founder next, the picture so far, and the fact sheets for the other commands."),
    ("lint", "Measure an English email draft against the playbook rules."),
    ("template", "Render one of the playbook's email templates; unfilled slots stay as [brackets]."),
    ("send-time", "The next send moments in the recipient's morning window, on both clocks."),
    ("cadence", "The five follow-up touches after a meeting, with dates on both clocks."),
    ("decode", "Decode what an American said and return the traffic-light verdict and the next move."),
    ("prep", "Build the prep sheet for a sales, investor or KOL meeting."),
    ("guard", "Check a talk track or question list for moves that burn a meeting."),
    ("scene", "The scene card for a simulation: character, injected lines, rules."),
    ("debrief", "Score the founder's side of a simulation transcript."),
    ("intro", "Check a warm intro against the intro protocol."),
    ("bench", "Route a topic to the right Dan Launchpad team member."),
    ("schema", "Show the fact sheet a command expects, with an example."),
    ("doctor", "Verify the install: seal, rule tables, clock math."),
]
FACT_COMMANDS = {
    "interview": (interview.SPEC, interview.EXAMPLE),
    "decode": (decode.SPEC, decode.EXAMPLE),
    "prep": (meeting.PREP_SPEC, meeting.PREP_EXAMPLE),
    "debrief": (meeting.DEBRIEF_SPEC, meeting.DEBRIEF_EXAMPLE),
    "intro": (intro.INTRO_SPEC, intro.INTRO_EXAMPLE),
}


def _lab(key, lang, **values):
    return fmt(tr(load("coach")["labels"][key], lang), **values)


def _stdin():
    """Standard input, read only when the caller asked for it with a dash.

    Reading it by default would hang a run that was started with no input on
    a host that leaves the stream open, so the engine never does.
    """
    return sys.stdin.read() if sys.stdin is not None else ""


def _read_text(args):
    path = getattr(args, "file", None)
    if path == "-":
        return _stdin()
    if path:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise PlaybookError("Cannot read %s (%s)." % (path, exc), code="unreadable_file")
    raise PlaybookError("No text given.", "Pass --file draft.txt, or --file - with the text on stdin.", "missing_input")


def _read_facts(args):
    if getattr(args, "json", None) is not None:
        return parse_json(args.json, "--json")
    source = getattr(args, "infile", None)
    if source == "-":
        return parse_json(_stdin(), "stdin")
    if source:
        try:
            with open(source, "r", encoding="utf-8") as handle:
                return parse_json(handle.read(), source)
        except (OSError, UnicodeDecodeError) as exc:
            raise PlaybookError("Cannot read %s (%s)." % (source, exc), code="unreadable_file")
    raise PlaybookError(
        "No fact sheet given.",
        "Pass --in facts.json, --in - with JSON on stdin, or --json '{...}'. Run `playbook.py schema %s` for the fields." % args.command,
        "missing_input",
    )


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=["brief", "json"], default="brief", help="brief = relay-ready text (default); json = full machine output")
    common.add_argument("--lang", choices=list(LANGS), default="he", help="language of the coaching lines (default: he)")
    common.add_argument("--unsealed", action="store_true", help="run even though the integrity seal is broken; the answer is stamped accordingly")

    parser = argparse.ArgumentParser(
        prog="playbook.py",
        description="American Business Playbook engine %s. The model interviews and writes; this judges." % __version__,
        epilog="Every answer ends with a stamp naming the engine version, the rule tables in use and anything that was not checked.",
    )
    parser.add_argument("--version", action="version", version="american-business-playbook %s" % __version__)
    sub = parser.add_subparsers(dest="command", metavar="command")
    helps = dict(COMMANDS)

    p = sub.add_parser("lint", parents=[common], help=helps["lint"], description=helps["lint"])
    p.add_argument("--type", default="cold", choices=mail.types(), help="email type (default: cold)")
    p.add_argument("--file", help="path to the draft, or - to read it from stdin")
    p.add_argument("--source", help="path to the founder's own material (original draft, notes); figures in the draft are checked against it")

    p = sub.add_parser("template", parents=[common], help=helps["template"], description=helps["template"])
    p.add_argument("--id", help="template id")
    p.add_argument("--list", action="store_true", help="list the templates")
    p.add_argument("--set", action="append", default=[], metavar="SLOT=VALUE", help="fill a slot; repeat for more")
    p.add_argument("--tz", help="recipient timezone or city (fills real dates in the scheduling template)")
    p.add_argument("--now", help="current date-time, ISO; a time without offset is read as Israel time")

    p = sub.add_parser("send-time", parents=[common], help=helps["send-time"], description=helps["send-time"])
    p.add_argument("--tz", required=True, help="recipient timezone: ET, CT, MT, PT, AZ, AKT, HT, an IANA name, or a major US city")
    p.add_argument("--now", help="current date-time, ISO; a time without offset is read as Israel time")
    p.add_argument("--count", type=int, default=3, help="how many slots to return (default: 3)")

    p = sub.add_parser("cadence", parents=[common], help=helps["cadence"], description=helps["cadence"])
    p.add_argument("--meeting-date", required=True, help="meeting date, YYYY-MM-DD")
    p.add_argument("--tz", default="ET", help="recipient timezone or city (default: ET)")
    p.add_argument("--today", help="today's date, YYYY-MM-DD; marks overdue touches")
    p.add_argument("--sent", default="", help="comma-separated touches already sent: recap,value,second_angle,breakup,nurture")
    p.add_argument("--ics", metavar="PATH", help="also write the five touches as a calendar file")

    for name in ("interview", "decode", "prep", "debrief", "intro"):
        p = sub.add_parser(name, parents=[common], help=helps[name], description=helps[name])
        p.add_argument("--in", dest="infile", help="path to the fact sheet (JSON), or - for stdin")
        p.add_argument("--json", help="the fact sheet as an inline JSON string")
        if name == "decode":
            p.add_argument("--force", action="store_true", help="give a verdict on a paraphrase; it is stamped provisional")

    p = sub.add_parser("guard", parents=[common], help=helps["guard"], description=helps["guard"])
    p.add_argument("--audience", required=True, choices=meeting.TYPES, help="who the words are aimed at")
    p.add_argument("--file", help="path to the text, or - to read it from stdin")

    p = sub.add_parser("scene", parents=[common], help=helps["scene"], description=helps["scene"])
    p.add_argument("--type", required=True, help="sales, investor or kol")
    p.add_argument("--seed", help="repeatable scene id; defaults to today's date")
    p.add_argument("--region", choices=meeting.REGIONS, help="regional style modifier")
    p.add_argument("--politics", action="store_true", help="the American also drops one political aside, to practice staying out of it")

    p = sub.add_parser("bench", parents=[common], help=helps["bench"], description=helps["bench"])
    p.add_argument("--topic", help="what the founder is stuck on")
    p.add_argument("--flag", help="a coaching flag: pricing_raised_without_model, strategic_fork, investor_thread")
    p.add_argument("--used", type=int, default=0, help="bench nudges already used this session")

    p = sub.add_parser("schema", parents=[common], help=helps["schema"], description=helps["schema"])
    p.add_argument("name", choices=sorted(FACT_COMMANDS), help="command whose fact sheet to describe")

    sub.add_parser("doctor", parents=[common], help=helps["doctor"], description=helps["doctor"])
    return parser


# ---------------------------------------------------------------- commands

def _cmd_lint(args, receipt):
    text = _read_text(args)
    source = None
    if args.source:
        try:
            with open(args.source, "r", encoding="utf-8") as handle:
                source = handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise PlaybookError("Cannot read %s (%s)." % (args.source, exc), code="unreadable_file")
    result = mail.lint(text, args.type, source=source, lang=args.lang, receipt=receipt)
    return result, mail.lint_brief(result, args.lang), EXIT_OK if result["status"] == "pass" else EXIT_REVISE


def _cmd_template(args, receipt):
    templates = load("templates")["templates"]
    if args.list or not args.id:
        result = {"templates": [{"id": t["id"], "type": t["type"], "title": t["title"], "when": t["when"], "slots": sorted(t["slots"])} for t in templates]}
        lines = ["%s (%s): %s\n    %s\n    slots: %s" % (t["id"], t["type"], t["title"], t["when"], ", ".join(sorted(t["slots"]))) for t in templates]
        return result, "\n".join(lines), EXIT_OK
    values = {}
    for pair in args.set:
        if "=" not in pair:
            raise PlaybookError("--set expects SLOT=VALUE (got %r)." % pair, code="bad_set")
        key, value = pair.split("=", 1)
        values[key.strip()] = value.strip()
    template = mail.get_template(args.id)
    slots = None
    if template.get("computed") == "scheduling_slots":
        if args.tz:
            zone = clock.resolve_zone(args.tz)
            now = clock.parse_now(args.now) if args.now else clock.utc_now()
            slots = clock.scheduling_slots(now, zone["code"])
            values.setdefault("their_tz", zone["code"])
            receipt.ran("scheduling_dates")
        else:
            receipt.skip("scheduling_dates", "no --tz given, so the dates stay as [date]")
    rendered = mail.render(args.id, values, slots)
    rendered["lint"] = mail.lint(rendered["text"], rendered["type"], lang=args.lang)
    rendered["israel_slots"] = slots
    lines = [rendered["text"], "", "--- %s (%s)" % (rendered["id"], rendered["type"]), rendered["when"]]
    if rendered["notes"]:
        lines.append(rendered["notes"])
    if rendered["open_slots"]:
        lines.append("%s:" % _lab("missing_slots", args.lang))
        lines.extend("- %s = %s" % (key, label) for key, label in rendered["open_slots"].items())
    if slots:
        lines.append("%s: %s" % (_lab("slots_israel", args.lang), " | ".join("%s = %s" % (slot["line"], slot["israel"]) for slot in slots)))
        for slot in slots:
            if slot["late_in_israel"]:
                lines.append("! %s" % _lab("slot_late", args.lang, line=slot["line"], israel=slot["israel"]))
    other = [item for item in rendered["lint"]["errors"] if item["check"] != "placeholder_left"] + rendered["lint"]["warnings"]
    lines.extend("- [%s] %s" % (item["check"], item["message"]) for item in other)
    receipt.ran("template_render")
    return rendered, "\n".join(lines), EXIT_OK


def _slot_line(slot, lang):
    line = "%s %s %s = %s %s (%s %s %s = %s %s)" % (
        slot["pretty"], slot["local_time"], slot["zone"], slot["israel_time"], _lab("israel", lang),
        _lab("window", lang), slot["window"], slot["zone"], slot["israel_window"], _lab("israel", lang),
    )
    return line


def _cmd_send_time(args, receipt):
    zone = clock.resolve_zone(args.tz)
    now = clock.parse_now(args.now) if args.now else clock.utc_now()
    if not args.now:
        receipt.assume(_lab("now_assumed", args.lang, now=now.strftime("%Y-%m-%d %H:%M")))
    if zone["how"] in ("city", "alias"):
        receipt.assume(_lab("zone_assumed", args.lang, zone=zone["code"], input=zone["input"]))
    count = max(1, min(args.count, 10))
    slots, skipped = clock.next_send_slots(now, zone["code"], count=count, lang=args.lang)
    receipt.ran("send_window")
    receipt.ran("holiday_windows")
    receipt.ran("israel_time")
    result = {"zone": zone, "now_utc": now.strftime("%Y-%m-%dT%H:%MZ"), "slots": slots, "skipped": skipped}
    lines = []
    if slots:
        best = slots[0]
        lines.append("%s: %s" % (_lab("best_send", args.lang), _slot_line(best, args.lang)))
        if best["when"] == "now":
            lines.append("  %s" % _lab("send_now", args.lang))
        if best.get("schedule_send"):
            lines.append("  %s" % _lab("schedule_send", args.lang))
        for note in best["notes"]:
            lines.append("  ! %s" % note["text"])
        if len(slots) > 1:
            lines.append("%s:" % _lab("alternatives", args.lang))
            lines.extend("- %s" % _slot_line(slot, args.lang) for slot in slots[1:])
    for item in skipped:
        lines.append("%s: %s (%s)" % (_lab("skipped_days", args.lang), item["name"], item["date"]))
    return result, "\n".join(lines), EXIT_OK


def _cmd_cadence(args, receipt):
    meeting_date = parse_date(args.meeting_date, "--meeting-date")
    zone = clock.resolve_zone(args.tz)
    today = parse_date(args.today, "--today") if args.today else None
    sent = [item.strip() for item in args.sent.split(",") if item.strip()]
    for item in sent:
        if item not in decode.TOUCHES:
            raise PlaybookError("--sent: unknown touch %r." % item, "Use: %s" % ", ".join(decode.TOUCHES), "bad_touch")
    if today is None:
        receipt.skip("touch_status", "no --today given, so no touch is marked overdue")
    if zone["how"] in ("city", "alias"):
        receipt.assume(_lab("zone_assumed", args.lang, zone=zone["code"], input=zone["input"]))
    touches = clock.cadence(meeting_date, zone["code"], today, sent, lang=args.lang)
    receipt.ran("cadence_windows")
    receipt.ran("holiday_windows")
    receipt.ran("israel_time")
    cfg = load("cadence")
    result = {"meeting_date": meeting_date.isoformat(), "zone": zone, "touches": touches, "rule": tr(cfg["closing_rule"], args.lang)}
    lines = [_lab("cadence_title", args.lang, date=clock.pretty_date(meeting_date), zone=zone["code"])]
    for touch in touches:
        line = "%d. %-13s %s %s %s = %s %s [%s]" % (
            touch["n"], touch["name"], touch["pretty"], touch["local_time"], touch["zone"],
            touch["israel_time"], _lab("israel", args.lang), _lab("status_" + touch["status"], args.lang),
        )
        if touch["next"]:
            line += " " + _lab("next_marker", args.lang)
        lines.append(line)
        detail = "   %s %s. %s" % (_lab("template", args.lang), touch["template"], touch["content"])
        lines.append(detail)
        if touch["note"]:
            lines.append("   (%s)" % touch["note"])
        for note in touch["notes"]:
            lines.append("   ! %s" % note["text"])
    lines.append(result["rule"])
    if args.ics:
        calendar = clock.to_ics(touches, "Follow-up", meeting_date)
        try:
            with open(args.ics, "w", encoding="utf-8", newline="") as handle:
                handle.write(calendar)
        except OSError as exc:
            raise PlaybookError("Cannot write %s (%s)." % (args.ics, exc), code="unwritable_file")
        result["ics"] = os.path.abspath(args.ics)
        lines.append("Calendar file: %s" % result["ics"])
        receipt.ran("ics_export")
    return result, "\n".join(lines), EXIT_OK


def _cmd_decode(args, receipt):
    result = decode.decode(_read_facts(args), args.lang, receipt, force=args.force)
    return result, decode.brief(result, args.lang), EXIT_OK


def _cmd_interview(args, receipt):
    result = interview.plan(_read_facts(args), args.lang, receipt)
    return result, interview.plan_brief(result, args.lang), EXIT_OK


def _cmd_prep(args, receipt):
    result = meeting.prep(_read_facts(args), args.lang, receipt)
    return result, meeting.prep_brief(result, args.lang), EXIT_OK


def _cmd_debrief(args, receipt):
    result = meeting.debrief(_read_facts(args), args.lang, receipt)
    return result, meeting.debrief_brief(result, args.lang), EXIT_OK


def _cmd_intro(args, receipt):
    result = intro.intro(_read_facts(args), args.lang, receipt)
    return result, intro.intro_brief(result, args.lang), EXIT_OK


def _cmd_guard(args, receipt):
    result = meeting.guard(_read_text(args), args.audience, args.lang)
    for rule in result["rules_checked"]:
        receipt.ran(rule)
    return result, meeting.guard_brief(result, args.lang), EXIT_OK if result["status"] == "pass" else EXIT_REVISE


def _cmd_scene(args, receipt):
    card = meeting.scene(args.type, seed=args.seed, region=args.region, lang=args.lang, politics=args.politics)
    if not args.seed:
        receipt.assume(_lab("seed_default", args.lang, seed=card["seed"]))
    receipt.ran("scene_card")
    return card, meeting.scene_brief(card, args.lang), EXIT_OK


def _cmd_bench(args, receipt):
    result = intro.route(args.topic, args.flag, args.used, args.lang)
    receipt.ran("bench_routing")
    return result, intro.route_brief(result, args.lang), EXIT_OK


def _cmd_schema(args, receipt):
    spec, example = FACT_COMMANDS[args.name]
    result = {"command": args.name, "fields": describe(spec), "example": example}
    lines = ["Fact sheet for `%s` (JSON object). Unknown fields are rejected." % args.name, ""]
    lines.extend(result["fields"])
    if args.name == "decode":
        lines.append("")
        lines.append("Signal ids by context (each needs evidence):")
        for context in decode.CONTEXTS:
            ids = decode.signal_ids(context)
            result.setdefault("signals", {})[context] = ids
            for light in ("green", "yellow", "red"):
                if ids[light]:
                    lines.append("  %s/%s: %s" % (context, light, ", ".join(ids[light])))
    if args.name == "interview":
        lines.append("")
        lines.append("Question ids, with the mode and level of each (1 must, 2 sharpens, 3 depth) and how to record the answer:")
        result["questions"] = []
        for question in load("interview")["questions"]:
            where = ", ".join("%s %d" % (mode, level) for mode, level in question["level"].items())
            result["questions"].append({"id": question["id"], "levels": question["level"], "record_as": interview.record_as(question)})
            lines.append("  %s (%s): %s" % (question["id"], where, interview.record_as(question)))
    lines.extend(["", "Example:", json.dumps(example, ensure_ascii=False, indent=2)])
    return result, "\n".join(lines), EXIT_OK


def _self_test():
    """A few fixed cases with known answers. Returns a list of (name, ok)."""
    import datetime as dt

    out = []
    example = [t for t in load("templates")["templates"] if t["id"] == "cold"][0]["example"]
    out.append(("lint: the guide's cold email is clean", mail.lint(example, "cold", lang="en")["status"] == "pass"))
    verdict = decode.decode(dict(decode.EXAMPLE), "en")["verdict"]
    out.append(("decode: compliments with no step are Yellow leaning Red", verdict["light"] == "yellow" and verdict["lean"] == "red"))
    touches = clock.cadence(dt.date(2026, 8, 10), "ET")
    out.append(("cadence: 2026-08-10 gives recap on 2026-08-11", touches[0]["date"] == "2026-08-11"))
    slot = clock.describe_slot("ET", dt.date(2026, 12, 1), dt.time(9, 30))
    out.append(("clock: 09:30 ET on 2026-12-01 is 16:30 in Israel", slot["israel_time"] == "16:30"))
    gap = clock.describe_slot("ET", dt.date(2026, 3, 17), dt.time(9, 30))
    out.append(("clock: the March DST gap week is 15:30 in Israel", gap["israel_time"] == "15:30"))
    guard = meeting.guard("What is your budget for this round?", "investor", "en")
    out.append(("guard: BANT aimed at an investor fails", guard["status"] == "fail"))
    return out


def _compile_all():
    """Compile every phrase pattern in every rule table. Returns the count."""
    count = 0
    decoder = load("decoder")
    for row in decoder["rows"]:
        count += len(PhraseSet(row["patterns"] + [m for m in row.get("counter", []) if m not in ("dated_proposal", "permission_to_say_no")]))
    for hint in decoder["green_hints"]:
        count += len(PhraseSet(hint["patterns"]))
    for level in decoder["compliments"]["levels"]:
        count += len(PhraseSet(level["patterns"] + level.get("extension_patterns", [])))
    count += len(PhraseSet(decoder["permission_to_say_no"]["markers"]))
    email = load("email")
    for key in ("pushy", "command_openers", "directive", "checking_in", "nudge_only", "hurt_tone", "throat_clearing", "formal_greetings", "deck_attached", "linkedin_pitch"):
        count += len(PhraseSet(merged(email[key])))
    for family in email["softeners"].values():
        count += len(PhraseSet(merged(family)))
    meetings = load("meetings")
    for rule in meetings["guards"].values():
        count += len(PhraseSet(rule["patterns"]))
    for item in meetings["israelisms"]["items"]:
        count += len(PhraseSet(item["patterns"]))
    for row in meetings["extra_lines"].values():
        count += len(PhraseSet(row["patterns"] + row["counter"]))
    return count


def _cmd_doctor(args, receipt, seal_report):
    checks = []
    checks.append(("python %d.%d (3.9 or newer needed)" % sys.version_info[:2], sys.version_info >= (3, 9)))
    status = seal_report["status"]
    detail = " (%s)" % seal.explain(seal_report) if status == "broken" else ""
    checks.append(("integrity seal: %s%s" % (status, detail), status == "ok"))
    try:
        count = _compile_all()
        checks.append(("rule tables load and %d phrase patterns compile" % count, True))
    except PlaybookError as exc:
        checks.append(("rule tables: %s" % exc.message, False))
        count = 0
    try:
        gaps = interview.check_bank()
        checks.append(("question bank: %d questions, each tied to a real field%s" % (len(load("interview")["questions"]), "" if not gaps else " (%s)" % "; ".join(gaps[:3])), not gaps))
    except PlaybookError as exc:
        checks.append(("question bank: %s" % exc.message, False))
    try:
        for name, ok in _self_test():
            checks.append((name, ok))
    except Exception as exc:  # a self-test that raises is a failed self-test
        checks.append(("self-test raised %s: %s" % (type(exc).__name__, exc), False))
    result = {"checks": [{"check": name, "ok": ok} for name, ok in checks], "ok": all(ok for _name, ok in checks), "skill_root": SKILL_ROOT}
    lines = ["american-business-playbook %s doctor" % __version__]
    lines.extend("%s  %s" % ("PASS" if ok else "FAIL", name) for name, ok in checks)
    lines.append("All good." if result["ok"] else "Problems found. Reinstall from the release, or run tools/seal.py --write if you edited the files on purpose.")
    receipt.ran("doctor")
    return result, "\n".join(lines), EXIT_OK if result["ok"] else EXIT_REVISE


HANDLERS = {
    "interview": _cmd_interview,
    "lint": _cmd_lint,
    "template": _cmd_template,
    "send-time": _cmd_send_time,
    "cadence": _cmd_cadence,
    "decode": _cmd_decode,
    "prep": _cmd_prep,
    "debrief": _cmd_debrief,
    "intro": _cmd_intro,
    "guard": _cmd_guard,
    "scene": _cmd_scene,
    "bench": _cmd_bench,
    "schema": _cmd_schema,
}


def _print(text, stream=None):
    stream = stream or sys.stdout
    stream.write(text + "\n")


def main(argv=None, seal_report=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    as_json = args.format == "json"
    if seal_report is None:
        seal_report = seal.verify(SKILL_ROOT)
    receipt = Receipt(args.command)
    try:
        if args.command == "doctor":
            result, text, code = _cmd_doctor(args, receipt, seal_report)
        else:
            if seal_report["status"] == "broken" and not args.unsealed:
                payload = seal.refusal(seal_report)
                if as_json:
                    _print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    _print("SEAL BROKEN: %s\n%s" % (payload["message"], payload["hint"]), sys.stderr)
                return EXIT_SEAL
            result, text, code = HANDLERS[args.command](args, receipt)
    except PlaybookError as exc:
        if as_json:
            _print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        else:
            _print("Error: %s" % exc.message, sys.stderr)
            if exc.hint:
                _print("Hint: %s" % exc.hint, sys.stderr)
        return EXIT_USAGE
    seal_label = {"ok": "ok", "absent": "absent", "broken": "BROKEN, run with --unsealed"}[seal_report["status"]]
    today = None
    if isinstance(result, dict) and result.get("today"):
        today = parse_date(result["today"])
    receipt_dict = receipt.as_dict(seal_label, seal.rules_digest(SKILL_ROOT), today or israel_today())
    if as_json:
        _print(json.dumps({"ok": True, "command": args.command, "result": result, "receipt": receipt_dict}, ensure_ascii=False, indent=2, default=str))
    else:
        _print(text)
        for note in receipt_dict["assumptions"]:
            _print("%s: %s" % (_lab("assumptions", args.lang), note))
        _print(stamp_line(receipt_dict, args.lang))
    return code
