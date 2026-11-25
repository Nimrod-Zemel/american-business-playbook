"""Meeting prep, the guard, simulation scenes and the debrief score.

The model plays the American in a simulation; nothing here writes dialogue.
This module decides what the model is not allowed to decide for itself: which
framework applies (and that BANT never runs on an investor), which lines get
injected, and how the founder's side of the transcript scores.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re

from . import clock
from .core import PlaybookError, Receipt, fmt, israel_today, label, load, tr
from .decode import CURRENCIES
from .phrases import PhraseSet, norm
from .schema import validate

TYPES = ["sales", "investor", "kol"]
TYPE_ALIASES = {
    "customer": "sales", "partner": "sales", "prospect": "sales", "client": "sales",
    "vc": "investor", "angel": "investor", "fund": "investor",
    "expert": "kol", "domain_expert": "kol", "advisor": "kol",
}
REGIONS = ["new_york", "west_coast", "midwest_south", "other"]
HEBREW = re.compile(r"[\u0590-\u05ff]")
DATED = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|tomorrow|next week|this week|end of (?:the )?week|eow"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}"
    r"|\d{1,2}(?:st|nd|rd|th)|\d{1,2}/\d{1,2}|\d{1,2}(?::\d{2})? ?(?:am|pm))\b",
    re.IGNORECASE,
)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
NOT_SOFT_NOS = ("politics", "social_default")
CLARITY_MARKERS = [
    "what would you need to see", "strong yes", "specific number", "process from here",
    "your process", "realistic timeline", "consider following", "what would need to change",
]

PREP_SPEC = {
    "type": {"type": "enum", "values": TYPES, "aliases": TYPE_ALIASES, "doc": "sales (customer or partner), investor, or kol (domain expert). Mandatory: it decides the framework."},
    "goal_currency": {"type": "enum", "values": CURRENCIES, "doc": "What the founder wants to walk out with."},
    "goal": {"type": "str", "doc": "The goal in the founder's words."},
    "the_ask": {"type": "str", "doc": "The one ask the founder will make before the meeting ends."},
    "city": {"type": "str", "doc": "Where the American is based."},
    "region": {"type": "enum", "values": REGIONS, "doc": "Overrides the region guessed from the city."},
    "tz": {"type": "str", "doc": "Recipient timezone, when the city does not settle it."},
    "meeting_minutes": {"type": "int", "min": 10, "max": 180, "default": 30},
    "meeting_date": {"type": "date"},
    "today": {"type": "date"},
    "counterpart": {"type": "object", "props": {
        "name": {"type": "str"},
        "role": {"type": "str"},
        "org": {"type": "str"},
    }},
    "meeting_number": {"type": "int", "min": 1, "default": 1, "doc": "1 for a first meeting."},
    "live_thread": {"type": "bool", "default": False, "doc": "True when a fundraise is actively running."},
    "background": {"type": "str", "doc": "Relationship history, in the founder's words."},
    "bench_used": {"type": "int", "min": 0, "default": 0},
}
PREP_EXAMPLE = {
    "type": "investor",
    "goal_currency": "calendar_time",
    "goal": "a second meeting with a second partner",
    "the_ask": "What would you need to see for this to be a strong yes?",
    "city": "New York",
    "meeting_minutes": 30,
    "meeting_date": "2026-12-02",
    "counterpart": {"name": "Jennifer", "role": "Partner", "org": "a US seed fund"},
}

DEBRIEF_SPEC = {
    "type": {"type": "enum", "values": TYPES, "aliases": TYPE_ALIASES, "required": True},
    "injected": {"type": "list", "items": {"type": "str"}, "doc": "Row ids from the scene card. Omit and pass seed instead to recompute them."},
    "seed": {"type": "str", "doc": "The seed printed on the scene card."},
    "turns": {
        "type": "list", "required": True, "max_items": 400,
        "doc": "The transcript, in order.",
        "items": {"type": "object", "props": {
            "who": {"type": "enum", "values": ["founder", "american"], "required": True},
            "text": {"type": "str", "required": True},
        }},
    },
    "outcome": {"type": "object", "doc": "How the conversation ended, as the American character saw it.", "props": {
        "result": {"type": "enum", "values": ["dated_step", "clean_no", "vague"], "required": True},
    }},
    "bench_used": {"type": "int", "min": 0, "default": 0},
}
DEBRIEF_EXAMPLE = {
    "type": "sales",
    "seed": "2026-11-24",
    "turns": [
        {"who": "american", "text": "This is really interesting!"},
        {"who": "founder", "text": "Thanks. Would Tuesday or Thursday work for a 20-minute follow-up with your data lead?"},
        {"who": "american", "text": "Send me a deck and I'll take a look."},
        {"who": "founder", "text": "Happy to send a one-pager today. Would Thursday at 10am work to walk through it?"},
    ],
    "outcome": {"result": "dated_step"},
}

_SETS = {}


def _set(key, patterns):
    if key not in _SETS:
        _SETS[key] = PhraseSet(patterns)
    return _SETS[key]


def _pick(seed, slot, options):
    """Version-independent deterministic choice."""
    digest = hashlib.sha256(("%s|%s" % (seed, slot)).encode("utf-8")).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def detect_region(city):
    key = " ".join(str(city or "").lower().replace(".", "").replace(",", " ").split())
    if not key:
        return None
    for region_id, region in load("meetings")["regions"].items():
        for alias in region["aliases"]:
            if key == alias or key.startswith(alias + " "):
                return region_id
    return None


def _row(row_id):
    for row in load("decoder")["rows"]:
        if row["id"] == row_id:
            return row
    extra = load("meetings")["extra_lines"]
    if row_id in extra:
        row = dict(extra[row_id])
        row["id"] = row_id
        return row
    raise PlaybookError("Unknown decoder row %r." % row_id, code="unknown_row")


def soft_nos_for(kind, lang):
    """The soft-nos to expect in a meeting of this type, with the counter-move."""
    rows = []
    if kind == "kol":
        rows.append(_row("its_great"))
    for row in load("decoder")["rows"]:
        if not row["patterns"] or kind not in row["contexts"] or row["lean"] == "green":
            continue
        if kind == "investor" and row["table"] != "investor_speak":
            continue
        if kind != "investor" and row["table"] == "investor_speak":
            continue
        if kind == "kol" and row["table"] == "traffic_light_phrase":
            continue
        if row["table"] in NOT_SOFT_NOS:
            continue
        rows.append(row)
    out = []
    for row in rows:
        move = row["move"]
        if kind in row.get("move_by_context", {}):
            move = row["move_by_context"][kind]
        out.append({"row": row["id"], "said": row["said"], "means": tr(row["means"], lang), "move": tr(move, lang)})
    return out


# -------------------------------------------------------------------- prep

def prep(data, lang="he", receipt=None):
    """Build the prep sheet, or return the intake questions that are still open."""
    receipt = receipt or Receipt("prep")
    facts = validate(data, PREP_SPEC)
    meetings = load("meetings")
    intake = meetings["prep_intake"]
    missing, optional = [], []
    for question in intake["questions"]:
        if question["field"] in facts:
            continue
        entry = {"id": question["id"], "field": question["field"], "question": tr(question, lang), "voice_ok": question["voice_ok"]}
        if question["voice_ok"]:
            entry["invite"] = tr(load("signals")["intake"]["voice_note_invite"], lang)
        (missing if question["required"] else optional).append(entry)
    ask_next = (missing + optional)[:intake["max_questions_per_turn"]]
    if "type" not in facts:
        receipt.skip("prep_sheet", "the meeting type is unknown; classification comes first")
        return {"status": "needs_intake", "ask_next": ask_next, "sheet": None, "hard_rule": None}
    if missing:
        receipt.skip("prep_sheet", "intake incomplete: %s" % ", ".join(item["field"] for item in missing))
        return {"status": "needs_intake", "type": facts["type"], "ask_next": ask_next, "sheet": None, "hard_rule": tr(meetings["hard_rule"], lang) if facts["type"] == "investor" else None}

    kind = facts["type"]
    spec = meetings["types"][kind]
    minutes = facts["meeting_minutes"]
    end_at = minutes - 2
    region = facts.get("region") or detect_region(facts.get("city"))
    if region is None:
        region = "other"
        receipt.assume(label("coach", "no_region", lang))
    elif "region" not in facts:
        receipt.assume(fmt(label("coach", "region_assumed", lang), region=region, input=facts["city"]))
    region_cfg = meetings["regions"][region]
    currencies = dict((item["id"], item) for item in load("decoder")["currencies"])

    sheet = {
        "type": kind,
        "type_label": tr(spec["label"], lang),
        "mindset": tr(spec["mindset"], lang),
        "framework": tr(spec["framework"], lang),
        "bant": spec["bant"],
        "hard_rule": tr(meetings["hard_rule"], lang) if kind == "investor" else None,
        "goal": {
            "currency": facts["goal_currency"],
            "currency_label": tr(currencies[facts["goal_currency"]], lang),
            "text": facts.get("goal", ""),
            "rule": tr(meetings["goal_rule"], lang),
        },
        "the_ask": facts["the_ask"],
        "timebox": {
            "minutes": minutes,
            "end_at": end_at,
            "opening": fmt(meetings["conduct"]["frame"]["template"], minutes=minutes) if kind == "sales" else None,
            "hard_stop": meetings["conduct"]["hard_stop"]["said"],
        },
        "small_talk": {
            "why": meetings["small_talk"]["why"],
            "safe": meetings["small_talk"]["safe_he" if lang == "he" else "safe"],
            "forbidden": meetings["small_talk"]["forbidden_he" if lang == "he" else "forbidden"],
            "region": region,
            "region_label": tr(region_cfg["label"], lang),
            "modifier": tr(region_cfg["modifier"], lang),
            "bridge_line": meetings["small_talk"]["bridge"]["line"],
            "how_are_you": meetings["small_talk"]["how_are_you"]["answer"],
        },
        "conduct": [tr(meetings["conduct"]["turn_taking"], lang), tr(meetings["conduct"]["enthusiasm"], lang)],
        "politics": {
            "rule": tr(meetings["politics"]["iron_rule"], lang),
            "acknowledge": meetings["politics"]["acknowledge"][0],
            "bridge": meetings["politics"]["bridge"],
        },
        "around": [tr(rule, lang) for rule in meetings["rapid_fire"]["rules"]],
        "soft_nos": soft_nos_for(kind, lang),
        "closing_rule": meetings["sales"]["mechanics"][-1],
    }
    if kind == "sales":
        sheet["bant_table"] = meetings["sales"]["bant"]
        sheet["bant_note"] = meetings["sales"]["bant_note"]
        sheet["mechanics"] = [fmt(line, minutes=minutes, end_at=end_at) for line in meetings["sales"]["mechanics"]]
        sheet["permission_lines"] = load("decoder")["permission_to_say_no"]["lines"]
    elif kind == "investor":
        block = meetings["investor"]
        sheet["demonstrate"] = block["demonstrate"]
        sheet["may_ask"] = block["may_ask"]
        sheet["pass_is_relationship"] = block["pass_is_relationship"]
        role = norm(facts.get("counterpart", {}).get("role", ""))
        active = {"always"}
        if "associate" in role or "analyst" in role:
            active.add("associate")
        if facts["meeting_number"] >= 2:
            active.add("second_meeting")
        if facts["live_thread"]:
            active.add("live_thread")
        sheet["advanced"] = [
            {"id": key, "title": item["title"], "text": item["text"]}
            for key, item in block["advanced"].items() if item["when"] in active
        ]
    else:
        block = meetings["kol"]
        sheet["premise"] = block["premise"]
        sheet["opening_line"] = block["opening"]
        sheet["extraction_bank"] = block["extraction_bank"]
        sheet["mom_test"] = block["mom_test"]
        sheet["techniques"] = block["techniques"]
    receipt.ran("framework_by_type")

    recap = None
    if "meeting_date" in facts:
        zone_text = facts.get("tz") or facts.get("city")
        try:
            zone = clock.resolve_zone(zone_text) if zone_text else None
        except PlaybookError:
            zone = None
        if zone:
            touches = clock.cadence(facts["meeting_date"], zone["code"], lang=lang)
            recap = touches[0]
            receipt.ran("recap_date")
            if zone["how"] in ("city", "alias"):
                receipt.assume(fmt(label("coach", "zone_assumed", lang), zone=zone["code"], input=zone["input"]))
        else:
            receipt.skip("recap_date", "no timezone could be read from tz or city")
    else:
        receipt.skip("recap_date", "no meeting_date given")
    sheet["recap"] = recap

    bench = None
    bench_cfg = load("bench")
    if kind == "investor" and bench_cfg["enabled"] and facts["bench_used"] < bench_cfg["max_nudges_per_session"]:
        dana = [person for person in bench_cfg["people"] if person["id"] == "dana"]
        if dana:
            bench = {"person": "dana", "name": dana[0]["name"], "form": "referral", "nudge_he": dana[0]["sample_nudge_he"]}
    return {"status": "ready", "type": kind, "ask_next": optional[:1], "sheet": sheet, "bench": bench}


def prep_brief(result, lang="he"):
    coach = load("coach")
    lab = lambda key, **kw: fmt(tr(coach["labels"][key], lang), **kw)
    lines = []
    if result["status"] == "needs_intake":
        if result.get("hard_rule"):
            lines.append(result["hard_rule"])
        lines.append("%s:" % lab("ask_next", n=load("meetings")["prep_intake"]["max_questions_per_turn"]))
        for index, entry in enumerate(result["ask_next"], 1):
            line = "%d. %s" % (index, entry["question"])
            if entry.get("invite"):
                line += " (%s)" % entry["invite"]
            lines.append(line)
        return "\n".join(lines)
    sheet = result["sheet"]
    lines.append("%s: %s" % (lab("prep_title"), sheet["type_label"]))
    lines.append("%s: %s" % (lab("mindset"), sheet["mindset"]))
    lines.append("%s: %s" % (lab("framework"), sheet["framework"]))
    if sheet["hard_rule"]:
        lines.append("%s %s" % (lab("bant_off"), sheet["hard_rule"]))
    goal = sheet["goal"]
    lines.append("%s: %s%s" % (lab("goal"), goal["currency_label"], (" - " + goal["text"]) if goal["text"] else ""))
    lines.append('%s: "%s"' % (lab("the_ask"), sheet["the_ask"]))
    box = sheet["timebox"]
    lines.append(lab("timebox", minutes=box["minutes"], end_at=box["end_at"]))
    if box["opening"]:
        lines.append('  %s: "%s"' % (lab("open_with"), box["opening"]))
    lines.append('  %s: "%s"' % (lab("hard_stop"), box["hard_stop"]))
    talk = sheet["small_talk"]
    lines.append("%s (%s): %s" % (lab("small_talk"), talk["region_label"], talk["modifier"]))
    lines.append("  %s: %s | %s: %s" % (lab("safe"), ", ".join(talk["safe"]), lab("forbidden"), ", ".join(talk["forbidden"])))
    lines.append('  %s: "%s" | "How are you?" -> "%s"' % (lab("bridge_line"), talk["bridge_line"], talk["how_are_you"]))
    lines.append("%s: %s" % (lab("politics"), sheet["politics"]["rule"]))
    lines.append('  "%s" -> "%s"' % (sheet["politics"]["acknowledge"], sheet["politics"]["bridge"]))
    lines.append("%s:" % lab("in_the_room"))
    lines.extend("- %s" % item for item in sheet["conduct"])
    if sheet["type"] == "sales":
        lines.append("%s:" % lab("bant_heading"))
        for row in sheet["bant_table"]:
            lines.append("- %s: %s. %s" % (row["letter"], row["learn"], row["phrasing"]))
        lines.append("%s:" % lab("mechanics"))
        lines.extend("- %s" % item for item in sheet["mechanics"])
    elif sheet["type"] == "investor":
        lines.append("%s:" % lab("demonstrate"))
        lines.extend("- %s" % item for item in sheet["demonstrate"])
        lines.append("%s:" % lab("may_ask"))
        lines.extend('- "%s"' % item["q"] for item in sheet["may_ask"])
        for item in sheet["advanced"]:
            lines.append("%s: %s" % (item["title"], item["text"]))
        lines.append(sheet["pass_is_relationship"])
    else:
        lines.append('%s: "%s"' % (lab("open_door"), sheet["opening_line"]))
        lines.append("%s:" % lab("extraction_bank"))
        lines.extend('- "%s"' % item for item in sheet["extraction_bank"])
        lines.append("%s:" % sheet["mom_test"]["title"])
        lines.extend('- "%s"' % item for item in sheet["mom_test"]["ask"])
        lines.append("- %s" % sheet["mom_test"]["never"])
        lines.append("%s:" % lab("techniques"))
        lines.extend("- %s" % item for item in sheet["techniques"])
    lines.append("%s:" % lab("soft_nos"))
    for row in sheet["soft_nos"]:
        lines.append('- "%s" -> %s. %s: %s' % (row["said"], row["means"], lab("move"), row["move"]))
    lines.append(sheet["closing_rule"])
    lines.append("%s:" % lab("around_meeting"))
    lines.extend("- %s" % item for item in sheet["around"])
    if sheet["recap"]:
        recap = sheet["recap"]
        lines.append("%s: %s (%s recap) %s %s %s = %s %s" % (
            lab("after"), recap["name"], lab("template"), recap["pretty"], recap["local_time"], recap["zone"], recap["israel_time"], lab("israel"),
        ))
    if result.get("bench"):
        lines.append("%s (%s): %s" % (lab("bench"), result["bench"]["name"], result["bench"]["nudge_he"]))
    lines.append(lab("simulate_offer"))
    return "\n".join(lines)


# ------------------------------------------------------------------- guard

def israelisms(lines):
    """Blunt founder wordings found in the given lines, with the American phrasing."""
    out = []
    for item in load("meetings")["israelisms"]["items"]:
        regexes = _set("isr:" + item["id"], item["patterns"])
        excluded = [norm(text) for text in item.get("except", [])]
        for line in lines:
            for sentence in SENTENCE_END.split(line):
                normalized = norm(sentence)
                if not normalized or any(normalized.startswith(skip) for skip in excluded):
                    continue
                hit = regexes.starts(normalized, True) if item.get("start_only") else (regexes.hits(normalized, True) or [None])[0]
                if hit:
                    entry = {"id": item["id"], "said": sentence.strip(), "american": item["american"], "origin": item["origin"]}
                    if not any(old["id"] == entry["id"] and old["said"] == entry["said"] for old in out):
                        out.append(entry)
    return out


def guard(text, audience, lang="he"):
    """Check a talk track, a question list or the founder's lines against the guard rules."""
    if audience not in TYPES:
        raise PlaybookError("Unknown audience %r." % audience, "Use one of: %s" % ", ".join(TYPES), "bad_audience")
    normalized = norm(text)
    violations = []
    for guard_id, rule in load("meetings")["guards"].items():
        if audience not in rule["audience"]:
            continue
        hits = _set("guard:" + guard_id, rule["patterns"]).hits(normalized, True)
        if hits:
            violations.append({
                "guard": guard_id,
                "level": rule["level"],
                "hits": hits,
                "message": fmt(tr(rule["message"], lang), hits=", ".join('"%s"' % hit for hit in hits)),
            })
    lines = [line for line in text.replace("\r", "").split("\n") if line.strip()]
    found = israelisms(lines)
    hebrew = bool(HEBREW.search(text))
    status = "fail" if any(item["level"] == "error" for item in violations) else "pass"
    return {
        "audience": audience,
        "status": status,
        "violations": violations,
        "israelisms": found,
        "hebrew": hebrew,
        "rules_checked": [key for key, rule in load("meetings")["guards"].items() if audience in rule["audience"]],
    }


