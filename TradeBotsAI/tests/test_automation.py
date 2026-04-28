import tempfile
import unittest
from pathlib import Path

from app.automation import append_price_if_new, last_recorded_timestamp


class AutomationTests(unittest.TestCase):
    def test_append_price_if_new_skips_duplicate_last_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "live.csv"
            self.assertTrue(append_price_if_new(csv_path, "Mar 11 Yr 1", 28.99))
            self.assertFalse(append_price_if_new(csv_path, "Mar 11 Yr 1", 29.01))

            rows = csv_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1], "Mar 11 Yr 1,28.99")

    def test_append_price_if_new_allows_duplicates_when_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "live.csv"
            append_price_if_new(csv_path, "Mar 11 Yr 1", 28.99)
            appended = append_price_if_new(
                csv_path,
                "Mar 11 Yr 1",
                29.01,
                allow_duplicates=True,
            )

            rows = csv_path.read_text(encoding="utf-8").splitlines()

        self.assertTrue(appended)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2], "Mar 11 Yr 1,29.01")

    def test_last_recorded_timestamp_returns_none_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "missing.csv"

            self.assertIsNone(last_recorded_timestamp(csv_path))


if __name__ == "__main__":
    unittest.main()
