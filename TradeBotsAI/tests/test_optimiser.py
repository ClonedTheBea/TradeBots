import json
import tempfile
import unittest
from pathlib import Path

from data.csv_loader import load_candles_from_csv
from data.models import BacktestResult
from strategy.optimiser import (
    OptimisationConfig,
    objective,
    save_best_parameters,
    signal_config_from_params,
    suggest_signal_config,
)


class FakeTrial:
    def suggest_int(self, name, low, high):
        values = {
            "sma_short": 10,
            "sma_long": 30,
        }
        return values.get(name, low)

    def suggest_float(self, name, low, high):
        values = {
            "rsi_buy": 30.0,
            "rsi_sell": 70.0,
            "buy_score_threshold": 3.0,
            "sell_score_threshold": -3.0,
        }
        return values.get(name, low)


BEST_PARAMS = {
    "sma_short": 10,
    "sma_long": 30,
    "rsi_buy": 30.0,
    "rsi_sell": 70.0,
    "buy_score_threshold": 3.0,
    "sell_score_threshold": -3.0,
}


class OptimiserTests(unittest.TestCase):
    def test_suggest_signal_config_maps_trial_values(self):
        config = suggest_signal_config(FakeTrial())

        self.assertEqual(config.short_sma_period, 10)
        self.assertEqual(config.long_sma_period, 30)
        self.assertEqual(config.rsi_buy_threshold, 30.0)
        self.assertEqual(config.rsi_sell_threshold, 70.0)
        self.assertEqual(config.buy_score_threshold, 3.0)
        self.assertEqual(config.sell_score_threshold, -3.0)

    def test_objective_uses_backtest_return_minus_drawdown_penalty(self):
        candles = load_candles_from_csv(Path("data/sample_ohlcv.csv"))

        value = objective(
            FakeTrial(),
            candles,
            symbol="SIM",
            optimisation_config=OptimisationConfig(drawdown_penalty=0.25),
        )

        self.assertIsInstance(value, float)

    def test_save_best_parameters_writes_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "best.json"
            backtest = BacktestResult(
                symbol="SIM",
                starting_cash=1000.0,
                ending_cash=1100.0,
                total_return_pct=10.0,
                trades=(),
                signals=(),
                win_rate=0.0,
                average_profit_per_trade=0.0,
                max_drawdown_pct=2.0,
            )

            save_best_parameters(BEST_PARAMS, 9.5, backtest, output_path)

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["best_params"], BEST_PARAMS)
        self.assertEqual(payload["objective_value"], 9.5)
        self.assertEqual(payload["metrics"]["total_return_pct"], 10.0)
        self.assertEqual(payload["signal_config"], signal_config_from_params(BEST_PARAMS).__dict__)


if __name__ == "__main__":
    unittest.main()
