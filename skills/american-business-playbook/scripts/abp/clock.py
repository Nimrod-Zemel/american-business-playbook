"""Time rules: US zones, Israel time, holiday windows, send slots, the cadence.

Everything is computed from first principles (the daylight-saving laws of the
US and Israel, and the holiday rules in data/cadence.json), so the result does
not depend on a timezone database being installed and never needs the network.
The test suite cross-checks every conversion against the system tz database
where one exists.
"""

from __future__ import annotations

import datetime as dt
import hashlib

from .core import PlaybookError, check_year, load, tr

WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SUNDAY = 6
LATE_HOUR_ISRAEL = 21


# ---------------------------------------------------------------- calendar

def nth_weekday(year, month, weekday, n):
    """The n-th given weekday (Monday=0) of a month."""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


def last_weekday(year, month, weekday):
    """The last given weekday (Monday=0) of a month."""
    if month == 12:
        last = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        last = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def week_monday_friday(day):
    monday = day - dt.timedelta(days=day.weekday())
    return monday, monday + dt.timedelta(days=4)


def month_end(day):
    """The last day of the month that contains day."""
    if day.month == 12:
        return dt.date(day.year, 12, 31)
    return dt.date(day.year, day.month + 1, 1) - dt.timedelta(days=1)


def parse_hhmm(text):
    hours, minutes = text.split(":")
    return dt.time(int(hours), int(minutes))


def pretty_date(day):
    return "%s %d %s %d" % (WEEKDAYS_SHORT[day.weekday()], day.day, MONTHS_SHORT[day.month - 1], day.year)


def weekday_name(day, lang="en"):
    """The full weekday name in the coaching language, from data/cadence.json."""
    return tr(load("cadence")["weekday_names"], lang)[day.weekday()]


# ------------------------------------------------------------------- zones

def zones():
    return load("cadence")["zones"]


def resolve_zone(text):
    """Turn what the founder said ("ET", "Austin", "America/Chicago") into a zone code."""
    cfg = load("cadence")
    raw = str(text or "").strip()
    if not raw:
        raise PlaybookError(
            "The recipient's timezone is missing.",
            "Ask where the recipient is based, then pass --tz ET|CT|MT|PT, a US city, or an IANA name.",
            "missing_zone",
        )
    upper = raw.upper()
    if upper in cfg["zones"]:
        return {"code": upper, "how": "code", "input": raw}
    for code, zone in cfg["zones"].items():
        if raw.lower() == zone["iana"].lower():
            return {"code": code, "how": "iana", "input": raw}
    key = " ".join(raw.lower().replace(".", "").replace(",", " ").split())
    if key in cfg["zone_aliases"]:
        return {"code": cfg["zone_aliases"][key], "how": "alias", "input": raw}
    cities = cfg["cities"]
    candidates = [key]
    if "," in raw:
        candidates.append(" ".join(raw.split(",")[0].lower().replace(".", "").split()))
    for candidate in candidates:
        if candidate in cities and not candidate.startswith("_"):
            return {"code": cities[candidate], "how": "city", "input": raw}
    raise PlaybookError(
        "Unknown timezone or city %r." % raw,
        "Use ET, CT, MT, PT, AZ, AKT, HT, an IANA name such as America/Chicago, or a major US city.",
        "unknown_zone",
    )


def us_dst_dates(year):
    """(start, end) dates of US daylight time: second Sunday of March, first Sunday of November."""
    return nth_weekday(year, 3, SUNDAY, 2), nth_weekday(year, 11, SUNDAY, 1)


def us_offset_hours(code, utc):
    """UTC offset in hours of a US zone at a UTC instant (naive datetime)."""
    zone = zones()[code]
    std = zone["std_offset_hours"]
    if not zone["dst"]:
        return std
    start, end = us_dst_dates(utc.year)
    start_utc = dt.datetime.combine(start, dt.time(2, 0)) - dt.timedelta(hours=std)
    end_utc = dt.datetime.combine(end, dt.time(2, 0)) - dt.timedelta(hours=std + 1)
    return std + 1 if start_utc <= utc < end_utc else std


def us_local(code, utc):
    return utc + dt.timedelta(hours=us_offset_hours(code, utc))


def us_to_utc(code, local):
    """UTC instant of a wall-clock time in a US zone (naive datetimes)."""
    zone = zones()[code]
    std = zone["std_offset_hours"]
    offset = std
    if zone["dst"]:
        start, end = us_dst_dates(local.year)
        if dt.datetime.combine(start, dt.time(2, 0)) <= local < dt.datetime.combine(end, dt.time(2, 0)):
            offset = std + 1
    return local - dt.timedelta(hours=offset)


