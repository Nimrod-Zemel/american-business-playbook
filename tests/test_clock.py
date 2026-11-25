"""Time math: zones, Israel time, holiday windows, send slots, the cadence."""

import datetime as dt
import json
import os
import unittest

import _util
from abp import clock
from abp.core import PlaybookError

try:
    from zoneinfo import ZoneInfo

    ZoneInfo("America/New_York")
    ZoneInfo("Asia/Jerusalem")
    HAVE_TZ = True
except Exception:  # no tz database on this machine
    HAVE_TZ = False

D = dt.date
ZONES = ["ET", "CT", "MT", "PT", "AZ", "AKT", "HT"]


def days(start, end):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


class CalendarTest(unittest.TestCase):
    def test_nth_and_last_weekday(self):
        self.assertEqual(clock.nth_weekday(2026, 11, 3, 4), D(2026, 11, 26))  # Thanksgiving
        self.assertEqual(clock.nth_weekday(2026, 9, 0, 1), D(2026, 9, 7))    # Labor Day
        self.assertEqual(clock.last_weekday(2026, 5, 0), D(2026, 5, 25))     # Memorial Day
        self.assertEqual(clock.last_weekday(2026, 12, 6), D(2026, 12, 27))
        self.assertEqual(clock.month_end(D(2028, 2, 3)), D(2028, 2, 29))
        self.assertEqual(clock.month_end(D(2026, 12, 3)), D(2026, 12, 31))

    def test_us_daylight_time_dates(self):
        self.assertEqual(clock.us_dst_dates(2026), (D(2026, 3, 8), D(2026, 11, 1)))
        self.assertEqual(clock.us_dst_dates(2027), (D(2027, 3, 14), D(2027, 11, 7)))

    def test_israel_daylight_time_dates(self):
        start, end = clock.israel_dst_utc_bounds(2026)
        self.assertEqual(start, dt.datetime(2026, 3, 27, 0, 0))   # Friday 02:00 local
        self.assertEqual(end, dt.datetime(2026, 10, 24, 23, 0))   # Sunday 25 Oct 02:00 local
        start, end = clock.israel_dst_utc_bounds(2025)
        self.assertEqual((start.date(), end.date()), (D(2025, 3, 28), D(2025, 10, 25)))


class FederalHolidaysTest(unittest.TestCase):
    """Dates as published by OPM (opm.gov federal holidays page, read 2026-11-24)."""

    OPM = {
        2026: ["01-01", "01-19", "02-16", "05-25", "06-19", "07-03", "09-07", "10-12", "11-11", "11-26", "12-25"],
        2027: ["01-01", "01-18", "02-15", "05-31", "06-18", "07-05", "09-06", "10-11", "11-11", "11-25", "12-24"],
    }

    def test_matches_opm_for_2026_and_2027(self):
        for year, expected in self.OPM.items():
            # OPM lists a New Year's Day observed on 31 December under the following year.
            got = [
                day.strftime("%m-%d") for holiday, _name, day in clock.federal_holidays(year)
                if not (holiday == "new_years_day" and day.month == 12)
            ]
            self.assertEqual(got, expected, year)

    def test_weekend_rule(self):
        self.assertEqual(clock.observed(D(2026, 7, 4)), D(2026, 7, 3))    # Saturday -> Friday
        self.assertEqual(clock.observed(D(2027, 7, 4)), D(2027, 7, 5))    # Sunday -> Monday
        self.assertEqual(clock.observed(D(2026, 11, 11)), D(2026, 11, 11))

    def test_new_year_observed_in_the_previous_year_is_attributed_correctly(self):
        # 1 Jan 2028 is a Saturday, so it is observed on Friday 31 Dec 2027.
        self.assertIn(D(2027, 12, 31), [day for _i, _n, day in clock.federal_holidays(2027)])
        self.assertNotIn(D(2028, 1, 1), [day for _i, _n, day in clock.federal_holidays(2028)])


