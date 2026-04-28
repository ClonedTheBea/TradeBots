"""SQLite storage layer for local advisory records."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
import json
from types import TracebackType
from typing import Any, Iterable

from data.models import BacktestResult, Candle, Signal, Trade


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
                entry_price REAL NOT NULL,
                exit_time TEXT,
                exit_price REAL,
                qty REAL NOT NULL,
                side TEXT NOT NULL DEFAULT 'LONG',
                entry_confidence REAL,
                exit_confidence REAL,
                entry_reason_json TEXT NOT NULL DEFAULT '[]',
                exit_reason_json TEXT NOT NULL DEFAULT '[]',
                profit_loss REAL,
                profit_loss_pct REAL,
                duration_minutes REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                qty REAL NOT NULL,
                avg_entry_price REAL NOT NULL,
                last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS strategy_parameters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                lookback_days INTEGER NOT NULL,
                sma_short INTEGER NOT NULL,
                sma_long INTEGER NOT NULL,
                rsi_buy REAL NOT NULL,
                rsi_sell REAL NOT NULL,
                buy_score_threshold REAL NOT NULL,
                sell_score_threshold REAL NOT NULL,
                stop_loss_pct REAL NOT NULL,
                take_profit_pct REAL NOT NULL,
                total_return_pct REAL NOT NULL,
                max_drawdown_pct REAL NOT NULL,
                win_rate_pct REAL NOT NULL,
                trade_count INTEGER NOT NULL,
                score REAL NOT NULL,
                train_return_pct REAL,
                validation_return_pct REAL,
                train_drawdown_pct REAL,
                validation_drawdown_pct REAL,
                train_win_rate_pct REAL,
                validation_win_rate_pct REAL,
                validation_trade_count INTEGER,
                overfit_warning TEXT,
                promotion_status TEXT,
                rejection_reasons_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
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

            CREATE TABLE IF NOT EXISTS alpaca_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                status TEXT,
                raw_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alpaca_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                qty REAL NOT NULL,
                market_value REAL,
                source TEXT NOT NULL DEFAULT 'alpaca_paper',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alpaca_trade_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL,
                qty REAL,
                status TEXT NOT NULL,
                reason TEXT,
                order_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS market_candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                timeframe TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, symbol, timestamp, timeframe)
            );
            """
        )
        self._ensure_column("signals", "session_id", "TEXT")
        self._ensure_column("signals", "score", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("signals", "close_price", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("signals", "reasons_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("signals", "reasons", "TEXT NOT NULL DEFAULT '[]'")
        self._migrate_trades_table_if_needed()
        self._ensure_column("strategy_parameters", "train_return_pct", "REAL")
        self._ensure_column("strategy_parameters", "validation_return_pct", "REAL")
        self._ensure_column("strategy_parameters", "train_drawdown_pct", "REAL")
        self._ensure_column("strategy_parameters", "validation_drawdown_pct", "REAL")
        self._ensure_column("strategy_parameters", "train_win_rate_pct", "REAL")
        self._ensure_column("strategy_parameters", "validation_win_rate_pct", "REAL")
        self._ensure_column("strategy_parameters", "validation_trade_count", "INTEGER")
        self._ensure_column("strategy_parameters", "overfit_warning", "TEXT")
        self._ensure_column("strategy_parameters", "promotion_status", "TEXT")
        self._ensure_column("strategy_parameters", "rejection_reasons_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("backtest_results", "signal_count", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(
            "backtest_results",
            "average_profit_per_trade",
            "REAL NOT NULL DEFAULT 0",
        )
        conn.commit()

    def save_alpaca_trade_action(
        self,
        symbol: str,
        action: str,
        status: str,
        reason: str | None = None,
        confidence: float | None = None,
        qty: float | None = None,
        order_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self._conn().execute(
            """
            INSERT INTO alpaca_trade_actions (
                session_id, symbol, action, confidence, qty, status, reason, order_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                symbol.upper(),
                action,
                confidence,
                qty,
                status,
                reason,
                order_id,
            ),
        )
        self._conn().commit()

    def record_trade_entry(
        self,
        symbol: str,
        entry_time: str,
        entry_price: float,
        qty: float,
        entry_confidence: float,
        entry_reasons: Iterable[str],
    ) -> int:
        cursor = self._conn().execute(
            """
            INSERT INTO trades (
                symbol, entry_time, entry_price, qty, side,
                entry_confidence, entry_reason_json
            )
            VALUES (?, ?, ?, ?, 'LONG', ?, ?)
            """,
            (
                symbol.upper(),
                entry_time,
                entry_price,
                qty,
                entry_confidence,
                json.dumps(list(entry_reasons)),
            ),
        )
        self._upsert_position(symbol, qty, entry_price, entry_time)
        self._conn().commit()
        return int(cursor.lastrowid)

    def record_trade_exit(
        self,
        symbol: str,
        exit_time: str,
        exit_price: float,
        exit_confidence: float,
        exit_reasons: Iterable[str],
    ) -> dict[str, Any] | None:
        open_trade = self.get_open_trade(symbol)
        if open_trade is None:
            return None

        qty = float(open_trade["qty"])
        entry_price = float(open_trade["entry_price"])
        profit_loss = (exit_price - entry_price) * qty
        profit_loss_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price else 0.0
        duration_minutes = _duration_minutes(open_trade["entry_time"], exit_time)
        self._conn().execute(
            """
            UPDATE trades
            SET
                exit_time = ?,
                exit_price = ?,
                exit_confidence = ?,
                exit_reason_json = ?,
                profit_loss = ?,
                profit_loss_pct = ?,
                duration_minutes = ?
            WHERE id = ?
            """,
            (
                exit_time,
                exit_price,
                exit_confidence,
                json.dumps(list(exit_reasons)),
                round(profit_loss, 2),
                round(profit_loss_pct, 4),
                duration_minutes,
                open_trade["id"],
            ),
        )
        self._conn().execute("DELETE FROM positions WHERE symbol = ?", (symbol.upper(),))
        self._conn().commit()
        return self.get_trade_by_id(int(open_trade["id"]))

    def get_open_trade(self, symbol: str) -> dict[str, Any] | None:
        cursor = self._conn().execute(
            """
            SELECT
                id, symbol, entry_time, entry_price, exit_time, exit_price,
                qty, side, entry_confidence, exit_confidence,
                entry_reason_json, exit_reason_json, profit_loss,
                profit_loss_pct, duration_minutes, created_at
            FROM trades
            WHERE symbol = ? AND exit_time IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        )
        row = cursor.fetchone()
        return _trade_row_to_dict(row) if row else None

    def get_trade_by_id(self, trade_id: int) -> dict[str, Any] | None:
        cursor = self._conn().execute(
            """
            SELECT
                id, symbol, entry_time, entry_price, exit_time, exit_price,
                qty, side, entry_confidence, exit_confidence,
                entry_reason_json, exit_reason_json, profit_loss,
                profit_loss_pct, duration_minutes, created_at
            FROM trades
            WHERE id = ?
            """,
            (trade_id,),
        )
        row = cursor.fetchone()
        return _trade_row_to_dict(row) if row else None

    def get_completed_trades(
        self,
        limit: int | None = None,
        since_days: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["exit_time IS NOT NULL"]
        params: list[Any] = []
        if since_days is not None:
            if since_days <= 0:
                raise ValueError("since_days must be positive")
            clauses.append("datetime(exit_time) >= datetime('now', ?)")
            params.append(f"-{since_days} days")
        limit_sql = ""
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be positive")
            limit_sql = "LIMIT ?"
            params.append(limit)
        cursor = self._conn().execute(
            f"""
            SELECT
                id, symbol, entry_time, entry_price, exit_time, exit_price,
                qty, side, entry_confidence, exit_confidence,
                entry_reason_json, exit_reason_json, profit_loss,
                profit_loss_pct, duration_minutes, created_at
            FROM trades
            WHERE {' AND '.join(clauses)}
            ORDER BY exit_time DESC, id DESC
            {limit_sql}
            """,
            params,
        )
        return [_trade_row_to_dict(row) for row in cursor.fetchall()]

    def save_strategy_parameters(
        self,
        params: dict[str, Any],
        active: bool = True,
    ) -> int:
        symbol = str(params["symbol"]).upper()
        timeframe = str(params["timeframe"])
        if active:
            self._conn().execute(
                """
                UPDATE strategy_parameters
                SET is_active = 0
                WHERE symbol = ? AND timeframe = ? AND is_active = 1
                """,
                (symbol, timeframe),
            )
        cursor = self._conn().execute(
            """
            INSERT INTO strategy_parameters (
                symbol, timeframe, lookback_days, sma_short, sma_long,
                rsi_buy, rsi_sell, buy_score_threshold, sell_score_threshold,
                stop_loss_pct, take_profit_pct, total_return_pct,
                max_drawdown_pct, win_rate_pct, trade_count, score,
                train_return_pct, validation_return_pct, train_drawdown_pct,
                validation_drawdown_pct, train_win_rate_pct, validation_win_rate_pct,
                validation_trade_count, overfit_warning, promotion_status,
                rejection_reasons_json, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                timeframe,
                int(params["lookback_days"]),
                int(params["sma_short"]),
                int(params["sma_long"]),
                float(params["rsi_buy"]),
                float(params["rsi_sell"]),
                float(params["buy_score_threshold"]),
                float(params["sell_score_threshold"]),
                float(params["stop_loss_pct"]),
                float(params["take_profit_pct"]),
                float(params["total_return_pct"]),
                float(params["max_drawdown_pct"]),
                float(params["win_rate_pct"]),
                int(params["trade_count"]),
                float(params["score"]),
                _optional_float(params.get("train_return_pct")),
                _optional_float(params.get("validation_return_pct")),
                _optional_float(params.get("train_drawdown_pct")),
                _optional_float(params.get("validation_drawdown_pct")),
                _optional_float(params.get("train_win_rate_pct")),
                _optional_float(params.get("validation_win_rate_pct")),
                _optional_int(params.get("validation_trade_count")),
                params.get("overfit_warning"),
                params.get("promotion_status"),
                json.dumps(list(params.get("rejection_reasons") or [])),
                1 if active else 0,
            ),
        )
        self._conn().commit()
        return int(cursor.lastrowid)

    def promote_strategy_parameters(self, row_id: int) -> None:
        cursor = self._conn().execute(
            "SELECT symbol, timeframe FROM strategy_parameters WHERE id = ?",
            (row_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"strategy parameter row not found: {row_id}")
        symbol, timeframe = row
        self._conn().execute(
            """
            UPDATE strategy_parameters
            SET is_active = 0
            WHERE symbol = ? AND timeframe = ? AND is_active = 1
            """,
            (symbol, timeframe),
        )
        self._conn().execute(
            """
            UPDATE strategy_parameters
            SET is_active = 1, promotion_status = 'promoted'
            WHERE id = ?
            """,
            (row_id,),
        )
        self._conn().commit()

    def get_active_strategy_parameters(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        cursor = self._conn().execute(
            """
            SELECT
                id, symbol, timeframe, lookback_days, sma_short, sma_long,
                rsi_buy, rsi_sell, buy_score_threshold, sell_score_threshold,
                stop_loss_pct, take_profit_pct, total_return_pct,
                max_drawdown_pct, win_rate_pct, trade_count, score,
                train_return_pct, validation_return_pct, train_drawdown_pct,
                validation_drawdown_pct, train_win_rate_pct, validation_win_rate_pct,
                validation_trade_count, overfit_warning, promotion_status,
                rejection_reasons_json, created_at, is_active
            FROM strategy_parameters
            WHERE symbol = ? AND timeframe = ? AND is_active = 1
            ORDER BY
                CASE
                    WHEN overfit_warning IS NULL OR overfit_warning = '' THEN 0
                    ELSE 1
                END,
                id DESC
            LIMIT 1
            """,
            (symbol.upper(), timeframe),
        )
        row = cursor.fetchone()
        return _strategy_params_row_to_dict(row) if row else None

    def get_latest_strategy_parameters(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        cursor = self._conn().execute(
            """
            SELECT
                id, symbol, timeframe, lookback_days, sma_short, sma_long,
                rsi_buy, rsi_sell, buy_score_threshold, sell_score_threshold,
                stop_loss_pct, take_profit_pct, total_return_pct,
                max_drawdown_pct, win_rate_pct, trade_count, score,
                train_return_pct, validation_return_pct, train_drawdown_pct,
                validation_drawdown_pct, train_win_rate_pct, validation_win_rate_pct,
                validation_trade_count, overfit_warning, promotion_status,
                rejection_reasons_json, created_at, is_active
            FROM strategy_parameters
            WHERE symbol = ? AND timeframe = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (symbol.upper(), timeframe),
        )
        row = cursor.fetchone()
        return _strategy_params_row_to_dict(row) if row else None

    def save_market_candles(
        self,
        candles: Iterable[Candle],
        provider: str,
        symbol: str,
        timeframe: str,
    ) -> int:
        rows = [
            (
                provider,
                symbol.upper(),
                candle.timestamp,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                timeframe,
            )
            for candle in candles
        ]
        if not rows:
            return 0
        self._conn().executemany(
            """
            INSERT OR REPLACE INTO market_candles (
                provider, symbol, timestamp, open, high, low, close, volume, timeframe
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn().commit()
        return len(rows)

    def save_alpaca_order(self, order: Any) -> None:
        self._conn().execute(
            """
            INSERT INTO alpaca_orders (order_id, symbol, side, qty, status, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                getattr(order, "order_id", None),
                getattr(order, "symbol", ""),
                getattr(order, "side", ""),
                getattr(order, "qty", 0),
                getattr(order, "status", None),
                getattr(order, "raw", str(order)),
            ),
        )
        self._conn().commit()

    def save_alpaca_position(self, position: Any, symbol: str | None = None) -> None:
        if position is None:
            self._conn().execute(
                """
                INSERT INTO alpaca_positions (symbol, qty, market_value)
                VALUES (?, ?, ?)
                """,
                (symbol or "", 0.0, None),
            )
        else:
            self._conn().execute(
                """
                INSERT INTO alpaca_positions (symbol, qty, market_value)
                VALUES (?, ?, ?)
                """,
                (
                    getattr(position, "symbol", symbol or ""),
                    getattr(position, "qty", 0),
                    getattr(position, "market_value", None),
                ),
            )
        self._conn().commit()

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
                symbol, entry_time, entry_price, exit_time, exit_price,
                qty, side, entry_reason_json, exit_reason_json,
                profit_loss, profit_loss_pct, duration_minutes
            )
            VALUES (?, ?, ?, ?, ?, ?, 'LONG', ?, ?, ?, ?, ?)
            """,
            (
                trade.symbol,
                trade.entry_time,
                trade.entry_price,
                trade.exit_time,
                trade.exit_price,
                trade.quantity,
                json.dumps([trade.reason]),
                json.dumps([trade.reason]),
                trade.profit_loss,
                trade.profit_loss_pct,
                _duration_minutes(trade.entry_time, trade.exit_time),
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

    def _migrate_trades_table_if_needed(self) -> None:
        columns = {
            row[1]: row for row in self._conn().execute("PRAGMA table_info(trades)").fetchall()
        }
        if "qty" in columns and "entry_confidence" in columns:
            return

        self._conn().execute("ALTER TABLE trades RENAME TO trades_legacy")
        self._conn().execute(
            """
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_time TEXT,
                exit_price REAL,
                qty REAL NOT NULL,
                side TEXT NOT NULL DEFAULT 'LONG',
                entry_confidence REAL,
                exit_confidence REAL,
                entry_reason_json TEXT NOT NULL DEFAULT '[]',
                exit_reason_json TEXT NOT NULL DEFAULT '[]',
                profit_loss REAL,
                profit_loss_pct REAL,
                duration_minutes REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        legacy_columns = set(columns)
        if legacy_columns:
            quantity_expression = "quantity" if "quantity" in legacy_columns else "qty"
            self._conn().execute(
                f"""
                INSERT INTO trades (
                    id, symbol, entry_time, entry_price, exit_time, exit_price,
                    qty, side, entry_reason_json, exit_reason_json,
                    profit_loss, profit_loss_pct, duration_minutes, created_at
                )
                SELECT
                    id, symbol, entry_time, entry_price, exit_time, exit_price,
                    {quantity_expression}, 'LONG', '[]', '[]',
                    profit_loss, profit_loss_pct, NULL, created_at
                FROM trades_legacy
                """
            )
        self._conn().execute("DROP TABLE trades_legacy")
        self._conn().commit()

    def _upsert_position(
        self,
        symbol: str,
        qty: float,
        avg_entry_price: float,
        last_updated: str,
    ) -> None:
        self._conn().execute(
            """
            INSERT INTO positions (symbol, qty, avg_entry_price, last_updated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                qty = excluded.qty,
                avg_entry_price = excluded.avg_entry_price,
                last_updated = excluded.last_updated
            """,
            (symbol.upper(), qty, avg_entry_price, last_updated),
        )


def _reasons_json(signal: Signal) -> str:
    return json.dumps(list(signal.reasons))


def _trade_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "symbol": row[1],
        "entry_time": row[2],
        "entry_price": row[3],
        "exit_time": row[4],
        "exit_price": row[5],
        "qty": row[6],
        "side": row[7],
        "entry_confidence": row[8],
        "exit_confidence": row[9],
        "entry_reason_json": row[10],
        "exit_reason_json": row[11],
        "entry_reasons": json.loads(row[10] or "[]"),
        "exit_reasons": json.loads(row[11] or "[]"),
        "profit_loss": row[12],
        "profit_loss_pct": row[13],
        "duration_minutes": row[14],
        "created_at": row[15],
    }


def _duration_minutes(entry_time: str, exit_time: str) -> float | None:
    try:
        entry = _parse_datetime(entry_time)
        exit_ = _parse_datetime(exit_time)
    except ValueError:
        return None
    return round((exit_ - entry).total_seconds() / 60, 4)


def _parse_datetime(value: str) -> Any:
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


def _strategy_params_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "symbol": row[1],
        "timeframe": row[2],
        "lookback_days": row[3],
        "sma_short": row[4],
        "sma_long": row[5],
        "rsi_buy": row[6],
        "rsi_sell": row[7],
        "buy_score_threshold": row[8],
        "sell_score_threshold": row[9],
        "stop_loss_pct": row[10],
        "take_profit_pct": row[11],
        "total_return_pct": row[12],
        "max_drawdown_pct": row[13],
        "win_rate_pct": row[14],
        "trade_count": row[15],
        "score": row[16],
        "train_return_pct": row[17],
        "validation_return_pct": row[18],
        "train_drawdown_pct": row[19],
        "validation_drawdown_pct": row[20],
        "train_win_rate_pct": row[21],
        "validation_win_rate_pct": row[22],
        "validation_trade_count": row[23],
        "overfit_warning": row[24],
        "promotion_status": row[25],
        "rejection_reasons_json": row[26],
        "rejection_reasons": json.loads(row[26] or "[]"),
        "created_at": row[27],
        "is_active": bool(row[28]),
    }


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