def guard_brief(result, lang="he"):
    lines = ["Guard (%s): %s" % (result["audience"], result["status"])]
    for item in result["violations"]:
        lines.append("- [%s/%s] %s" % (item["level"], item["guard"], item["message"]))
    if result["israelisms"]:
        lines.append(tr(load("meetings")["debrief"]["labels"]["israelisms"], lang) + ":")
        for item in result["israelisms"]:
            lines.append('- "%s" -> %s' % (item["said"], item["american"]))
    if not result["violations"] and not result["israelisms"]:
        lines.append("- %s" % ", ".join(result["rules_checked"]))
    return "\n".join(lines)


# ------------------------------------------------------------------- scene

def scene(kind, seed=None, region=None, today=None, lang="he", politics=False):
    """The scene card for a simulation: the character, the injected lines, the rules.

    With politics=True the American also drops one political aside, so the
    founder can practice staying out of it. It is off by default: the same
    seed keeps giving the same scene."""
    if kind in TYPE_ALIASES:
        kind = TYPE_ALIASES[kind]
    if kind not in TYPES:
        raise PlaybookError(
            "Unknown meeting type %r." % kind,
            "Classify the meeting first: %s." % ", ".join(TYPES),
            "bad_type",
        )
    meetings = load("meetings")
    if seed is None:
        seed = (today or israel_today()).isoformat()
    seed = str(seed)
    character = meetings["characters"][meetings["types"][kind]["character"]]
    injected = []
    for slot in ("sugar", "deferral"):
        row = _row(_pick(seed, slot, character[slot]))
        injected.append({
            "slot": "sugar_coated_no" if slot == "sugar" else "vague_deferral",
            "row": row["id"],
            "line": row.get("scene_line", row["said"]),
            "means": tr(row["means"], lang),
            "move": tr(row["move"], lang),
            "scored": True,
        })
    for probe in character.get("probes", []):
        row = _row(probe)
        injected.append({
            "slot": "probe",
            "row": row["id"],
            "line": row["said"],
            "means": tr(row["means"], lang),
            "move": tr(row["move"], lang),
            "scored": False,
        })
    if politics:
        row = _row(meetings["politics"]["asides"][kind])
        injected.append({
            "slot": "politics_aside",
            "row": row["id"],
            "line": row["said"],
            "means": tr(row["means"], lang),
            "move": tr(row["move"], lang),
            "scored": False,
        })
    region_cfg = meetings["regions"].get(region or "", None)
    rules = meetings["simulation_rules"]
    return {
        "type": kind,
        "seed": seed,
        "bant": meetings["types"][kind]["bant"],
        "character": {
            "name": character["name"],
            "role": character["role"],
            "sheet": character["sheet"],
            "opener": character["opener"],
            "rewards": character["rewards"],
            "punishes": character["punishes"],
        },
        "inject": injected,
        "region": {"id": region, "modifier": tr(region_cfg["modifier"], "en")} if region_cfg else None,
        "rules": rules["en"],
        "setup_line": fmt(tr(rules["setup_line"], lang), name=character["name"], role=character["role"]),
        "start_exception": tr(rules["start_exception"], lang),
        "debrief_with": {"type": kind, "seed": seed, "injected": [item["row"] for item in injected]},
    }


