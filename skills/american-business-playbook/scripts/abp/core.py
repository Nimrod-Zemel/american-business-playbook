"""Shared plumbing: paths, data loading, errors, language helpers and the receipt."""

from __future__ import annotations

import datetime as dt
import json
import os

from . import __version__

ENGINE_NAME = "american-business-playbook"
ENGINE = "%s %s" % (ENGINE_NAME, __version__)

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_ROOT = os.path.dirname(SCRIPTS_DIR)
DATA_DIR = os.path.join(SKILL_ROOT, "data")

LANGS = ("he", "en")
DEFAULT_LANG = "he"

EXIT_OK = 0
EXIT_REVISE = 1
EXIT_USAGE = 2
EXIT_SEAL = 3


class PlaybookError(Exception):
    """A problem the caller can fix: bad input, unknown zone, missing field."""

    def __init__(self, message, hint="", code="bad_input"):
        Exception.__init__(self, message)
        self.message = message
        self.hint = hint
        self.code = code

    def as_dict(self):
        out = {"ok": False, "error": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out


_CACHE = {}


def load(name):
    """Load data/<name>.json once and keep it."""
    if name not in _CACHE:
        path = os.path.join(DATA_DIR, name + ".json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                _CACHE[name] = json.load(handle)
        except OSError as exc:
            raise PlaybookError(
                "Rule table data/%s.json is missing or unreadable (%s)." % (name, exc),
                "Reinstall the skill; its data folder is incomplete.",
                "broken_install",
            )
        except ValueError as exc:
            raise PlaybookError(
                "Rule table data/%s.json is not valid JSON (%s)." % (name, exc),
                "Fix the file, then run tools/seal.py --write.",
                "broken_install",
            )
    return _CACHE[name]


def tr(node, lang):
    """Pick the language variant of a {"en": ..., "he": ...} node."""
    if isinstance(node, dict):
        if lang in node:
            return node[lang]
        return node.get("en", "")
    return node


def label(table, key, lang):
    """A label from data/<table>.json -> labels."""
    return tr(load(table)["labels"][key], lang)


def fmt(template, **values):
    """str.format that leaves unknown {placeholders} alone."""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def israel_today(now_utc=None):
    """Today's date on the founder's clock (Israel)."""
    from . import clock

    if now_utc is None:
        now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return clock.israel_local(now_utc).date()


# The daylight-saving and holiday rules in clock.py are checked for these years.
FIRST_YEAR, LAST_YEAR = 2016, 2099


def check_year(year, field, text):
    """Refuse a date far outside the years the clock rules were written for."""
    if not FIRST_YEAR <= year <= LAST_YEAR:
        raise PlaybookError(
            "%s is outside the years this engine supports, %d to %d (got %r)." % (field, FIRST_YEAR, LAST_YEAR, text),
            "Check the year for a typo.",
            "date_out_of_range",
        )


def parse_date(text, field="date"):
    try:
        day = dt.datetime.strptime(str(text).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise PlaybookError(
            "%s must be a date written as YYYY-MM-DD (got %r)." % (field, text),
            "Example: 2026-08-10",
        )
    check_year(day.year, field, text)
    return day


# THIRD-PARTY: founder-skills (idea only). Naming every step that did not run
# follows the disclosure codes of founder-skills by lool ventures. The code is
# this project's. Record: NOTICE.txt, and THIRD_PARTY_NOTICES.md in the repository.
class Receipt(object):
    """What ran, what was skipped and what was assumed. Printed with every answer.

    A skill that silently skips a check and still hands out a score is the
    failure this object exists to prevent: whatever did not run is named.
    """

    def __init__(self, command):
        self.command = command
        self.checks = []
        self.skipped = []
        self.assumptions = []

    def ran(self, check):
        if check not in self.checks:
            self.checks.append(check)

    def skip(self, check, why):
        self.skipped.append({"check": check, "why": why})

    def assume(self, text):
        if text not in self.assumptions:
            self.assumptions.append(text)

    def as_dict(self, seal_status="unchecked", rules="", today=None):
        out = {
            "engine": ENGINE,
            "command": self.command,
            "rules": rules,
            "seal": seal_status,
            "checks_run": list(self.checks),
            "checks_skipped": list(self.skipped),
            "assumptions": list(self.assumptions),
        }
        if today is not None:
            out["today"] = today.isoformat()
        return out


def stamp_line(receipt_dict, lang):
    """The one-line proof that code produced this answer."""
    coach = load("coach")
    skipped = ""
    if receipt_dict.get("checks_skipped"):
        skipped = tr(coach["stamp"]["skipped_prefix"], lang) + ", ".join(
            item["check"] for item in receipt_dict["checks_skipped"]
        )
    return fmt(
        tr(coach["stamp"]["verified"], lang),
        engine=receipt_dict.get("engine", ENGINE),
        rules=receipt_dict.get("rules", ""),
        seal=receipt_dict.get("seal", "unchecked"),
        skipped=skipped,
    )
