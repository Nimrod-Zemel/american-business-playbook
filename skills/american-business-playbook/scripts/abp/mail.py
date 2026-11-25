"""The email linter and the template renderer.

The model writes the English. This module only measures it against the rules
in data/email.json: counts, one ask, tone, softeners, typography, leftover
[brackets] and numbers that are not in the founder's own material.
"""

from __future__ import annotations

import re

from .core import PlaybookError, fmt, load, tr
from .phrases import PhraseSet, merged, norm

HEBREW = re.compile(r"[\u0590-\u05ff]")
DASHES = {"\u2013": "en dash", "\u2014": "em dash"}
HIDDEN = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u200e": "left-to-right mark",
    "\u200f": "right-to-left mark",
    "\u202a": "bidi embedding",
    "\u202b": "bidi embedding",
    "\u202c": "bidi pop",
    "\u202d": "bidi override",
    "\u202e": "bidi override",
    "\u2066": "bidi isolate",
    "\u2067": "bidi isolate",
    "\u2068": "bidi isolate",
    "\u2069": "bidi isolate",
    "\ufeff": "byte-order mark",
    "\u00ad": "soft hyphen",
}
PLACEHOLDER = re.compile(r"\[[^\[\]\n]{1,120}\]")
WORD = re.compile(r"\b[\w'/-]+\b")
BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d{1,2}[.)])\s+")
SEPARATOR = re.compile(r"^\s*-{3,}\s*$")
SUBJECT = re.compile(r"^\s*subject\s*:\s*", re.IGNORECASE)
QUOTED = re.compile(r"\"[^\"\n]{0,240}\"|\u201c[^\u201d\n]{0,240}\u201d")
GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|dear|good (?:morning|afternoon|evening))\b[ \t]*"
    r"(?:(?:mr|mrs|ms|dr|prof)\.?[ \t]+)?"
    r"(?:\[[^\]\n]+\]|[^\n,!:.?\-]{0,40}?)[ \t]*(?:,|!|:|\s-\s|$)[ \t]*",
    re.IGNORECASE,
)
TERMINAL = re.compile(r"[.!?][\"')\]]*$")
# A sentence ends at . ! or ?. After a closing quote or bracket it ends only
# when the next word is not lowercase: `She asked "why now?" and moved on.`
# is one sentence.
SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"')\]])\s+(?![a-z])")
NUMBER = re.compile(
    r"(?<![\w.])\$?(\d[\d,]*(?:\.\d+)?)\s?(%|percent|x|k|m|mm|bn|b|million|billion|thousand)?(?![\w])",
    re.IGNORECASE,
)
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}

_SETS = {}


def _phrase_set(name):
    """Compiled phrase sets from data/email.json, built once."""
    if name not in _SETS:
        cfg = load("email")
        if name.startswith("softeners."):
            _SETS[name] = PhraseSet(merged(cfg["softeners"][name.split(".", 1)[1]]))
        else:
            _SETS[name] = PhraseSet(merged(cfg[name]))
    return _SETS[name]


def types():
    return sorted(load("email")["types"])


# ----------------------------------------------------------------- parsing

def _split_sentences(paragraph, abbreviations):
    """Sentences of one paragraph, plus short colon lead-ins that are not counted."""
    shielded = paragraph
    for abbr in abbreviations:
        # Whole abbreviations only: "ms." must not match the end of "claims.".
        shielded = re.sub(r"(?<![A-Za-z])" + re.escape(abbr), lambda m: m.group(0).replace(".", "\x00"), shielded, flags=re.IGNORECASE)
    sentences, lead_ins = [], []
    for piece in SPLIT.split(shielded):
        piece = piece.replace("\x00", ".").strip()
        if not piece:
            continue
        if not TERMINAL.search(piece) and piece.endswith(":") and len(piece.split()) < 4:
            lead_ins.append(piece)
            continue
        colon = piece.find(": ")
        if colon != -1 and TERMINAL.search(piece):
            head, rest = piece[:colon].strip(), piece[colon + 2:].strip()
            if rest and 0 < len(head.split()) < 4 and head.lower() not in ("re", "fw", "fwd"):
                lead_ins.append(head + ":")
                piece = rest
        sentences.append(piece)
    return sentences, lead_ins