def scene_brief(card, lang="he"):
    lines = [
        "Scene card (%s, seed %s)" % (card["type"], card["seed"]),
        "Setup line: %s" % card["setup_line"],
        "Play: %s, %s." % (card["character"]["name"], card["character"]["role"]),
        card["character"]["sheet"],
        "Open with: %s" % card["character"]["opener"],
    ]
    if card["region"]:
        lines.append("Region: %s" % card["region"]["modifier"])
    lines.append("Inject, once each, verbatim, at a natural moment:")
    for item in card["inject"]:
        lines.append('- [%s] "%s"' % (item["slot"], item["line"]))
    lines.append("Rewards: %s" % "; ".join(card["character"]["rewards"]))
    lines.append("Punishes: %s" % card["character"]["punishes"])
    lines.append("Rules:")
    lines.extend("- %s" % rule for rule in card["rules"])
    lines.append(card["start_exception"])
    lines.append("After STOP: run debrief with type=%s seed=%s and the full transcript." % (card["type"], card["seed"]))
    return "\n".join(lines)


# ----------------------------------------------------------------- debrief

def _countered(row, replies):
    """True when one of the founder's replies uses the table's counter-move."""
    permission = _set("permission", load("decoder")["permission_to_say_no"]["markers"])
    joined = " ".join(replies)
    normalized = norm(joined)
    plain = [marker for marker in row.get("counter", []) if marker not in ("dated_proposal", "permission_to_say_no")]
    if plain and _set("counter:" + row["id"], plain).any(normalized, True):
        return True
    if "dated_proposal" in row.get("counter", []) and DATED.search(joined):
        return True
    if "permission_to_say_no" in row.get("counter", []) and permission.any(normalized, True):
        return True
    return False