def israel_dst_utc_bounds(year):
    """(start, end) UTC instants of Israel daylight time.

    IDT starts on the Friday before the last Sunday of March at 02:00 local
    (00:00 UTC) and ends on the last Sunday of October at 02:00 local
    (23:00 UTC the day before).
    """
    start_day = last_weekday(year, 3, SUNDAY) - dt.timedelta(days=2)
    end_day = last_weekday(year, 10, SUNDAY)
    start = dt.datetime.combine(start_day, dt.time(2, 0)) - dt.timedelta(hours=2)
    end = dt.datetime.combine(end_day, dt.time(2, 0)) - dt.timedelta(hours=3)
    return start, end


def israel_offset_hours(utc):
    start, end = israel_dst_utc_bounds(utc.year)
    return 3 if start <= utc < end else 2


def israel_local(utc):
    return utc + dt.timedelta(hours=israel_offset_hours(utc))


def israel_to_utc(local):
    """UTC instant of a wall-clock time in Israel (naive datetimes)."""
    guess = local - dt.timedelta(hours=2)
    if israel_offset_hours(guess) == 3:
        guess = local - dt.timedelta(hours=3)
    return guess


def parse_now(text):
    """Parse --now into a naive UTC datetime. A time with no offset is read as Israel time."""
    raw = str(text).strip()
    if raw.upper().endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        raise PlaybookError(
            "--now must be an ISO date-time (got %r)." % text,
            "Examples: 2026-11-24T14:16 (Israel time) or 2026-11-24T12:16+00:00",
        )
    check_year(parsed.year, "--now", text)
    if parsed.tzinfo is None:
        return israel_to_utc(parsed)
    return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- holidays

def holiday_windows(year):
    """Blocked windows that touch the given calendar year: (id, name, start, end)."""
    out = []
    for window in load("cadence")["holiday_windows"]:
        if window["rule"] == "week_of_nth_weekday":
            anchor = nth_weekday(year, window["month"], window["weekday"], window["n"])
            start, end = week_monday_friday(anchor)
            out.append((window["id"], window["name"], start, end))
        elif window["rule"] == "fixed_range":
            (m1, d1), (m2, d2) = window["start"], window["end"]
            if (m2, d2) < (m1, d1):
                out.append((window["id"], window["name"], dt.date(year, m1, d1), dt.date(year + 1, m2, d2)))
                out.append((window["id"], window["name"], dt.date(year - 1, m1, d1), dt.date(year, m2, d2)))
            else:
                out.append((window["id"], window["name"], dt.date(year, m1, d1), dt.date(year, m2, d2)))
    return out


def observed(day):
    """OPM weekend rule: Saturday is observed on Friday, Sunday on Monday."""
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def federal_holidays(year):
    """Observed federal holidays that fall in the given calendar year: (id, name, date)."""
    out = []
    for target_year in (year, year + 1):
        for item in load("cadence")["federal_holidays"]["days"]:
            if item["rule"] == "fixed":
                day = observed(dt.date(target_year, item["month"], item["day"]))
            elif item["rule"] == "nth_weekday":
                day = nth_weekday(target_year, item["month"], item["weekday"], item["n"])
            else:
                day = last_weekday(target_year, item["month"], item["weekday"])
            if day.year == year:
                out.append((item["id"], item["name"], day))
    return sorted(out, key=lambda entry: entry[2])


def blocked(day, federal=None):
    """Why a date is closed for sending, or None. Windows first, then single-day holidays."""
    for wid, name, start, end in holiday_windows(day.year):
        if start <= day <= end:
            return {"id": wid, "name": name, "kind": "window"}
    if federal is None:
        federal = load("cadence")["federal_holidays"]["enabled"]
    if federal:
        for hid, name, when in federal_holidays(day.year):
            if when == day:
                return {"id": hid, "name": name, "kind": "federal_holiday"}
    return None


def next_open_weekday(day, federal=None):
    while day.weekday() >= 5 or blocked(day, federal):
        day += dt.timedelta(days=1)
    return day


# ------------------------------------------------------------ conversions

def _hhmm(value):
    return "%02d:%02d" % (value.hour, value.minute)


def _offset_text(hours):
    return "%s%02d:00" % ("+" if hours >= 0 else "-", abs(hours))


def convert(code, day, clock_time):
    """A recipient wall-clock moment, shown on both clocks."""
    local = dt.datetime.combine(day, clock_time)
    utc = us_to_utc(code, local)
    israel = israel_local(utc)
    us_off = us_offset_hours(code, utc)
    il_off = israel_offset_hours(utc)
    std_gap = 2 - zones()[code]["std_offset_hours"]
    return {
        "utc": utc,
        "israel": israel,
        "us_offset": us_off,
        "israel_offset": il_off,
        "hours_ahead": il_off - us_off,
        "usual_hours_ahead": std_gap,
    }


