"""The meeting decoder: phrase matching, the traffic-light verdict, the next move.

The model's part is to get the founder's facts into a fact sheet. Everything
after that is rule evaluation: the same fact sheet always yields the same
verdict, and the verdict cannot be argued up by an optimistic paraphrase.
"""

from __future__ import annotations

import datetime as dt

from . import clock
from .core import PlaybookError, Receipt, fmt, israel_today, label, load, parse_date, tr
from .phrases import PhraseSet, norm
from .schema import validate

CONTEXTS = ["sales", "investor", "kol"]
CURRENCIES = ["calendar_time", "data_access", "intro", "signature", "money"]
TOUCHES = ["recap", "value", "second_angle", "breakup", "nurture"]
FLAGS = ["pricing_raised_without_model", "strategic_fork", "founder_resists_verdict"]
RE_ENTRY_AFTER_DAYS = 10
BAR_EXTRACTION_ROWS = ("too_early", "keep_posted", "more_traction")

SPEC = {
    "context": {
        "type": "enum", "values": CONTEXTS, "required": True,
        "aliases": {"customer": "sales", "partner": "sales", "vc": "investor", "angel": "investor", "fund": "investor", "expert": "kol"},
        "doc": "Who the American is: sales (customer or partner), investor, or kol (domain expert).",
    },
    "today": {"type": "date", "doc": "Today's date on the founder's calendar. Defaults to the system date in Israel."},
    "meeting_date": {"type": "date", "doc": "Date of the meeting or of the last live interaction."},
    "source": {
        "type": "enum", "values": ["recall", "transcript", "email_thread"], "default": "recall",
        "doc": "recall = the founder is telling the story; transcript or email_thread = their exact words are in front of you.",
    },
    "quotes": {
        "type": "list", "max_items": 60, "items": {"type": "str"},
        "doc": "What the American said, word for word. Never a paraphrase.",
    },
    "next_step": {
        "type": "object", "nullable": True,
        "doc": "The next step, if one exists.",
        "props": {
            "exists": {"type": "bool", "required": True, "doc": "Is there any agreed next step?"},
            "date": {"type": "date", "nullable": True, "doc": "Its calendar date. No date means no dated step."},
            "proposed_by": {"type": "enum", "values": ["them", "founder", "nobody"], "doc": "Who proposed it."},
            "accepted_by_them": {"type": "bool", "doc": "True when it is on THEIR calendar or they confirmed it in writing."},
            "what": {"type": "str", "doc": "What the step is."},
        },
    },
    "cost_to_them": {
        "type": "list", "max_items": 10,
        "doc": "What this has cost THEM so far. An empty list means: nothing yet.",
        "items": {"type": "object", "props": {
            "currency": {"type": "enum", "values": CURRENCIES, "required": True},
            "evidence": {"type": "str", "required": True, "doc": "The concrete thing: a date, a name, a file."},
        }},
    },
    "signals": {
        "type": "list", "max_items": 20,
        "doc": "Signals the founder reports. Each needs evidence or it does not count. Run `schema decode` for the ids.",
        "items": {"type": "object", "props": {
            "id": {"type": "str", "required": True},
            "evidence": {"type": "str", "allow_empty": True, "default": ""},
        }},
    },
    "their_questions": {"type": "int", "min": 0, "doc": "How many real questions they asked."},
    "touches_sent": {"type": "int", "min": 0, "default": 0, "doc": "Follow-ups sent since their last reply, all unanswered."},
    "touches_done": {"type": "list", "items": {"type": "enum", "values": TOUCHES}, "doc": "Cadence touches already sent."},
    "last_reply_date": {"type": "date", "doc": "Date of their last reply."},
    "reply_latency_days": {"type": "number", "min": 0, "doc": "Their typical reply time, in days."},
    "tz": {"type": "str", "doc": "Recipient timezone or city, for the send date of the next move."},
    "decision_needed": {"type": "str", "doc": "The decision the founder needs from this debrief."},
    "flags": {"type": "list", "items": {"type": "enum", "values": FLAGS}, "doc": "Coaching context flags."},
    "bench_used": {"type": "int", "min": 0, "default": 0, "doc": "Bench nudges already used in this session."},
}