class HolidayWindowsTest(unittest.TestCase):
    def test_the_four_playbook_windows(self):
        cases = [
            (D(2026, 11, 23), "Thanksgiving week"), (D(2026, 11, 27), "Thanksgiving week"),
            (D(2026, 12, 15), "Winter shutdown"), (D(2027, 1, 5), "Winter shutdown"), (D(2026, 1, 2), "Winter shutdown"),
            (D(2026, 7, 1), "Independence Day week"), (D(2026, 7, 7), "Independence Day week"),
            (D(2026, 9, 7), "Labor Day week"), (D(2026, 9, 11), "Labor Day week"),
        ]
        for day, name in cases:
            self.assertEqual(clock.blocked(day)["name"], name, day)

    def test_days_just_outside_the_windows_are_open(self):
        for day in (D(2026, 11, 20), D(2026, 11, 30), D(2026, 12, 14), D(2027, 1, 6), D(2026, 6, 30), D(2026, 7, 8), D(2026, 9, 14)):
            self.assertIsNone(clock.blocked(day), day)

    def test_single_federal_holidays_can_be_switched_off(self):
        veterans = D(2026, 11, 11)
        self.assertEqual(clock.blocked(veterans)["kind"], "federal_holiday")
        self.assertIsNone(clock.blocked(veterans, federal=False))

    def test_august_is_a_caution_not_a_block(self):
        self.assertIsNone(clock.blocked(D(2026, 8, 12)))
        self.assertIn("august", [note["id"] for note in clock.date_notes(D(2026, 8, 12), "ET")])


class ConversionTest(unittest.TestCase):
    def israel(self, zone, day, hhmm):
        return clock.describe_slot(zone, day, clock.parse_hhmm(hhmm))["israel_time"]

    def test_the_guides_reality_check(self):
        # "a 9:30 AM ET send is 16:30 in Israel (15:30 during the DST gap weeks)"
        self.assertEqual(self.israel("ET", D(2026, 12, 1), "09:30"), "16:30")
        self.assertEqual(self.israel("ET", D(2026, 6, 16), "09:30"), "16:30")
        self.assertEqual(self.israel("ET", D(2026, 3, 17), "09:30"), "15:30")   # US changed, Israel not yet
        self.assertEqual(self.israel("ET", D(2026, 10, 27), "09:30"), "15:30")  # Israel changed back, US not yet

    def test_other_zones(self):
        self.assertEqual(self.israel("CT", D(2026, 12, 1), "09:30"), "17:30")
        self.assertEqual(self.israel("MT", D(2026, 12, 1), "09:30"), "18:30")
        self.assertEqual(self.israel("PT", D(2026, 12, 1), "09:30"), "19:30")
        self.assertEqual(self.israel("AZ", D(2026, 7, 14), "09:30"), "19:30")   # no DST in Arizona
        self.assertEqual(self.israel("HT", D(2026, 12, 1), "09:30"), "21:30")

    def test_gap_weeks_are_flagged(self):
        notes = [note["id"] for note in clock.date_notes(D(2026, 3, 17), "ET")]
        self.assertIn("dst_gap", notes)
        self.assertNotIn("dst_gap", [note["id"] for note in clock.date_notes(D(2026, 12, 1), "ET")])
        self.assertNotIn("dst_gap", [note["id"] for note in clock.date_notes(D(2026, 6, 16), "ET")])

    def test_quarter_edges(self):
        self.assertIn("quarter_end", [n["id"] for n in clock.date_notes(D(2026, 9, 24), "ET")])
        self.assertNotIn("quarter_end", [n["id"] for n in clock.date_notes(D(2026, 9, 10), "ET")])
        self.assertIn("quarter_start", [n["id"] for n in clock.date_notes(D(2026, 10, 6), "ET")])
        self.assertNotIn("quarter_start", [n["id"] for n in clock.date_notes(D(2026, 10, 27), "ET")])

    def test_round_trips(self):
        for zone in ZONES:
            for local in (dt.datetime(2026, 1, 15, 9, 30), dt.datetime(2026, 7, 15, 9, 30), dt.datetime(2026, 3, 8, 9, 30)):
                self.assertEqual(clock.us_local(zone, clock.us_to_utc(zone, local)), local, zone)
        for local in (dt.datetime(2026, 1, 15, 14, 16), dt.datetime(2026, 7, 15, 14, 16)):
            self.assertEqual(clock.israel_local(clock.israel_to_utc(local)), local)

    @unittest.skipUnless(HAVE_TZ, "no tz database on this machine")
    def test_every_day_for_25_years_agrees_with_the_tz_database(self):
        """Our own DST rules against the IANA database, 2016 through 2040."""
        israel = ZoneInfo("Asia/Jerusalem")
        checked = 0
        for zone, spec in clock.zones().items():
            tz = ZoneInfo(spec["iana"])
            for day in days(D(2016, 1, 1), D(2040, 12, 31)):
                for hhmm in ((9, 30), (13, 0)):
                    aware = dt.datetime(day.year, day.month, day.day, hhmm[0], hhmm[1], tzinfo=tz)
                    want = aware.astimezone(israel)
                    got = clock.convert(zone, day, dt.time(*hhmm))["israel"]
                    if (got.date(), got.hour, got.minute) != (want.date(), want.hour, want.minute):
                        self.fail("%s %s %02d:%02d: engine says %s, tz database says %s" % (zone, day, hhmm[0], hhmm[1], got, want))
                    checked += 1
        self.assertGreater(checked, 120000)

    @unittest.skipUnless(HAVE_TZ, "no tz database on this machine")
    def test_utc_to_local_agrees_with_the_tz_database_every_hour_of_2026(self):
        utc = dt.datetime(2026, 1, 1, 0, 0)
        israel = ZoneInfo("Asia/Jerusalem")
        eastern = ZoneInfo("America/New_York")
        while utc.year == 2026:
            aware = utc.replace(tzinfo=dt.timezone.utc)
            self.assertEqual(clock.israel_local(utc), aware.astimezone(israel).replace(tzinfo=None), utc)
            self.assertEqual(clock.us_local("ET", utc), aware.astimezone(eastern).replace(tzinfo=None), utc)
            utc += dt.timedelta(hours=1)


