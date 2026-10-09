import unittest
from scheduling import parse_start, positive_integer, schedule_fields


class SchedulingValidationTests(unittest.TestCase):
    def test_havana_winter_and_summer_convert_to_utc(self):
        for date, expected in (("2026-01-15", "2026-01-15T23:00:00+00:00"), ("2026-07-15", "2026-07-15T22:00:00+00:00")):
            start = parse_start(date, "18:00")
            self.assertEqual(start.isoformat(), expected)
            self.assertEqual(schedule_fields(start)["date"], date)
        self.assertEqual(schedule_fields(None), {"startsAt": None, "date": None})

    def test_nonexistent_and_ambiguous_havana_times_rejected(self):
        for date in ("2026-03-08", "2026-11-01"):
            with self.assertRaisesRegex(ValueError, "cambio de horario"):
                parse_start(date, "00:30")

    def test_invalid_dates_times_and_numbers(self):
        for date, time in (("2026-02-30", "18:00"), ("2026-01-01", "25:00"), (None, "18:00"), ("2026-1-1", "18:00"), ("2026-01-01", "18:00:00"), ("9999-12-31", "23:00")):
            with self.assertRaises(ValueError):
                parse_start(date, time)
        for number in (True, 0, -1, 1.2, "1e2", "x", None, "9" * 5000, 2147483648):
            with self.assertRaises(ValueError):
                positive_integer(number, "El número")
        self.assertEqual(positive_integer("12", "El número"), 12)
