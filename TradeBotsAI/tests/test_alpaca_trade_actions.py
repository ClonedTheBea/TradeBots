import sqlite3
import tempfile
import unittest
from pathlib import Path

from storage.sqlite_store import SQLiteStore


class AlpacaTradeActionStorageTests(unittest.TestCase):
    def test_save_alpaca_trade_action_records_skipped_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tradebots.sqlite"
            with SQLiteStore(db_path) as store:
                store.initialize()
                store.save_alpaca_trade_action(
                    symbol="AAPL",
                    action="HOLD",
                    status="skipped",
                    reason="HOLD",
                    confidence=0.17,
                    qty=1,
                    session_id="cycle-1",
                )

            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute(
                    """
                    SELECT session_id, symbol, action, confidence, qty, status, reason
                    FROM alpaca_trade_actions
                    """
                ).fetchone()
            finally:
                conn.close()

        self.assertEqual(row, ("cycle-1", "AAPL", "HOLD", 0.17, 1.0, "skipped", "HOLD"))


if __name__ == "__main__":
    unittest.main()