class ZoneResolutionTest(unittest.TestCase):
    def test_codes_aliases_iana_and_cities(self):
        cases = {
            "ET": "ET", "pt": "PT", "EST": "ET", "Pacific": "PT", "America/Chicago": "CT", "america/los_angeles": "PT",
            "Austin": "CT", "New York, NY": "ET", "St. Louis": "CT", "SF": "PT", "Phoenix": "AZ", "Boston": "ET",
        }
        for text, code in cases.items():
            self.assertEqual(clock.resolve_zone(text)["code"], code, text)

    def test_how_the_zone_was_found_is_reported(self):
        self.assertEqual(clock.resolve_zone("ET")["how"], "code")
        self.assertEqual(clock.resolve_zone("Boston")["how"], "city")

    def test_unknown_or_missing_zone_is_an_error_not_a_guess(self):
        for text in ("Narnia", "", None, "Europe/Paris"):
            with self.assertRaises(PlaybookError):
                clock.resolve_zone(text)


class NowParsingTest(unittest.TestCase):
    def test_naive_time_is_israel_time(self):
        self.assertEqual(clock.parse_now("2026-11-24T14:16"), dt.datetime(2026, 11, 24, 12, 16))
        self.assertEqual(clock.parse_now("2026-07-01T14:16"), dt.datetime(2026, 7, 1, 11, 16))

    def test_offsets_and_z(self):
        self.assertEqual(clock.parse_now("2026-11-24T12:16Z"), dt.datetime(2026, 11, 24, 12, 16))
        self.assertEqual(clock.parse_now("2026-11-24T07:16-05:00"), dt.datetime(2026, 11, 24, 12, 16))

    def test_garbage_is_rejected(self):
        with self.assertRaises(PlaybookError):
            clock.parse_now("tomorrow morning")


