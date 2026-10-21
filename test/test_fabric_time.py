"""FAA-65: the public date API of fabric_time, on the cases fabric-time.mjs reads too (test/fixtures/kit-time-cases.json)."""
import datetime as dt
import json
import math
import sys
import unittest
from pathlib import Path

from test_fabric_service import load  # noqa: E402

ft = load("fabric_time")

CASES = json.loads((Path(__file__).parent / "fixtures/kit-time-cases.json").read_text(encoding="utf-8"))
nan_null = lambda x: None if math.isnan(x) else int(x)  # noqa: E731


class Dates(unittest.TestCase):
    def test_parse(self):
        for text, expected in CASES["parse"]:
            with self.subTest(text=text):
                self.assertEqual(nan_null(ft.parse_rfc3339_ms(text)), expected)

    def test_utc_date(self):
        for text, expected in CASES["utcDate"]:
            with self.subTest(text=text):
                self.assertEqual(nan_null(ft.utc_date_ms(text)), expected)

    def test_days_and_formatting(self):
        for ms, day in CASES["utcDay"]:
            self.assertEqual(ft.utc_day(ms), day)
        for ms, text in CASES["format"]:
            self.assertEqual(ft.format_rfc3339(ms), text)
            self.assertEqual(ft.parse_rfc3339_ms(text), ms, "format and parse round-trip")
        for today, days, window in CASES["window"]:
            self.assertEqual(ft.day_window(today, days), window)
        for bad in (math.nan, math.inf):
            with self.assertRaises(ValueError):
                ft.utc_day(bad)

    def test_clock(self):
        self.assertEqual(ft.clock_ms(dt.datetime(2026, 10, 21, 9, tzinfo=dt.timezone.utc)), 1792573200000)
        self.assertEqual(ft.clock_ms(1792573200), 1792573200000)
        for bad in (dt.datetime(2026, 10, 21, 9), True, "1792573200", None, math.inf):
            self.assertTrue(math.isnan(ft.clock_ms(bad)), bad)
        self.assertEqual(ft.now_ms(lambda: 1792573200.5), 1792573200500)


if __name__ == "__main__":
    unittest.main()
