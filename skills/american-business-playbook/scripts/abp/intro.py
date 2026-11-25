"""The Intro Economy as a checklist, and the Bench as a routing table."""

from __future__ import annotations

from .core import PlaybookError, Receipt, fmt, load, tr
from .phrases import norm
from .schema import validate

STAGES = ["asking", "received", "after_meeting", "connecting"]

INTRO_SPEC = {
    "stage": {
        "type": "enum", "values": STAGES, "required": True,
        "aliases": {"request": "asking", "requesting": "asking", "landed": "received", "reply": "received", "done": "after_meeting", "close": "after_meeting", "connect": "connecting"},
        "doc": "asking = requesting an intro; received = an intro landed; after_meeting = the meeting happened; connecting = you want to connect two others.",
    },
    "connector": {"type": "str", "doc": "First name of the person who made or will make the intro."},
    "forwardable_attached": {"type": "bool", "doc": "asking: is a forwardable email attached?"},
    "gave_before": {"type": "bool", "doc": "asking: have you done something for this connector before?"},
    "hours_since_intro": {"type": "number", "min": 0, "doc": "received: hours since the intro email arrived."},
    "replied": {"type": "bool", "doc": "received: did you already reply?"},
    "moved_to_bcc": {"type": "bool", "doc": "received: did your first reply move the connector to BCC?"},
    "hours_since_meeting": {"type": "number", "min": 0, "doc": "after_meeting: hours since the meeting."},
    "loop_closed": {"type": "bool", "doc": "after_meeting: did you tell the connector what happened?"},
    "both_agreed": {"type": "bool", "doc": "connecting: did both people agree to be connected?"},
}
INTRO_EXAMPLE = {"stage": "received", "connector": "Sarah", "hours_since_intro": 30, "replied": False}


def intro(data, lang="he", receipt=None):
    """Check where the founder stands against the intro protocol."""
    receipt = receipt or Receipt("intro")
    facts = validate(data, INTRO_SPEC)
    cfg = load("intro")
    msg = lambda key, **kw: fmt(tr(cfg["messages"][key], lang), **kw)
    limits = dict((key, item["value"]) for key, item in cfg["thresholds"].items())
    stage = facts["stage"]
    connector = facts.get("connector", "[Connector]")
    items, templates, unknown = [], [], []

    def item(rule, ok, text):
        items.append({"rule": rule, "ok": ok, "text": text})

    if stage == "asking":
        if "forwardable_attached" in facts:
            if facts["forwardable_attached"]:
                item("double_opt_in", True, msg("forwardable_ok"))
            else:
                item("double_opt_in", False, msg("attach_forwardable"))
                templates.append("forwardable")
        else:
            item("double_opt_in", False, msg("attach_forwardable"))
            templates.append("forwardable")
        if "gave_before" not in facts:
            item("give_first", None, msg("give_first_unknown"))
            unknown.append("gave_before")
        elif facts["gave_before"]:
            item("give_first", True, msg("give_first_ok"))
        else:
            item("give_first", False, msg("give_first_no"))
    elif stage == "received":
        hours = facts.get("hours_since_intro")
        if hours is None:
            unknown.append("hours_since_intro")
            receipt.skip("reply_speed", "hours_since_intro not given")
        else:
            shown = "%g" % hours
            if facts.get("replied"):
                item("speed", hours <= limits["reply_late_hours"], msg("reply_on_time" if hours <= limits["reply_late_hours"] else "reply_late", hours=shown))
            elif hours > limits["reply_late_hours"]:
                item("speed", False, msg("reply_late", hours=shown))
                templates.append("intro_reply_bcc")
            else:
                item("speed", False, msg("reply_now", hours=shown))
                templates.append("intro_reply_bcc")
            receipt.ran("reply_speed")
        if facts.get("moved_to_bcc"):
            item("bcc", True, msg("bcc_ok"))
        else:
            item("bcc", False, msg("bcc_missing"))
            if "intro_reply_bcc" not in templates:
                templates.append("intro_reply_bcc")
    elif stage == "after_meeting":
        if facts.get("loop_closed"):
            item("close_loop", True, msg("loop_closed"))
        else:
            item("close_loop", False, msg("loop_open", connector=connector))
            templates.extend(["loop_close", "thank_you"])
    else:
        if facts.get("both_agreed"):
            item("double_opt_in", True, msg("opt_in_ok"))
        else:
            item("double_opt_in", False, msg("opt_in_missing"))
    receipt.ran("intro_protocol")
    rules = [{"id": rule["id"], "title": tr(rule["title"], lang), "text": tr(rule["text"], lang)} for rule in cfg["rules"]]
    return {
        "stage": stage,
        "stage_label": tr(cfg["stages"][stage], lang),
        "status": "ok" if all(entry["ok"] for entry in items if entry["ok"] is not None) and not unknown else "act",
        "items": items,
        "templates": templates,
        "unknown": unknown,
        "premise": cfg["premise_he"] if lang == "he" else cfg["premise"],
        "rules": rules,
    }


