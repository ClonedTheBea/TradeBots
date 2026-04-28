import tempfile
import unittest
from pathlib import Path

from app.main import _signal_engine_for_symbol
from storage.sqlite_store import SQLiteStore


def params(symbol="BB", score=1.0, sma_short=5, sma_long=30):
    return {
        "symbol": symbol,
        "timeframe": "1Day",
        "lookback_days": 365,
        "sma_short": sma_short,
        "sma_long": sma_long,
        "rsi_buy": 30.0,
        "rsi_sell": 70.0,
        "buy_score_threshold": 3.0,
        "sell_score_threshold": -3.0,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 10.0,
        "total_return_pct": 12.0,
        "max_drawdown_pct": 4.0,
        "win_rate_pct": 60.0,
        "trade_count": 8,
        "score": score,
    }


def validated_params(symbol="BB", warning=""):
    payload = params(symbol=symbol, score=3.0)
    payload.update(
        {
            "train_return_pct": 10.0,
            "validation_return_pct": 4.0,
            "train_drawdown_pct": 3.0,
            "validation_drawdown_pct": 5.0,
            "train_win_rate_pct": 60.0,
            "validation_win_rate_pct": 50.0,
            "validation_trade_count": 4,
            "overfit_warning": warning,
        }
    )
    return payload


class StrategyParameterStorageTests(unittest.TestCase):
    def test_parameter_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with SQLiteStore(Path(tmpdir) / "params.sqlite") as store:
                store.initialize()
                store.save_strategy_parameters(params(), active=True)

                loaded = store.get_active_strategy_parameters("bb", "1Day")

        self.assertEqual(loaded["symbol"], "BB")
        self.assertEqual(loaded["sma_short"], 5)
        self.assertEqual(loaded["stop_loss_pct"], 5.0)

    def test_active_parameter_replacement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with SQLiteStore(Path(tmpdir) / "params.sqlite") as store:
                store.initialize()
                first_id = store.save_strategy_parameters(params(score=1.0, sma_short=5), active=True)
                second_id = store.save_strategy_parameters(params(score=2.0, sma_short=8), active=True)

                loaded = store.get_active_strategy_parameters("BB", "1Day")
                active_count = store._conn().execute(
                    "SELECT COUNT(*) FROM strategy_parameters WHERE symbol='BB' AND timeframe='1Day' AND is_active=1"
                ).fetchone()[0]

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(active_count, 1)
        self.assertEqual(loaded["sma_short"], 8)

    def test_signal_engine_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with SQLiteStore(Path(tmpdir) / "params.sqlite") as store:
                store.initialize()

                engine, source = _signal_engine_for_symbol(store, "BB", "1Day")

        self.assertEqual(source, "default")
        self.assertEqual(engine.config.short_sma_period, 10)

    def test_signal_engine_uses_active_tuned_params(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with SQLiteStore(Path(tmpdir) / "params.sqlite") as store:
                store.initialize()
                store.save_strategy_parameters(params(sma_short=4, sma_long=40), active=True)

                engine, source = _signal_engine_for_symbol(store, "BB", "1Day")

        self.assertEqual(source, "tuned")
        self.assertEqual(engine.config.short_sma_period, 4)
        self.assertEqual(engine.config.long_sma_period, 40)

    def test_validation_metrics_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with SQLiteStore(Path(tmpdir) / "params.sqlite") as store:
                store.initialize()
                store.save_strategy_parameters(validated_params(), active=True)

                loaded = store.get_active_strategy_parameters("BB", "1Day")

        self.assertEqual(loaded["validation_return_pct"], 4.0)
        self.assertEqual(loaded["validation_trade_count"], 4)
        self.assertEqual(loaded["overfit_warning"], "")


if __name__ == "__main__":
    unittest.main()