def date_notes(day, code, lang="en"):
    """Cautions attached to a send date: August, quarter edges, the DST gap."""
    cautions = load("cadence")["cautions"]
    notes = []
    if day.month == 8:
        notes.append({"id": "august", "text": tr(cautions["august"], lang)})
    if day.month in (3, 6, 9, 12):
        if (month_end(day) - day).days < cautions["quarter_end"]["last_days"]:
            notes.append({"id": "quarter_end", "text": tr(cautions["quarter_end"], lang)})
    if day.month in (1, 4, 7, 10) and day.day <= cautions["quarter_start"]["first_days"]:
        notes.append({"id": "quarter_start", "text": tr(cautions["quarter_start"], lang)})
    moment = convert(code, day, parse_hhmm(load("cadence")["send_window"]["representative"]))
    if zones()[code]["dst"] and moment["hours_ahead"] != moment["usual_hours_ahead"]:
        notes.append({"id": "dst_gap", "text": tr(cautions["dst_gap"], lang)})
    return notes


def describe_slot(code, day, clock_time, lang="en", when="scheduled"):
    """Everything the founder needs to know about one send moment."""
    window = load("cadence")["send_window"]
    start, end = parse_hhmm(window["start"]), parse_hhmm(window["end"])
    moment = convert(code, day, clock_time)
    win_start = convert(code, day, start)["israel"]
    win_end = convert(code, day, end)["israel"]
    out = {
        "date": day.isoformat(),
        "weekday": weekday_name(day, "en"),
        "weekday_he": weekday_name(day, "he"),
        "pretty": pretty_date(day),
        "zone": code,
        "local_time": _hhmm(clock_time),
        "window": "%s-%s" % (window["start"], window["end"]),
        "when": when,
        "utc": moment["utc"].strftime("%Y-%m-%dT%H:%MZ"),
        "utc_offset": _offset_text(moment["us_offset"]),
        "israel_date": moment["israel"].date().isoformat(),
        "israel_time": _hhmm(moment["israel"]),
        "israel_window": "%s-%s" % (_hhmm(win_start), _hhmm(win_end)),
        "israel_utc_offset": _offset_text(moment["israel_offset"]),
        "israel_hours_ahead": moment["hours_ahead"],
        "notes": date_notes(day, code, lang),
    }
    if moment["israel"].hour >= 18 or moment["israel"].date() != day:
        out["schedule_send"] = True
    return out


# -------------------------------------------------------------- send slots

def next_send_slots(now_utc, code, count=3, federal=None, lang="en"):
    """The next `count` send moments inside the Tuesday-to-Thursday morning window.

    Returns (slots, skipped) where skipped names every preferred day that was
    passed over before the first slot and why.
    """
    window = load("cadence")["send_window"]
    start, end = parse_hhmm(window["start"]), parse_hhmm(window["end"])
    representative = parse_hhmm(window["representative"])
    local_now = us_local(code, now_utc)
    day = local_now.date()
    slots, skipped = [], []
    for _ in range(400):
        if len(slots) >= count:
            break
        if day.weekday() in window["weekdays"]:
            reason = blocked(day, federal)
            if reason:
                if not slots and (not skipped or skipped[-1]["name"] != reason["name"]):
                    skipped.append({"date": day.isoformat(), "name": reason["name"], "kind": reason["kind"]})
            elif day == local_now.date():
                now_time = local_now.time()
                if now_time <= end:
                    if now_time >= start:
                        slots.append(describe_slot(code, day, dt.time(now_time.hour, now_time.minute), lang, "now"))
                    else:
                        slots.append(describe_slot(code, day, representative, lang, "today"))
                elif not slots:
                    skipped.append({"date": day.isoformat(), "name": "today's send window has closed", "kind": "window_closed"})
            else:
                slots.append(describe_slot(code, day, representative, lang))
        day += dt.timedelta(days=1)
    return slots, skipped


def scheduling_slots(now_utc, code, federal=None):
    """Three offer slots for the scheduling template: the next open Tue, Wed and Thu."""
    offers = [(1, "9:00", "11:00"), (2, "8:00", "10:00"), (3, "13:00", "15:00")]
    local_today = us_local(code, now_utc).date()
    out = []
    cursor = local_today + dt.timedelta(days=1)
    for weekday, start, end in offers:
        day = cursor
        for _ in range(120):
            if day.weekday() == weekday and not blocked(day, federal):
                break
            day += dt.timedelta(days=1)
        cursor = day + dt.timedelta(days=1)
        il_start = convert(code, day, parse_hhmm(start))["israel"]
        il_end = convert(code, day, parse_hhmm(end))["israel"]
        out.append({
            "date": day.isoformat(),
            "line": "%s %s %d, %s-%s" % (WEEKDAYS_SHORT[day.weekday()], MONTHS_SHORT[day.month - 1], day.day, start, end),
            "israel": "%s-%s" % (_hhmm(il_start), _hhmm(il_end)),
            "late_in_israel": il_start.hour >= LATE_HOUR_ISRAEL or il_start.hour < 6,
        })
    return out