EXAMPLE = {
    "context": "sales",
    "today": "2026-11-24",
    "meeting_date": "2026-11-17",
    "quotes": ["This is amazing!", "Let's keep in touch."],
    "next_step": {"exists": False},
    "cost_to_them": [],
    "their_questions": 0,
    "tz": "ET",
}

_ROWS = {}


def _row_sets():
    if not _ROWS:
        data = load("decoder")
        for row in data["rows"]:
            _ROWS[row["id"]] = PhraseSet(row["patterns"]) if row["patterns"] else None
        for hint in data["green_hints"]:
            _ROWS["hint:" + hint["id"]] = PhraseSet(hint["patterns"])
        for level in data["compliments"]["levels"]:
            _ROWS["compliment:%d" % level["level"]] = PhraseSet(level["patterns"] + level.get("extension_patterns", []))
    return _ROWS


def signal_ids(context):
    table = load("signals")
    if context == "kol":
        return {"green": [item["id"] for item in table["kol"]["real_feedback_signals"]], "yellow": [], "red": []}
    block = table[context]
    out = dict((light, [item["id"] for item in block[light]]) for light in ("green", "yellow", "red"))
    if context == "investor":
        out["green"] = out["green"] + [block["process"]["open_diligence_signal"]]
    return out


def signal_label(context, signal_id, lang):
    table = load("signals")
    pools = [table["kol"]["real_feedback_signals"]] if context == "kol" else [table[context][light] for light in ("green", "yellow", "red")]
    for pool in pools:
        for item in pool:
            if item["id"] == signal_id:
                return tr(item["label"], lang)
    process = table["investor"]["process"]
    if signal_id == process["open_diligence_signal"]:
        return tr(process["open_diligence_label"], lang)
    return signal_id


def match_quotes(quotes, context, lang="he"):
    """Match verbatim lines against the decoder tables."""
    data = load("decoder")
    sets = _row_sets()
    decoded, compliments, hints, unmatched = [], [], [], []
    for quote in quotes:
        normalized = norm(quote)
        token_count = len(normalized.split())
        found = False
        for row in data["rows"]:
            regexes = sets[row["id"]]
            if regexes is None or context not in row["contexts"]:
                continue
            if regexes.any(normalized, True):
                move = row["move"]
                if context in row.get("move_by_context", {}):
                    move = row["move_by_context"][context]
                decoded.append({
                    "quote": quote,
                    "row": row["id"],
                    "table": row["table"],
                    "said": row["said"],
                    "means": tr(row["means"], lang),
                    "move": tr(move, lang),
                    "lean": row["lean"],
                    "soft_no": row["soft_no"],
                    "suggests_signal": row.get("suggests_signal"),
                    "shadowed_by": row.get("shadowed_by", []),
                    "shown": True,
                })
                found = True
        for hint in data["green_hints"]:
            if sets["hint:" + hint["id"]].any(normalized, True):
                hints.append({"quote": quote, "signal": hint["id"], "label": tr(hint["label"], lang)})
                found = True
        for level in data["compliments"]["levels"]:
            if level.get("standalone") and token_count > 4:
                continue
            if sets["compliment:%d" % level["level"]].any(normalized, True):
                compliments.append({
                    "quote": quote,
                    "level": level["level"],
                    "reading": tr(level["reading"], lang),
                })
                found = True
                break
        if not found:
            unmatched.append(quote)
    for row in decoded:
        twins = [other["row"] for other in decoded if other["quote"] == row["quote"]]
        if any(name in twins for name in row["shadowed_by"]):
            row["shown"] = False
    return {"decoded": decoded, "compliments": compliments, "hints": hints, "unmatched": unmatched}


