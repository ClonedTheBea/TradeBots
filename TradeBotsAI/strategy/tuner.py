"""Symbol-specific strategy tuning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data.models import BacktestResult, Candle
from strategy.backtest import BacktestConfig, Backtester
from strategy.signals import SignalConfig, SignalEngine


@dataclass(frozen=True)
class TuningConfig:
    trials: int = 100
    minimum_trade_count: int = 3
    starting_cash: float = 10_000.0


@dataclass(frozen=True)
class TuningResult:
    params: dict[str, int | float]
    score: float
    backtest: BacktestResult


def tune_strategy_for_symbol(
    candles: list[Candle],
    symbol: str,
    config: TuningConfig,
    optuna_module: Any | None = None,
) -> TuningResult:
    if config.trials <= 0:
        raise ValueError("trials must be positive")
    optuna = optuna_module or _load_optuna()
    study = optuna.create_study(direction="maximize")
    study.optimize(lambda trial: tuning_objective(trial, candles, symbol, config), n_trials=config.trials)
    best_params = dict(study.best_params)
    best_backtest = run_tuned_backtest(candles, best_params, symbol, config)
    return TuningResult(best_params, study.best_value, best_backtest)


def tuning_objective(
    trial: Any,
    candles: list[Candle],
    symbol: str,
    config: TuningConfig,
) -> float:
    params = suggest_tuning_params(trial)
    if int(params["sma_short"]) >= int(params["sma_long"]):
        return -1_000_000.0
    result = run_tuned_backtest(candles, params, symbol, config)
    return score_backtest(result, config.minimum_trade_count)


def suggest_tuning_params(trial: Any) -> dict[str, int | float]:
    sma_short = trial.suggest_int("sma_short", 3, 30)
    sma_long = trial.suggest_int("sma_long", 20, 120)
    return {
        "sma_short": sma_short,
        "sma_long": sma_long,
        "rsi_buy": trial.suggest_float("rsi_buy", 20.0, 45.0),
        "rsi_sell": trial.suggest_float("rsi_sell", 55.0, 85.0),
        "buy_score_threshold": trial.suggest_float("buy_score_threshold", 2.0, 6.0),
        "sell_score_threshold": trial.suggest_float("sell_score_threshold", -6.0, -2.0),
        "stop_loss_pct": trial.suggest_float("stop_loss_pct", 1.0, 12.0),
        "take_profit_pct": trial.suggest_float("take_profit_pct", 2.0, 25.0),
    }


def run_tuned_backtest(
    candles: list[Candle],
    params: dict[str, int | float],
    symbol: str,
    config: TuningConfig,
) -> BacktestResult:
    engine = SignalEngine(signal_config_from_tuned_params(params))
    return Backtester(
        engine,
        BacktestConfig(
            starting_cash=config.starting_cash,
            stop_loss_pct=float(params["stop_loss_pct"]),
            take_profit_pct=float(params["take_profit_pct"]),
        ),
    ).run(candles, symbol=symbol)


def signal_config_from_tuned_params(params: dict[str, Any]) -> SignalConfig:
    return SignalConfig(
        short_sma_period=int(params["sma_short"]),
        long_sma_period=int(params["sma_long"]),
        rsi_buy_threshold=float(params["rsi_buy"]),
        rsi_sell_threshold=float(params["rsi_sell"]),
        buy_score_threshold=float(params["buy_score_threshold"]),
        sell_score_threshold=float(params["sell_score_threshold"]),
    )


def score_backtest(result: BacktestResult, minimum_trade_count: int = 3) -> float:
    trade_count = len(result.trades)
    too_few_trade_penalty = max(minimum_trade_count - trade_count, 0) * 25.0
    excessive_trade_penalty = max(trade_count - 80, 0) * 0.5
    drawdown_penalty = result.max_drawdown_pct * 1.25
    win_rate_bonus = result.win_rate * 20.0
    return (
        result.total_return_pct
        + win_rate_bonus
        - drawdown_penalty
        - too_few_trade_penalty
        - excessive_trade_penalty
    )


def tuning_result_to_storage_params(
    result: TuningResult,
    symbol: str,
    timeframe: str,
    lookback_days: int,
) -> dict[str, int | float | str]:
    params = result.params
    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "lookback_days": lookback_days,
        "sma_short": int(params["sma_short"]),
        "sma_long": int(params["sma_long"]),
        "rsi_buy": float(params["rsi_buy"]),
        "rsi_sell": float(params["rsi_sell"]),
        "buy_score_threshold": float(params["buy_score_threshold"]),
        "sell_score_threshold": float(params["sell_score_threshold"]),
        "stop_loss_pct": float(params["stop_loss_pct"]),
        "take_profit_pct": float(params["take_profit_pct"]),
        "total_return_pct": result.backtest.total_return_pct,
        "max_drawdown_pct": result.backtest.max_drawdown_pct,
        "win_rate_pct": result.backtest.win_rate * 100,
        "trade_count": len(result.backtest.trades),
        "score": result.score,
    }


def _load_optuna() -> Any:
    try:
        import optuna
    except ImportError as exc:
        raise RuntimeError(
            "Optuna is required for symbol tuning. Install it with "
            "`python -m pip install -r requirements.txt` or `python -m pip install optuna`."
        ) from exc
    return optuna