def intro_brief(result, lang="he"):
    lines = ["Intro (%s): %s" % (result["stage"], result["stage_label"])]
    for entry in result["items"]:
        mark = "?" if entry["ok"] is None else ("ok" if entry["ok"] else "do")
        lines.append("- [%s] %s" % (mark, entry["text"]))
    if result["templates"]:
        lines.append("%s: %s" % (tr(load("coach")["labels"]["template"], lang), ", ".join(result["templates"])))
    return "\n".join(lines)


# ------------------------------------------------------------------- bench

def route(topic=None, flag=None, used=0, lang="he"):
    """Who on the bench owns a topic, and the only two forms a nudge may take."""
    bench = load("bench")
    if not bench["enabled"]:
        return {"enabled": False, "person": None}
    if used >= bench["max_nudges_per_session"]:
        return {
            "enabled": True,
            "person": None,
            "budget_left": 0,
            "message": fmt(tr(bench["budget_spent"], lang), max=bench["max_nudges_per_session"]),
        }
    chosen = None
    if flag:
        for person in bench["people"]:
            if flag in person["flags"]:
                chosen = person
                break
    if chosen is None and topic:
        wanted = norm(topic)
        best = 0
        for person in bench["people"]:
            score = 0
            for keyword in person["topics"]:
                key = norm(keyword)
                if key and (" %s " % key) in (" %s " % wanted):
                    score += len(key.split())
            if score > best:
                best, chosen = score, person
    if chosen is None:
        if not topic and not flag:
            raise PlaybookError("Give the bench a topic.", "Example: bench --topic pricing", "missing_topic")
        return {"enabled": True, "person": None, "budget_left": bench["max_nudges_per_session"] - used, "message": "No bench owner for this topic."}
    gender = "he_" + chosen.get("gender", "m")
    forms = {}
    for form, node in bench["nudge_forms"].items():
        template = node["en"] if lang == "en" else node[gender]
        forms[form] = fmt(template, name=chosen["first_name"], name_he=chosen["first_name_he"])
    return {
        "enabled": True,
        "person": chosen["id"],
        "name": chosen["name"],
        "role": chosen["role"],
        "why": chosen["route_why"],
        "facts": chosen["facts"],
        "sample_nudge_he": chosen["sample_nudge_he"],
        "allowed_forms": forms,
        "rules": bench["usage_rules"],
        "budget_left": bench["max_nudges_per_session"] - used - 1,
    }


def route_brief(result, lang="he"):
    if not result.get("person"):
        return result.get("message", "Bench is disabled.")
    lines = [
        "Bench: %s, %s" % (result["name"], result["role"]),
        "Why: %s" % result["why"],
        "Nudge (Hebrew coaching layer only): %s" % result["sample_nudge_he"],
        "Allowed forms:",
    ]
    lines.extend("- %s" % text for text in result["allowed_forms"].values())
    lines.append("Budget left this session: %d" % result["budget_left"])
    return "\n".join(lines)