def _intake(facts, lang):
    """The questions still open, at most three per turn."""
    table = load("signals")["intake"]
    have_words = bool(facts.get("quotes"))
    missing_required, optional = [], []
    for question in table["questions"]:
        field = question["field"]
        present = field in facts and facts[field] is not None
        if field == "quotes":
            present = have_words
        if present:
            continue
        # Price, security and integration are a buyer's questions. An investor and an expert are asked their own.
        wording = question.get("by_context", {}).get(facts["context"], question)
        entry = {"id": question["id"], "field": field, "question": tr(wording, lang), "voice_ok": question["voice_ok"]}
        if question["required_for_verdict"]:
            missing_required.append(entry)
        else:
            optional.append(entry)
    if facts["source"] != "recall" and "decision_needed" not in facts:
        clarifier = table["transcript_clarifier"]
        optional.insert(0, {"id": clarifier["id"], "field": clarifier["field"], "question": tr(clarifier, lang), "voice_ok": False})
    limit = table["max_questions_per_turn"]
    ask = (missing_required + optional)[:limit]
    for entry in ask:
        if entry["voice_ok"]:
            entry["invite"] = tr(table["voice_note_invite"], lang)
    return missing_required, ask


def _collect_signals(facts, matched, context, receipt):
    """Evidenced signals by light, plus the ones claimed without evidence."""
    ids = signal_ids(context)
    thresholds = load("signals")["thresholds"]
    known = set(ids["green"] + ids["yellow"] + ids["red"])
    lights = {"green": [], "yellow": [], "red": []}
    claimed = []

    def add(signal_id, evidence, how):
        for light in ("green", "yellow", "red"):
            if signal_id in ids[light]:
                if not any(item["id"] == signal_id for item in lights[light]):
                    lights[light].append({"id": signal_id, "evidence": evidence, "how": how})

    for item in facts.get("signals", []):
        key = item["id"].strip().lower().replace(" ", "_").replace("-", "_")
        if key not in known:
            raise PlaybookError(
                "signals: %r is not a known signal for the %s context." % (item["id"], context),
                "Known ids: %s" % ", ".join(sorted(known)),
                "unknown_signal",
            )
        if item["evidence"].strip():
            add(key, item["evidence"].strip(), "reported")
        else:
            claimed.append(key)

    if context == "sales":
        for hint in matched["hints"]:
            add(hint["signal"], hint["quote"], "quote")
    for row in matched["decoded"]:
        if row["suggests_signal"]:
            add(row["suggests_signal"], row["quote"], "quote")

    step = facts.get("next_step") or {}
    booked = "next_meeting_booked_in_meeting" if context == "sales" else "second_meeting_scheduled_in_meeting"
    if step_is_theirs(step) and context in ("sales", "investor"):
        who = "proposed by them" if step.get("proposed_by") == "them" else "accepted by them"
        add(booked, "%s on %s, %s" % (step.get("what", "next step"), step["date"].isoformat(), who), "next_step")

    if "reply_latency_days" in facts and context == "sales":
        if facts["reply_latency_days"] <= thresholds["fast_reply_days"]["value"]:
            add("fast_replies", "replies in about %s day(s)" % facts["reply_latency_days"], "fact")
    if facts["touches_sent"] >= thresholds["ghosting_touches"]["value"]:
        add("ghosting", "%d touches unanswered" % facts["touches_sent"], "fact")
    keep_posted = [row for row in matched["decoded"] if row["row"] == "keep_posted"]
    if keep_posted and facts.get("their_questions") == 0:
        add("keep_posted_no_questions", keep_posted[0]["quote"], "quote + zero questions")
    if any(item["id"] == "added_people" for item in lights["green"]):
        lights["yellow"] = [item for item in lights["yellow"] if item["id"] != "loop_in_unnamed"]
    praise = [item for item in matched["compliments"] if item["level"] >= 4]
    has_step = bool(step.get("exists"))
    if praise and not has_step and context == "sales":
        add("compliments_no_step", praise[0]["quote"], "quote")
    receipt.ran("signals")
    return lights, claimed