# ----------------------------------------------------------------- cadence

def _note(key, lang, **values):
    text = tr(load("cadence")["notes"][key], lang)
    for name, value in values.items():
        text = text.replace("{%s}" % name, str(value))
    return text


def _pick_slot(meeting, first, last, federal, lang="en"):
    """A send date inside [first, last] days after the meeting.

    Preference order: Tuesday to Thursday and open; any open weekday; otherwise
    the first open weekday after the window.
    """
    preferred = load("cadence")["send_window"]["weekdays"]
    window = [meeting + dt.timedelta(days=i) for i in range(first, last + 1)]
    for day in window:
        if day.weekday() in preferred and not blocked(day, federal):
            return day, ""
    for day in window:
        if day.weekday() < 5 and not blocked(day, federal):
            return day, _note("outside_window", lang)
    pushed = next_open_weekday(window[-1] + dt.timedelta(days=1), federal)
    return pushed, _note("pushed", lang)


def _recap_slot(meeting, federal, lang="en"):
    """Recaps go out within 24 hours; they skip weekends but never wait for holidays."""
    day = meeting + dt.timedelta(days=1)
    note = _note("recap_24h", lang)
    if day.weekday() >= 5:
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        note = _note("recap_weekend", lang, weekday=weekday_name(day, lang))
    if blocked(day, federal):
        note += "; " + _note("recap_holiday", lang)
    return day, note


def cadence(meeting, code, today=None, sent=(), federal=None, lang="en"):
    """The five touches after a meeting, with dates on both clocks and a status each."""
    cfg = load("cadence")
    representative = parse_hhmm(cfg["send_window"]["representative"])
    picked = []
    for touch in cfg["touches"]:
        if touch["id"] == "recap":
            day, note = _recap_slot(meeting, federal, lang)
        else:
            day, note = _pick_slot(meeting, touch["window_days"][0], touch["window_days"][1], federal, lang)
        picked.append([touch, day, note])
    for index in range(1, len(picked)):
        previous = picked[index - 1][1]
        if picked[index][1] <= previous + dt.timedelta(days=1):
            picked[index][1] = next_open_weekday(previous + dt.timedelta(days=cfg["min_gap_days"]), federal)
            # The earlier note described a date this touch no longer has.
            picked[index][2] = _note("respaced", lang, days=cfg["min_gap_days"])
    out = []
    next_marked = False
    for touch, day, note in picked:
        slot = describe_slot(code, day, representative, lang)
        if touch["id"] in sent:
            status = "sent"
        elif today is None:
            status = "planned"
        elif day < today:
            status = "overdue"
        elif day == today:
            status = "due_today"
        else:
            status = "upcoming"
        is_next = False
        if status != "sent" and not next_marked:
            is_next = True
            next_marked = True
        slot.update({
            "id": touch["id"],
            "n": touch["n"],
            "name": tr(touch["name"], lang),
            "timing": touch["timing"],
            "template": touch["template"],
            "content": touch["content_he"] if lang == "he" else touch["content"],
            "note": note,
            "status": status,
            "next": is_next,
        })
        out.append(slot)
    return out


# --------------------------------------------------------------------- ics

def _ics_escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(touches, title, meeting):
    """An iCalendar file with one 15-minute reminder per touch, in UTC.

    Deterministic: the same cadence always produces the same bytes.
    """
    stamp = dt.datetime.combine(meeting, dt.time(0, 0)).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//american-business-playbook//cadence//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for touch in touches:
        start = dt.datetime.strptime(touch["utc"], "%Y-%m-%dT%H:%MZ")
        end = start + dt.timedelta(minutes=15)
        summary = "%s: %s (send %s %s)" % (title, touch["name"], touch["local_time"], touch["zone"])
        description = "Touch %d of 5. %s Template: %s." % (touch["n"], touch["content"], touch["template"])
        uid = hashlib.sha256(("%s|%s|%s" % (title, touch["id"], touch["utc"])).encode("utf-8")).hexdigest()[:24]
        lines.extend([
            "BEGIN:VEVENT",
            "UID:%s@american-business-playbook" % uid,
            "DTSTAMP:%s" % stamp,
            "DTSTART:%s" % start.strftime("%Y%m%dT%H%M%SZ"),
            "DTEND:%s" % end.strftime("%Y%m%dT%H%M%SZ"),
            "SUMMARY:%s" % _ics_escape(summary),
            "DESCRIPTION:%s" % _ics_escape(description),
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
