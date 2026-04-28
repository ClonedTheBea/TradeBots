"""Command line entry point for the advisory engine."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, time as datetime_time
from pathlib import Path
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.capture import DEFAULT_LIVE_CSV, run_capture_once
from app.output import print_advisory_output
from app.recorder import record_manual_step
from data.csv_loader import load_candles_from_csv
from decision.advisor import build_advice
from storage.sqlite_store import SQLiteStore
from strategy.backtest import BacktestConfig, Backtester
from strategy.signals import SignalConfig, SignalEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TradeBots AI advisory assistant")
    subparsers = parser.add_subparsers(dest="command")
    capture_parser = subparsers.add_parser(
        "capture-once",
        help="Capture one screenshot, OCR the Trade Bots HUD, append price, and run advisory",
    )
    capture_parser.add_argument(
        "--debug",
        action="store_true",
        help="Save a debug screenshot and print raw OCR text",
    )
    capture_parser.add_argument(
        "--csv",
        default=str(DEFAULT_LIVE_CSV),
        help="Close-only CSV path to append captured prices",
    )
    capture_parser.add_argument(
        "--symbol",
        default="GAME",
        help="Optional symbol/name for the captured scenario",
    )
    watch_parser = subparsers.add_parser(
        "watch-screen",
        help="Wait for F8, capture the Trade Bots HUD, append price, and run advisory",
    )
    watch_parser.add_argument(
        "--debug",
        action="store_true",
        help="Save debug screenshots and print raw OCR/parsed fields",
    )
    watch_parser.add_argument(
        "--csv",
        default=str(DEFAULT_LIVE_CSV),
        help="Close-only CSV path to append captured prices",
    )
    watch_parser.add_argument(
        "--symbol",
        default="GAME",
        help="Optional symbol/name for the watched scenario",
    )
    watch_parser.add_argument(
        "--hotkey",
        default="f8",
        help="Hotkey to capture the current screen",
    )
    auto_step_parser = subparsers.add_parser(
        "auto-step",
        help="Repeatedly press STEP, OCR the HUD, append price, and run advisory",
    )
    auto_step_parser.add_argument(
        "--debug",
        action="store_true",
        help="Save debug screenshots and print raw OCR/parsed fields",
    )
    auto_step_parser.add_argument(
        "--csv",
        default=str(DEFAULT_LIVE_CSV),
        help="Close-only CSV path to append captured prices",
    )
    auto_step_parser.add_argument(
        "--symbol",
        default="GAME",
        help="Optional symbol/name for the auto-step scenario",
    )
    auto_step_parser.add_argument(
        "--max-steps",
        type=int,
        help="Stop after this many STEP clicks",
    )
    auto_step_parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="Append even when the parsed game date matches the last CSV row",
    )
    auto_trade_parser = subparsers.add_parser(
        "auto-trade",
        help="Simulation-only auto trade loop using advisory signals",
    )
    auto_trade_parser.add_argument(
        "--debug",
        action="store_true",
        help="Save debug screenshots and print raw OCR/parsed fields",
    )
    auto_trade_parser.add_argument(
        "--csv",
        default=str(DEFAULT_LIVE_CSV),
        help="Close-only CSV path to append captured prices",
    )
    auto_trade_parser.add_argument(
        "--symbol",
        default="GAME",
        help="Optional symbol/name for the auto-trade scenario",
    )
    auto_trade_parser.add_argument(
        "--max-steps",
        type=int,
        help="Stop after this many STEP clicks",
    )
    auto_trade_parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="Append even when the parsed game date matches the last CSV row",
    )
    auto_trade_parser.add_argument(
        "--confirm-auto-trade",
        action="store_true",
        help="Allow simulation BUY/SELL/PROCESS TRADE clicks when config also enables auto trade",
    )
    mouse_pos_parser = subparsers.add_parser(
        "mouse-pos",
        help="Print the current mouse position every 0.5 seconds for STEP calibration",
    )
    mouse_pos_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Only print coordinates; do not save the last position for auto-step",
    )
    for command_name, help_text in (
        ("set-buy-button", "Save the current mouse position as the BUY button"),
        ("set-sell-button", "Save the current mouse position as the SELL button"),
        ("set-process-trade-button", "Save the current mouse position as PROCESS TRADE"),
        ("set-slider-handle", "Save the current mouse position as the slider handle/start point"),
        ("set-slider-right", "Save the current mouse position as the slider far-right point"),
        ("set-step-button", "Save the current mouse position as the STEP button"),
    ):
        subparsers.add_parser(command_name, help=help_text)
    subparsers.add_parser(
        "show-calibration",
        help="Print the loaded auto-step/auto-trade calibration coordinates",
    )
    for command_name, help_text in (
        ("test-buy-click", "Click the saved BUY coordinate once"),
        ("test-sell-click", "Click the saved SELL coordinate once"),
        ("test-process-click", "Click the saved PROCESS TRADE coordinate once"),
        ("test-slider-handle-click", "Click the saved SLIDER HANDLE coordinate once"),
        ("test-slider-click", "Click the saved SLIDER RIGHT coordinate once"),
        ("test-step-click", "Click the saved STEP coordinate once"),
    ):
        subparsers.add_parser(command_name, help=help_text)
    alpaca_advice_parser = subparsers.add_parser(
        "alpaca-advice",
        help="Fetch Alpaca paper market data and run advisory analysis",
    )
    alpaca_advice_parser.add_argument("--symbol")
    alpaca_advice_parser.add_argument("--symbols", help="Comma-separated symbols, e.g. AAPL,MSFT,TSLA")
    alpaca_advice_parser.add_argument("--timeframe", default="1Day")
    alpaca_advice_parser.add_argument("--lookback", type=int, default=180)
    alpaca_advice_parser.add_argument("--db", default="tradebots_ai.sqlite")

    alpaca_trade_parser = subparsers.add_parser(
        "alpaca-paper-trade",
        help="Submit a confirmed Alpaca paper order from the advisory signal",
    )
    alpaca_trade_parser.add_argument("--symbol")
    alpaca_trade_parser.add_argument("--symbols", help="Comma-separated symbols, e.g. AAPL,MSFT,TSLA")
    alpaca_trade_parser.add_argument("--qty", type=float, required=True)
    alpaca_trade_parser.add_argument("--timeframe", default="1Day")
    alpaca_trade_parser.add_argument("--lookback", type=int, default=180)
    alpaca_trade_parser.add_argument("--confirm-paper", action="store_true")
    alpaca_trade_parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.50,
        help="Minimum signal confidence required before submitting a paper order",
    )
    alpaca_trade_parser.add_argument(
        "--top-only",
        action="store_true",
        help="Only trade the highest-confidence eligible signal",
    )
    alpaca_trade_parser.add_argument("--db", default="tradebots_ai.sqlite")

    scheduler_parser = subparsers.add_parser(
        "run-scheduler",
        help="Run repeated Alpaca paper-trading scans for server use",
    )
    scheduler_parser.add_argument("--symbols", required=True, help="Comma-separated symbols, e.g. AAPL,MSFT,TSLA")
    scheduler_parser.add_argument("--interval-minutes", type=float, default=15)
    scheduler_parser.add_argument("--confidence-threshold", type=float, default=0.65)
    scheduler_parser.add_argument("--qty", type=float, default=1.0)
    scheduler_parser.add_argument("--timeframe", default="1Day")
    scheduler_parser.add_argument("--lookback", type=int, default=180)
    scheduler_parser.add_argument("--confirm-paper", action="store_true")
    scheduler_parser.add_argument("--top-only", action="store_true")
    scheduler_parser.add_argument("--market-hours-only", action="store_true")
    scheduler_parser.add_argument("--db", default="tradebots_ai.sqlite")

    performance_parser = subparsers.add_parser(
        "performance-report",
        help="Report completed paper/backtest trade performance",
    )
    performance_parser.add_argument("--last", type=int, help="Show only the last N completed trades")
    performance_parser.add_argument("--since", type=int, help="Filter completed trades from the last DAYS days")
    performance_parser.add_argument("--db", default="tradebots_ai.sqlite")

    for command_name, help_text in (
        ("marketstack-fetch", "Fetch MarketStack OHLCV candles and save them locally"),
        ("marketstack-advice", "Fetch MarketStack candles and run advisory analysis"),
        ("marketstack-backtest", "Fetch MarketStack candles and run a backtest"),
    ):
        marketstack_parser = subparsers.add_parser(command_name, help=help_text)
        marketstack_parser.add_argument("--symbol", required=True)
        marketstack_parser.add_argument("--timeframe", default="1Day")
        marketstack_parser.add_argument("--lookback", type=int, default=180)
        marketstack_parser.add_argument("--date-from")
        marketstack_parser.add_argument("--date-to")
        marketstack_parser.add_argument("--refresh", action="store_true")
        marketstack_parser.add_argument("--db", default="tradebots_ai.sqlite")
        if command_name == "marketstack-fetch":
            marketstack_parser.add_argument(
                "--output-csv",
                help="Optional CSV path to write fetched candles",
            )

    parser.add_argument("--csv", help="Path to OHLCV or close-only candle CSV data")
    parser.add_argument(
        "--db",
        default="tradebots_ai.sqlite",
        help="SQLite database path for signals and backtest results",
    )
    parser.add_argument(
        "--symbol",
        default="UNKNOWN",
        help="Optional symbol/name for the imported scenario",
    )
    parser.add_argument(
        "--optimise",
        "--optimize",
        action="store_true",
        help="Run Optuna strategy optimisation instead of normal advisory mode",
    )
    parser.add_argument(
        "--optimisation-trials",
        "--optimization-trials",
        type=int,
        default=50,
        help="Number of Optuna trials to run when optimisation is enabled",
    )
    parser.add_argument(
        "--optimisation-output",
        "--optimization-output",
        default="best_strategy_params.json",
        help="JSON file path for best optimisation parameters",
    )
    parser.add_argument(
        "--record-step",
        action="store_true",
        help="Prompt for one timestamp and close price, append it to the CSV, then run advisory if ready",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "capture-once":
        try:
            return run_capture_once(
                SignalEngine(SignalConfig()),
                symbol=args.symbol,
                csv_path=args.csv,
                debug=args.debug,
            )
        except (RuntimeError, ValueError) as exc:
            print(exc)
            return 1
    if args.command == "watch-screen":
        try:
            return run_watch_screen(args.csv, args.symbol, args.hotkey, args.debug)
        except RuntimeError as exc:
            print(exc)
            return 1
    if args.command == "auto-step":
        from app.automation import run_auto_step

        try:
            return run_auto_step(
                csv_path=args.csv,
                symbol=args.symbol,
                max_steps=args.max_steps,
                allow_duplicates=args.allow_duplicates,
                debug=args.debug,
            )
        except (RuntimeError, ValueError) as exc:
            print(exc)
            return 1
    if args.command == "auto-trade":
        from app.automation import run_auto_trade

        try:
            return run_auto_trade(
                csv_path=args.csv,
                symbol=args.symbol,
                max_steps=args.max_steps,
                allow_duplicates=args.allow_duplicates,
                debug=args.debug,
                confirm_auto_trade=args.confirm_auto_trade,
            )
        except (RuntimeError, ValueError) as exc:
            print(exc)
            return 1
    if args.command == "mouse-pos":
        from app.automation import run_mouse_position_printer

        try:
            return run_mouse_position_printer(save=not args.no_save)
        except RuntimeError as exc:
            print(exc)
            return 1
    coordinate_commands = {
        "set-buy-button": "buy_button",
        "set-sell-button": "sell_button",
        "set-process-trade-button": "process_trade",
        "set-slider-handle": "slider_handle",
        "set-slider-right": "slider_right",
        "set-step-button": "step_button",
    }
    if args.command in coordinate_commands:
        from app.automation import save_current_mouse_position

        try:
            return save_current_mouse_position(coordinate_commands[args.command])
        except RuntimeError as exc:
            print(exc)
            return 1
    if args.command == "show-calibration":
        from app.automation import run_show_calibration

        return run_show_calibration()
    click_test_commands = {
        "test-buy-click": "buy_button",
        "test-sell-click": "sell_button",
        "test-process-click": "process_trade",
        "test-slider-handle-click": "slider_handle",
        "test-slider-click": "slider_right",
        "test-step-click": "step_button",
    }
    if args.command in click_test_commands:
        from app.automation import click_calibrated_target

        try:
            return click_calibrated_target(click_test_commands[args.command])
        except RuntimeError as exc:
            print(exc)
            return 1
    if args.command == "alpaca-advice":
        return run_alpaca_advice(args.symbol, args.symbols, args.timeframe, args.lookback, args.db)
    if args.command == "alpaca-paper-trade":
        return run_alpaca_paper_trade(
            args.symbol,
            args.symbols,
            args.qty,
            args.timeframe,
            args.lookback,
            args.confirm_paper,
            args.confidence_threshold,
            args.top_only,
            args.db,
        )
    if args.command == "run-scheduler":
        return run_scheduler(
            args.symbols,
            args.interval_minutes,
            args.confidence_threshold,
            args.qty,
            args.timeframe,
            args.lookback,
            args.confirm_paper,
            args.top_only,
            args.market_hours_only,
            args.db,
        )
    if args.command == "performance-report":
        return run_performance_report(args.db, args.last, args.since)
    if args.command == "marketstack-fetch":
        return run_marketstack_fetch(
            args.symbol,
            args.timeframe,
            args.lookback,
            args.date_from,
            args.date_to,
            args.refresh,
            args.db,
            args.output_csv,
        )
    if args.command == "marketstack-advice":
        return run_marketstack_advice(
            args.symbol,
            args.timeframe,
            args.lookback,
            args.date_from,
            args.date_to,
            args.refresh,
            args.db,
        )
    if args.command == "marketstack-backtest":
        return run_marketstack_backtest(
            args.symbol,
            args.timeframe,
            args.lookback,
            args.date_from,
            args.date_to,
            args.refresh,
            args.db,
        )

    if not args.csv:
        print("CSV path is required unless using capture-once, watch-screen, auto-step, or mouse-pos.")
        return 1

    csv_path = Path(args.csv)

    if args.record_step:
        return record_manual_step(csv_path, SignalEngine(SignalConfig()), args.symbol)

    candles = load_candles_from_csv(csv_path)
    if any(candle.is_synthetic for candle in candles):
        print(
            "Warning: close-only data detected. Open/high/low were set equal to close "
            "and volume was set to 0; indicators that need true OHLCV may be less reliable."
        )

    if args.optimise:
        from strategy.optimiser import OptimisationConfig, optimise_strategy

        try:
            optimisation = optimise_strategy(
                candles,
                symbol=args.symbol,
                config=OptimisationConfig(
                    trials=args.optimisation_trials,
                    output_path=args.optimisation_output,
                ),
            )
        except RuntimeError as exc:
            print(exc)
            return 1

        print("Optimisation complete")
        print(f"Best objective: {optimisation.best_value:.4f}")
        print(f"Best params: {optimisation.best_params}")
        print(
            "Best backtest: "
            f"return={optimisation.best_backtest.total_return_pct:.2f}% "
            f"max_drawdown={optimisation.best_backtest.max_drawdown_pct:.2f}% "
            f"trades={len(optimisation.best_backtest.trades)}"
        )
        print(f"Saved best parameters to: {Path(optimisation.output_path).resolve()}")
        return 0

    signal_engine = SignalEngine(SignalConfig())
    signal = signal_engine.latest_signal(candles, symbol=args.symbol)
    session_id = uuid4().hex

    with SQLiteStore(args.db) as store:
        store.initialize()
        store.save_signal(signal, session_id=session_id)
        backtester = Backtester(signal_engine, BacktestConfig())
        result = backtester.run(
            candles,
            symbol=args.symbol,
            signal_store=store,
            session_id=session_id,
        )
        store.save_backtest_result(result)
        for trade in result.trades:
            store.save_trade(trade)

    advice = build_advice(signal, result)

    print_advisory_output(args.symbol, signal, advice)
    print(f"Session: {session_id}")
    print(
        "Backtest: "
        f"start=${result.starting_cash:.2f} "
        f"end=${result.ending_cash:.2f} "
        f"return={result.total_return_pct:.2f}% "
        f"trades={len(result.trades)} "
        f"signals={len(result.signals)} "
        f"win_rate={result.win_rate:.2f} "
        f"avg_profit=${result.average_profit_per_trade:.2f} "
        f"max_drawdown={result.max_drawdown_pct:.2f}%"
    )
    print(f"Stored results in: {Path(args.db).resolve()}")
    return 0


@dataclass(frozen=True)
class AlpacaAdviceResult:
    symbol: str
    signal: object
    position: object | None
    error: str | None = None
    submitted_order: object | None = None
    skipped_reason: str | None = None


def run_alpaca_advice(
    symbol: str | None,
    symbols_text: str | None,
    timeframe: str,
    lookback: int,
    db_path: str,
) -> int:
    from broker.alpaca_client import AlpacaPaperClient

    try:
        client = AlpacaPaperClient.from_env()
    except (RuntimeError, ValueError) as exc:
        print(exc)
        return 1

    try:
        symbols = _parse_symbol_list(symbol, symbols_text)
    except ValueError as exc:
        print(exc)
        return 1

    results: list[AlpacaAdviceResult] = []
    signal_engine = SignalEngine(SignalConfig())
    with SQLiteStore(db_path) as store:
        store.initialize()
        for normalized_symbol in symbols:
            try:
                candles = client.get_bars(normalized_symbol, timeframe=timeframe, lookback=lookback)
                signal = signal_engine.latest_signal(candles, symbol=normalized_symbol)
                position = client.get_position(normalized_symbol)
                store.save_signal(signal, session_id=f"alpaca-advice-{normalized_symbol}")
                store.save_alpaca_position(position, symbol=normalized_symbol)
                results.append(AlpacaAdviceResult(normalized_symbol, signal, position))
            except (RuntimeError, ValueError) as exc:
                results.append(AlpacaAdviceResult(normalized_symbol, None, None, error=str(exc)))

    if len(results) == 1 and results[0].error is None:
        result = results[0]
        print("Alpaca paper advice")
        print_advisory_output(result.symbol, result.signal)
        if result.position:
            print(f"Paper position: qty={result.position.qty:g}, market_value={result.position.market_value}")
        else:
            print("Paper position: none")

    _print_alpaca_summary(results)
    return 1 if any(result.error for result in results) else 0


def run_marketstack_fetch(
    symbol: str,
    timeframe: str,
    lookback: int,
    date_from: str | None,
    date_to: str | None,
    refresh: bool,
    db_path: str,
    output_csv: str | None,
) -> int:
    try:
        candles = _fetch_marketstack_candles(symbol, timeframe, lookback, date_from, date_to, refresh)
    except (RuntimeError, ValueError) as exc:
        print(exc)
        return 1

    normalized_symbol = symbol.upper()
    with SQLiteStore(db_path) as store:
        store.initialize()
        saved_count = store.save_market_candles(candles, "marketstack", normalized_symbol, timeframe)

    print(f"Fetched {len(candles)} MarketStack candles for {normalized_symbol} ({timeframe}).")
    print(f"Saved {saved_count} candles to SQLite: {Path(db_path).resolve()}")
    if output_csv:
        _write_candles_csv(candles, output_csv)
        print(f"Saved candles to CSV: {Path(output_csv).resolve()}")
    return 0


def run_marketstack_advice(
    symbol: str,
    timeframe: str,
    lookback: int,
    date_from: str | None,
    date_to: str | None,
    refresh: bool,
    db_path: str,
) -> int:
    try:
        candles = _fetch_marketstack_candles(symbol, timeframe, lookback, date_from, date_to, refresh)
    except (RuntimeError, ValueError) as exc:
        print(exc)
        return 1

    normalized_symbol = symbol.upper()
    signal_engine = SignalEngine(SignalConfig())
    session_id = f"marketstack-advice-{normalized_symbol}-{uuid4().hex}"
    try:
        signal = signal_engine.latest_signal(candles, symbol=normalized_symbol)
        backtester = Backtester(signal_engine, BacktestConfig())
        result = backtester.run(candles, symbol=normalized_symbol)
        advice = build_advice(signal, result)
    except ValueError as exc:
        print(exc)
        return 1

    with SQLiteStore(db_path) as store:
        store.initialize()
        store.save_market_candles(candles, "marketstack", normalized_symbol, timeframe)
        store.save_signal(signal, session_id=session_id)

    print(f"MarketStack advice ({timeframe})")
    print_advisory_output(normalized_symbol, signal, advice)
    print(f"Session: {session_id}")
    return 0


def run_marketstack_backtest(
    symbol: str,
    timeframe: str,
    lookback: int,
    date_from: str | None,
    date_to: str | None,
    refresh: bool,
    db_path: str,
) -> int:
    try:
        candles = _fetch_marketstack_candles(symbol, timeframe, lookback, date_from, date_to, refresh)
    except (RuntimeError, ValueError) as exc:
        print(exc)
        return 1

    normalized_symbol = symbol.upper()
    session_id = f"marketstack-backtest-{normalized_symbol}-{uuid4().hex}"
    signal_engine = SignalEngine(SignalConfig())
    try:
        with SQLiteStore(db_path) as store:
            store.initialize()
            store.save_market_candles(candles, "marketstack", normalized_symbol, timeframe)
            result = Backtester(signal_engine, BacktestConfig()).run(
                candles,
                symbol=normalized_symbol,
                signal_store=store,
                session_id=session_id,
            )
            store.save_backtest_result(result)
            for trade in result.trades:
                store.save_trade(trade)
    except ValueError as exc:
        print(exc)
        return 1

    print(f"MarketStack backtest for {normalized_symbol} ({timeframe})")
    print(
        "Backtest: "
        f"start=${result.starting_cash:.2f} "
        f"end=${result.ending_cash:.2f} "
        f"return={result.total_return_pct:.2f}% "
        f"trades={len(result.trades)} "
        f"signals={len(result.signals)} "
        f"win_rate={result.win_rate:.2f} "
        f"avg_profit=${result.average_profit_per_trade:.2f} "
        f"max_drawdown={result.max_drawdown_pct:.2f}%"
    )
    print(f"Session: {session_id}")
    print(f"Stored results in: {Path(db_path).resolve()}")
    return 0


def _fetch_marketstack_candles(
    symbol: str,
    timeframe: str,
    lookback: int,
    date_from: str | None,
    date_to: str | None,
    refresh: bool,
):
    from providers.marketstack import MarketStackClient

    if lookback <= 0:
        raise ValueError("lookback must be positive")

    client = MarketStackClient.from_env()
    normalized_timeframe = timeframe.strip().lower()
    if normalized_timeframe in {"1day", "day", "1d"}:
        return client.fetch_eod(
            symbol,
            date_from=date_from,
            date_to=date_to,
            limit=lookback,
            refresh=refresh,
        )

    interval = _marketstack_interval_for_timeframe(timeframe)
    return client.fetch_intraday(
        symbol,
        interval=interval,
        date_from=date_from,
        date_to=date_to,
        limit=lookback,
        refresh=refresh,
    )


def _marketstack_interval_for_timeframe(timeframe: str) -> str:
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


def _write_candles_csv(candles, output_csv: str) -> None:
    csv_path = Path(output_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "symbol", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "timestamp": candle.timestamp,
                    "symbol": candle.symbol,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
            )


def run_alpaca_paper_trade(
    symbol: str | None,
    symbols_text: str | None,
    qty: float,
    timeframe: str,
    lookback: int,
    confirm_paper: bool,
    confidence_threshold: float,
    top_only: bool,
    db_path: str,
) -> int:
    from broker.alpaca_client import AlpacaPaperClient

    if not confirm_paper:
        print("Refusing to submit paper order: pass --confirm-paper to confirm.")
        return 1
    if not 0 <= confidence_threshold <= 1:
        print("confidence-threshold must be between 0 and 1.")
        return 1

    try:
        client = AlpacaPaperClient.from_env()
        symbols = _parse_symbol_list(symbol, symbols_text)
    except (RuntimeError, ValueError) as exc:
        print(exc)
        return 1

    results = _run_alpaca_trade_scan(
        client=client,
        symbols=symbols,
        qty=qty,
        timeframe=timeframe,
        lookback=lookback,
        confidence_threshold=confidence_threshold,
        top_only=top_only,
        execute_orders=True,
        db_path=db_path,
        session_id=f"alpaca-paper-trade-{uuid4().hex}",
    )
    _print_alpaca_trade_results(results, qty)
    return 1 if any(result.error for result in results) else 0


def run_scheduler(
    symbols_text: str,
    interval_minutes: float,
    confidence_threshold: float,
    qty: float,
    timeframe: str,
    lookback: int,
    confirm_paper: bool,
    top_only: bool,
    market_hours_only: bool,
    db_path: str,
    max_cycles: int | None = None,
) -> int:
    from broker.alpaca_client import AlpacaPaperClient

    if interval_minutes <= 0:
        print("interval-minutes must be positive.")
        return 1
    if not 0 <= confidence_threshold <= 1:
        print("confidence-threshold must be between 0 and 1.")
        return 1

    try:
        symbols = _parse_symbol_list(None, symbols_text)
        client = AlpacaPaperClient.from_env()
    except (RuntimeError, ValueError) as exc:
        print(exc)
        return 1

    mode = "confirmed paper execution" if confirm_paper else "dry run"
    print(
        f"Starting scheduler for {', '.join(symbols)} every {interval_minutes:g} minutes "
        f"({mode})."
    )
    if not confirm_paper:
        print("Dry-run mode: pass --confirm-paper to submit Alpaca paper orders.")

    cycle = 0
    interval_seconds = interval_minutes * 60
    try:
        while max_cycles is None or cycle < max_cycles:
            cycle += 1
            cycle_id = f"scheduler-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
            cycle_started_at = datetime.now().isoformat(timespec="seconds")
            print(f"[{cycle_started_at}] Scheduler cycle {cycle} start: {cycle_id}")

            if market_hours_only and not _is_us_market_hours():
                print("Outside regular US market hours; skipping scan.")
            else:
                results = _run_alpaca_trade_scan(
                    client=client,
                    symbols=symbols,
                    qty=qty,
                    timeframe=timeframe,
                    lookback=lookback,
                    confidence_threshold=confidence_threshold,
                    top_only=top_only,
                    execute_orders=confirm_paper,
                    db_path=db_path,
                    session_id=cycle_id,
                )
                _print_alpaca_trade_results(results, qty)

            print(f"[{datetime.now().isoformat(timespec='seconds')}] Scheduler cycle {cycle} end: {cycle_id}")
            if max_cycles is not None and cycle >= max_cycles:
                break
            print(f"Sleeping {interval_minutes:g} minutes until next cycle.")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("Scheduler stopped by Ctrl+C.")
        return 0
    return 0


def run_performance_report(db_path: str, last: int | None, since_days: int | None) -> int:
    try:
        with SQLiteStore(db_path) as store:
            store.initialize()
            trades = store.get_completed_trades(limit=last, since_days=since_days)
    except ValueError as exc:
        print(exc)
        return 1

    report = _build_performance_report(trades)
    print(report)
    return 0


def _build_performance_report(trades: list[dict]) -> str:
    if not trades:
        return "Summary:\n- Total trades: 0\n- Win rate: 0.00%\n- Total PnL: $0.00\n- Avg PnL per trade: $0.00\n- Best trade: n/a\n- Worst trade: n/a\n- Avg duration: 0.00 minutes\n\nPer-symbol breakdown:\nNo completed trades."

    total_trades = len(trades)
    wins = sum(1 for trade in trades if (trade["profit_loss"] or 0) > 0)
    total_pnl = sum(float(trade["profit_loss"] or 0) for trade in trades)
    avg_pnl = total_pnl / total_trades
    best_trade = max(trades, key=lambda trade: trade["profit_loss"] or 0)
    worst_trade = min(trades, key=lambda trade: trade["profit_loss"] or 0)
    durations = [float(trade["duration_minutes"]) for trade in trades if trade["duration_minutes"] is not None]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    lines = [
        "Summary:",
        f"- Total trades: {total_trades}",
        f"- Win rate: {(wins / total_trades) * 100:.2f}%",
        f"- Total PnL: ${total_pnl:.2f}",
        f"- Avg PnL per trade: ${avg_pnl:.2f}",
        f"- Best trade: {best_trade['symbol']} ${best_trade['profit_loss']:.2f} ({best_trade['profit_loss_pct']:.2f}%)",
        f"- Worst trade: {worst_trade['symbol']} ${worst_trade['profit_loss']:.2f} ({worst_trade['profit_loss_pct']:.2f}%)",
        f"- Avg duration: {avg_duration:.2f} minutes",
        "",
        "Per-symbol breakdown:",
    ]

    for symbol in sorted({trade["symbol"] for trade in trades}):
        symbol_trades = [trade for trade in trades if trade["symbol"] == symbol]
        symbol_wins = sum(1 for trade in symbol_trades if (trade["profit_loss"] or 0) > 0)
        symbol_pnl = sum(float(trade["profit_loss"] or 0) for trade in symbol_trades)
        lines.extend(
            [
                f"{symbol}:",
                f"- trades: {len(symbol_trades)}",
                f"- win rate: {(symbol_wins / len(symbol_trades)) * 100:.2f}%",
                f"- total PnL: ${symbol_pnl:.2f}",
            ]
        )
    return "\n".join(lines)


def _run_alpaca_trade_scan(
    client,
    symbols: list[str],
    qty: float,
    timeframe: str,
    lookback: int,
    confidence_threshold: float,
    top_only: bool,
    execute_orders: bool,
    db_path: str,
    session_id: str,
) -> list[AlpacaAdviceResult]:
    results: list[AlpacaAdviceResult] = []
    signal_engine = SignalEngine(SignalConfig())
    with SQLiteStore(db_path) as store:
        store.initialize()
        for normalized_symbol in symbols:
            try:
                candles = _with_api_retries(
                    lambda symbol=normalized_symbol: client.get_bars(
                        symbol,
                        timeframe=timeframe,
                        lookback=lookback,
                    ),
                    f"fetch bars for {normalized_symbol}",
                )
                signal = signal_engine.latest_signal(candles, symbol=normalized_symbol)
                position = _with_api_retries(
                    lambda symbol=normalized_symbol: client.get_position(symbol),
                    f"fetch position for {normalized_symbol}",
                )
                store.save_signal(signal, session_id=session_id)
                store.save_alpaca_position(position, symbol=normalized_symbol)
                results.append(AlpacaAdviceResult(normalized_symbol, signal, position))
            except Exception as exc:
                print(f"{normalized_symbol} scan failed: {exc}")
                results.append(AlpacaAdviceResult(normalized_symbol, None, None, error=str(exc)))

        candidates = _select_alpaca_trade_candidates(results, confidence_threshold, top_only)
        candidate_symbols = {result.symbol for result in candidates}
        updated_results: list[AlpacaAdviceResult] = []
        for result in results:
            if result.error is not None:
                updated_results.append(result)
                continue

            skip_reason = _alpaca_trade_skip_reason(result, confidence_threshold)
            if result.symbol not in candidate_symbols:
                skip_reason = skip_reason or "top-only not selected"
            if skip_reason:
                skipped = AlpacaAdviceResult(
                    result.symbol,
                    result.signal,
                    result.position,
                    skipped_reason=skip_reason,
                )
                _save_alpaca_trade_action(store, skipped, qty, "skipped", session_id)
                updated_results.append(skipped)
                continue

            if not execute_orders:
                dry_run = AlpacaAdviceResult(
                    result.symbol,
                    result.signal,
                    result.position,
                    skipped_reason="dry run: pass --confirm-paper to submit order",
                )
                _save_alpaca_trade_action(store, dry_run, qty, "dry_run", session_id)
                updated_results.append(dry_run)
                continue

            try:
                order = _with_api_retries(
                    lambda result=result: client.submit_paper_order(
                        result.symbol,
                        qty=qty,
                        side=result.signal.action,
                    ),
                    f"submit paper order for {result.symbol}",
                )
                new_position = _with_api_retries(
                    lambda symbol=result.symbol: client.get_position(symbol),
                    f"fetch post-order position for {result.symbol}",
                )
                store.save_alpaca_order(order)
                store.save_alpaca_position(new_position, symbol=result.symbol)
                submitted = AlpacaAdviceResult(
                    result.symbol,
                    result.signal,
                    new_position,
                    submitted_order=order,
                )
                if result.signal.action == "BUY":
                    store.record_trade_entry(
                        symbol=result.symbol,
                        entry_time=result.signal.timestamp,
                        entry_price=result.signal.close,
                        qty=float(getattr(order, "qty", qty) or qty),
                        entry_confidence=result.signal.confidence,
                        entry_reasons=result.signal.reasons,
                    )
                elif result.signal.action == "SELL":
                    closed_trade = store.record_trade_exit(
                        symbol=result.symbol,
                        exit_time=result.signal.timestamp,
                        exit_price=result.signal.close,
                        exit_confidence=result.signal.confidence,
                        exit_reasons=result.signal.reasons,
                    )
                    if closed_trade is None:
                        print(f"{result.symbol} SELL submitted, but no open tracked trade was found to close.")
                _save_alpaca_trade_action(store, submitted, qty, "submitted", session_id)
                updated_results.append(submitted)
            except Exception as exc:
                failed = AlpacaAdviceResult(
                    result.symbol,
                    result.signal,
                    result.position,
                    error=str(exc),
                )
                _save_alpaca_trade_action(store, failed, qty, "failed", session_id, reason=str(exc))
                print(f"{result.symbol} order attempt failed: {exc}")
                updated_results.append(failed)
        return updated_results


def _save_alpaca_trade_action(
    store: SQLiteStore,
    result: AlpacaAdviceResult,
    qty: float,
    status: str,
    session_id: str,
    reason: str | None = None,
) -> None:
    signal = result.signal
    order = result.submitted_order
    store.save_alpaca_trade_action(
        symbol=result.symbol,
        action=getattr(signal, "action", "ERROR"),
        status=status,
        reason=reason or result.skipped_reason,
        confidence=getattr(signal, "confidence", None),
        qty=qty,
        order_id=getattr(order, "order_id", None),
        session_id=session_id,
    )


def _print_alpaca_trade_results(results: list[AlpacaAdviceResult], qty: float) -> None:
    _print_alpaca_summary(results)
    for result in results:
        if result.submitted_order is not None:
            print(f"Submitted Alpaca PAPER {result.signal.action} order for {qty:g} {result.symbol}")
            print(f"Order id: {result.submitted_order.order_id}")
            print(f"Status: {result.submitted_order.status}")
        elif result.skipped_reason:
            print(f"{result.symbol} skipped: {result.skipped_reason}")
        elif result.error:
            print(f"{result.symbol} failed: {result.error}")


def _parse_symbol_list(symbol: str | None, symbols_text: str | None) -> list[str]:
    raw_symbols: list[str] = []
    if symbol:
        raw_symbols.append(symbol)
    if symbols_text:
        raw_symbols.extend(symbols_text.split(","))
    symbols: list[str] = []
    seen: set[str] = set()
    for raw_symbol in raw_symbols:
        normalized = raw_symbol.strip().upper()
        if not normalized:
            continue
        if normalized not in seen:
            symbols.append(normalized)
            seen.add(normalized)
    if not symbols:
        raise ValueError("Pass --symbol or --symbols.")
    return symbols


def _select_alpaca_trade_candidates(
    results: list[AlpacaAdviceResult],
    confidence_threshold: float,
    top_only: bool,
) -> list[AlpacaAdviceResult]:
    candidates = [
        result
        for result in results
        if result.error is None and _alpaca_trade_skip_reason(result, confidence_threshold) is None
    ]
    if top_only and candidates:
        return [max(candidates, key=lambda result: result.signal.confidence)]
    return candidates


def _alpaca_trade_skip_reason(result: AlpacaAdviceResult, confidence_threshold: float) -> str | None:
    signal = result.signal
    if signal.action == "HOLD":
        return "HOLD"
    if signal.confidence < confidence_threshold:
        return "confidence below threshold"
    if signal.action == "BUY" and result.position is not None:
        return "already holding"
    if signal.action == "SELL" and result.position is None:
        return "no position to sell"
    return None


def _print_alpaca_summary(results: list[AlpacaAdviceResult]) -> None:
    print("Summary:")
    for result in results:
        print(_format_alpaca_summary_line(result))


def _format_alpaca_summary_line(result: AlpacaAdviceResult) -> str:
    if result.error is not None:
        return f"{result.symbol} \u2192 ERROR ({result.error})"
    marker = ""
    if result.submitted_order is not None:
        marker = " \u2705"
    elif result.skipped_reason:
        marker = f" ({result.skipped_reason})"
    elif result.signal.action == "SELL":
        marker = " \u26a0 (if holding)" if result.position is not None else " \u26a0 (no holding)"
    return f"{result.symbol} \u2192 {result.signal.action} ({result.signal.confidence:.2f}){marker}"


def _with_api_retries(operation, label: str, max_attempts: int = 3, base_delay_seconds: float = 1.0):
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt >= max_attempts or not _is_temporary_api_error(exc):
                raise
            delay = base_delay_seconds * (2 ** (attempt - 1))
            print(f"Temporary API error during {label}: {exc}. Retrying in {delay:g}s.")
            time.sleep(delay)
    raise RuntimeError(f"{label} failed after retries")


def _is_temporary_api_error(exc: Exception) -> bool:
    text = str(exc).lower()
    temporary_markers = (
        "429",
        "rate limit",
        "timeout",
        "temporar",
        "connection",
        "500",
        "502",
        "503",
        "504",
        "service unavailable",
    )
    return any(marker in text for marker in temporary_markers)


def _is_us_market_hours(now: datetime | None = None) -> bool:
    eastern = ZoneInfo("America/New_York")
    current = now.astimezone(eastern) if now else datetime.now(eastern)
    if current.weekday() >= 5:
        return False
    market_open = datetime_time(9, 30)
    market_close = datetime_time(16, 0)
    return market_open <= current.time() <= market_close


def run_watch_screen(csv_path: str, symbol: str, hotkey: str, debug: bool) -> int:
    from app.recorder import append_close_price
    from game_interface.hotkey_listener import listen_for_hotkey
    from game_interface.ocr_reader import read_ocr_text
    from game_interface.screen_capture import capture_screen
    from game_interface.screen_state import parse_screen_state

    signal_engine = SignalEngine(SignalConfig())

    def capture_and_advise() -> None:
        try:
            image = capture_screen(debug=debug)
            raw_text = read_ocr_text(image, debug=debug)
            state = parse_screen_state(raw_text)
            if debug:
                print("Raw OCR text:")
                print(raw_text)
                print("Parsed fields:")
                print(f"  date={state.game_date}")
                print(f"  price={state.price}")
                print(f"  gain_percent={state.gain_percent}")
                print(f"  cash={state.cash}")
                print(f"  holdings={state.holdings}")
                print(f"  selected_trade_action={state.selected_trade_action}")
                print(f"  slider_state={state.slider_state}")

            if state.price is None:
                print("Could not parse current price from OCR text")
                return

            timestamp = state.game_date or state.captured_at
            append_close_price(csv_path, timestamp, state.price)
            print(f"Captured {timestamp}: close={state.price:.4f}")

            try:
                candles = load_candles_from_csv(csv_path)
            except ValueError as exc:
                message = str(exc)
                if "At least 35 candles" in message:
                    print(f"Need more captured prices before advisory is available. {message}")
                    return
                raise

            signal = signal_engine.latest_signal(candles, symbol=symbol)
            print_advisory_output(symbol, signal)
        except Exception as exc:
            print(f"Capture failed: {exc}")

    try:
        listen_for_hotkey(capture_and_advise, hotkey=hotkey)
    except KeyboardInterrupt:
        print("Stopped watch-screen mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