def parse(text, kind):
    """Split a draft into subject, greeting, sentences, questions and counts."""
    cfg = load("email")
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    subject = None
    lines = []
    for line in raw.split("\n"):
        if subject is None and SUBJECT.match(line):
            subject = SUBJECT.sub("", line).strip()
            continue
        lines.append(line)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    full_text = "\n".join(lines).strip()

    blurb_lines = []
    if kind == "intro":
        for index, line in enumerate(lines):
            if SEPARATOR.match(line):
                blurb_lines = lines[index + 1:]
                lines = lines[:index]
                break
        while lines and not lines[-1].strip():
            lines.pop()

    greeting = None
    if lines:
        match = GREETING.match(lines[0])
        if match:
            greeting = match.group(0).strip()
            rest = lines[0][match.end():]
            lines = ([rest] if rest.strip() else []) + lines[1:]

    signoffs = set(cfg["signoffs"])
    body_lines = []
    for line in lines:
        key = line.strip().lower().rstrip(",!.").strip()
        if key in signoffs and line.strip():
            break
        body_lines.append(line)
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    content = [line for line in body_lines if line.strip()]
    if len(content) >= 2 and len(body_lines) >= 2 and not body_lines[-2].strip():
        last = body_lines[-1].strip()
        if len(last.split()) <= 4 and not re.search(r"[.?!:]$", last) and not BULLET.match(last):
            body_lines = body_lines[:-2]

    def units(source_lines):
        sentences, lead_ins, paragraphs = [], [], []
        buffer, block = [], {"lines": 0, "sentences": 0, "words": 0}

        def flush():
            if buffer:
                found, leads = _split_sentences(" ".join(buffer), cfg["abbreviations"])
                sentences.extend(found)
                lead_ins.extend(leads)
                block["sentences"] += len(found)
                block["words"] += len(WORD.findall(" ".join(buffer)))
                del buffer[:]

        for line in source_lines:
            if not line.strip():
                flush()
                if block["lines"]:
                    paragraphs.append(dict(block))
                block.update({"lines": 0, "sentences": 0, "words": 0})
                continue
            block["lines"] += 1
            if BULLET.match(line):
                flush()
                sentences.append(BULLET.sub("", line).strip())
            else:
                buffer.append(line.strip())
        flush()
        if block["lines"]:
            paragraphs.append(dict(block))
        return sentences, lead_ins, paragraphs

    sentences, lead_ins, paragraphs = units(body_lines)
    blurb_sentences = units(blurb_lines)[0] if blurb_lines else []

    def questions(items):
        found = []
        pleasantries = [norm(p) for p in cfg["pleasantry_questions"]]
        for sentence in items:
            bare = QUOTED.sub(" ", sentence)
            if "?" not in bare:
                continue
            if any(norm(bare).startswith(p) for p in pleasantries):
                continue
            found.append(sentence)
        return found

    core_text = " ".join(lead_ins + sentences + blurb_sentences)
    return {
        "subject": subject,
        "greeting": greeting,
        "first_line": lines[0].strip() if lines else "",
        "sentences": sentences,
        "blurb_sentences": blurb_sentences,
        "lead_ins": lead_ins,
        "paragraphs": paragraphs,
        "questions": questions(sentences),
        "blurb_questions": questions(blurb_sentences),
        "words": len(WORD.findall(core_text)),
        "chars": len(full_text),
        "first_raw_line": full_text.split("\n")[0] if full_text else "",
        "body": "\n".join(body_lines),
        "raw": raw,
    }


# ------------------------------------------------------------------ checks