class SendSlotsTest(unittest.TestCase):
    def test_thanksgiving_week_is_skipped(self):
        slots, skipped = clock.next_send_slots(clock.parse_now("2026-11-24T14:16"), "ET")
        self.assertEqual([slot["date"] for slot in slots], ["2026-12-01", "2026-12-02", "2026-12-03"])
        self.assertEqual(slots[0]["local_time"], "09:30")
        self.assertEqual(slots[0]["israel_time"], "16:30")
        self.assertEqual(slots[0]["israel_window"], "15:30-17:30")
        self.assertEqual(skipped[0]["name"], "Thanksgiving week")

    def test_inside_the_window_means_send_now(self):
        now = clock.us_to_utc("ET", dt.datetime(2026, 10, 13, 9, 5))  # a Tuesday
        slots, _skipped = clock.next_send_slots(now, "ET", count=1)
        self.assertEqual((slots[0]["date"], slots[0]["when"], slots[0]["local_time"]), ("2026-10-13", "now", "09:05"))

    def test_before_the_window_means_later_today(self):
        now = clock.us_to_utc("ET", dt.datetime(2026, 10, 13, 6, 0))
        slots, _skipped = clock.next_send_slots(now, "ET", count=1)
        self.assertEqual((slots[0]["date"], slots[0]["when"], slots[0]["local_time"]), ("2026-10-13", "today", "09:30"))

    def test_after_the_window_means_the_next_open_day(self):
        now = clock.us_to_utc("ET", dt.datetime(2026, 10, 13, 11, 0))
        slots, skipped = clock.next_send_slots(now, "ET", count=1)
        self.assertEqual(slots[0]["date"], "2026-10-14")
        self.assertEqual(skipped[0]["kind"], "window_closed")

    def test_evening_in_israel_is_flagged_for_scheduling(self):
        slots, _skipped = clock.next_send_slots(clock.parse_now("2026-11-24T14:16"), "PT", count=1)
        self.assertEqual(slots[0]["israel_time"], "19:30")
        self.assertTrue(slots[0].get("schedule_send"))
        slots, _skipped = clock.next_send_slots(clock.parse_now("2026-11-24T14:16"), "ET", count=1)
        self.assertFalse(slots[0].get("schedule_send"))

    def test_slots_never_land_on_a_closed_day(self):
        """From 400 different starting moments, every slot is Tue-Thu, open, inside the window."""
        start = dt.datetime(2026, 1, 1, 5, 0)
        for step in range(400):
            now = start + dt.timedelta(hours=37 * step)
            for zone in ("ET", "PT"):
                slots, _skipped = clock.next_send_slots(now, zone, count=3)
                self.assertEqual(len(slots), 3)
                previous = None
                for slot in slots:
                    day = D.fromisoformat(slot["date"])
                    self.assertIn(day.weekday(), (1, 2, 3), slot)
                    self.assertIsNone(clock.blocked(day), slot)
                    self.assertTrue("08:30" <= slot["local_time"] <= "10:30", slot)
                    if previous:
                        self.assertGreater(day, previous)
                    previous = day

    def test_scheduling_slots_are_the_next_open_tue_wed_thu(self):
        slots = clock.scheduling_slots(clock.parse_now("2026-11-24T14:16"), "ET")
        self.assertEqual([slot["line"] for slot in slots], ["Tue Dec 1, 9:00-11:00", "Wed Dec 2, 8:00-10:00", "Thu Dec 3, 13:00-15:00"])
        self.assertEqual([slot["israel"] for slot in slots], ["16:00-18:00", "15:00-17:00", "20:00-22:00"])
        self.assertEqual([slot["late_in_israel"] for slot in slots], [False, False, False])
        late = clock.scheduling_slots(clock.parse_now("2026-11-24T14:16"), "PT")
        self.assertTrue(late[2]["late_in_israel"])

    def test_a_slot_that_starts_at_nine_in_the_evening_in_israel_is_flagged(self):
        """13:00 Central is 21:00 in Israel: the founder should know before offering it."""
        central = clock.scheduling_slots(clock.parse_now("2026-11-24T14:16"), "CT")
        self.assertEqual(central[2]["israel"][:5], "21:00")
        self.assertEqual([slot["late_in_israel"] for slot in central], [False, False, True])
        eastern = clock.scheduling_slots(clock.parse_now("2026-11-24T14:16"), "ET")
        self.assertEqual(eastern[2]["israel"][:5], "20:00")
        self.assertFalse(eastern[2]["late_in_israel"])


