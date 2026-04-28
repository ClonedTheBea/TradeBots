import tempfile
import unittest
from pathlib import Path

from app.main import _build_performance_report
from storage.sqlite_store import SQLiteStore


class TradeLifecycleTests(unittest.TestCase):
    def test_trade_lifecycle_buy_then_sell_calculates_outcome(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with SQLiteStore(Path(tmpdir) / "trades.sqlite") as store:
                store.initialize()
                store.record_trade_entry(
                    symbol="AAPL",
                    entry_time="2026-04-28T14:30:00",
                    entry_price=100.0,
                    qty=2,
                    entry_confidence=0.7,
                    entry_reasons=("entry reason",),
                )
                closed = store.record_trade_exit(
                    symbol="AAPL",
                    exit_time="2026-04-28T15:00:00",
                    exit_price=110.0,
                    exit_confidence=0.8,
                    exit_reasons=("exit reason",),
                )
                trades = store.get_completed_trades()

        self.assertIsNotNone(closed)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["profit_loss"], 20.0)
        self.assertEqual(trades[0]["profit_loss_pct"], 10.0)
        self.assertEqual(trades[0]["duration_minutes"], 30.0)
        self.assertEqual(trades[0]["entry_reasons"], ["entry reason"])
        self.assertEqual(trades[0]["exit_reasons"], ["exit reason"])

    def test_open_trade_is_not_counted_as_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with SQLiteStore(Path(tmpdir) / "trades.sqlite") as store:
                store.initialize()
                store.record_trade_entry(
                    symbol="MSFT",
                    entry_time="2026-04-28T14:30:00",
                    entry_price=200.0,
                    qty=1,
                    entry_confidence=0.7,
                    entry_reasons=("entry reason",),
                )

                trades = store.get_completed_trades()

        self.assertEqual(trades, [])

    def test_performance_report_summarizes_completed_trades(self):
        trades = [
            {
                "symbol": "AAPL",
                "profit_loss": 20.0,
                "profit_loss_pct": 10.0,
                "duration_minutes": 30.0,
            },
            {
                "symbol": "MSFT",
                "profit_loss": -5.0,
                "profit_loss_pct": -2.5,
                "duration_minutes": 15.0,
            },
        ]

        report = _build_performance_report(trades)

        self.assertIn("- Total trades: 2", report)
        self.assertIn("- Win rate: 50.00%", report)
        self.assertIn("- Total PnL: $15.00", report)
        self.assertIn("- Best trade: AAPL $20.00 (10.00%)", report)
        self.assertIn("MSFT:", report)
        self.assertIn("- total PnL: $-5.00", report)


if __name__ == "__main__":
    unittest.main()