def _is_open_question(sentence, cfg):
    """True when the ask clearly opens with what/how/why and offers no either-or."""
    bare = norm(QUOTED.sub(" ", sentence))
    if " or " in " %s " % bare:
        return False
    clauses = [norm(part) for part in re.split(r"[,;:]|\s-\s", QUOTED.sub(" ", sentence)) if norm(part)]
    firsts = [clause.split()[0] for clause in clauses]
    if any(first in cfg["closed_starters"] for first in firsts):
        return False
    return any(first in cfg["open_starters"] for first in firsts)


def _command_sentences(parsed, cfg):
    """Sentences that open with an instruction, shown by their first words."""
    lead_ins = set(cfg["command_lead_ins"])
    found = []
    for sentence in parsed["sentences"]:
        words = norm(sentence).split()
        for _ in range(2):
            if words and words[0] in lead_ins:
                words = words[1:]
        if _phrase_set("command_openers").starts(" ".join(words), True):
            parts = sentence.split()
            shown = "'%s%s'" % (" ".join(parts[:6]).rstrip(".,!?"), "..." if len(parts) > 6 else "")
            if shown not in found:
                found.append(shown)
    return found


def _count_commands(parsed, cfg):
    return len(_command_sentences(parsed, cfg))


def numbers_in(text):
    """Business figures in a text as floats, ignoring clock times, dates and years."""
    lowered = text.lower()
    found = []
    for match in NUMBER.finditer(lowered):
        digits, unit = match.group(1), (match.group(2) or "")
        start, end = match.span()
        before, after = lowered[max(0, start - 12):start], lowered[end:end + 12]
        if re.match(r"^:\d{2}", after) or re.search(r"\d:$", before):
            continue
        if re.match(r"^\s?(?:am|pm)\b", after) or re.match(r"^(?:st|nd|rd|th)\b", after):
            continue
        if re.search(MONTH + r"\.?\s$", before) or re.match(r"^\s" + MONTH + r"\b", after):
            continue
        if re.match(r"^[-/]\d", after) or re.search(r"\d[-/]$", before):
            continue
        try:
            value = float(digits.replace(",", ""))
        except ValueError:
            continue
        if not unit and 1900 <= value <= 2100 and "," not in digits and "." not in digits:
            continue
        value *= SCALE.get(unit, 1.0)
        found.append((value, match.group(0).strip()))
    return found


def _plain_for_numbers(text):
    """Lowercase text with URLs, [brackets], list numbering and hyphens out of the way."""
    out = re.sub(r"https?://\S+", " ", text.lower())
    out = PLACEHOLDER.sub(" ", out)
    out = "\n".join(BULLET.sub("", line) for line in out.split("\n"))
    return out.replace("-", " ")


def _verify_numbers(draft, source, whitelist):
    """Figures in the draft that do not appear anywhere in the founder's source."""
    known = set(round(value, 6) for value, _shown in numbers_in(_plain_for_numbers(source)))
    cleaned = _plain_for_numbers(draft)
    for phrase in whitelist:
        cleaned = cleaned.replace(phrase, " ")
    out = []
    for value, shown in numbers_in(cleaned):
        if round(value, 6) in known:
            continue
        if shown not in out:
            out.append(shown)
    return out


NUMBER_WHITELIST = ["20 minute", "20 minutes", "15 minute", "15 minutes", "30 minute", "30 minutes", "6 months", "24 hours"]


