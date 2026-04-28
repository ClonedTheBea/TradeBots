import unittest

from data.models import Candle
from strategy.tuner import TuningConfig, tune_strategy_for_symbol, tuning_objective


class FixedTrial:
    def __init__(self, values):
        self.values = values

    def suggest_int(self, name, low, high):
        return self.values[name]

    def suggest_float(self, name, low, high):
        return self.values[name]


class FakeStudy:
    def __init__(self):
        self.best_params = None
        self.best_value = None

    def optimize(self, objective, n_trials):
        trial_values = [
            {
                "sma_short": 5,
                "sma_long": 25,
                "rsi_buy": 30.0,
                "rsi_sell": 70.0,
                "buy_score_threshold": 2.0,
                "sell_score_threshold": -2.0,
                "stop_loss_pct": 5.0,
                "take_profit_pct": 10.0,
            },
            {
                "sma_short": 8,
                "sma_long": 30,
                "rsi_buy": 35.0,
                "rsi_sell": 65.0,
                "buy_score_threshold": 3.0,
                "sell_score_threshold": -3.0,
                "stop_loss_pct": 4.0,
                "take_profit_pct": 8.0,
            },
        ][:n_trials]
        for values in trial_values:
            score = objective(FixedTrial(values))
            if self.best_value is None or score > self.best_value:
                self.best_value = score
                self.best_params = values


class FakeOptuna:
    def create_study(self, direction):
        self.direction = direction
        return FakeStudy()


def candles(count=160):
    return [
        Candle(
            timestamp=f"2026-01-{(index % 28) + 1:02d}T14:{index % 60:02d}:00",
            open=100 + (index * 0.3),
            high=101 + (index * 0.3),
            low=99 + (index * 0.3),
            close=100 + (index * 0.3),
            volume=1000,
        )
        for index in range(count)
    ]


class TunerTests(unittest.TestCase):
    def test_constraint_handling_rejects_short_sma_not_less_than_long(self):
        score = tuning_objective(
            FixedTrial(
                {
                    "sma_short": 30,
                    "sma_long": 20,
                    "rsi_buy": 30.0,
                    "rsi_sell": 70.0,
                    "buy_score_threshold": 3.0,
                    "sell_score_threshold": -3.0,
                    "stop_loss_pct": 5.0,
                    "take_profit_pct": 10.0,
                }
            ),
            candles(),
            "BB",
            TuningConfig(trials=1),
        )

        self.assertLess(score, -999_000)

    def test_optimizer_can_run_tiny_mocked_trial_set(self):
        result = tune_strategy_for_symbol(
            candles(),
            "BB",
            TuningConfig(trials=2, minimum_trade_count=0),
            optuna_module=FakeOptuna(),
        )

        self.assertIn("sma_short", result.params)
        self.assertIsInstance(result.score, float)
        self.assertEqual(result.backtest.symbol, "BB")


if __name__ == "__main__":
    unittest.main()
