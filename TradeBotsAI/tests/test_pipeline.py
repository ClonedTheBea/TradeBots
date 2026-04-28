import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()

