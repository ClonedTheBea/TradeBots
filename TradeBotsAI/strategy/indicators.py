"""Technical indicator calculations."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class BollingerPoint:
    middle: float
    upper: float
    lower: float


@dataclass(frozen=True)
class MACDPoint:
    macd: float
    signal: float
    histogram: float


def sma(values: list[float], period: int) -> list[float | None]:
    _validate_period(period)
    output: list[float | None] = []
    rolling_sum = 0.0

    for index, value in enumerate(values):
        rolling_sum += value
        if index >= period:
            rolling_sum -= values[index - period]
        output.append(rolling_sum / period if index >= period - 1 else None)

    return output


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    _validate_period(period)
    if len(values) <= period:
        return [None] * len(values)

    output: list[float | None] = [None] * len(values)
    gains = []
    losses = []

    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    output[period] = _rsi_value(avg_gain, avg_loss)

    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        output[index] = _rsi_value(avg_gain, avg_loss)

    return output


def macd(
    values: list[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> list[MACDPoint | None]:
    _validate_period(fast_period)
    _validate_period(slow_period)
    _validate_period(signal_period)
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")

    fast = ema(values, fast_period)
    slow = ema(values, slow_period)
    macd_line: list[float | None] = [
        fast_value - slow_value if fast_value is not None and slow_value is not None else None
        for fast_value, slow_value in zip(fast, slow)
    ]
    signal_line = ema_optional(macd_line, signal_period)

    output: list[MACDPoint | None] = []
    for macd_value, signal_value in zip(macd_line, signal_line):
        if macd_value is None or signal_value is None:
            output.append(None)
        else:
            output.append(MACDPoint(macd_value, signal_value, macd_value - signal_value))
    return output


def bollinger_bands(
    values: list[float],
    period: int = 20,
    standard_deviations: float = 2.0,
) -> list[BollingerPoint | None]:
    _validate_period(period)
    output: list[BollingerPoint | None] = []

    for index in range(len(values)):
        if index < period - 1:
            output.append(None)
            continue

        window = values[index - period + 1 : index + 1]
        middle = sum(window) / period
        variance = sum((value - middle) ** 2 for value in window) / period
        stddev = sqrt(variance)
        output.append(
            BollingerPoint(
                middle=middle,
                upper=middle + (standard_deviations * stddev),
                lower=middle - (standard_deviations * stddev),
            )
        )

    return output


def ema(values: list[float], period: int) -> list[float | None]:
    _validate_period(period)
    if len(values) < period:
        return [None] * len(values)

    output: list[float | None] = [None] * len(values)
    multiplier = 2 / (period + 1)
    current = sum(values[:period]) / period
    output[period - 1] = current

    for index in range(period, len(values)):
        current = ((values[index] - current) * multiplier) + current
        output[index] = current

    return output


def ema_optional(values: list[float | None], period: int) -> list[float | None]:
    concrete_values: list[float] = []
    output: list[float | None] = [None] * len(values)
    multiplier = 2 / (period + 1)
    current: float | None = None

    for index, value in enumerate(values):
        if value is None:
            continue

        concrete_values.append(value)
        if current is None and len(concrete_values) == period:
            current = sum(concrete_values) / period
            output[index] = current
        elif current is not None:
            current = ((value - current) * multiplier) + current
            output[index] = current

    return output


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100 - (100 / (1 + relative_strength))


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be positive")