def step_is_theirs(step):
    """A dated step counts only when they proposed it or accepted it.

    "I told them I would send a proposal by Friday" has a date and costs them
    nothing; by the iron rule it is not a commitment.
    """
    if not step or not step.get("exists") or not step.get("date"):
        return False
    return step.get("proposed_by") == "them" or step.get("accepted_by_them") is True


def _age_days(facts, today):
    anchor = facts.get("last_reply_date") or facts.get("meeting_date")
    if anchor is None:
        return None
    return max(0, (today - anchor).days)


def _judge(facts, matched, lights, context, today):
    """Apply the decision rules. Returns the verdict dict with its rule trace."""
    table = load("signals")
    step = facts.get("next_step") or {}
    dated = step_is_theirs(step)
    future = bool(dated and step["date"] >= today)
    one_sided = bool(step.get("exists") and step.get("date") and not dated)
    paid = [item for item in facts.get("cost_to_them", []) if item["evidence"].strip()]
    commitment = dated or bool(paid)
    soft_no = any(row["soft_no"] for row in matched["decoded"])
    only_praise = bool(matched["compliments"]) and not lights["green"]
    zero_questions = facts.get("their_questions") == 0
    trace = []

    if lights["red"] and not future:
        light, lean, headline = "red", None, "red"
        trace.append("R1")
    elif lights["red"] and future:
        light, lean, headline = "yellow", None, "yellow_conflict"
        trace.append("R2")
    elif lights["green"] and commitment:
        light, lean = "green", None
        headline = "green_investor" if context == "investor" else "green"
        trace.append("G1")
    else:
        light = "yellow"
        trace.append("Y1")
        if lights["green"]:
            lean, headline = "green", "yellow_lean_green"
        elif not step.get("exists") and not paid and (zero_questions or soft_no or only_praise):
            lean, headline = "red", "yellow_lean_red"
        else:
            lean, headline = None, "yellow"

    age = _age_days(facts, today)
    forced = False
    if light == "yellow" and age is not None and age > table["thresholds"]["yellow_max_age_days"]["value"]:
        forced = True
        trace.append("Y14")
    return {
        "light": light,
        "lean": lean,
        "headline_key": headline,
        "rules_fired": trace,
        "dated_next_step": dated,
        "one_sided_date": one_sided,
        "next_step_in_future": future,
        "paid_currencies": [item["currency"] for item in paid],
        "age_days": age,
        "forced_decision": forced,
    }


def _send_date(facts, today, target, receipt, lang):
    """When to send the next touch: the planned date if still ahead, else the next open slot."""
    if "tz" not in facts:
        receipt.skip("send_date", "no tz given, so no send date was computed")
        return None
    zone = clock.resolve_zone(facts["tz"])
    receipt.ran("send_date")
    if zone["how"] in ("city", "alias"):
        receipt.assume(fmt(label("coach", "zone_assumed", lang), zone=zone["code"], input=zone["input"]))
    representative = clock.parse_hhmm(load("cadence")["send_window"]["representative"])
    if target is not None and target >= today:
        return clock.describe_slot(zone["code"], target, representative, lang)
    now = clock.israel_to_utc(dt.datetime.combine(today, dt.time(9, 0)))
    slots, _skipped = clock.next_send_slots(now, zone["code"], count=1, lang=lang)
    return slots[0] if slots else None