def politics_in(turns, lang="he"):
    """What the founder did each time the American raised politics.

    The guide's rule is not to initiate, not to join and not to correct. So
    the reply that follows a political line is read three ways: it bridged
    back to business with the table's own line, it joined (agreement is a
    position), or it simply stayed out."""
    cfg = load("meetings")["politics"]
    rows = [row for row in load("decoder")["rows"] if row["table"] == "politics" and row["patterns"]]
    joining = _set("politics:joining", cfg["joining"]["patterns"])
    out = []
    for index, turn in enumerate(turns):
        if turn["who"] != "american":
            continue
        for row in rows:
            if not _set("row:" + row["id"], row["patterns"]).any(turn["text"]):
                continue
            replies = [later["text"] for later in turns[index + 1:] if later["who"] == "founder"][:1]
            entry = {"line": turn["text"], "row": row["id"], "move": tr(row["move"], lang), "outcome": "stayed_out"}
            hits = joining.hits(norm(" ".join(replies)), True) if replies else []
            if replies and _countered(row, replies):
                entry["outcome"] = "bridged"
            elif hits:
                entry["outcome"] = "joined"
                entry["violation"] = {
                    "guard": "joined_politics",
                    "level": "error",
                    "hits": hits,
                    "message": fmt(tr(cfg["joining"]["message"], lang), hits=", ".join(hits)),
                }
            out.append(entry)
            break
    return out


