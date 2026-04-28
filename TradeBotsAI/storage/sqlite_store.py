"""SQLite storage layer for local advisory records."""

from __future__ import annotations

import sqlite3
from pathlib import Path
import json
from types import TracebackType
from typing import Any, Iterable

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
                session_id TEXT,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                close_price REAL NOT NULL DEFAULT 0,
                reasons_json TEXT NOT NULL DEFAULT '[]',
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
        self._ensure_column("signals", "session_id", "TEXT")
        self._ensure_column("signals", "score", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("signals", "close_price", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("signals", "reasons_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("signals", "reasons", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("backtest_results", "signal_count", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(
            "backtest_results",
            "average_profit_per_trade",
            "REAL NOT NULL DEFAULT 0",
        )
        conn.commit()

    def save_signal(self, signal: Signal, session_id: str | None = None) -> None:
        self._conn().execute(
            """
            INSERT INTO signals (
                session_id, symbol, timestamp, close_price, action, score,
                confidence, reasons_json, reasons, reason, close
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                signal.symbol,
                signal.timestamp,
                signal.close,
                signal.action,
                signal.score,
                signal.confidence,
                _reasons_json(signal),
                _reasons_json(signal),
                signal.reason,
                signal.close,
            ),
        )
        self._conn().commit()

    def save_signals_bulk(
        self,
        signals: Iterable[Signal],
        session_id: str | None = None,
    ) -> None:
        rows = [
            (
                session_id,
                signal.symbol,
                signal.timestamp,
                signal.close,
                signal.action,
                signal.score,
                signal.confidence,
                _reasons_json(signal),
                _reasons_json(signal),
                signal.reason,
                signal.close,
            )
            for signal in signals
        ]
        if not rows:
            return

        self._conn().executemany(
            """
            INSERT INTO signals (
                session_id, symbol, timestamp, close_price, action, score,
                confidence, reasons_json, reasons, reason, close
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn().commit()

    def get_recent_signals(
        self,
        limit: int = 20,
        session_id: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be positive")

        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = self._conn().execute(
            f"""
            SELECT
                id, session_id, timestamp, symbol, close_price, action,
                score, confidence, reasons_json, created_at
            FROM signals
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = []
        for row in cursor.fetchall():
            reasons_json = row[8]
            rows.append(
                {
                    "id": row[0],
                    "session_id": row[1],
                    "timestamp": row[2],
                    "symbol": row[3],
                    "close_price": row[4],
                    "action": row[5],
                    "score": row[6],
                    "confidence": row[7],
                    "reasons_json": reasons_json,
                    "reasons": json.loads(reasons_json),
                    "created_at": row[9],
                }
            )
        return rows

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


def _reasons_json(signal: Signal) -> str:
    return json.dumps(list(signal.reasons))
