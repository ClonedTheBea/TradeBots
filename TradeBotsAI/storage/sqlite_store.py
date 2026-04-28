"""SQLite storage layer for local advisory records."""

from __future__ import annotations

import sqlite3
from pathlib import Path
import json
from types import TracebackType

from data.models import BacktestResult, Signal, Trade


class SQLiteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> "SQLiteStore":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)

    def close(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None

    def initialize(self) -> None:
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                reasons TEXT NOT NULL DEFAULT '[]',
                reason TEXT NOT NULL,
                close REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                quantity REAL NOT NULL,
                profit_loss REAL NOT NULL,
                profit_loss_pct REAL NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                starting_cash REAL NOT NULL,
                ending_cash REAL NOT NULL,
                total_return_pct REAL NOT NULL,
                trade_count INTEGER NOT NULL,
                signal_count INTEGER NOT NULL DEFAULT 0,
                win_rate REAL NOT NULL,
                average_profit_per_trade REAL NOT NULL DEFAULT 0,
                max_drawdown_pct REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self._ensure_column("signals", "score", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("signals", "reasons", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("backtest_results", "signal_count", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(
            "backtest_results",
            "average_profit_per_trade",
            "REAL NOT NULL DEFAULT 0",
        )
        conn.commit()

    def save_signal(self, signal: Signal) -> None:
        self._conn().execute(
            """
            INSERT INTO signals (
                symbol, timestamp, action, confidence, score, reasons, reason, close
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.symbol,
                signal.timestamp,
                signal.action,
                signal.confidence,
                signal.score,
                json.dumps(list(signal.reasons)),
                signal.reason,
                signal.close,
            ),
        )
        self._conn().commit()

    def save_trade(self, trade: Trade) -> None:
        self._conn().execute(
            """
            INSERT INTO trades (
                symbol, entry_time, exit_time, entry_price, exit_price,
                quantity, profit_loss, profit_loss_pct, reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.symbol,
                trade.entry_time,
                trade.exit_time,
                trade.entry_price,
                trade.exit_price,
                trade.quantity,
                trade.profit_loss,
                trade.profit_loss_pct,
                trade.reason,
            ),
        )
        self._conn().commit()

    def save_backtest_result(self, result: BacktestResult) -> None:
        self._conn().execute(
            """
            INSERT INTO backtest_results (
                symbol, starting_cash, ending_cash, total_return_pct,
                trade_count, signal_count, win_rate, average_profit_per_trade, max_drawdown_pct
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.symbol,
                result.starting_cash,
                result.ending_cash,
                result.total_return_pct,
                len(result.trades),
                len(result.signals),
                result.win_rate,
                result.average_profit_per_trade,
                result.max_drawdown_pct,
            ),
        )
        self._conn().commit()

    def _conn(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("SQLiteStore is not connected")
        return self.connection

    def _ensure_column(self, table_name: str, column_name: str, definition: str) -> None:
        columns = {
            row[1] for row in self._conn().execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            self._conn().execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
