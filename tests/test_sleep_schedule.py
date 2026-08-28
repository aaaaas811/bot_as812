import unittest
from datetime import datetime

from plugins._31966_plugin.sleep_schedule import is_scheduled_sleep_time


class SleepScheduleTest(unittest.TestCase):
    def test_scheduled_sleep_window_boundaries(self):
        cases = [
            (datetime(2026, 1, 1, 0, 0), True),
            (datetime(2026, 1, 1, 7, 59), True),
            (datetime(2026, 1, 1, 8, 0), False),
        ]

        for current_time, expected in cases:
            with self.subTest(current_time=current_time):
                self.assertIs(is_scheduled_sleep_time(current_time), expected)


if __name__ == "__main__":
    unittest.main()
