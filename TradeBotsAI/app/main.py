"""Command line entry point for the advisory engine."""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import uuid4

from app.capture import DEFAULT_LIVE_CSV, run_capture_once
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
        ("test-slider-click", "Click the saved SLIDER RIGHT coordinate once"),
        ("test-step-click", "Click the saved STEP coordinate once"),
    ):
        subparsers.add_parser(command_name, help=help_text)

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

    print(f"Decision: {advice.action}")
    print(f"Raw Confidence: {advice.raw_confidence:.2f}")
    print(f"Adjusted Confidence: {advice.adjusted_confidence:.2f}")
    print(f"Score: {signal.score:.2f}")
    print(f"Reason: {advice.reason}")
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
            print(f"Recommendation: {signal.action}")
            print(f"Confidence: {signal.confidence:.2f}")
            print(f"Score: {signal.score:.2f}")
            print(f"Reasons: {signal.reason}")
        except Exception as exc:
            print(f"Capture failed: {exc}")

    try:
        listen_for_hotkey(capture_and_advise, hotkey=hotkey)
    except KeyboardInterrupt:
        print("Stopped watch-screen mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
