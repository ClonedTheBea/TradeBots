"""Combine latest signal and backtest context into advisory output."""

from __future__ import annotations

from data.models import Advice, BacktestResult, Signal, Trade


DEFAULT_RECENT_TRADE_COUNT = 10


def build_advice(
    signal: Signal,
    backtest_result: BacktestResult,
    recent_trade_count: int = DEFAULT_RECENT_TRADE_COUNT,
) -> Advice:
    raw_confidence = signal.confidence
    adjusted_confidence = raw_confidence
    reasons = [signal.reason]

    if backtest_result.trades:
        recent_win_rate = calculate_recent_win_rate(backtest_result.trades, recent_trade_count)
        reasons.append(f"recent win rate is {recent_win_rate:.2f}")

        if recent_win_rate < 0.40:
            adjusted_confidence = raw_confidence * 0.70
            reasons.append("Confidence reduced due to weak recent trade performance")
        elif recent_win_rate > 0.70:
            adjusted_confidence = min(raw_confidence * 1.20, 1.0)
            reasons.append("Confidence increased due to strong recent trade performance")
    else:
        reasons.append("backtest produced no completed trades")

    adjusted_confidence = round(adjusted_confidence, 4)
    return Advice(
        action=signal.action,
        confidence=adjusted_confidence,
        raw_confidence=round(raw_confidence, 4),
        adjusted_confidence=adjusted_confidence,
        reason="; ".join(reasons),
    )


def calculate_recent_win_rate(
    trades: tuple[Trade, ...] | list[Trade],
    recent_trade_count: int = DEFAULT_RECENT_TRADE_COUNT,
) -> float:
    if recent_trade_count <= 0:
        raise ValueError("recent_trade_count must be positive")
    recent_trades = list(trades)[-recent_trade_count:]
    if not recent_trades:
        return 0.0
    wins = sum(1 for trade in recent_trades if trade.profit_loss > 0)
    return wins / len(recent_trades)