class CadenceTest(unittest.TestCase):
    def dates(self, meeting, **kwargs):
        return [touch["date"] for touch in clock.cadence(meeting, "ET", **kwargs)]

    def test_the_documented_example(self):
        self.assertEqual(self.dates(D(2026, 8, 10)), ["2026-08-11", "2026-08-13", "2026-08-18", "2026-08-25", "2026-11-10"])

    def test_reproduces_the_v1_scheduler_on_1096_meeting_dates(self):
        with open(os.path.join(_util.FIXTURES, "v1_cadence_2026_2028.json"), "r", encoding="utf-8") as handle:
            golden = json.load(handle)["dates"]
        self.assertEqual(len(golden), 1096)
        for key, expected in golden.items():
            self.assertEqual(self.dates(D.fromisoformat(key), federal=False), expected, key)

    def test_invariants_hold_for_every_meeting_date_in_five_years(self):
        for meeting in days(D(2026, 1, 1), D(2030, 12, 31)):
            touches = clock.cadence(meeting, "ET")
            dates = [D.fromisoformat(touch["date"]) for touch in touches]
            self.assertEqual([touch["id"] for touch in touches], ["recap", "value", "second_angle", "breakup", "nurture"])
            self.assertGreater(dates[0], meeting)
            for earlier, later in zip(dates, dates[1:]):
                self.assertGreaterEqual((later - earlier).days, 2, meeting)
            for touch, day in zip(touches, dates):
                self.assertLess(day.weekday(), 5, (meeting, touch["id"]))
                if touch["id"] != "recap":
                    self.assertIsNone(clock.blocked(day), (meeting, touch["id"], day))

    def test_recaps_never_wait_for_holidays(self):
        touches = clock.cadence(D(2026, 11, 23), "ET")
        self.assertEqual(touches[0]["date"], "2026-11-24")
        self.assertIn("recaps do not wait", touches[0]["note"])

    def test_friday_meeting_recap_goes_out_monday(self):
        touches = clock.cadence(D(2026, 10, 9), "ET")
        self.assertEqual(touches[0]["date"], "2026-10-12")  # Columbus Day: still sent, recaps do not wait
        self.assertIn("Monday", touches[0]["note"])

    def test_a_note_never_describes_a_date_the_touch_no_longer_has(self):
        """A touch that was respaced onto a Tuesday to Thursday must not still say it is outside that window."""
        outside = clock._note("outside_window", "en")
        for meeting in days(D(2026, 1, 1), D(2028, 12, 31)):
            for touch in clock.cadence(meeting, "ET"):
                if D.fromisoformat(touch["date"]).weekday() in (1, 2, 3):
                    self.assertNotIn(outside, touch["note"], (meeting, touch["id"]))

    def test_notes_follow_the_coaching_language(self):
        english = clock.cadence(D(2026, 11, 20), "ET", lang="en")
        hebrew = clock.cadence(D(2026, 11, 20), "ET", lang="he")
        self.assertEqual([t["date"] for t in english], [t["date"] for t in hebrew])
        self.assertIn("send first thing Monday", english[0]["note"])
        self.assertIn("respaced to keep 2+ days", english[2]["note"])
        for touch in hebrew[:3]:
            self.assertTrue(touch["note"])
            self.assertFalse(any("a" <= char <= "z" for char in touch["note"].lower()), touch["note"])

    def test_status_and_next_marker(self):
        touches = clock.cadence(D(2026, 8, 10), "ET", today=D(2026, 8, 13), sent=["recap"])
        self.assertEqual([touch["status"] for touch in touches], ["sent", "due_today", "upcoming", "upcoming", "upcoming"])
        self.assertEqual([touch["next"] for touch in touches], [False, True, False, False, False])
        late = clock.cadence(D(2026, 8, 10), "ET", today=D(2026, 8, 20))
        self.assertEqual(late[0]["status"], "overdue")
        self.assertTrue(late[0]["next"])
        self.assertEqual(clock.cadence(D(2026, 8, 10), "ET")[0]["status"], "planned")

    def test_dates_do_not_depend_on_the_zone_but_israel_times_do(self):
        east = clock.cadence(D(2026, 8, 10), "ET")
        west = clock.cadence(D(2026, 8, 10), "PT")
        self.assertEqual([t["date"] for t in east], [t["date"] for t in west])
        self.assertEqual((east[0]["israel_time"], west[0]["israel_time"]), ("16:30", "19:30"))

    def test_ics_export_is_valid_and_deterministic(self):
        touches = clock.cadence(D(2026, 8, 10), "ET")
        first = clock.to_ics(touches, "Follow-up", D(2026, 8, 10))
        second = clock.to_ics(clock.cadence(D(2026, 8, 10), "ET"), "Follow-up", D(2026, 8, 10))
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(first.endswith("END:VCALENDAR\r\n"))
        self.assertEqual(first.count("BEGIN:VEVENT"), 5)
        self.assertEqual(first.count("END:VEVENT"), 5)
        self.assertIn("DTSTART:20260811T133000Z", first)  # 09:30 EDT
        uids = [line for line in first.split("\r\n") if line.startswith("UID:")]
        self.assertEqual(len(set(uids)), 5)


if __name__ == "__main__":
    unittest.main()