def _prescribe(facts, verdict, matched, today, receipt, lang):
    """Name the next cadence step and its template."""
    cfg = load("cadence")
    if facts["context"] == "investor" and any(row["row"] in BAR_EXTRACTION_ROWS for row in matched["decoded"]):
        receipt.ran("investor_soft_pass")
        return {
            "touch": "reply",
            "name": tr(cfg["off_cadence_touches"]["bar_extraction_reply"], lang),
            "template": "bar_extraction",
            "content": "",
            "why": "investor_soft_pass",
            "send": None,
            "note": "",
            "then": {
                "touch": "investor_update",
                "name": tr(cfg["off_cadence_touches"]["investor_update"], lang),
                "template": "investor_update",
                "date": None,
            },
        }
    done = set(facts.get("touches_done", []))
    touches = dict((touch["id"], touch) for touch in cfg["touches"])
    planned, notes = {}, {}
    meeting = facts.get("meeting_date")
    if meeting is not None:
        code = clock.resolve_zone(facts["tz"])["code"] if "tz" in facts else "ET"
        for item in clock.cadence(meeting, code, today, done, lang=lang):
            planned[item["id"]] = dt.datetime.strptime(item["date"], "%Y-%m-%d").date()
            notes[item["id"]] = item["note"]
        receipt.ran("cadence_position")
    else:
        receipt.skip("cadence_position", "no meeting_date given, so the next touch is chosen by verdict only")

    order = [touch["id"] for touch in cfg["touches"]]

    def move(touch_id, template=None, why=""):
        touch = touches[touch_id]
        target = planned.get(touch_id)
        slot = _send_date(facts, today, target, receipt, lang)
        following = None
        for later in order[order.index(touch_id) + 1:]:
            if later not in done:
                when = planned.get(later)
                following = {
                    "touch": later,
                    "name": tr(touches[later]["name"], lang),
                    "template": touches[later]["template"],
                    "date": when.isoformat() if when and when >= today else None,
                }
                break
        return {
            "touch": touch_id,
            "name": tr(touch["name"], lang),
            "template": template or touch["template"],
            "content": touch["content_he"] if lang == "he" else touch["content"],
            "why": why,
            "send": slot,
            "note": notes.get(touch_id, "") if target is not None and target >= today else "",
            "then": following,
        }

    light = verdict["light"]
    since = (today - meeting).days if meeting is not None else None
    if light == "red" or verdict["forced_decision"]:
        if "breakup" not in done:
            out = move("breakup", why="red_or_forced")
        else:
            out = move("nurture", why="after_breakup")
        out["alternative"] = "archive" if verdict["forced_decision"] else None
        return out
    if light == "green":
        if "recap" not in done:
            return move("recap", why="green_recap")
        return {"touch": None, "name": "", "template": None, "content": "", "why": "green_hold", "send": None, "note": "", "then": None}
    if not done and since is not None and since > RE_ENTRY_AFTER_DAYS:
        return move("value", template="re_entry", why="founder_went_silent")
    for touch_id in ("recap", "value", "second_angle", "breakup"):
        if touch_id not in done:
            return move(touch_id, why="next_in_cadence")
    return move("nurture", why="after_breakup")


def _bench(facts, context, lang):
    bench = load("bench")
    if not bench["enabled"] or facts["bench_used"] >= bench["max_nudges_per_session"]:
        return None
    flags = list(facts.get("flags", []))
    if context == "investor":
        flags.append("investor_thread")
    for person in bench["people"]:
        if any(flag in person["flags"] for flag in flags):
            form = "referral" if "investor_thread" in person["flags"] else "question"
            return {
                "person": person["id"],
                "name": person["name"],
                "role": person["role"],
                "form": form,
                "nudge_he": person["sample_nudge_he"],
                "rule": "Hebrew coaching layer only. A hypothetical question or a referral. Never invent what they said.",
            }
    return None


