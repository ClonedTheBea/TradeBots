"""Core data models used throughout the advisory engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    symbol: str
    timestamp: str
    action: str
    confidence: float
    score: float
    reasons: tuple[str, ...]
    reason: str
    close: float


@dataclass(frozen=True)
class Trade:
    symbol: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    profit_loss: float
    profit_loss_pct: float
    reason: str


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    starting_cash: float
    ending_cash: float
    total_return_pct: float
    trades: tuple[Trade, ...]
    signals: tuple[Signal, ...]
    win_rate: float
    average_profit_per_trade: float
    max_drawdown_pct: float


@dataclass(frozen=True)
class Advice:
    action: str
    confidence: float
    raw_confidence: float
    adjusted_confidence: float
    reason: str