def lint(text, kind="cold", source=None, lang="he", receipt=None):
    """Measure a draft against the playbook rules. Returns a result dict."""
    cfg = load("email")
    if kind not in cfg["types"]:
        raise PlaybookError(
            "Unknown email type %r." % kind,
            "Use one of: %s" % ", ".join(types()),
            "bad_type",
        )
    if not text or not text.strip():
        raise PlaybookError("The draft is empty.", "Pass --file draft.txt or pipe the text on stdin.", "empty_draft")
    rules = cfg["types"][kind]
    parsed = parse(text, kind)
    flags = []

    def flag(check, **values):
        message = cfg["messages"][check]
        flags.append({
            "check": check,
            "level": message["level"],
            "message": fmt(tr(message, lang), type=kind, **values),
            "data": values,
        })

    def ran(check):
        if receipt is not None:
            receipt.ran(check)

    normalized = norm(parsed["body"] + " " + " ".join(parsed["blurb_sentences"]))
    n_sentences = len(parsed["sentences"]) + len(parsed["blurb_sentences"])

    # length
    if "max_sentences" in rules:
        ran("length_sentences")
        if n_sentences > rules["max_sentences"]:
            flag("length_sentences", n=n_sentences, max=rules["max_sentences"])
    if "max_words" in rules:
        ran("length_words")
        if parsed["words"] > rules["max_words"]:
            flag("length_words", n=parsed["words"], max=rules["max_words"])
        elif "target_words" in rules and parsed["words"] > rules["target_words"]:
            flag("length_words_target", n=parsed["words"], target=rules["target_words"])
    if "max_chars" in rules:
        ran("linkedin_long")
        if parsed["chars"] > rules["max_chars"]:
            flag("linkedin_long", n=parsed["chars"], max=rules["max_chars"])

    # asks: a question is an ask, and so is an instruction ("Send me your availability.")
    ran("command_tone")
    commands = _command_sentences(parsed, cfg)
    questions = len(parsed["questions"])
    asks = questions + len(commands)
    policy = rules["asks"]
    if policy == "exactly_one":
        ran("one_ask")
        if asks > 1:
            flag("ask_many", n=asks)
        if questions == 0:
            flag("ask_none")
        elif questions == 1 and _is_open_question(parsed["questions"][0], cfg):
            flag("ask_open", q=parsed["questions"][0][:90])
    elif policy == "at_most_one":
        ran("one_ask")
        if asks > 1:
            flag("ask_many_soft", n=asks)
    if commands:
        flag("command_tone", hits=", ".join(commands))
    elif policy == "update":
        ran("update_sections")
        present = []
        ask_lines = 0
        for line in parsed["body"].split("\n"):
            head = line.strip().lower()
            for section in rules["sections"] + rules.get("optional_sections", []):
                if re.match(r"^%s\b[^:\n]{0,20}:" % re.escape(section.lower()), head):
                    present.append(section)
                    if section == "Ask" and head.split(":", 1)[1].strip():
                        ask_lines += 1
        missing = [section for section in rules["sections"] if section not in present]
        if missing:
            flag("update_sections", hits=", ".join(missing))
        if "Ask" in present and ask_lines != 1:
            flag("update_ask", n=ask_lines)
    if kind == "intro":
        ran("blurb_questions")
        if len(parsed["blurb_questions"]) > 1:
            flag("blurb_questions", n=len(parsed["blurb_questions"]))

    # tone
    ran("pushy")
    hits = _phrase_set("pushy").hits(normalized, True)
    if hits:
        flag("pushy", hits=", ".join(hits))

    ran("directive")
    hits = _phrase_set("directive").hits(normalized, True)
    if hits:
        flag("directive", hits=", ".join(hits))

    ran("checking_in")
    hits = _phrase_set("checking_in").hits(normalized, True)
    if hits:
        flag("checking_in", hits=", ".join('"%s"' % hit for hit in hits))
    hits = _phrase_set("nudge_only").hits(normalized, True)
    if hits:
        flag("nudge_only", hits=", ".join(hits))

    ran("hurt_tone")
    hits = _phrase_set("hurt_tone").hits(normalized, True)
    if hits:
        flag("hurt_tone", hits=", ".join(hits))

    ran("over_apology")
    apology_words = merged(cfg["apology"])
    apologies = sum(normalized.split().count(word) for word in apology_words)
    opens_with_apology = bool(parsed["sentences"]) and any(
        word in norm(parsed["sentences"][0]).split() for word in apology_words
    )
    if apologies >= 2 or opens_with_apology:
        flag("over_apology", n=apologies)

    softener_rule = rules.get("softener", "any")
    if softener_rule != "none":
        ran("softener")
        families = ["request", "release"] if softener_rule == "request_or_release" else ["request", "release", "appreciation"]
        if not any(_phrase_set("softeners." + family).any(normalized, True) for family in families):
            flag("softener_missing")

    # opener
    if parsed["sentences"]:
        ran("bluf")
        opener_hit = _phrase_set("throat_clearing").starts(norm(parsed["sentences"][0]), True)
        if opener_hit and kind in ("cold", "conference", "followup", "intro"):
            flag("bluf", s=parsed["sentences"][0][:70])
    ran("formal_greeting")
    formal = _phrase_set("formal_greetings").starts(norm(parsed["first_raw_line"]), True)
    if formal:
        flag("formal_greeting", s=formal)

    # subject
    subject_rule = rules.get("subject", "optional")
    if subject_rule != "none":
        ran("subject")
        subject = parsed["subject"]
        if subject is None:
            if subject_rule == "expected":
                flag("subject_missing")
        elif not subject:
            flag("subject_empty")
        elif len(subject) > cfg["subject_max_chars"]:
            flag("subject_long", n=len(subject))
        elif norm(PLACEHOLDER.sub("", subject)) in [norm(item) for item in merged(cfg["generic_subjects"])]:
            flag("subject_generic", s=subject)

    # layout
    ran("paragraphs")
    limits = cfg["paragraph"]
    long_blocks = [
        block for block in parsed["paragraphs"]
        if block["lines"] > limits["max_lines"] or block["sentences"] > limits["max_sentences"] or block["words"] > limits["max_words"]
    ]
    if long_blocks and kind not in ("investor_update", "linkedin", "scheduling"):
        flag("paragraph_long", n=len(long_blocks))

    # typography and language
    ran("typography")
    whole = parsed["raw"]
    if any(mark in whole for mark in DASHES):
        flag("typography_dash")
    hidden = sorted(set(HIDDEN[ch] for ch in whole if ch in HIDDEN))
    if hidden:
        flag("hidden_chars", hits=", ".join(hidden))
    ran("language")
    if HEBREW.search(whole):
        flag("hebrew_in_english")

    # facts
    ran("placeholders")
    placeholders = []
    for item in PLACEHOLDER.findall(whole):
        if item not in placeholders:
            placeholders.append(item)
    if placeholders:
        flag("placeholder_left", hits=", ".join(placeholders))

    if kind in ("cold", "conference"):
        ran("deck_attached")
        if _phrase_set("deck_attached").any(normalized, True):
            flag("deck_attached")
    if kind == "linkedin":
        hits = _phrase_set("linkedin_pitch").hits(normalized, True)
        if hits:
            flag("linkedin_pitch", hits=", ".join(hits))

    unverified = []
    before = None
    if source is not None and source.strip():
        ran("numbers_vs_source")
        unverified = _verify_numbers(whole, source, NUMBER_WHITELIST)
        if unverified:
            flag("unverified_number", hits=", ".join(unverified))
        before_parsed = parse(source, kind)
        before = {
            "sentences": len(before_parsed["sentences"]) + len(before_parsed["blurb_sentences"]),
            "words": before_parsed["words"],
            "asks": len(before_parsed["questions"]) + _count_commands(before_parsed, cfg),
        }
    elif receipt is not None:
        receipt.skip("numbers_vs_source", "no --source given, so figures were not compared with the founder's own material")
    if kind == "investor_update" and receipt is not None:
        receipt.skip("same_kpis_every_month", "needs last month's update; compare by hand")

    errors = [item for item in flags if item["level"] == "error"]
    warnings = [item for item in flags if item["level"] == "warn"]
    return {
        "type": kind,
        "status": "revise" if errors else "pass",
        "stats": {
            "sentences": n_sentences,
            "words": parsed["words"],
            "asks": asks,
            "chars": parsed["chars"],
            "max_sentences": rules.get("max_sentences"),
            "max_words": rules.get("max_words"),
            "asks_policy": policy,
            "subject": parsed["subject"],
        },
        "before": before,
        "errors": errors,
        "warnings": warnings,
        "missing_facts": placeholders,
        "unverified_numbers": unverified,
    }


