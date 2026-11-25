"""The interview: what to ask the founder next, and the picture so far.

The bank in data/interview.json is broad on purpose. This module is what
makes a broad bank usable in a conversation. Given what the founder has
already said, it:

  1. picks the next questions, at most three, musts before refinements,
  2. draws the picture: what is known in each dimension and what is missing,
  3. raises the guide's cautions that the answers so far trigger,
  4. composes the fact sheets and command lines for the other commands.

The model asks, in the founder's language, and records each answer under
the question's id. It does not choose the questions and it does not build a
fact sheet by hand: both are done here, the same way every time.

Three outcomes: `ask` (a must is still open, nothing can run), `run_and_ask`
(the musts are in: run the commands now and keep sharpening), `ready`
(nothing left at this depth, or the founder said stop).

Two things keep a broad bank from becoming an interrogation. A question is
asked only where it applies. And a must can ease: when the founder brought a
draft, the draft answers for the ask and the proof, so those questions drop
to "sharpens" and the rewrite does not wait for them.
"""

from __future__ import annotations

import difflib
import json
import re

from . import decode, intro, meeting
from .core import DEFAULT_LANG, PlaybookError, Receipt, fmt, load, tr
from .schema import check, validate

MODES = ["email", "decode", "prep", "scene", "intro"]
DEPTHS = ["quick", "standard", "deep"]
KINDS = ["text", "choice", "bool", "date", "int", "number", "quotes", "list", "costs", "signals"]
LISTS = ("quotes", "list", "costs", "signals")
ENTRY = "python3 scripts/playbook.py"

# The commands a mode hands off to, the first being the one the mode exists for.
MODE_COMMANDS = {
    "email": ["lint", "send-time", "cadence"],
    "decode": ["decode"],
    "prep": ["prep", "guard"],
    "scene": ["scene"],
    "intro": ["intro"],
}
SHEETS = {"decode": decode.SPEC, "prep": meeting.PREP_SPEC, "intro": intro.INTRO_SPEC}
# `after` names the file the founder or the model has to write before the command can run.
ARGS = {
    "lint": {"needs": ["--type"], "tail": ["--file", "rewrite.txt"], "after": "rewrite"},
    "send-time": {"needs": ["--tz"], "tail": [], "after": None},
    "cadence": {"needs": ["--meeting-date"], "tail": [], "after": None},
    "scene": {"needs": ["--type"], "tail": [], "after": None},
    "guard": {"needs": ["--audience"], "tail": ["--file", "talk.txt"], "after": "talk"},
}
SAFE_WORD = re.compile(r"^[A-Za-z0-9_./:,+=-]+$")

SPEC = {
    "mode": {
        "type": "enum", "values": MODES, "required": True,
        "aliases": {"mail": "email", "meeting": "decode", "thread": "decode", "debrief": "decode", "prepare": "prep", "simulation": "scene", "simulate": "scene"},
        "doc": "What the founder came for: email, decode (a meeting or thread), prep, scene (a simulation) or intro.",
    },
    "answers": {
        "type": "map", "default": {},
        "doc": "What the founder has said so far, keyed by question id. Each question printed by this command says how to record its answer. null means: there is none.",
    },
    "skipped": {
        "type": "list", "items": {"type": "str"}, "default": [],
        "doc": "Ids of questions the founder could not or would not answer. They are not asked again.",
    },
    "depth": {"type": "enum", "values": DEPTHS, "doc": "quick = musts only, standard = musts and what sharpens, deep = the whole bank for this situation."},
    "stop": {"type": "bool", "default": False, "doc": "True when the founder says enough. The commands run with what there is, and the gaps are named."},
    "today": {"type": "date", "doc": "Today's date on the founder's calendar. Passed on to the fact sheets."},
}
EXAMPLE = {
    "mode": "decode",
    "today": "2026-11-24",
    "answers": {
        "context": "sales",
        "quotes": ["This is amazing! Let's keep in touch."],
        "next_step_exists": False,
    },
}


