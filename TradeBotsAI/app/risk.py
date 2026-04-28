"""Portfolio-level paper-trading risk guardrails."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskSettings:
    max_open_positions: int = 3
    max_position_value_pct: float = 25.0
    max_total_exposure_pct: float = 75.0
    max_daily_realized_loss_pct: float = 5.0
    cooldown_minutes_after_loss: int = 60
    account_value: float = 10_000.0


@dataclass(frozen=True)
class RiskSnapshot:
    open_positions: list[dict]
    daily_realized_pnl: float
    cooldown_symbols: set[str]


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reasons: list[str]


def evaluate_buy_guardrails(
    symbol: str,
    estimated_position_value: float,
    snapshot: RiskSnapshot,
    settings: RiskSettings,
) -> RiskDecision:
    reasons: list[str] = []
    normalized_symbol = symbol.upper()
    account_value = max(settings.account_value, 1.0)
    open_symbols = {str(position["symbol"]).upper() for position in snapshot.open_positions}
    open_count_after_buy = len(open_symbols | {normalized_symbol})
    current_exposure = sum(
        float(position.get("qty") or 0) * float(position.get("avg_entry_price") or 0)
        for position in snapshot.open_positions
    )
    existing_symbol_exposure = sum(
        float(position.get("qty") or 0) * float(position.get("avg_entry_price") or 0)
        for position in snapshot.open_positions
        if str(position["symbol"]).upper() == normalized_symbol
    )
    new_exposure = current_exposure - existing_symbol_exposure + estimated_position_value

    if open_count_after_buy > settings.max_open_positions:
        reasons.append("max open positions reached")
    if (estimated_position_value / account_value) * 100 > settings.max_position_value_pct:
        reasons.append("position size too large")
    if (new_exposure / account_value) * 100 > settings.max_total_exposure_pct:
        reasons.append("total exposure too high")
    daily_loss_limit = -(account_value * (settings.max_daily_realized_loss_pct / 100))
    if snapshot.daily_realized_pnl <= daily_loss_limit:
        reasons.append("daily loss limit reached")
    if normalized_symbol in snapshot.cooldown_symbols:
        reasons.append("symbol cooldown active")
    return RiskDecision(allowed=not reasons, reasons=reasons)


def total_exposure_value(open_positions: list[dict]) -> float:
    return sum(
        float(position.get("qty") or 0) * float(position.get("avg_entry_price") or 0)
        for position in open_positions
    )
