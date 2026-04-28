"""Console output helpers for advisory results."""

from __future__ import annotations

from data.models import Advice, Signal


def print_advisory_output(
    symbol: str,
    signal: Signal,
    advice: Advice | None = None,
) -> None:
    """Print a readable advisory summary without changing signal semantics."""
    print(f"Symbol: {symbol.upper()}")
    print(f"Action: {advice.action if advice else signal.action}")
    print(f"Score: {_format_number(signal.score)}")
    if advice:
        print(f"Raw Confidence: {advice.raw_confidence:.2f}")
        print(f"Adjusted Confidence: {advice.adjusted_confidence:.2f}")
    else:
        print(f"Confidence: {signal.confidence:.2f}")
    print()
    print("Reasons:")
    for reason in _advisory_reasons(signal, advice):
        print(f"- {reason}")


def _advisory_reasons(signal: Signal, advice: Advice | None) -> list[str]:
    reasons = list(signal.reasons) or [signal.reason]
    if advice is None:
        return reasons

    for part in advice.reason.split(";"):
        cleaned = part.strip()
        if cleaned and cleaned != signal.reason and cleaned not in reasons:
            reasons.append(cleaned)
    return reasons


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"