def decode(data, lang="he", receipt=None, force=False):
    """Decode a meeting or thread. Returns intake questions or a verdict."""
    receipt = receipt or Receipt("decode")
    facts = validate(data, SPEC)
    context = facts["context"]
    today = facts.get("today") or israel_today()
    if "today" not in facts:
        receipt.assume(fmt(label("coach", "today_assumed", lang), date=today.isoformat()))
    table = load("signals")
    decoder = load("decoder")

    matched = match_quotes(facts.get("quotes", []), context, lang)
    receipt.ran("phrase_tables")
    missing_required, ask_next = _intake(facts, lang)

    base = {
        "context": context,
        "today": today.isoformat(),
        "decoded": matched["decoded"],
        "compliments": matched["compliments"],
        "compliment_rule": tr(decoder["compliments"]["rule_of_thumb"], lang),
        "green_hints": matched["hints"],
        "unmatched_quotes": matched["unmatched"],
        "ask_next": ask_next,
        "iron_rule": tr(decoder["iron_rule"], lang),
    }
    if missing_required and not force:
        receipt.skip("verdict", "intake incomplete: %s" % ", ".join(item["field"] for item in missing_required))
        base["status"] = "needs_intake"
        base["verdict"] = None
        return base

    lights, claimed = _collect_signals(facts, matched, context, receipt)
    provisional = bool(missing_required)

    if context == "kol":
        real = bool(lights["green"]) or any(item["level"] == 2 for item in matched["compliments"])
        key = "kol_real" if real else "kol_polite"
        verdict = {
            "light": None,
            "kind": "feedback",
            "feedback": "real" if real else "polite",
            "headline": tr(table["headlines"][key], lang),
            "rules_fired": ["K1"],
            "forced_decision": False,
            "age_days": _age_days(facts, today),
        }
        extraction = [] if real else load("meetings")["kol"]["extraction_bank"][:3]
        base.update({
            "status": "provisional" if provisional else "verdict",
            "verdict": verdict,
            "signals": lights,
            "claimed_without_evidence": claimed,
            "extraction_questions": extraction,
            "next_move": None,
            "push": tr(table["pushes"]["yellow" if not real else "green"], lang),
            "bench": _bench(facts, context, lang),
        })
        receipt.ran("verdict")
        return base

    verdict = _judge(facts, matched, lights, context, today)
    verdict["kind"] = "traffic_light"
    verdict["headline"] = tr(table["headlines"][verdict["headline_key"]], lang)
    if verdict["forced_decision"]:
        verdict["forced_text"] = fmt(tr(table["forced_decision"], lang), age=verdict["age_days"])
    receipt.ran("verdict")

    process = None
    if context == "investor":
        in_process = verdict["next_step_in_future"] or any(item["id"] == "open_diligence_request" for item in lights["green"])
        block = table["investor"]["process"]
        process = {"status": "in_process" if in_process else "nurture", "text": tr(block["in_process" if in_process else "nurture"], lang)}

    step = _prescribe(facts, verdict, matched, today, receipt, lang)
    step["why_text"] = tr(load("cadence")["next_moves"][step["why"]], lang)

    extraction = []
    weak = facts.get("their_questions") == 0 or (matched["compliments"] and not lights["green"])
    if verdict["light"] != "green" and weak and context != "investor":
        extraction = load("meetings")["kol"]["extraction_bank"][:3]

    silence = None
    if facts["touches_sent"] >= 1:
        row = [item for item in decoder["rows"] if item["id"] == "total_silence"][0]
        silence = {"touches": facts["touches_sent"], "means": tr(row["means"], lang), "move": tr(row["move"], lang)}

    push_key = "resists_verdict" if "founder_resists_verdict" in facts.get("flags", []) else verdict["light"]
    base.update({
        "status": "provisional" if provisional else "verdict",
        "verdict": verdict,
        "signals": lights,
        "claimed_without_evidence": claimed,
        "fund_status": process,
        "silence": silence,
        "next_move": step,
        "permission_line": decoder["permission_to_say_no"]["lines"][1] if verdict["light"] == "yellow" and step["template"] != "bar_extraction" else None,
        "extraction_questions": extraction,
        "push": tr(table["pushes"][push_key], lang),
        "bench": _bench(facts, context, lang),
    })
    return base


