"""Command line entry point for the advisory engine."""

from __future__ import annotations

import argparse
from pathlib import Path

from data.csv_loader import load_candles_from_csv
from decision.advisor import build_advice
from storage.sqlite_store import SQLiteStore
from strategy.backtest import BacktestConfig, Backtester
from strategy.signals import SignalConfig, SignalEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TradeBots AI advisory assistant")
    parser.add_argument("--csv", required=True, help="Path to OHLCV candle CSV data")
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv)
    candles = load_candles_from_csv(csv_path)

    signal_engine = SignalEngine(SignalConfig())
    signal = signal_engine.latest_signal(candles, symbol=args.symbol)

    backtester = Backtester(signal_engine, BacktestConfig())
    result = backtester.run(candles, symbol=args.symbol)

    advice = build_advice(signal, result)

    with SQLiteStore(args.db) as store:
        store.initialize()
        for historical_signal in result.signals:
            store.save_signal(historical_signal)
        store.save_backtest_result(result)
        for trade in result.trades:
            store.save_trade(trade)

    print(f"Decision: {advice.action}")
    print(f"Confidence: {advice.confidence:.2f}")
    print(f"Score: {signal.score:.2f}")
    print(f"Reason: {advice.reason}")
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