# ------------------------------------------------------------------ answers

def _shape(question):
    """The schema one recorded answer must satisfy."""
    kind = question["kind"]
    if kind == "text":
        return {"type": "str"}
    if kind == "choice":
        return {"type": "enum", "values": question["choices"]}
    if kind == "bool":
        return {"type": "bool"}
    if kind == "date":
        return {"type": "date"}
    if kind == "int":
        return {"type": "int", "min": 0}
    if kind == "number":
        return {"type": "number", "min": 0}
    if kind == "quotes":
        return {"type": "list", "items": {"type": "str"}}
    if kind == "list":
        inner = {"type": "enum", "values": question["choices"]} if question.get("choices") else {"type": "str"}
        return {"type": "list", "items": inner}
    if kind == "costs":
        currencies = [item["id"] for item in load("decoder")["currencies"]]
        return {"type": "list", "items": {"type": "object", "props": {
            "currency": {"type": "enum", "values": currencies, "required": True},
            "evidence": {"type": "str", "required": True},
        }}}
    if kind == "signals":
        return {"type": "list", "items": {"type": "object", "props": {
            "id": {"type": "enum", "values": question["signals"], "required": True},
            "evidence": {"type": "str", "required": True},
        }}}
    raise AssertionError("unknown question kind %r" % kind)


def record_as(question):
    """One line telling the model how to write this answer down."""
    kind = question["kind"]
    if kind == "text":
        return "text"
    if kind == "choice":
        return "one of: %s" % " | ".join(question["choices"])
    if kind == "bool":
        return "true or false"
    if kind == "date":
        return "YYYY-MM-DD, or null when there is none"
    if kind in ("int", "number"):
        return "a number"
    if kind == "quotes":
        return "a list of their lines, word for word"
    if kind == "list":
        return "a list of: %s" % " | ".join(question["choices"]) if question.get("choices") else "a list of short lines"
    if kind == "costs":
        currencies = " | ".join(item["id"] for item in load("decoder")["currencies"])
        return 'a list of {"currency": %s, "evidence": "the concrete thing"}; [] when it cost them nothing' % currencies
    return 'a list of {"id": %s, "evidence": "what happened"}; [] when none of them happened' % " | ".join(question["signals"])


def _clean(answers, questions):
    """Validate every recorded answer. An id the bank does not know is an error, not something to drop."""
    by_id = dict((question["id"], question) for question in questions)
    out = {}
    for key, value in answers.items():
        if key not in by_id:
            close = difflib.get_close_matches(key, list(by_id), n=1)
            raise PlaybookError(
                "answers.%s: the question bank has no question with this id." % key,
                ("Did you mean %r? " % close[0] if close else "") + "Run `playbook.py schema interview` for every id.",
                "unknown_question",
            )
        question = by_id[key]
        if value is None:
            out[key] = [] if question["kind"] in LISTS else None
            continue
        cleaned = check(value, _shape(question), "answers.%s" % key)
        out[key] = cleaned.isoformat() if question["kind"] == "date" else cleaned
    return out


# ------------------------------------------------------------ applicability

def _holds(condition, answers):
    key = condition["q"]
    if key not in answers:
        return False
    if condition.get("answered"):
        return True
    if "is" in condition:
        return answers[key] == condition["is"]
    if "min" in condition:
        return answers[key] is not None and answers[key] >= condition["min"]
    return answers[key] in condition["in"]


def level_of(question, mode, answers):
    """How much this answer matters here: 1 must, 2 sharpens, 3 depth. A must can ease on an earlier answer."""
    level = question["level"][mode]
    ease = question.get("eases")
    if ease and level < ease["to"] and all(_holds(condition, answers) for condition in ease["when"]):
        return ease["to"]
    return level


def applies(question, mode, answers):
    """Does this question belong in this conversation, given what is already known?"""
    if mode not in question["level"]:
        return False
    if "contexts" in question and answers.get("context") not in question["contexts"]:
        return False
    if mode in question.get("when_not_in_modes", []):
        return True
    return all(_holds(condition, answers) for condition in question.get("when", []))


