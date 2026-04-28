"""CSV ingestion for OHLCV or close-only candles."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from data.models import Candle


_ALIASES = {
    "timestamp": ("timestamp", "datetime", "date", "time"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c", "last"),
    "volume": ("volume", "vol", "v"),
}


def load_candles_from_csv(path: str | Path) -> list[Candle]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV file is missing a header row")

        column_map = _resolve_columns(reader.fieldnames)
        candles = [_row_to_candle(row, column_map, line_no) for line_no, row in enumerate(reader, 2)]

    if len(candles) < 35:
        raise ValueError("At least 35 candles are required for MACD and RSI analysis")
    return candles


def _resolve_columns(fieldnames: Iterable[str]) -> dict[str, str]:
    normalized = {name.strip().lower(): name for name in fieldnames}
    resolved: dict[str, str] = {}

    for canonical in ("timestamp", "close"):
        for alias in _ALIASES[canonical]:
            if alias in normalized:
                resolved[canonical] = normalized[alias]
                break
        if canonical not in resolved:
            raise ValueError(f"CSV is missing required column: {canonical}")

    for canonical in ("open", "high", "low", "volume"):
        for alias in _ALIASES[canonical]:
            if alias in normalized:
                resolved[canonical] = normalized[alias]
                break

    return resolved


def _row_to_candle(row: dict[str, str], column_map: dict[str, str], line_no: int) -> Candle:
    try:
        close = _to_float(row[column_map["close"]])
        is_close_only = not {"open", "high", "low", "volume"}.issubset(column_map)
        return Candle(
            timestamp=row[column_map["timestamp"]].strip(),
            open=_to_float(row[column_map["open"]]) if "open" in column_map else close,
            high=_to_float(row[column_map["high"]]) if "high" in column_map else close,
            low=_to_float(row[column_map["low"]]) if "low" in column_map else close,
            close=close,
            volume=_to_float(row[column_map["volume"]]) if "volume" in column_map else 0.0,
            is_synthetic=is_close_only,
        )
    except KeyError as exc:
        raise ValueError(f"Malformed CSV row at line {line_no}") from exc
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value at line {line_no}") from exc


def _to_float(value: str) -> float:
    return float(value.strip().replace(",", ""))