def brief(result, lang="he"):
    """A relay-ready text rendering of a decode result."""
    coach = load("coach")
    lab = lambda key, **kw: fmt(tr(coach["labels"][key], lang), **kw)
    lines = []
    if result["status"] == "needs_intake":
        lines.append(lab("needs_intake"))
    else:
        if result["status"] == "provisional":
            lines.append(lab("provisional"))
        verdict = result["verdict"]
        lines.append("%s: %s" % (lab("verdict"), verdict["headline"]))
        if verdict.get("forced_text"):
            lines.append(verdict["forced_text"])
        if result.get("fund_status"):
            lines.append("%s: %s" % (lab("status"), result["fund_status"]["text"]))
        reasons = []
        for light in ("green", "yellow", "red"):
            for item in result["signals"][light]:
                reasons.append("- [%s] %s (%s)" % (light, signal_label(result["context"], item["id"], lang), item["evidence"]))
        if verdict.get("kind") == "traffic_light":
            if verdict["one_sided_date"]:
                reasons.append("- %s: %s" % (lab("dated_step"), lab("one_sided")))
            else:
                reasons.append("- %s: %s" % (lab("dated_step"), lab("yes" if verdict["dated_next_step"] else "no")))
            reasons.append("- %s: %s" % (lab("paid"), ", ".join(verdict["paid_currencies"]) or lab("none")))
        if reasons:
            lines.append("%s:" % lab("why"))
            lines.extend(reasons)
        if result.get("claimed_without_evidence"):
            lines.append("%s: %s" % (lab("claimed"), ", ".join(result["claimed_without_evidence"])))
    if result["decoded"]:
        lines.append("%s:" % lab("decoded"))
        for row in result["decoded"]:
            if row["shown"]:
                lines.append('- "%s" -> %s. %s: %s' % (row["quote"], row["means"], lab("move"), row["move"]))
    if result["compliments"]:
        lines.append("%s:" % lab("compliments"))
        for item in result["compliments"]:
            lines.append('- "%s" -> %s' % (item["quote"], item["reading"]))
    if result.get("silence"):
        lines.append("- %s" % result["silence"]["means"])
    if result["unmatched_quotes"]:
        lines.append("%s:" % lab("unmatched"))
        lines.extend('- "%s"' % quote for quote in result["unmatched_quotes"])
    if result["status"] != "needs_intake":
        lines.append("%s: %s" % (lab("iron_rule"), result["iron_rule"]))
        step = result.get("next_move")
        if step:
            if step["touch"]:
                text = "%s: %s (%s %s). %s" % (lab("next_move"), step["name"], lab("template"), step["template"], step["why_text"])
                lines.append(text)
                if step.get("send"):
                    slot = step["send"]
                    lines.append("  %s: %s %s %s = %s %s" % (lab("send_on"), slot["pretty"], slot["local_time"], slot["zone"], slot["israel_time"], lab("israel")))
                    for note in slot["notes"]:
                        lines.append("  ! %s" % note["text"])
                if step.get("note"):
                    lines.append("  (%s)" % step["note"])
                if step.get("then"):
                    after = step["then"]
                    when = ", %s" % clock.pretty_date(parse_date(after["date"])) if after.get("date") else ""
                    lines.append("  %s: %s (%s %s)%s" % (lab("then"), after["name"], lab("template"), after["template"], when))
                if step.get("alternative") == "archive":
                    lines.append("  %s" % lab("archive_alt"))
            else:
                lines.append("%s: %s" % (lab("next_move"), step["why_text"]))
        if result.get("permission_line"):
            lines.append('%s: "%s"' % (lab("permission"), result["permission_line"]))
        if result.get("extraction_questions"):
            lines.append("%s:" % lab("extraction"))
            lines.extend('- "%s"' % question for question in result["extraction_questions"])
        lines.append("%s: %s" % (lab("push"), result["push"]))
        if result.get("bench"):
            lines.append("%s (%s): %s" % (lab("bench"), result["bench"]["name"], result["bench"]["nudge_he"]))
    if result["ask_next"]:
        lines.append("%s:" % lab("ask_next", n=load("signals")["intake"]["max_questions_per_turn"]))
        for index, entry in enumerate(result["ask_next"], 1):
            line = "%d. %s" % (index, entry["question"])
            if entry.get("invite"):
                line += " (%s)" % entry["invite"]
            lines.append(line)
    return "\n".join(lines)
