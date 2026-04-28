import unittest

from data.models import BacktestResult, Signal, Trade
from decision.advisor import build_advice, calculate_recent_win_rate


def signal(confidence=0.5):
    reasons = ("weighted signal reason",)
    return Signal(
        symbol="SIM",
        timestamp="2024-04-01",
        action="BUY",
        confidence=confidence,
        score=3.0,
        reasons=reasons,
        reason="; ".join(reasons),
        close=100.0,
    )


def trade(profit_loss):
    return Trade(
        symbol="SIM",
        entry_time="2024-04-01",
        exit_time="2024-04-02",
        entry_price=100.0,
        exit_price=101.0 if profit_loss > 0 else 99.0,
        quantity=1.0,
        profit_loss=profit_loss,
        profit_loss_pct=profit_loss,
        reason="test trade",
    )


def result(trades):
    return BacktestResult(
        symbol="SIM",
        starting_cash=1000.0,
        ending_cash=1000.0,
        total_return_pct=0.0,
        trades=tuple(trades),
        signals=(),
        win_rate=0.0,
        average_profit_per_trade=0.0,
        max_drawdown_pct=0.0,
    )


class AdvisorTests(unittest.TestCase):
    def test_recent_win_rate_uses_last_n_closed_trades(self):
        trades = [trade(-1.0), trade(-1.0), trade(1.0), trade(1.0)]

        self.assertEqual(calculate_recent_win_rate(trades, recent_trade_count=2), 1.0)

    def test_cold_recent_performance_reduces_confidence(self):
        advice = build_advice(signal(0.5), result([trade(-1.0), trade(-2.0), trade(1.0)]))

        self.assertEqual(advice.raw_confidence, 0.5)
        self.assertEqual(advice.adjusted_confidence, 0.35)
        self.assertEqual(advice.confidence, advice.adjusted_confidence)
        self.assertIn("Confidence reduced due to weak recent trade performance", advice.reason)

    def test_neutral_recent_performance_keeps_confidence(self):
        advice = build_advice(signal(0.5), result([trade(-1.0), trade(2.0)]))

        self.assertEqual(advice.raw_confidence, 0.5)
        self.assertEqual(advice.adjusted_confidence, 0.5)
        self.assertNotIn("Confidence reduced", advice.reason)
        self.assertNotIn("Confidence increased", advice.reason)

    def test_hot_recent_performance_increases_confidence(self):
        advice = build_advice(signal(0.9), result([trade(1.0), trade(2.0), trade(-1.0), trade(3.0)]))

        self.assertEqual(advice.raw_confidence, 0.9)
        self.assertEqual(advice.adjusted_confidence, 1.0)
        self.assertIn("Confidence increased due to strong recent trade performance", advice.reason)

    def test_no_trades_keeps_confidence(self):
        advice = build_advice(signal(0.5), result([]))

        self.assertEqual(advice.raw_confidence, 0.5)
        self.assertEqual(advice.adjusted_confidence, 0.5)
        self.assertIn("backtest produced no completed trades", advice.reason)


if __name__ == "__main__":
    unittest.main()
