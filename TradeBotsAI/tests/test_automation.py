import tempfile
import unittest
from pathlib import Path

from app.automation import (
    append_price_if_new,
    execute_trade,
    last_recorded_timestamp,
    load_step_config,
    save_step_config,
)
from game_interface.config import STEP_BUTTON_X, STEP_BUTTON_Y, STEP_DELAY_SECONDS
from game_interface.screen_state import ScreenState


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

        self.assertEqual(config["step_button_x"], STEP_BUTTON_X)
        self.assertEqual(config["step_button_y"], STEP_BUTTON_Y)
        self.assertEqual(config["step_delay_seconds"], STEP_DELAY_SECONDS)

    def test_save_and_load_step_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "automation_config.json"

            save_step_config(123, 456, delay_seconds=0.9, config_path=config_path)
            config = load_step_config(config_path)

        self.assertEqual(config["step_button_x"], 123)
        self.assertEqual(config["step_button_y"], 456)
        self.assertEqual(config["step_delay_seconds"], 0.9)

    def test_buy_with_no_holdings_executes(self):
        result = execute_trade(
            "BUY",
            screen_state(holdings=0.0),
            dry_run=False,
            pyautogui_module=FakePyAutoGui(),
            config=fake_config(),
        )

        self.assertTrue(result.executed)
        self.assertTrue(result.clicked_buy)
        self.assertFalse(result.clicked_sell)
        self.assertTrue(result.moved_slider)
        self.assertTrue(result.clicked_process_trade)

    def test_buy_with_holdings_skips(self):
        result = execute_trade("BUY", screen_state(holdings=10.0), dry_run=False)

        self.assertFalse(result.executed)
        self.assertEqual(result.skipped_reason, "BUY skipped: already holding stock.")

    def test_sell_with_holdings_executes(self):
        result = execute_trade(
            "SELL",
            screen_state(holdings=10.0),
            dry_run=False,
            pyautogui_module=FakePyAutoGui(),
            config=fake_config(),
        )

        self.assertTrue(result.executed)
        self.assertFalse(result.clicked_buy)
        self.assertTrue(result.clicked_sell)
        self.assertTrue(result.moved_slider)
        self.assertTrue(result.clicked_process_trade)

    def test_sell_with_no_holdings_skips(self):
        result = execute_trade("SELL", screen_state(holdings=0.0), dry_run=False)

        self.assertFalse(result.executed)
        self.assertEqual(result.skipped_reason, "SELL skipped: no holdings.")

    def test_hold_skips(self):
        result = execute_trade("HOLD", screen_state(holdings=0.0), dry_run=False)

        self.assertFalse(result.executed)
        self.assertEqual(result.skipped_reason, "HOLD signal: no trade.")


class FakePyAutoGui:
    def __init__(self):
        self.calls = []

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def moveTo(self, x, y):
        self.calls.append(("moveTo", x, y))

    def dragTo(self, x, y, duration=0):
        self.calls.append(("dragTo", x, y, duration))


def screen_state(holdings):
    return ScreenState(
        raw_text="",
        game_date="Mar 11 Yr 1",
        price=28.99,
        gain_percent=3.24,
        cash=495.0,
        holdings=holdings,
        captured_at="2026-04-28T12:00:00",
    )


def fake_config():
    return {
        "buy_button_x": 1,
        "buy_button_y": 2,
        "sell_button_x": 3,
        "sell_button_y": 4,
        "slider_right_x": 5,
        "slider_right_y": 6,
        "process_trade_x": 7,
        "process_trade_y": 8,
        "slider_drag_duration_seconds": 0,
    }


if __name__ == "__main__":
    unittest.main()
