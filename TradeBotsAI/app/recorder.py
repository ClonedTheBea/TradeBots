"""Manual close-price recorder for Trade Bots STEP data."""

from __future__ import annotations

import csv
from pathlib import Path

from data.csv_loader import load_candles_from_csv
from strategy.signals import SignalEngine


def append_close_price(csv_path: str | Path, timestamp: str, close: float) -> None:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    should_write_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("timestamp", "close"))
        if should_write_header:
            writer.writeheader()
        writer.writerow({"timestamp": timestamp, "close": close})


def record_manual_step(csv_path: str | Path, signal_engine: SignalEngine, symbol: str) -> int:
    timestamp = input("Timestamp/date for this STEP: ").strip()
    price_text = input("Current Trade Bots price: ").strip()
    close = float(price_text.replace(",", ""))

    append_close_price(csv_path, timestamp, close)
    print(f"Recorded {timestamp}: close={close:.4f}")

    try:
        candles = load_candles_from_csv(csv_path)
    except ValueError as exc:
        message = str(exc)
        if "At least 35 candles" in message:
            print(f"Need more prices before advisory is available. {message}")
            return 0
        raise

    signal = signal_engine.latest_signal(candles, symbol=symbol)
    print(f"Decision: {signal.action}")
    print(f"Confidence: {signal.confidence:.2f}")
    print(f"Score: {signal.score:.2f}")
    print(f"Reason: {signal.reason}")
    return 0
