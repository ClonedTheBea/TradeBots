import unittest

from app.risk import RiskSettings, RiskSnapshot, evaluate_buy_guardrails


def snapshot(open_positions=None, daily_realized_pnl=0.0, cooldown_symbols=None):
    return RiskSnapshot(
        open_positions=open_positions or [],
        daily_realized_pnl=daily_realized_pnl,
        cooldown_symbols=set(cooldown_symbols or []),
    )


class RiskGuardrailTests(unittest.TestCase):
    def test_blocks_max_open_positions_reached(self):
        decision = evaluate_buy_guardrails(
            "TSLA",
            1000,
            snapshot(
                open_positions=[
                    {"symbol": "AAPL", "qty": 1, "avg_entry_price": 100},
                    {"symbol": "MSFT", "qty": 1, "avg_entry_price": 100},
                    {"symbol": "NVDA", "qty": 1, "avg_entry_price": 100},
                ]
            ),
            RiskSettings(max_open_positions=3),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("max open positions reached", decision.reasons)

    def test_blocks_position_size_too_large(self):
        decision = evaluate_buy_guardrails(
            "AAPL",
            2600,
            snapshot(),
            RiskSettings(account_value=10_000, max_position_value_pct=25),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("position size too large", decision.reasons)

    def test_blocks_total_exposure_too_high(self):
        decision = evaluate_buy_guardrails(
            "TSLA",
            2000,
            snapshot(open_positions=[{"symbol": "AAPL", "qty": 60, "avg_entry_price": 100}]),
            RiskSettings(account_value=10_000, max_total_exposure_pct=75),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("total exposure too high", decision.reasons)

    def test_blocks_daily_loss_limit_reached(self):
        decision = evaluate_buy_guardrails(
            "AAPL",
            1000,
            snapshot(daily_realized_pnl=-500),
            RiskSettings(account_value=10_000, max_daily_realized_loss_pct=5),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("daily loss limit reached", decision.reasons)

    def test_blocks_symbol_cooldown_active(self):
        decision = evaluate_buy_guardrails(
            "AAPL",
            1000,
            snapshot(cooldown_symbols={"AAPL"}),
            RiskSettings(),
        )

        self.assertFalse(decision.allowed)
        self.assertIn("symbol cooldown active", decision.reasons)

    def test_allows_buy_when_risk_within_limits(self):
        decision = evaluate_buy_guardrails(
            "AAPL",
            1000,
            snapshot(),
            RiskSettings(),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reasons, [])


if __name__ == "__main__":
    unittest.main()
