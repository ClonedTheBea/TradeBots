import io
import unittest
from contextlib import redirect_stdout

from app.output import print_advisory_output
from data.models import Advice, Signal


class OutputTests(unittest.TestCase):
    def test_print_advisory_output_with_adjusted_confidence_and_bullets(self):
        signal = Signal(
            symbol="AAPL",
            timestamp="2024-01-01",
            action="HOLD",
            confidence=0.1667,
            score=1.0,
            reasons=("SMA slightly bullish", "RSI neutral", "MACD weak crossover"),
            reason="SMA slightly bullish; RSI neutral; MACD weak crossover",
            close=100.0,
        )
        advice = Advice(
            action="HOLD",
            confidence=0.15,
            raw_confidence=0.1667,
            adjusted_confidence=0.15,
            reason="SMA slightly bullish; RSI neutral; MACD weak crossover; recent win rate is 0.33",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            print_advisory_output("aapl", signal, advice)

        self.assertEqual(
            output.getvalue(),
            "\n".join(
                [
                    "Symbol: AAPL",
                    "Action: HOLD",
                    "Score: 1",
                    "Raw Confidence: 0.17",
                    "Adjusted Confidence: 0.15",
                    "",
                    "Reasons:",
                    "- SMA slightly bullish",
                    "- RSI neutral",
                    "- MACD weak crossover",
                    "- recent win rate is 0.33",
                    "",
                ]
            ),
        )

    def test_print_advisory_output_without_advice_uses_confidence(self):
        signal = Signal(
            symbol="GAME",
            timestamp="step-001",
            action="BUY",
            confidence=0.5,
            score=3.0,
            reasons=("SMA bullish",),
            reason="SMA bullish",
            close=10.0,
        )

        output = io.StringIO()
        with redirect_stdout(output):
            print_advisory_output("GAME", signal)

        self.assertIn("Confidence: 0.50", output.getvalue())
        self.assertIn("- SMA bullish", output.getvalue())


if __name__ == "__main__":
    unittest.main()
