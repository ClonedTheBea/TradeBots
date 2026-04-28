import csv
import tempfile
import unittest
from pathlib import Path

from app.batch_optimise import (
    BatchOptimiseConfig,
    ValidationRunSummary,
    load_batch_symbols,
    run_batch_optimise,
    write_summary_csv,
)
from data.models import BacktestResult, Candle


def candles(symbol="AAPL"):
    return [
        Candle(
            timestamp=f"2026-01-{index + 1:02d}T00:00:00",
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1000,
            symbol=symbol,
        )
        for index in range(12)
    ]


def backtest_result(symbol, total_return_pct, drawdown_pct, trades):
    return BacktestResult(
        symbol=symbol,
        starting_cash=10_000.0,
        ending_cash=10_000.0 + total_return_pct,
        total_return_pct=total_return_pct,
        trades=tuple(object() for _ in range(trades)),
        signals=(),
        win_rate=0.5,
        average_profit_per_trade=1.0,
        max_drawdown_pct=drawdown_pct,
    )


class BatchOptimiseTests(unittest.TestCase):
    def test_symbol_config_loading_ignores_blanks_comments_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch_symbols.txt"
            path.write_text("# watchlist\n\nAAPL\nmsft\nAAPL\n", encoding="utf-8")

            symbols = load_batch_symbols(path)

        self.assertEqual(symbols, ["AAPL", "MSFT"])

    def test_csv_summary_writing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "summary.csv"

            write_summary_csv(
                [
                    {
                        "symbol": "AAPL",
                        "timeframe": "1Day",
                        "lookback": 365,
                        "trials": 2000,
                        "status": "ok",
                    }
                ],
                path,
            )

            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows[0]["symbol"], "AAPL")
        self.assertEqual(rows[0]["status"], "ok")
        self.assertIn("final_return_pct", rows[0])

    def test_sequence_orchestration_uses_backtest_validate_backtest_validate_backtest(self):
        calls = []

        def fetch(symbol, timeframe, lookback, refresh):
            calls.append(("fetch", symbol, timeframe, lookback, refresh))
            return candles(symbol)

        def backtest(source, symbol, timeframe, db_path):
            calls.append(("backtest", symbol))
            return backtest_result(symbol, len(calls), 2.0, 3), 42

        def validate(source, symbol, timeframe, lookback, train_ratio, trials, db_path):
            calls.append(("validate", symbol, trials))
            return ValidationRunSummary(4.5, 6, True, 99, ())

        with tempfile.TemporaryDirectory() as tmpdir:
            config = BatchOptimiseConfig(
                symbols=["AAPL"],
                output_dir=tmpdir,
                db_path=":memory:",
                trials=7,
                refresh_data=True,
            )

            exit_code, _log_path, summary_path = run_batch_optimise(
                config,
                fetch_candles=fetch,
                backtest_active=backtest,
                validate_symbol=validate,
            )

            with summary_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [call[0] for call in calls],
            ["fetch", "backtest", "validate", "backtest", "validate", "backtest"],
        )
        self.assertEqual(rows[0]["first_promoted"], "True")
        self.assertEqual(rows[0]["active_params_id"], "42")
        self.assertEqual(rows[0]["status"], "ok")

    def test_continue_on_error_logs_error_and_processes_next_symbol(self):
        calls = []

        def fetch(symbol, timeframe, lookback, refresh):
            calls.append(symbol)
            if symbol == "AAPL":
                raise RuntimeError("boom")
            return candles(symbol)

        def backtest(source, symbol, timeframe, db_path):
            return backtest_result(symbol, 1.0, 1.0, 1), None

        def validate(source, symbol, timeframe, lookback, train_ratio, trials, db_path):
            return ValidationRunSummary(1.0, 5, False, 1, ("not enough edge",))

        with tempfile.TemporaryDirectory() as tmpdir:
            config = BatchOptimiseConfig(
                symbols=["AAPL", "MSFT"],
                output_dir=tmpdir,
                continue_on_error=True,
            )

            exit_code, _log_path, summary_path = run_batch_optimise(
                config,
                fetch_candles=fetch,
                backtest_active=backtest,
                validate_symbol=validate,
            )

            with summary_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(exit_code, 1)
        self.assertEqual(calls, ["AAPL", "MSFT"])
        self.assertEqual(rows[0]["status"], "error")
        self.assertEqual(rows[0]["error_message"], "boom")
        self.assertEqual(rows[1]["status"], "ok")

    def test_without_continue_on_error_stops_on_first_error(self):
        calls = []

        def fetch(symbol, timeframe, lookback, refresh):
            calls.append(symbol)
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = BatchOptimiseConfig(symbols=["AAPL", "MSFT"], output_dir=tmpdir)

            exit_code, _log_path, summary_path = run_batch_optimise(config, fetch_candles=fetch)

            with summary_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(exit_code, 1)
        self.assertEqual(calls, ["AAPL"])
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
