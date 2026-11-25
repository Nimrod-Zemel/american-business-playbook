"""Phrase patterns: the small matching syntax used by every rule table.

Rule tables are edited by people who know the playbook, not regular
expressions, so a pattern is written the way the phrase is spoken:

    keep us|me posted|updated        alternatives inside one word position
    ?really interesting              a leading ? makes that word optional
    send me ... deck                 ... allows up to five words in between
    integrat*                        a trailing * matches any ending
    re:\\bq[1-4]\\b                    escape hatch: a raw regular expression

Text and patterns are normalized the same way before matching: lowercase,
apostrophes dropped ("don't" becomes "dont"), every other punctuation mark
becomes a space. A pattern therefore matches regardless of quotes, casing or
punctuation, and always on whole words.
"""

from __future__ import annotations

import re

from .core import PlaybookError

_APOSTROPHES = "'\u2019\u2018\u02bc`\u00b4"
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
_ALT_OK = re.compile(r"^\w+\*?$", re.UNICODE)
GAP_MAX = 5


def norm(text):
    """Normalize text for matching. Idempotent."""
    out = str(text).lower()
    for mark in _APOSTROPHES:
        out = out.replace(mark, "")
    out = _NON_WORD.sub(" ", out).replace("_", " ")
    return " ".join(out.split())


def tokens(text):
    return norm(text).split()


def _alt_regex(alt, pattern):
    cleaned = alt.lower()
    for mark in _APOSTROPHES:
        cleaned = cleaned.replace(mark, "")
    if not _ALT_OK.match(cleaned):
        raise PlaybookError(
            "Bad phrase pattern %r: %r is not a single word." % (pattern, alt),
            "Write multi-word alternatives as separate patterns, and hyphenated words as two words.",
            "bad_pattern",
        )
    if cleaned.endswith("*"):
        return re.escape(cleaned[:-1]) + r"\w*"
    return re.escape(cleaned)


def compile_phrase(pattern):
    """Compile one phrase pattern into a regular expression over normalized text."""
    if pattern.startswith("re:"):
        try:
            return re.compile(pattern[3:], re.UNICODE)
        except re.error as exc:
            raise PlaybookError("Bad raw pattern %r: %s" % (pattern, exc), code="bad_pattern")
    words = pattern.split()
    if not words:
        raise PlaybookError("Empty phrase pattern.", code="bad_pattern")
    parts = []
    last = len(words) - 1
    for index, word in enumerate(words):
        if word == "...":
            if index in (0, last):
                raise PlaybookError(
                    "Bad phrase pattern %r: ... cannot be the first or last word." % pattern,
                    code="bad_pattern",
                )
            parts.append(r"(?: \w+){0,%d}" % GAP_MAX)
            continue
        optional = word.startswith("?")
        body = "(?:%s)" % "|".join(_alt_regex(alt, pattern) for alt in word.lstrip("?").split("|"))
        if index == 0:
            if optional:
                raise PlaybookError(
                    "Bad phrase pattern %r: the first word cannot be optional." % pattern,
                    code="bad_pattern",
                )
            parts.append(body)
        elif optional:
            parts.append("(?: %s)?" % body)
        else:
            parts.append(" " + body)
    return re.compile(r"(?<!\w)" + "".join(parts) + r"(?!\w)", re.UNICODE)


class PhraseSet(object):
    """A compiled list of phrase patterns."""

    def __init__(self, patterns):
        self.patterns = list(patterns)
        self._compiled = [(pattern, compile_phrase(pattern)) for pattern in self.patterns]

    def __len__(self):
        return len(self.patterns)

    def hits(self, text, already_normalized=False):
        """Every distinct stretch of text that matches, in order of appearance."""
        normalized = text if already_normalized else norm(text)
        found = []
        for _pattern, regex in self._compiled:
            for match in regex.finditer(normalized):
                found.append((match.start(), match.end(), match.group(0)))
        found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
        out = []
        covered_until = -1
        seen = set()
        for start, end, text_hit in found:
            if start < covered_until:
                continue
            covered_until = end
            if text_hit not in seen:
                seen.add(text_hit)
                out.append(text_hit)
        return out

    def any(self, text, already_normalized=False):
        normalized = text if already_normalized else norm(text)
        return any(regex.search(normalized) for _pattern, regex in self._compiled)

    def starts(self, text, already_normalized=False):
        """The matched opener when the text starts with one of the patterns, else None."""
        normalized = text if already_normalized else norm(text)
        best = None
        for _pattern, regex in self._compiled:
            match = regex.match(normalized)
            if match and (best is None or len(match.group(0)) > len(best)):
                best = match.group(0)
        return best


def merged(node, keys=("playbook", "extension")):
    """Flatten a {"playbook": [...], "extension": [...]} node into one list."""
    if isinstance(node, list):
        return list(node)
    out = []
    for key in keys:
        out.extend(node.get(key, []))
    return out
