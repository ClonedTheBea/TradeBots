import unittest

from data.models import Candle
from strategy.signals import SignalConfig, SignalEngine


def candles_from_closes(closes):
    return [
        Candle(
            timestamp=f"2024-01-{index + 1:02d}",
            open=close,
            high=close + 0.5,
            low=close - 0.5,
            close=close,
            volume=1000,
        )
        for index, close in enumerate(closes)
    ]


class SignalEngineTests(unittest.TestCase):
    def test_weighted_buy_signal_returns_score_and_reasons(self):
        closes = []
        price = 100.0
        for index in range(45):
            price += -0.8 if index % 3 == 0 else 1.0
            closes.append(round(price, 2))
        candles = candles_from_closes(closes)
        engine = SignalEngine(SignalConfig(rsi_buy_threshold=-1, rsi_sell_threshold=101))

        signal = engine.latest_signal(candles, symbol="SIM")

        self.assertEqual(signal.action, "BUY")
        self.assertGreaterEqual(signal.score, 3.0)
        self.assertGreater(signal.confidence, 0.0)
        self.assertLessEqual(signal.confidence, 1.0)
        self.assertIsInstance(signal.reasons, tuple)
        self.assertTrue(any("RSI" in reason for reason in signal.reasons))
        self.assertIn(";", signal.reason)

    def test_score_thresholds_map_to_actions(self):
        from strategy.signals import _score_to_action

        self.assertEqual(_score_to_action(3), "BUY")
        self.assertEqual(_score_to_action(-3), "SELL")
        self.assertEqual(_score_to_action(2), "HOLD")
        self.assertEqual(_score_to_action(-2), "HOLD")


if __name__ == "__main__":
    unittest.main()
