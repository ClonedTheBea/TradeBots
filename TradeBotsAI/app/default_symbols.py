"""Shared default symbol loading."""

from __future__ import annotations

from pathlib import Path


DEFAULT_SYMBOLS = ["AAPL", "MSFT", "BB"]
DEFAULT_SYMBOL_CONFIG = "config/batch_symbols.txt"


def load_default_symbols(path: str | Path = DEFAULT_SYMBOL_CONFIG) -> list[str]:
    try:
        from app.batch_optimise import load_batch_symbols

        return load_batch_symbols(path)
    except (OSError, ValueError):
        return list(DEFAULT_SYMBOLS)


def default_symbols_text(path: str | Path = DEFAULT_SYMBOL_CONFIG) -> str:
    return ",".join(load_default_symbols(path))
