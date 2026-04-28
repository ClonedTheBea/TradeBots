"""Command line entry point for the advisory engine."""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import uuid4

from app.recorder import record_manual_step
from data.csv_loader import load_candles_from_csv
from decision.advisor import build_advice
from storage.sqlite_store import SQLiteStore
from strategy.backtest import BacktestConfig, Backtester
from strategy.signals import SignalConfig, SignalEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TradeBots AI advisory assistant")
    parser.add_argument("--csv", required=True, help="Path to OHLCV or close-only candle CSV data")
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


if __name__ == "__main__":
    raise SystemExit(main())