def debrief(data, lang="he", receipt=None):
    """Score the founder's side of a simulation transcript."""
    receipt = receipt or Receipt("debrief")
    facts = validate(data, DEBRIEF_SPEC)
    kind = facts["type"]
    meetings = load("meetings")
    cfg = meetings["debrief"]
    weights = dict((key, value) for key, value in cfg["weights"].items() if not key.startswith("_"))
    turns = facts["turns"]
    founder = [turn["text"] for turn in turns if turn["who"] == "founder"]
    if not founder:
        raise PlaybookError("The transcript has no founder turns.", "Each turn needs who: founder or american.", "empty_transcript")

    if "injected" in facts:
        injected_ids = facts["injected"]
    elif "seed" in facts:
        injected_ids = scene(kind, seed=facts["seed"])["debrief_with"]["injected"]
    else:
        injected_ids = []
        receipt.skip("decoded", "no injected lines given (pass injected or seed from the scene card)")

    caught, missed, undelivered = [], [], []
    all_scorable = set()
    for character in meetings["characters"].values():
        all_scorable.update(character["sugar"] + character["deferral"])
    for row_id in injected_ids:
        row = _row(row_id)
        if row_id not in all_scorable:
            continue
        detector = _set("row:" + row_id, row["patterns"]) if row["patterns"] else None
        position = None
        for index, turn in enumerate(turns):
            if turn["who"] == "american" and detector is not None and detector.any(turn["text"]):
                position = index
                break
        if position is None:
            undelivered.append(row_id)
            continue
        replies = [turn["text"] for turn in turns[position + 1:] if turn["who"] == "founder"][:2]
        move = row["move"]
        if kind in row.get("move_by_context", {}):
            move = row["move_by_context"][kind]
        entry = {"row": row_id, "line": turns[position]["text"], "means": tr(row["means"], lang), "move": tr(move, lang)}
        (caught if replies and _countered(row, replies) else missed).append(entry)

    points, assessed = {}, {}
    delivered = len(caught) + len(missed)
    if delivered:
        points["decoded"] = weights["decoded"] * len(caught) / float(delivered)
        assessed["decoded"] = True
        receipt.ran("decoded")
    elif injected_ids:
        receipt.skip("decoded", "none of the injected lines appear in the American's turns")

    founder_text = " ".join(founder)
    founder_norm = norm(founder_text)
    proposed_date = bool(DATED.search(founder_text))
    permission = _set("permission", load("decoder")["permission_to_say_no"]["markers"]).any(founder_norm, True)
    clarity = permission or _set("clarity", CLARITY_MARKERS).any(founder_norm, True)
    if kind == "kol":
        clarity = clarity or _set("counter:its_great", _row("its_great")["counter"]).any(founder_norm, True)

    outcome = facts.get("outcome", {}).get("result")
    if outcome is None:
        receipt.skip("outcome", "no outcome given; scored from the founder's lines only")
        outcome = "vague"
    if outcome == "dated_step":
        points["outcome"] = weights["outcome"] if proposed_date else weights["outcome"] / 2.0
    elif outcome == "clean_no":
        points["outcome"] = weights["outcome"] if clarity else weights["outcome"] / 2.0
    else:
        points["outcome"] = weights["outcome"] / 3.0 if proposed_date else 0.0
    assessed["outcome"] = True
    receipt.ran("outcome")

    points["clarity_tool"] = weights["clarity_tool"] if clarity else 0.0
    assessed["clarity_tool"] = True

    checked = guard("\n".join(founder), kind, lang)
    political = politics_in(turns, lang)
    checked["violations"].extend(item["violation"] for item in political if item["outcome"] == "joined")
    slips = sum(1 for line in founder if HEBREW.search(line))
    discipline = weights["discipline"]
    for item in checked["violations"]:
        discipline -= 1.0 if item["level"] == "error" else 0.5
    if slips:
        discipline -= 0.5
    points["discipline"] = max(0.0, discipline)
    assessed["discipline"] = True
    receipt.ran("guard")

    isms = checked["israelisms"]
    points["register"] = weights["register"] if not isms else (weights["register"] / 2.0 if len(isms) <= 2 else 0.0)
    assessed["register"] = True
    receipt.ran("israelisms")

    possible = sum(weights[key] for key in assessed)
    earned = sum(points[key] for key in assessed)
    score = max(1.0, round(10.0 * earned / possible, 1)) if possible else 1.0

    ratios = [(points[key] / weights[key], index, key) for index, key in enumerate(weights) if key in assessed]
    weakest = sorted(ratios)[0][2]
    if any(item["level"] == "error" for item in checked["violations"]):
        weakest = "discipline"  # a move that burns the meeting outranks every other drill
    breakdown = [
        {
            "dimension": key,
            "label": tr(cfg["dimension_labels"][key], lang),
            "points": round(points[key], 2) if key in assessed else None,
            "of": weights[key],
        }
        for key in weights
    ]
    bench = None
    bench_cfg = load("bench")
    if kind == "investor" and bench_cfg["enabled"] and facts["bench_used"] < bench_cfg["max_nudges_per_session"]:
        dana = [person for person in bench_cfg["people"] if person["id"] == "dana"][0]
        bench = {"person": "dana", "name": dana["name"], "form": "referral", "nudge_he": dana["sample_nudge_he"]}
    return {
        "type": kind,
        "score": score,
        "out_of": 10,
        "breakdown": breakdown,
        "signals_missed": missed,
        "signals_decoded": caught,
        "not_delivered": undelivered,
        "dated_next_step": outcome == "dated_step" and proposed_date,
        "outcome": outcome,
        "proposed_a_date": proposed_date,
        "israelisms": isms,
        "violations": checked["violations"],
        "politics": [dict((key, item[key]) for key in ("line", "row", "outcome", "move")) for item in political],
        "hebrew_slips": slips,
        "drill": {"dimension": weakest, "text": tr(cfg["drills"][weakest], lang)},
        "bench": bench,
    }


