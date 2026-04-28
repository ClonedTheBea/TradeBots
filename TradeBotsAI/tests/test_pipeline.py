import tempfile
import unittest
from pathlib import Path

from app.recorder import append_close_price
from data.csv_loader import load_candles_from_csv
from decision.advisor import build_advice
from storage.sqlite_store import SQLiteStore
from strategy.backtest import BacktestConfig, Backtester
from strategy.signals import SignalConfig, SignalEngine


class PipelineTests(unittest.TestCase):
    def test_csv_signal_backtest_and_storage_pipeline(self):
        candles = load_candles_from_csv(Path("data/sample_ohlcv.csv"))
        engine = SignalEngine(SignalConfig())

        signal = engine.latest_signal(candles, symbol="SIM")
        result = Backtester(engine, BacktestConfig()).run(candles, symbol="SIM")
        advice = build_advice(signal, result)

        self.assertIn(signal.action, {"BUY", "SELL", "HOLD"})
        self.assertIn(advice.action, {"BUY", "SELL", "HOLD"})
        self.assertGreaterEqual(advice.confidence, 0.0)
        self.assertLessEqual(advice.confidence, 1.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tradebots.sqlite"
            with SQLiteStore(db_path) as store:
                store.initialize()
                store.save_signal(signal)
                store.save_backtest_result(result)
                for trade in result.trades:
                    store.save_trade(trade)

            self.assertTrue(db_path.exists())

    def test_close_only_csv_loads_as_synthetic_candles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "close_only.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                handle.write("timestamp,close\n")
                for index in range(35):
                    handle.write(f"2024-05-{index + 1:02d},{100 + index}\n")

            candles = load_candles_from_csv(csv_path)

        self.assertEqual(len(candles), 35)
        self.assertTrue(all(candle.is_synthetic for candle in candles))
        self.assertEqual(candles[0].open, candles[0].close)
        self.assertEqual(candles[0].high, candles[0].close)
        self.assertEqual(candles[0].low, candles[0].close)
        self.assertEqual(candles[0].volume, 0.0)

    def test_manual_recorder_appends_close_only_csv_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "manual_prices.csv"

            append_close_price(csv_path, "2024-06-01", 101.25)
            append_close_price(csv_path, "2024-06-02", 102.5)

            content = csv_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(content[0], "timestamp,close")
        self.assertEqual(content[1], "2024-06-01,101.25")
        self.assertEqual(content[2], "2024-06-02,102.5")


if __name__ == "__main__":
    unittest.main()
