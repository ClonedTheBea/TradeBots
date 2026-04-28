"""Combine latest signal and backtest context into advisory output."""

from __future__ import annotations

from data.models import Advice, BacktestResult, Signal


def build_advice(signal: Signal, backtest_result: BacktestResult) -> Advice:
    confidence = signal.confidence
    reasons = [signal.reason]

    if backtest_result.trades:
        if backtest_result.total_return_pct > 0:
            confidence = min(confidence + 0.1, 1.0)
            reasons.append(f"strategy backtest is positive at {backtest_result.total_return_pct:.2f}%")
        else:
            confidence = max(confidence - 0.1, 0.0)
            reasons.append(f"strategy backtest is negative at {backtest_result.total_return_pct:.2f}%")
        reasons.append(f"historical win rate is {backtest_result.win_rate:.2f}")
    else:
        reasons.append("backtest produced no completed trades")

    return Advice(
        action=signal.action,
        confidence=round(confidence, 4),
        reason="; ".join(reasons),
    )

