import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.main import (
    AlpacaAdviceResult,
    _format_alpaca_summary_line,
    _is_us_market_hours,
    _parse_symbol_list,
    _select_alpaca_trade_candidates,
)
from data.models import Signal


def signal(symbol, action, confidence):
    return Signal(
        symbol=symbol,
        timestamp="2024-01-01",
        action=action,
        confidence=confidence,
        score=confidence * 6,
        reasons=("test",),
        reason="test",
        close=100.0,
    )


class AlpacaMultiSymbolTests(unittest.TestCase):
    def test_parse_symbol_list_accepts_comma_separated_symbols(self):
        self.assertEqual(
            _parse_symbol_list("aapl", "MSFT, tsla,AAPL"),
            ["AAPL", "MSFT", "TSLA"],
        )

    def test_parse_symbol_list_requires_at_least_one_symbol(self):
        with self.assertRaisesRegex(ValueError, "Pass --symbol or --symbols"):
            _parse_symbol_list(None, "")

    def test_select_trade_candidates_applies_threshold_and_top_only(self):
        results = [
            AlpacaAdviceResult("AAPL", signal("AAPL", "BUY", 0.55), None),
            AlpacaAdviceResult("MSFT", signal("MSFT", "BUY", 0.82), None),
            AlpacaAdviceResult("TSLA", signal("TSLA", "BUY", 0.45), None),
        ]

        candidates = _select_alpaca_trade_candidates(results, confidence_threshold=0.50, top_only=True)

        self.assertEqual([result.symbol for result in candidates], ["MSFT"])

    def test_select_trade_candidates_respects_no_shorting(self):
        results = [
            AlpacaAdviceResult("AAPL", signal("AAPL", "SELL", 0.80), None),
            AlpacaAdviceResult("MSFT", signal("MSFT", "SELL", 0.72), SimpleNamespace(qty=1)),
        ]

        candidates = _select_alpaca_trade_candidates(results, confidence_threshold=0.50, top_only=False)

        self.assertEqual([result.symbol for result in candidates], ["MSFT"])

    def test_format_summary_line_marks_executed_trade(self):
        result = AlpacaAdviceResult(
            "MSFT",
            signal("MSFT", "BUY", 0.71),
            None,
            submitted_order=SimpleNamespace(order_id="order-1", status="accepted"),
        )

        self.assertEqual(_format_alpaca_summary_line(result), "MSFT \u2192 BUY (0.71) \u2705")

    def test_format_summary_line_marks_sell_context(self):
        result = AlpacaAdviceResult(
            "TSLA",
            signal("TSLA", "SELL", 0.66),
            SimpleNamespace(qty=1),
        )

        self.assertEqual(_format_alpaca_summary_line(result), "TSLA \u2192 SELL (0.66) \u26a0 (if holding)")

    def test_market_hours_helper_uses_regular_weekday_hours(self):
        eastern = ZoneInfo("America/New_York")

        self.assertTrue(_is_us_market_hours(datetime(2026, 4, 28, 10, 0, tzinfo=eastern)))
        self.assertFalse(_is_us_market_hours(datetime(2026, 4, 28, 8, 0, tzinfo=eastern)))
        self.assertFalse(_is_us_market_hours(datetime(2026, 5, 2, 10, 0, tzinfo=eastern)))


if __name__ == "__main__":
    unittest.main()
