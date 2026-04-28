"""Simple long-only backtesting engine."""

from __future__ import annotations

from dataclasses import dataclass

from data.models import BacktestResult, Candle, Signal, Trade
from strategy.signals import SignalEngine


@dataclass(frozen=True)
class BacktestConfig:
    starting_cash: float = 10_000.0
    position_fraction: float = 1.0


class Backtester:
    def __init__(self, signal_engine: SignalEngine, config: BacktestConfig) -> None:
        if not 0 < config.position_fraction <= 1:
            raise ValueError("position_fraction must be between 0 and 1")
        self.signal_engine = signal_engine
        self.config = config

    def run(
        self,
        candles: list[Candle],
        symbol: str = "UNKNOWN",
        signal_store: object | None = None,
        session_id: str | None = None,
    ) -> BacktestResult:
        if not candles:
            raise ValueError("Cannot backtest without candles")

        cash = self.config.starting_cash
        quantity = 0.0
        entry_price = 0.0
        entry_time = ""
        trades: list[Trade] = []
        signals: list[Signal] = []
        equity_curve: list[float] = []

        signal_start_index = _signal_start_index(self.signal_engine)
        for index, candle in enumerate(candles):
            if index < signal_start_index:
                equity_curve.append(cash + (quantity * candle.close))
                continue

            signal = self.signal_engine.signal_at(candles[: index + 1], index, symbol)
            signals.append(signal)

            if signal.action == "BUY" and quantity == 0:
                allocation = cash * self.config.position_fraction
                quantity = allocation / candle.close
                cash -= allocation
                entry_price = candle.close
                entry_time = candle.timestamp
            elif signal.action == "SELL" and quantity > 0:
                proceeds = quantity * candle.close
                cash += proceeds
                trades.append(
                    _close_trade(
                        symbol=symbol,
                        entry_time=entry_time,
                        exit_time=candle.timestamp,
                        entry_price=entry_price,
                        exit_price=candle.close,
                        quantity=quantity,
                        reason=signal.reason,
                    )
                )
                quantity = 0.0
                entry_price = 0.0
                entry_time = ""

            equity_curve.append(cash + (quantity * candle.close))

        last_candle = candles[-1]
        if quantity > 0:
            cash += quantity * last_candle.close
            trades.append(
                _close_trade(
                    symbol=symbol,
                    entry_time=entry_time,
                    exit_time=last_candle.timestamp,
                    entry_price=entry_price,
                    exit_price=last_candle.close,
                    quantity=quantity,
                    reason="closed at end of backtest",
                )
            )

        ending_cash = cash
        total_return_pct = ((ending_cash - self.config.starting_cash) / self.config.starting_cash) * 100
        wins = sum(1 for trade in trades if trade.profit_loss > 0)
        win_rate = wins / len(trades) if trades else 0.0
        average_profit = sum(trade.profit_loss for trade in trades) / len(trades) if trades else 0.0

        result = BacktestResult(
            symbol=symbol,
            starting_cash=self.config.starting_cash,
            ending_cash=round(ending_cash, 2),
            total_return_pct=round(total_return_pct, 4),
            trades=tuple(trades),
            signals=tuple(signals),
            win_rate=round(win_rate, 4),
            average_profit_per_trade=round(average_profit, 2),
            max_drawdown_pct=round(_max_drawdown_pct(equity_curve), 4),
        )
        if signal_store is not None:
            signal_store.save_signals_bulk(result.signals, session_id=session_id)
        return result


def _close_trade(
    symbol: str,
    entry_time: str,
    exit_time: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
    reason: str,
) -> Trade:
    profit_loss = (exit_price - entry_price) * quantity
    profit_loss_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price else 0.0
    return Trade(
        symbol=symbol,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=round(entry_price, 4),
        exit_price=round(exit_price, 4),
        quantity=round(quantity, 8),
        profit_loss=round(profit_loss, 2),
        profit_loss_pct=round(profit_loss_pct, 4),
        reason=reason,
    )


def _max_drawdown_pct(equity_curve: list[float]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            drawdown = ((peak - equity) / peak) * 100
            max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown


def _signal_start_index(signal_engine: SignalEngine) -> int:
    config = signal_engine.config
    macd_start_index = 26 + 9 - 2
    return max(
        config.long_sma_period - 1,
        config.rsi_period,
        config.bollinger_period - 1,
        macd_start_index,
    )
