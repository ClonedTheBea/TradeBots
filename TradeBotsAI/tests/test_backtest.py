import unittest

from data.models import Candle, Signal
from strategy.backtest import BacktestConfig, Backtester
from strategy.signals import SignalConfig


class ScriptedSignalEngine:
    def __init__(self, actions):
        self.config = SignalConfig()
        self.actions = actions

    def signal_at(self, candles, index, symbol="UNKNOWN"):
        candle = candles[index]
        action = self.actions.get(index, "HOLD")
        score = {"BUY": 3.0, "SELL": -3.0, "HOLD": 0.0}[action]
        reasons = (f"scripted {action.lower()} signal",)
        return Signal(
            symbol=symbol,
            timestamp=candle.timestamp,
            action=action,
            confidence=min(abs(score) / self.config.max_score, 1.0),
            score=score,
            reasons=reasons,
            reason="; ".join(reasons),
            close=candle.close,
        )


def candles(count):
    return [
        Candle(
            timestamp=f"2024-02-{index + 1:02d}",
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1000,
        )
        for index in range(count)
    ]


class BacktesterTests(unittest.TestCase):
    def test_backtest_records_scored_signals_and_trades_long_only(self):
        engine = ScriptedSignalEngine({33: "BUY", 34: "HOLD", 35: "SELL"})
        result = Backtester(engine, BacktestConfig(starting_cash=1000)).run(
            candles(38),
            symbol="SIM",
        )

        self.assertEqual(len(result.signals), 5)
        self.assertEqual([signal.action for signal in result.signals[:3]], ["BUY", "HOLD", "SELL"])
        self.assertEqual(result.signals[0].timestamp, "2024-02-34")
        self.assertEqual(result.signals[0].close, 133)
        self.assertEqual(result.signals[0].score, 3.0)
        self.assertGreater(result.signals[0].confidence, 0.0)
        self.assertEqual(result.signals[0].reasons, ("scripted buy signal",))

        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].entry_price, 133)
        self.assertEqual(result.trades[0].exit_price, 135)
        self.assertGreater(result.ending_cash, result.starting_cash)
        self.assertEqual(result.win_rate, 1.0)
        self.assertGreater(result.average_profit_per_trade, 0)
        self.assertGreaterEqual(result.max_drawdown_pct, 0)


if __name__ == "__main__":
    unittest.main()