def debrief_brief(result, lang="he"):
    labels = load("meetings")["debrief"]["labels"]
    lab = lambda key: tr(labels[key], lang)
    lines = ["%s: %s/10" % (lab("score"), ("%g" % result["score"]))]
    for item in result["breakdown"]:
        shown = "%g/%g" % (item["points"], item["of"]) if item["points"] is not None else "-/%g" % item["of"]
        lines.append("- %s: %s" % (item["label"], shown))
    lines.append("%s:" % lab("missed"))
    if result["signals_missed"]:
        for item in result["signals_missed"]:
            lines.append('- "%s" -> %s. %s' % (item["line"], item["means"], item["move"]))
    else:
        lines.append("- %s" % lab("none"))
    if result["signals_decoded"]:
        lines.append("%s: %s" % (lab("caught"), ", ".join('"%s"' % item["line"] for item in result["signals_decoded"])))
    lines.append("%s: %s" % (lab("dated"), lab("yes") if result["dated_next_step"] else lab("no")))
    for item in result["violations"]:
        lines.append("- [%s] %s" % (item["guard"], item["message"]))
    politics_labels = load("meetings")["politics"]["labels"]
    for item in result.get("politics", []):
        lines.append('%s: "%s" -> %s' % (tr(politics_labels["raised"], lang), item["line"], tr(politics_labels[item["outcome"]], lang)))
    if result["hebrew_slips"]:
        lines.append("%s: %d" % (lab("hebrew_slips"), result["hebrew_slips"]))
    lines.append("%s:" % lab("israelisms"))
    if result["israelisms"]:
        for item in result["israelisms"]:
            lines.append('- "%s" -> %s' % (item["said"], item["american"]))
    else:
        lines.append("- %s" % lab("none"))
    lines.append("%s: %s" % (lab("drill"), result["drill"]["text"]))
    if result.get("bench"):
        lines.append("%s: %s" % (result["bench"]["name"], result["bench"]["nudge_he"]))
    return "\n".join(lines)
