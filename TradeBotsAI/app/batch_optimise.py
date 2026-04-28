"""Scheduled batch optimisation pipeline."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from data.models import BacktestResult, Candle
from providers.marketstack import MarketStackClient
from storage.sqlite_store import SQLiteStore
from strategy.backtest import BacktestConfig, Backtester
from strategy.signals import SignalConfig, SignalEngine
from strategy.tuner import (
    TuningConfig,
    run_tuned_backtest,
    should_promote_parameters,
    validate_strategy_for_symbol,
    validation_result_to_storage_params,
)


BATCH_SUMMARY_FIELDS = [
    "symbol",
    "timeframe",
    "lookback",
    "trials",
    "initial_return_pct",
    "initial_drawdown_pct",
    "initial_trade_count",
    "first_validation_return_pct",
    "first_validation_trade_count",
    "first_promoted",
    "mid_return_pct",
    "mid_drawdown_pct",
    "mid_trade_count",
    "second_validation_return_pct",
    "second_validation_trade_count",
    "second_promoted",
    "final_return_pct",
    "final_drawdown_pct",
    "final_trade_count",
    "active_params_id",
    "status",
    "error_message",
]


@dataclass(frozen=True)
class BatchOptimiseConfig:
    symbols: list[str]
    timeframe: str = "1Day"
    lookback: int = 365
    trials: int = 2000
    train_ratio: float = 0.7
    refresh_data: bool = False
    continue_on_error: bool = False
    output_dir: str = "reports/batch_optimise"
    db_path: str = "tradebots_ai.sqlite"


@dataclass(frozen=True)
class ValidationRunSummary:
    validation_return_pct: float
    validation_trade_count: int
    promoted: bool
    row_id: int
    rejection_reasons: tuple[str, ...]


FetchCandles = Callable[[str, str, int, bool], list[Candle]]
BacktestActive = Callable[[list[Candle], str, str, str], tuple[BacktestResult, int | None]]
ValidateSymbol = Callable[[list[Candle], str, str, int, float, int, str], ValidationRunSummary]
Logger = Callable[[str], None]


def parse_symbol_list(symbols_text: str) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols_text.split(","):
        symbol = raw_symbol.strip().upper()
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    if not symbols:
        raise ValueError("At least one symbol is required.")
    return symbols


def load_batch_symbols(path: str | Path) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        symbol = line.strip()
        if not symbol or symbol.startswith("#"):
            continue
        normalized = symbol.upper()
        if normalized not in seen:
            symbols.append(normalized)
            seen.add(normalized)
    if not symbols:
        raise ValueError(f"No symbols found in {path}.")
    return symbols


def write_summary_csv(rows: Iterable[dict], path: str | Path) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=BATCH_SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in BATCH_SUMMARY_FIELDS})


def run_batch_optimise(
    config: BatchOptimiseConfig,
    fetch_candles: FetchCandles | None = None,
    backtest_active: BacktestActive | None = None,
    validate_symbol: ValidateSymbol | None = None,
    log: Logger | None = None,
) -> tuple[int, Path, Path]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"{timestamp}_batch.log"
    summary_path = output_dir / f"{timestamp}_summary.csv"
    rows: list[dict] = []
    exit_code = 0

    fetch = fetch_candles or fetch_marketstack_candles
    backtest = backtest_active or backtest_with_active_params
    validate = validate_symbol or validate_marketstack_symbol

    def emit(message: str) -> None:
        print(message)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
        if log is not None:
            log(message)

    emit("Batch optimise started")
    emit(
        f"Symbols={','.join(config.symbols)} timeframe={config.timeframe} "
        f"lookback={config.lookback} trials={config.trials}"
    )

    try:
        for symbol in config.symbols:
            row = _empty_summary_row(symbol, config)
            try:
                _run_symbol_sequence(symbol, row, config, fetch, backtest, validate, emit)
                row["status"] = "ok"
            except Exception as exc:
                row["status"] = "error"
                row["error_message"] = str(exc)
                exit_code = 1
                emit(f"{symbol}: ERROR: {exc}")
                rows.append(row)
                write_summary_csv(rows, summary_path)
                if not config.continue_on_error:
                    emit("Stopping after first error. Use --continue-on-error to keep going.")
                    break
                continue
            rows.append(row)
            write_summary_csv(rows, summary_path)
    finally:
        write_summary_csv(rows, summary_path)
        emit(f"Summary CSV: {summary_path}")
        emit(f"Log file: {log_path}")
        emit("Batch optimise finished")

    return exit_code, log_path, summary_path


def _run_symbol_sequence(
    symbol: str,
    row: dict,
    config: BatchOptimiseConfig,
    fetch_candles: FetchCandles,
    backtest_active: BacktestActive,
    validate_symbol: ValidateSymbol,
    log: Logger,
) -> None:
    log(f"{symbol}: fetching MarketStack candles")
    candles = fetch_candles(symbol, config.timeframe, config.lookback, config.refresh_data)
    if len(candles) < 2:
        raise ValueError(f"{symbol} returned too few candles for validation.")

    log(f"{symbol}: initial backtest")
    initial, active_id = backtest_active(candles, symbol, config.timeframe, config.db_path)
    _record_backtest(row, "initial", initial)

    log(f"{symbol}: first validation/tune")
    first = validate_symbol(
        candles,
        symbol,
        config.timeframe,
        config.lookback,
        config.train_ratio,
        config.trials,
        config.db_path,
    )
    row["first_validation_return_pct"] = first.validation_return_pct
    row["first_validation_trade_count"] = first.validation_trade_count
    row["first_promoted"] = first.promoted
    _log_validation(symbol, "first", first, log)

    log(f"{symbol}: mid backtest")
    mid, active_id = backtest_active(candles, symbol, config.timeframe, config.db_path)
    _record_backtest(row, "mid", mid)

    log(f"{symbol}: second validation/tune")
    second = validate_symbol(
        candles,
        symbol,
        config.timeframe,
        config.lookback,
        config.train_ratio,
        config.trials,
        config.db_path,
    )
    row["second_validation_return_pct"] = second.validation_return_pct
    row["second_validation_trade_count"] = second.validation_trade_count
    row["second_promoted"] = second.promoted
    _log_validation(symbol, "second", second, log)

    log(f"{symbol}: final backtest")
    final, active_id = backtest_active(candles, symbol, config.timeframe, config.db_path)
    _record_backtest(row, "final", final)
    row["active_params_id"] = active_id or ""


def _empty_summary_row(symbol: str, config: BatchOptimiseConfig) -> dict:
    return {
        "symbol": symbol,
        "timeframe": config.timeframe,
        "lookback": config.lookback,
        "trials": config.trials,
        "status": "pending",
        "error_message": "",
    }


def _record_backtest(row: dict, prefix: str, result: BacktestResult) -> None:
    row[f"{prefix}_return_pct"] = result.total_return_pct
    row[f"{prefix}_drawdown_pct"] = result.max_drawdown_pct
    row[f"{prefix}_trade_count"] = len(result.trades)


def _log_validation(symbol: str, label: str, summary: ValidationRunSummary, log: Logger) -> None:
    status = "promoted" if summary.promoted else "rejected"
    log(
        f"{symbol}: {label} validation {status} "
        f"return={summary.validation_return_pct:.2f}% "
        f"trades={summary.validation_trade_count}"
    )
    for reason in summary.rejection_reasons:
        log(f"{symbol}: {label} rejection reason: {reason}")


def fetch_marketstack_candles(symbol: str, timeframe: str, lookback: int, refresh: bool) -> list[Candle]:
    client = MarketStackClient.from_env()
    normalized_timeframe = timeframe.strip().lower()
    if normalized_timeframe in {"1day", "day", "1d"}:
        return client.fetch_eod(symbol, limit=lookback, refresh=refresh)
    interval = marketstack_interval_for_timeframe(timeframe)
    return client.fetch_intraday(symbol, interval=interval, limit=lookback, refresh=refresh)


def marketstack_interval_for_timeframe(timeframe: str) -> str:
    normalized = timeframe.strip().lower()
    mapping = {
        "1min": "1min",
        "1minute": "1min",
        "5min": "5min",
        "5minute": "5min",
        "10min": "10min",
        "10minute": "10min",
        "15min": "15min",
        "15minute": "15min",
        "30min": "30min",
        "30minute": "30min",
        "1hour": "1hour",
        "hour": "1hour",
        "1h": "1hour",
    }
    if normalized not in mapping:
        raise ValueError(
            "Unsupported MarketStack timeframe. Use 1Day, 1min, 5min, 10min, "
            "15min, 30min, or 1hour."
        )
    return mapping[normalized]


def backtest_with_active_params(
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    db_path: str,
) -> tuple[BacktestResult, int | None]:
    with SQLiteStore(db_path) as store:
        store.initialize()
        params = store.get_active_strategy_parameters(symbol, timeframe)

    if params:
        result = run_tuned_backtest(candles, params, symbol, TuningConfig())
        return result, int(params["id"])

    engine = SignalEngine(SignalConfig())
    result = Backtester(engine, BacktestConfig()).run(candles, symbol=symbol)
    return result, None


def validate_marketstack_symbol(
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    lookback: int,
    train_ratio: float,
    trials: int,
    db_path: str,
) -> ValidationRunSummary:
    result = validate_strategy_for_symbol(
        candles,
        symbol,
        train_ratio,
        TuningConfig(trials=trials),
    )
    stored = validation_result_to_storage_params(result, symbol, timeframe, lookback)
    decision = should_promote_parameters(stored)
    stored["promotion_status"] = "promoted" if decision.promote else "rejected"
    stored["rejection_reasons"] = decision.reasons

    with SQLiteStore(db_path) as store:
        store.initialize()
        row_id = store.save_strategy_parameters(stored, active=False)
        if decision.promote:
            store.promote_strategy_parameters(row_id)

    return ValidationRunSummary(
        validation_return_pct=result.validation_backtest.total_return_pct,
        validation_trade_count=len(result.validation_backtest.trades),
        promoted=decision.promote,
        row_id=row_id,
        rejection_reasons=tuple(decision.reasons),
    )
