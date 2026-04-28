import tempfile
import unittest
from pathlib import Path

from data.models import Signal
from storage.sqlite_store import SQLiteStore
from tests.test_backtest import ScriptedSignalEngine, candles
from strategy.backtest import BacktestConfig, Backtester


def signal(timestamp="2024-03-01", action="BUY", score=3.0):
    reasons = (f"{action} reason", "second reason")
    return Signal(
        symbol="SIM",
        timestamp=timestamp,
        action=action,
        confidence=min(abs(score) / 6.0, 1.0),
        score=score,
        reasons=reasons,
        reason="; ".join(reasons),
        close=123.45,
    )


class SQLiteSignalPersistenceTests(unittest.TestCase):
    def test_save_signal_and_get_recent_signals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with SQLiteStore(Path(tmpdir) / "signals.sqlite") as store:
                store.initialize()
                store.save_signal(signal(), session_id="session-1")

                rows = store.get_recent_signals(limit=1)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_id"], "session-1")
        self.assertEqual(rows[0]["symbol"], "SIM")
        self.assertEqual(rows[0]["close_price"], 123.45)
        self.assertEqual(rows[0]["action"], "BUY")
        self.assertEqual(rows[0]["score"], 3.0)
        self.assertEqual(rows[0]["reasons"], ["BUY reason", "second reason"])

    def test_save_signals_bulk_filters_recent_by_session_and_symbol(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with SQLiteStore(Path(tmpdir) / "signals.sqlite") as store:
                store.initialize()
                store.save_signals_bulk(
                    [
                        signal(timestamp="2024-03-01", action="BUY", score=3.0),
                        signal(timestamp="2024-03-02", action="SELL", score=-3.0),
                    ],
                    session_id="session-1",
                )
                store.save_signal(signal(timestamp="2024-03-03"), session_id="session-2")

                rows = store.get_recent_signals(
                    limit=10,
                    session_id="session-1",
                    symbol="SIM",
                )

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["timestamp"] for row in rows], ["2024-03-02", "2024-03-01"])

    def test_backtester_can_optionally_persist_generated_signals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = ScriptedSignalEngine({33: "BUY", 35: "SELL"})
            with SQLiteStore(Path(tmpdir) / "signals.sqlite") as store:
                store.initialize()
                result = Backtester(engine, BacktestConfig()).run(
                    candles(38),
                    symbol="SIM",
                    signal_store=store,
                    session_id="backtest-session",
                )
                rows = store.get_recent_signals(limit=10, session_id="backtest-session")

        self.assertEqual(len(rows), len(result.signals))
        self.assertEqual(rows[-1]["action"], "BUY")


if __name__ == "__main__":
    unittest.main()
