import tempfile
import unittest
from pathlib import Path

from app.automation import (
    append_price_if_new,
    last_recorded_timestamp,
    load_step_config,
    save_step_config,
)
from game_interface.config import STEP_BUTTON_X, STEP_BUTTON_Y, STEP_DELAY_SECONDS


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

    def test_step_config_defaults_when_runtime_config_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_step_config(Path(tmpdir) / "missing.json")

        self.assertEqual(config["x"], STEP_BUTTON_X)
        self.assertEqual(config["y"], STEP_BUTTON_Y)
        self.assertEqual(config["delay_seconds"], STEP_DELAY_SECONDS)

    def test_save_and_load_step_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "automation_config.json"

            save_step_config(123, 456, delay_seconds=0.9, config_path=config_path)
            config = load_step_config(config_path)

        self.assertEqual(config["x"], 123)
        self.assertEqual(config["y"], 456)
        self.assertEqual(config["delay_seconds"], 0.9)


if __name__ == "__main__":
    unittest.main()
