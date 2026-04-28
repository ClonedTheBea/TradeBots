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


@dataclass(frozen=True)
class WalkForwardValidationResult:
    params: dict[str, int | float]
    score: float
    train_backtest: BacktestResult
    validation_backtest: BacktestResult
    overfit_warning: str


@dataclass(frozen=True)
class PromotionThresholds:
    min_validation_return_pct: float = 0.0
    max_validation_drawdown_pct: float = 15.0
    min_validation_trade_count: int = 5
    min_validation_win_rate_pct: float = 40.0
    max_train_validation_gap_pct: float = 30.0


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reasons: list[str]


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


def validate_strategy_for_symbol(
    candles: list[Candle],
    symbol: str,
    train_ratio: float,
    config: TuningConfig,
    optuna_module: Any | None = None,
) -> WalkForwardValidationResult:
    train_candles, validation_candles = split_train_validation(candles, train_ratio)
    tuning = tune_strategy_for_symbol(train_candles, symbol, config, optuna_module=optuna_module)
    validation_backtest = run_tuned_backtest(validation_candles, tuning.params, symbol, config)
    warning = generate_overfit_warning(
        train_backtest=tuning.backtest,
        validation_backtest=validation_backtest,
        minimum_validation_trades=config.minimum_trade_count,
    )
    return WalkForwardValidationResult(
        params=tuning.params,
        score=tuning.score,
        train_backtest=tuning.backtest,
        validation_backtest=validation_backtest,
        overfit_warning=warning,
    )


def split_train_validation(
    candles: list[Candle],
    train_ratio: float,
) -> tuple[list[Candle], list[Candle]]:
    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio must be between 0 and 1")
    if len(candles) < 2:
        raise ValueError("At least two candles are required for validation")
    split_index = int(len(candles) * train_ratio)
    split_index = min(max(split_index, 1), len(candles) - 1)
    return candles[:split_index], candles[split_index:]


def generate_overfit_warning(
    train_backtest: BacktestResult,
    validation_backtest: BacktestResult,
    minimum_validation_trades: int = 3,
    max_validation_drawdown_pct: float = 25.0,
) -> str:
    warnings: list[str] = []
    if train_backtest.total_return_pct > 0 and validation_backtest.total_return_pct < 0:
        warnings.append("train positive but validation negative")
    if validation_backtest.total_return_pct < (train_backtest.total_return_pct * 0.35):
        warnings.append("validation return much worse than train return")
    if len(validation_backtest.trades) < minimum_validation_trades:
        warnings.append("validation trade count too low")
    if validation_backtest.max_drawdown_pct > max_validation_drawdown_pct:
        warnings.append("validation drawdown too high")
    return "; ".join(warnings)


def should_promote_parameters(
    metrics: dict[str, Any],
    thresholds: PromotionThresholds | None = None,
) -> PromotionDecision:
    config = thresholds or PromotionThresholds()
    reasons: list[str] = []
    validation_return = float(metrics.get("validation_return_pct") or 0)
    validation_drawdown = float(metrics.get("validation_drawdown_pct") or 0)
    validation_trade_count = int(metrics.get("validation_trade_count") or 0)
    validation_win_rate = float(metrics.get("validation_win_rate_pct") or 0)
    train_return = float(metrics.get("train_return_pct") or 0)
    overfit_warning = str(metrics.get("overfit_warning") or "").strip()

    if validation_return < config.min_validation_return_pct:
        reasons.append("Validation return is negative")
    if validation_trade_count < config.min_validation_trade_count:
        reasons.append(
            f"Trade count too low ({validation_trade_count} < {config.min_validation_trade_count})"
        )
    if validation_drawdown > config.max_validation_drawdown_pct:
        reasons.append(
            f"Validation drawdown too high ({validation_drawdown:.2f}% > {config.max_validation_drawdown_pct:.2f}%)"
        )
    if validation_win_rate < config.min_validation_win_rate_pct:
        reasons.append(
            f"Validation win rate too low ({validation_win_rate:.2f}% < {config.min_validation_win_rate_pct:.2f}%)"
        )
    if overfit_warning:
        reasons.append("Overfit warning triggered")
    if train_return > 0 and validation_return < 0:
        reason = "Train return positive but validation return negative"
        if reason not in reasons:
            reasons.append(reason)
    gap = abs(train_return - validation_return)
    if gap > config.max_train_validation_gap_pct:
        reasons.append(
            f"Train/validation return gap too large ({gap:.2f}% > {config.max_train_validation_gap_pct:.2f}%)"
        )
    return PromotionDecision(promote=not reasons, reasons=reasons)


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


def validation_result_to_storage_params(
    result: WalkForwardValidationResult,
    symbol: str,
    timeframe: str,
    lookback_days: int,
) -> dict[str, int | float | str]:
    payload = tuning_result_to_storage_params(
        TuningResult(result.params, result.score, result.train_backtest),
        symbol,
        timeframe,
        lookback_days,
    )
    payload.update(
        {
            "train_return_pct": result.train_backtest.total_return_pct,
            "validation_return_pct": result.validation_backtest.total_return_pct,
            "train_drawdown_pct": result.train_backtest.max_drawdown_pct,
            "validation_drawdown_pct": result.validation_backtest.max_drawdown_pct,
            "train_win_rate_pct": result.train_backtest.win_rate * 100,
            "validation_win_rate_pct": result.validation_backtest.win_rate * 100,
            "validation_trade_count": len(result.validation_backtest.trades),
            "overfit_warning": result.overfit_warning,
        }
    )
    return payload


def _load_optuna() -> Any:
    try:
        import optuna
    except ImportError as exc:
        raise RuntimeError(
            "Optuna is required for symbol tuning. Install it with "
            "`python -m pip install -r requirements.txt` or `python -m pip install optuna`."
        ) from exc
    return optuna