def lint_brief(result, lang="he"):
    """A relay-ready text rendering of a lint result."""
    cfg = load("email")
    lab = lambda key: tr(cfg["labels"][key], lang)
    stats = result["stats"]
    status = lab("status_pass") if result["status"] == "pass" else lab("status_revise")
    lines = ["Email lint (%s): %s" % (result["type"], status)]
    def ratio(value, limit):
        return "%d/%d" % (value, limit) if limit is not None else "%d" % value

    lines.append("%s: %s %s | %s %s | %s %d" % (
        lab("numbers"),
        lab("sentences"), ratio(stats["sentences"], stats["max_sentences"]),
        lab("words"), ratio(stats["words"], stats["max_words"]),
        lab("asks"), stats["asks"],
    ))
    if result["before"]:
        before = result["before"]
        lines.append("%s: %s %d -> %d | %s %d -> %d | %s %d -> %d" % (
            lab("before_after"),
            lab("sentences"), before["sentences"], stats["sentences"],
            lab("words"), before["words"], stats["words"],
            lab("asks"), before["asks"], stats["asks"],
        ))
    if result["errors"]:
        lines.append("%s:" % lab("must_fix"))
        lines.extend("- [%s] %s" % (item["check"], item["message"]) for item in result["errors"])
    if result["warnings"]:
        lines.append("%s:" % lab("consider"))
        lines.extend("- [%s] %s" % (item["check"], item["message"]) for item in result["warnings"])
    if result["missing_facts"]:
        lines.append("%s: %s" % (lab("ask_founder"), ", ".join(result["missing_facts"])))
    if result["status"] == "pass":
        lines.append(lab("clean_line"))
    if result["warnings"]:
        lines.append(lab("advisory"))
    return "\n".join(lines)


