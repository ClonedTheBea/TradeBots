"""Weighted signal engine for advisory decisions."""

from __future__ import annotations

from dataclasses import dataclass

from data.models import Candle, Signal
from strategy.indicators import bollinger_bands, macd, rsi, sma


@dataclass(frozen=True)
class SignalConfig:
    short_sma_period: int = 10
    long_sma_period: int = 30
    rsi_period: int = 14
    rsi_buy_threshold: float = 30.0
    rsi_sell_threshold: float = 70.0
    bollinger_period: int = 20
    max_score: float = 6.0


class SignalEngine:
    def __init__(self, config: SignalConfig) -> None:
        self.config = config

    def latest_signal(self, candles: list[Candle], symbol: str = "UNKNOWN") -> Signal:
        if not candles:
            raise ValueError("Cannot generate a signal without candles")
        return self.signal_at(candles, len(candles) - 1, symbol)

    def signal_at(self, candles: list[Candle], index: int, symbol: str = "UNKNOWN") -> Signal:
        if index < 0 or index >= len(candles):
            raise IndexError("signal index out of range")

        closes = [candle.close for candle in candles]
        short_sma = sma(closes, self.config.short_sma_period)
        long_sma = sma(closes, self.config.long_sma_period)
        rsi_values = rsi(closes, self.config.rsi_period)
        macd_values = macd(closes)
        bands = bollinger_bands(closes, self.config.bollinger_period)

        score = 0.0
        reasons: list[str] = []
        candle = candles[index]

        short_value = short_sma[index]
        long_value = long_sma[index]
        rsi_value = rsi_values[index]
        macd_value = macd_values[index]
        band = bands[index]

        if short_value is not None and long_value is not None:
            if short_value > long_value:
                score += 2.0
                reasons.append("SMA: short SMA is above long SMA (+2)")
            elif short_value < long_value:
                score -= 2.0
                reasons.append("SMA: short SMA is below long SMA (-2)")
            else:
                reasons.append("SMA: short SMA equals long SMA (0)")

        if rsi_value is not None:
            if rsi_value < self.config.rsi_buy_threshold:
                score += 2.0
                reasons.append(f"RSI: below {self.config.rsi_buy_threshold:.0f} at {rsi_value:.1f} (+2)")
            elif rsi_value > self.config.rsi_sell_threshold:
                score -= 2.0
                reasons.append(f"RSI: above {self.config.rsi_sell_threshold:.0f} at {rsi_value:.1f} (-2)")
            else:
                reasons.append(f"RSI: neutral at {rsi_value:.1f} (0)")

        if macd_value is not None:
            if macd_value.macd > macd_value.signal:
                score += 1.0
                reasons.append("MACD: MACD is above signal (+1)")
            elif macd_value.macd < macd_value.signal:
                score -= 1.0
                reasons.append("MACD: MACD is below signal (-1)")
            else:
                reasons.append("MACD: MACD equals signal (0)")

        if band is not None:
            if candle.close < band.lower:
                score += 1.0
                reasons.append("Bollinger Bands: price is below lower band (+1)")
            elif candle.close > band.upper:
                score -= 1.0
                reasons.append("Bollinger Bands: price is above upper band (-1)")
            else:
                reasons.append("Bollinger Bands: price is inside bands (0)")

        action = _score_to_action(score)
        confidence = min(abs(score) / self.config.max_score, 1.0)

        return Signal(
            symbol=symbol,
            timestamp=candle.timestamp,
            action=action,
            confidence=round(confidence, 4),
            score=score,
            reasons=tuple(reasons),
            reason="; ".join(reasons) if reasons else "insufficient indicator data",
            close=candle.close,
        )


def _score_to_action(score: float) -> str:
    if score >= 3.0:
        return "BUY"
    if score <= -3.0:
        return "SELL"
    return "HOLD"