# ------------------------------------------------------------------ handoff

def _put(sheet, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        sheet = sheet.setdefault(part, {})
    sheet[parts[-1]] = value


def _word(value):
    """One shell word. A value with anything unusual in it is single-quoted."""
    text = str(value)
    return text if SAFE_WORD.match(text) else "'%s'" % text.replace("'", "'\\''")


def _gate(command, sheet):
    """The facts this command will refuse to work without that the sheet still lacks."""
    if command == "decode":
        needed = ["context"] + [item["field"] for item in load("signals")["intake"]["questions"] if item["required_for_verdict"]]
    elif command == "prep":
        needed = [item["field"] for item in load("meetings")["prep_intake"]["questions"] if item["required"]]
    else:
        needed = [key for key, spec in SHEETS[command].items() if spec.get("required")]
    # An empty list is an answer (it cost them nothing so far). Only their words cannot be empty.
    return [field for field in needed if sheet.get(field) is None or (field == "quotes" and not sheet[field])]


def _lines(value):
    """A founder's answer as separate lines of text, the way it is saved to a file."""
    parts = value if isinstance(value, list) else str(value).split("\n")
    return [str(part).strip() for part in parts if str(part).strip()]


def compose(mode, answers, today=None):
    """Turn the answers into what the other commands take: fact sheets and argument lists."""
    sheets, flags, source, talk, fed, has_draft = {}, {}, [], [], set(), False
    for question in load("interview")["questions"]:
        value = answers.get(question["id"])
        if question["id"] not in answers or value is None:
            continue
        for feed in question["feeds"]:
            command = feed["command"]
            if "when_is" in feed and value != feed["when_is"]:
                continue
            if "path" in feed:
                # A copy: a later question may add to this list, and the recorded answer must stay as given.
                _put(sheets.setdefault(command, {}), feed["path"], list(value) if isinstance(value, list) else value)
            elif "extend" in feed:
                # The same line given twice, under two questions, is one line.
                target = sheets.setdefault(command, {}).setdefault(feed["extend"], [])
                target.extend(item for item in feed.get("value", value) if item not in target)
            elif "arg" in feed:
                shown = value
                if feed.get("via") == "region":
                    shown = meeting.detect_region(value)
                elif "join" in feed:
                    shown = feed["join"].join(value)
                # A command-line argument is one line: a stray line break in an answer does not travel.
                shown = " ".join(str(shown).split()) if shown is not None else ""
                if not shown:
                    continue
                flags.setdefault(command, {})[feed["arg"]] = shown
            elif "flag" in feed:
                flags.setdefault(command, {})[feed["flag"]] = True
            elif feed.get("source"):
                source.extend(line for line in _lines(value) if line not in source)
            elif feed.get("talk"):
                talk.extend(_lines(value))
            elif feed.get("draft"):
                has_draft = True
            if command in MODE_COMMANDS[mode]:
                fed.add(question["id"])
    handoff = []
    for command in MODE_COMMANDS[mode]:
        if command in SHEETS:
            sheet = sheets.get(command, {})
            if today is not None and "today" in SHEETS[command]:
                sheet["today"] = today.isoformat()
            handoff.append({"command": command, "argv": [command, "--in", "-"], "sheet": sheet, "after": None, "blocked_by": _gate(command, sheet)})
            continue
        given = dict(flags.get(command, {}))
        if command == "cadence" and today is not None and "--meeting-date" in given:
            given["--today"] = today.isoformat()
        argv = [command]
        for name, value in given.items():
            argv.extend([name] if value is True else [name, str(value)])
        blocked = [need for need in ARGS[command]["needs"] if need not in given]
        if command == "lint" and has_draft:
            # The founder's own draft is measured first, as it is, before anything is rewritten.
            handoff.append({"command": command, "argv": argv + ["--file", "draft.txt"], "sheet": None, "after": "draft", "blocked_by": list(blocked)})
        entry = {"command": command, "argv": argv + ARGS[command]["tail"], "sheet": None, "after": ARGS[command]["after"], "blocked_by": blocked}
        if command == "lint" and (source or has_draft):
            entry["argv"] = entry["argv"] + ["--source", "source.txt"]
            entry["source_lines"] = source
            entry["source_has_draft"] = has_draft
        if command == "guard" and talk:
            entry["talk_lines"] = talk
        handoff.append(entry)
    return handoff, fed


# --------------------------------------------------------------------- plan

def plan(data, lang="he", receipt=None):
    """Where the conversation stands: what to ask now, what is known, and what can already run."""
    receipt = receipt or Receipt("interview")
    facts = validate(data, SPEC)
    bank = load("interview")
    mode = facts["mode"]
    depth = facts.get("depth", bank["default_depth"])
    levels = bank["depths"][depth]["levels"]
    weights = bank["weights"]
    answers = _clean(facts["answers"], bank["questions"])
    known_ids = set(question["id"] for question in bank["questions"])
    for item in facts["skipped"]:
        if item not in known_ids:
            raise PlaybookError("skipped: the question bank has no question %r." % item, "Use the id printed with each question.", "unknown_question")
    skipped = set(facts["skipped"]) - set(answers)

    relevant = [question for question in bank["questions"] if applies(question, mode, answers)]
    level = dict((question["id"], level_of(question, mode, answers)) for question in relevant)
    in_depth = [question for question in relevant if level[question["id"]] in levels]
    open_now = [question for question in in_depth if question["id"] not in answers and question["id"] not in skipped]
    lead = bank["lead"].get(mode, [])
    position = dict((question["id"], index) for index, question in enumerate(bank["questions"]))
    open_now.sort(key=lambda question: (
        level[question["id"]],
        lead.index(question["id"]) if question["id"] in lead else len(lead) + position[question["id"]],
    ))
    musts_open = [question for question in open_now if level[question["id"]] == 1]
    deeper = [question for question in relevant if level[question["id"]] not in levels and question["id"] not in answers and question["id"] not in skipped]

    if facts["stop"]:
        status = "ready"
    elif musts_open:
        status = "ask"
    elif open_now:
        status = "run_and_ask"
    else:
        status = "ready"
    receipt.ran("question_bank")

    limit = bank["max_questions_per_turn"]
    ask_next = []
    for question in ([] if facts["stop"] else open_now[:limit]):
        entry = {
            "id": question["id"],
            "question": tr(question["ask"], lang),
            "why": tr(question["why"], lang),
            "level": level[question["id"]],
            "level_label": tr(bank["levels"][str(level[question["id"]])], lang),
            "record_as": record_as(question),
            "voice_ok": bool(question.get("voice_ok")),
        }
        ask_next.append(entry)

    dimensions = []
    for dimension in bank["dimensions"]:
        mine = [question for question in in_depth if question["dimension"] == dimension["id"]]
        if not mine:
            continue
        dimensions.append({
            "id": dimension["id"],
            "label": tr(dimension["label"], lang),
            "known": sum(1 for question in mine if question["id"] in answers),
            "of": len(mine),
            "missing_musts": [question["id"] for question in mine if level[question["id"]] == 1 and question["id"] not in answers],
            "skipped": [question["id"] for question in mine if question["id"] in skipped],
        })
    total = sum(weights[str(level[question["id"]])] for question in in_depth)
    earned = sum(weights[str(level[question["id"]])] for question in in_depth if question["id"] in answers)

    cautions = [
        {"id": item["id"], "text": tr(item["text"], lang)}
        for item in bank["cautions"]
        if mode not in item.get("not_in_modes", []) and all(_holds(condition, answers) for condition in item["when"])
    ]

    handoff, fed = compose(mode, answers, facts.get("today"))
    if lang != DEFAULT_LANG:
        # The lines are run as printed, so they carry the founder's language with them.
        for item in handoff:
            item["argv"][1:1] = ["--lang", lang]
    # A command whose missing argument no question of this conversation can supply is not "not yet".
    # It does not belong here: a cold email has no meeting to count a cadence from.
    reachable = set()
    for question in relevant:
        for feed in question["feeds"]:
            if "arg" in feed:
                reachable.add((feed["command"], feed["arg"]))
    for item in handoff[1:]:
        if item["sheet"] is None and item["blocked_by"] and not any((item["command"], need) in reachable for need in item["blocked_by"]):
            item["out_of_scope"] = True
    first = handoff[0]
    if facts["stop"] and first["command"] == "decode" and first["blocked_by"] and not set(first["blocked_by"]) & set(["context", "quotes"]):
        # A founder who stops early still gets their lines decoded. The decoder itself withholds the verdict and says why.
        first["partial"] = True
    if first["blocked_by"]:
        receipt.skip(first["command"], "the interview has not reached: %s" % ", ".join(first["blocked_by"]))
    if facts["stop"] and (musts_open or open_now):
        receipt.skip("interview_complete", "the founder stopped with %d questions open" % len(open_now))
    notes = [
        {"id": question["id"], "value": answers[question["id"]]}
        for question in bank["questions"]
        if question["id"] in answers and question["id"] not in fed and answers[question["id"]] not in (None, [])
    ]

    result = {
        "mode": mode,
        "mode_label": tr(bank["modes"][mode]["label"], lang),
        "depth": depth,
        "depth_label": tr(bank["depths"][depth]["label"], lang),
        "status": status,
        "stopped": facts["stop"],
        "can_run": not handoff[0]["blocked_by"],
        "ask_next": ask_next,
        "open_musts": [{"id": question["id"], "question": tr(question["ask"], lang), "why": tr(question["why"], lang)} for question in musts_open],
        "picture": {
            "known": sum(1 for question in in_depth if question["id"] in answers),
            "of": len(in_depth),
            "completeness": round(earned / float(total), 2) if total else 1.0,
            "dimensions": dimensions,
        },
        "remaining": {"at_this_depth": max(0, len(open_now) - len(ask_next)), "deeper": len(deeper)},
        # Named so the model can record what the founder already said without asking for it again.
        "waiting": [] if facts["stop"] else [question["id"] for question in open_now[limit:]],
        "cautions": cautions,
        "handoff": handoff,
        "context_notes": notes,
        "answers": answers,
    }
    if "today" in facts:
        result["today"] = facts["today"].isoformat()
    return result


def plan_brief(result, lang="he"):
    labels = load("interview")["labels"]
    lab = lambda key, **values: fmt(tr(labels[key], lang), **values)
    picture = result["picture"]
    lines = [
        lab("title", mode=result["mode_label"], known=picture["known"], total=picture["of"], percent=int(round(picture["completeness"] * 100))),
        "%s: %s" % (lab("depth"), result["depth_label"]),
    ]
    for item in picture["dimensions"]:
        line = "- %s: %d/%d" % (item["label"], item["known"], item["of"])
        if item["missing_musts"]:
            line += " (%s: %s)" % (lab("missing"), ", ".join(item["missing_musts"]))
        if item["skipped"]:
            line += " (%s: %s)" % (lab("skipped"), ", ".join(item["skipped"]))
        lines.append(line)
    if result["cautions"]:
        lines.append("%s:" % lab("cautions"))
        lines.extend("- %s" % item["text"] for item in result["cautions"])
    if result["ask_next"]:
        lines.append("%s:" % lab("ask_next", n=load("interview")["max_questions_per_turn"]))
        for index, item in enumerate(result["ask_next"], 1):
            voice = " (%s)" % lab("voice") if item["voice_ok"] else ""
            lines.append("%d. [%s] %s%s" % (index, item["level_label"], item["question"], voice))
            lines.append("   %s: %s" % (lab("why"), item["why"]))
            lines.append("   answers.%s = %s" % (item["id"], item["record_as"]))
        if result["waiting"]:
            lines.append(lab("more", n=len(result["waiting"]), ids=", ".join(result["waiting"])))
    elif result["stopped"]:
        lines.append(lab("stopped"))
        if result["open_musts"]:
            lines.append("%s:" % lab("open_musts"))
            lines.extend("- %s %s" % (item["question"], item["why"]) for item in result["open_musts"])
    else:
        lines.append(lab("ready"))
    if result["remaining"]["deeper"] and result["status"] == "ready":
        lines.append(lab("deeper", n=result["remaining"]["deeper"]))
    def show(item):
        command = "%s %s" % (ENTRY, " ".join(_word(part) for part in item["argv"]))
        if item["sheet"] is not None:
            lines.append("%s <<'JSON'" % command)
            lines.append(json.dumps(item["sheet"], ensure_ascii=False))
            lines.append("JSON")
        else:
            lines.append(command)

    runnable = [item for item in result["handoff"] if not item["blocked_by"]]
    blocked = [item for item in result["handoff"] if item["blocked_by"]]
    if runnable and result["status"] != "ask":
        now = [item for item in runnable if not item["after"]]
        if now:
            lines.append("%s:" % lab("run"))
        for item in now + [item for item in runnable if item["after"]]:
            if item.get("talk_lines"):
                lines.append("%s:" % lab("talk_file"))
            elif item["after"]:
                lines.append("%s:" % lab("after_" + item["after"]))
            show(item)
            if "source_lines" in item:
                key = "source_draft" if item["source_has_draft"] and not item["source_lines"] else "source_both" if item["source_has_draft"] else "source_file"
                lines.append(lab(key) + (":" if item["source_lines"] else ""))
                lines.extend("  %s" % line for line in item["source_lines"])
            if item.get("talk_lines"):
                lines.append("talk.txt:")
                lines.extend("  %s" % line for line in item["talk_lines"])
    for item in blocked:
        if item.get("partial"):
            lines.append("%s:" % lab("partial", fields=", ".join(item["blocked_by"])))
            show(item)
        elif item.get("out_of_scope"):
            continue
        elif item is result["handoff"][0] or result["status"] != "ask":
            lines.append(lab("not_yet", command=item["command"], fields=", ".join(item["blocked_by"])))
    if result["context_notes"]:
        lines.append("%s:" % lab("notes"))
        for item in result["context_notes"]:
            value = item["value"]
            shown = "; ".join(str(part) for part in value) if isinstance(value, list) else str(value)
            lines.append("- %s: %s" % (item["id"], shown))
    return "\n".join(lines)


# ---------------------------------------------------------------- integrity

def _paths(spec, prefix=""):
    """Every field path a fact-sheet spec accepts, with the spec of each."""
    out = {}
    for key, item in spec.items():
        path = prefix + key
        out[path] = item
        if item["type"] == "object":
            out.update(_paths(item["props"], path + "."))
    return out


def _bad_conditions(name, conditions, by_id):
    """Conditions that name no question, test nothing, or can never hold. The last kind hides a question for good."""
    problems = []
    for condition in conditions:
        target = by_id.get(condition["q"])
        if target is None:
            problems.append("%s: its condition names %s, which is not a question" % (name, condition["q"]))
        elif not any(key in condition for key in ("is", "in", "min", "answered")):
            problems.append("%s: its condition on %s tests nothing" % (name, condition["q"]))
        elif "min" in condition and target["kind"] not in ("int", "number"):
            problems.append("%s: a minimum needs a number, and %s is not one" % (name, condition["q"]))
        elif target["kind"] == "choice":
            for value in ([condition["is"]] if "is" in condition else condition.get("in", [])):
                if value not in target["choices"]:
                    problems.append("%s: %s can never be %r" % (name, condition["q"], value))
        elif target["kind"] == "bool" and "is" in condition and not isinstance(condition["is"], bool):
            problems.append("%s: %s is yes or no, and can never be %r" % (name, condition["q"], condition["is"]))
    return problems


def check_bank():
    """Problems in the bank itself: a question that fills no real field is a question for nothing."""
    bank = load("interview")
    problems, seen = [], set()
    dimensions = set(item["id"] for item in bank["dimensions"])
    ids = [question["id"] for question in bank["questions"]]
    by_id = dict((question["id"], question) for question in bank["questions"])
    all_signals = set()
    for context in decode.CONTEXTS:
        for group in decode.signal_ids(context).values():
            all_signals.update(group)
    for question in bank["questions"]:
        name = question["id"]
        if name in seen:
            problems.append("%s: the id is used twice" % name)
        seen.add(name)
        if question["dimension"] not in dimensions:
            problems.append("%s: unknown dimension %s" % (name, question["dimension"]))
        if question["kind"] not in KINDS:
            problems.append("%s: unknown kind %s" % (name, question["kind"]))
        if not question["level"] or any(mode not in MODES or level not in (1, 2, 3) for mode, level in question["level"].items()):
            problems.append("%s: level must map modes to 1, 2 or 3" % name)
        if question["kind"] == "choice" and not question.get("choices"):
            problems.append("%s: a choice question needs choices" % name)
        for signal in question.get("signals", []):
            if signal not in all_signals:
                problems.append("%s: %s is not a signal of the traffic light" % (name, signal))
        for context in question.get("contexts", []):
            if context not in decode.CONTEXTS:
                problems.append("%s: unknown context %s" % (name, context))
            for signal in question.get("signals", []):
                listed = [item for group in decode.signal_ids(context).values() for item in group]
                if signal not in listed:
                    problems.append("%s: %s is not a %s signal" % (name, signal, context))
        for condition in question.get("when", []):
            if condition["q"] in ids and ids.index(condition["q"]) > ids.index(name):
                problems.append("%s: it depends on %s, which comes later in the bank" % (name, condition["q"]))
        problems.extend(_bad_conditions(name, question.get("when", []) + (question.get("eases") or {}).get("when", []), by_id))
        ease = question.get("eases")
        if ease is not None:
            if ease.get("to") not in (2, 3) or not ease.get("when"):
                problems.append("%s: eases needs a level to drop to (2 or 3) and a condition" % name)
            for condition in ease.get("when", []):
                if condition["q"] not in ids or ids.index(condition["q"]) > ids.index(name):
                    problems.append("%s: it eases on %s, which is not an earlier question" % (name, condition["q"]))
        for language in ("en", "he"):
            if not question["ask"].get(language, "").strip() or not question["why"].get(language, "").strip():
                problems.append("%s: the question and its reason are needed in %s" % (name, language))
        for feed in question["feeds"]:
            command = feed["command"]
            if command in SHEETS:
                paths = _paths(SHEETS[command])
                target = feed.get("path") or feed.get("extend")
                if target not in paths:
                    problems.append("%s: %s has no field %s" % (name, command, target))
                elif "extend" in feed and paths[target]["type"] != "list":
                    problems.append("%s: %s.%s is not a list" % (name, command, target))
            elif command not in ARGS:
                problems.append("%s: feeds an unknown command %s" % (name, command))
            elif feed.get("source") and (command != "lint" or question["kind"] not in ("text", "quotes", "list")):
                problems.append("%s: only a text answer can become a source line for lint" % name)
            elif feed.get("talk") and (command != "guard" or question["kind"] != "text"):
                problems.append("%s: only a text answer can become the talk track for guard" % name)
            elif feed.get("draft") and command != "lint":
                problems.append("%s: only lint measures a draft" % name)
            elif not any(key in feed for key in ("arg", "flag", "source", "talk", "draft")):
                problems.append("%s: its feed to %s names no argument" % (name, command))
    for item in bank["cautions"]:
        problems.extend(_bad_conditions("caution %s" % item["id"], item["when"], by_id))
    for mode, names in bank["lead"].items():
        if mode.startswith("_"):
            continue
        for name in names:
            if name not in ids:
                problems.append("lead.%s: names %s, which is not a question" % (mode, name))
    return problems