# --------------------------------------------------------------- templates

def template_ids():
    return [item["id"] for item in load("templates")["templates"]]


def get_template(template_id):
    for item in load("templates")["templates"]:
        if item["id"] == template_id:
            return item
    raise PlaybookError(
        "Unknown template %r." % template_id,
        "Use one of: %s" % ", ".join(template_ids()),
        "unknown_template",
    )


def render(template_id, values=None, slots=None):
    """Fill a template. Unfilled slots stay as [brackets] and are listed as missing."""
    template = get_template(template_id)
    values = dict(values or {})
    subject, body = template.get("subject", ""), template["body"]
    for key in values:
        if key not in template["slots"]:
            raise PlaybookError(
                "Template %r has no slot %r." % (template_id, key),
                "Slots: %s" % ", ".join(sorted(template["slots"])),
                "unknown_slot",
            )
    for key, value in values.items():
        labels = template["slots"][key]
        if isinstance(labels, str):
            labels = [labels]
        for bracket in labels:
            subject = subject.replace(bracket, value)
            body = body.replace(bracket, value)
    if slots:
        for slot in slots:
            body = body.replace("[date]", slot["line"].split(",")[0].split(" ", 1)[1], 1)
    text = ("Subject: %s\n\n%s" % (subject, body)) if subject else body
    missing = []
    for item in PLACEHOLDER.findall(text):
        if item not in missing:
            missing.append(item)
    asks = {}
    for key, labels in template["slots"].items():
        first = labels if isinstance(labels, str) else labels[0]
        if key not in values:
            asks[key] = first
    return {
        "id": template["id"],
        "type": template["type"],
        "title": template["title"],
        "when": template["when"],
        "notes": template.get("notes", ""),
        "text": text,
        "missing": missing,
        "open_slots": asks,
    }
