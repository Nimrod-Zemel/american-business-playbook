"""A small validator for the fact sheets the model hands to the engine.

Strict on purpose: an unknown or misspelled field is an error, not something
to ignore, because a silently dropped fact would silently change a verdict.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json

from .core import PlaybookError, parse_date


def _fail(path, message, hint=""):
    raise PlaybookError("%s: %s" % (path or "input", message), hint, "bad_input")


def _check(value, spec, path):
    kind = spec["type"]
    if value is None:
        if spec.get("nullable"):
            return None
        _fail(path, "must not be null")
    if kind == "str":
        if not isinstance(value, str):
            _fail(path, "must be text")
        text = value.strip()
        if not text and not spec.get("allow_empty"):
            _fail(path, "must not be empty")
        return text
    if kind == "bool":
        if not isinstance(value, bool):
            _fail(path, "must be true or false")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(path, "must be a whole number")
        if "min" in spec and value < spec["min"]:
            _fail(path, "must be at least %s" % spec["min"])
        if "max" in spec and value > spec["max"]:
            _fail(path, "must be at most %s" % spec["max"])
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail(path, "must be a number")
        if "min" in spec and value < spec["min"]:
            _fail(path, "must be at least %s" % spec["min"])
        return value
    if kind == "date":
        if isinstance(value, dt.date):
            return value
        if not isinstance(value, str):
            _fail(path, "must be a date written as YYYY-MM-DD")
        return parse_date(value, path)
    if kind == "enum":
        if not isinstance(value, str):
            _fail(path, "must be one of: %s" % ", ".join(spec["values"]))
        key = value.strip().lower().replace(" ", "_").replace("-", "_")
        if key in spec.get("aliases", {}):
            key = spec["aliases"][key]
        if key not in spec["values"]:
            close = difflib.get_close_matches(key, spec["values"], n=1)
            hint = "Did you mean %r?" % close[0] if close else ""
            _fail(path, "%r is not one of: %s" % (value, ", ".join(spec["values"])), hint)
        return key
    if kind == "list":
        if not isinstance(value, list):
            _fail(path, "must be a list")
        if "max_items" in spec and len(value) > spec["max_items"]:
            _fail(path, "has %d items, the limit is %d" % (len(value), spec["max_items"]))
        return [_check(item, spec["items"], "%s[%d]" % (path, index)) for index, item in enumerate(value)]
    if kind == "object":
        return validate(value, spec["props"], path)
    if kind == "map":
        # Free keys: the caller knows them (the interview checks each against the question bank).
        if not isinstance(value, dict):
            _fail(path, "must be an object with named fields")
        return dict(value)
    raise AssertionError("unknown spec type %r" % kind)


def check(value, spec, path):
    """Validate one value against one spec. For callers whose field names are data, not code."""
    return _check(value, spec, path)


def validate(data, props, path=""):
    """Validate a dict against a props map and return a cleaned copy.

    Fields that are absent stay absent (the commands decide what a missing
    fact means), except when the spec gives a default.
    """
    if not isinstance(data, dict):
        _fail(path, "must be an object with named fields")
    out = {}
    for key in data:
        if key.startswith("_"):
            continue
        if key not in props:
            close = difflib.get_close_matches(key, list(props), n=1)
            hint = "Did you mean %r?" % close[0] if close else "Known fields: %s" % ", ".join(sorted(props))
            _fail(("%s.%s" % (path, key)).lstrip("."), "unknown field", hint)
    for key, spec in props.items():
        child = ("%s.%s" % (path, key)).lstrip(".")
        if key in data:
            out[key] = _check(data[key], spec, child)
        elif "default" in spec:
            out[key] = spec["default"]
        elif spec.get("required"):
            _fail(child, "is required", spec.get("doc", ""))
    return out


def describe(props, indent=0):
    """Human-readable lines describing a props map, for `playbook.py schema`."""
    lines = []
    pad = "  " * indent
    for key, spec in props.items():
        kind = spec["type"]
        shown = kind
        if kind == "enum":
            shown = " | ".join(spec["values"])
        elif kind == "list":
            inner = spec["items"]
            shown = "list of %s" % ("objects" if inner["type"] == "object" else inner["type"])
            if inner["type"] == "enum":
                shown = "list of (%s)" % " | ".join(inner["values"])
        elif kind == "date":
            shown = "YYYY-MM-DD"
        elif kind == "map":
            shown = "object"
        flag = " (required)" if spec.get("required") else ""
        lines.append("%s%s: %s%s" % (pad, key, shown, flag))
        if spec.get("doc"):
            lines.append("%s    %s" % (pad, spec["doc"]))
        if kind == "object":
            lines.extend(describe(spec["props"], indent + 1))
        elif kind == "list" and spec["items"]["type"] == "object":
            lines.extend(describe(spec["items"]["props"], indent + 1))
    return lines


def parse_json(text, source="input"):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise PlaybookError(
            "%s is not valid JSON (%s)." % (source, exc),
            "Pass the facts as a JSON object. Run `playbook.py schema <command>` for the fields and an example.",
            "bad_json",
        )
