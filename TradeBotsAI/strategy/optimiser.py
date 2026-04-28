"""Optional Optuna-based strategy parameter optimiser."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from data.models import BacktestResult, Candle
from strategy.backtest import BacktestConfig, Backtester
from strategy.signals import SignalConfig, SignalEngine


@dataclass(frozen=True)
class OptimisationConfig:
    trials: int = 50
    drawdown_penalty: float = 0.25
    output_path: str = "best_strategy_params.json"
    starting_cash: float = 10_000.0


@dataclass(frozen=True)
class OptimisationResult:
    best_params: dict[str, int | float]
    best_value: float
    best_backtest: BacktestResult
    output_path: str


def optimise_strategy(
    candles: list[Candle],
    symbol: str = "UNKNOWN",
    config: OptimisationConfig | None = None,
) -> OptimisationResult:
    optuna = _load_optuna()
    optimisation_config = config or OptimisationConfig()

    if optimisation_config.trials <= 0:
        raise ValueError("trials must be positive")

    study = optuna.create_study(direction="maximize")
    study.optimize(
        lambda trial: objective(
            trial,
            candles,
            symbol=symbol,
            optimisation_config=optimisation_config,
        ),
        n_trials=optimisation_config.trials,
    )

    best_signal_config = signal_config_from_params(study.best_params)
    best_backtest = run_backtest(candles, best_signal_config, symbol, optimisation_config)
    output_path = save_best_parameters(
        study.best_params,
        study.best_value,
        best_backtest,
        optimisation_config.output_path,
    )
    return OptimisationResult(
        best_params=dict(study.best_params),
        best_value=study.best_value,
        best_backtest=best_backtest,
        output_path=str(output_path),
    )


def objective(
    trial: Any,
    candles: list[Candle],
    symbol: str = "UNKNOWN",
    optimisation_config: OptimisationConfig | None = None,
) -> float:
    config = optimisation_config or OptimisationConfig()
    signal_config = suggest_signal_config(trial)
    result = run_backtest(candles, signal_config, symbol, config)
    return result.total_return_pct - (result.max_drawdown_pct * config.drawdown_penalty)


def suggest_signal_config(trial: Any) -> SignalConfig:
    sma_short = trial.suggest_int("sma_short", 5, 25)
    sma_long = trial.suggest_int("sma_long", sma_short + 5, 80)
    return SignalConfig(
        short_sma_period=sma_short,
        long_sma_period=sma_long,
        rsi_buy_threshold=trial.suggest_float("rsi_buy", 20.0, 45.0),
        rsi_sell_threshold=trial.suggest_float("rsi_sell", 55.0, 80.0),
        buy_score_threshold=trial.suggest_float("buy_score_threshold", 2.0, 5.0),
        sell_score_threshold=trial.suggest_float("sell_score_threshold", -5.0, -2.0),
    )


def signal_config_from_params(params: dict[str, int | float]) -> SignalConfig:
    return SignalConfig(
        short_sma_period=int(params["sma_short"]),
        long_sma_period=int(params["sma_long"]),
        rsi_buy_threshold=float(params["rsi_buy"]),
        rsi_sell_threshold=float(params["rsi_sell"]),
        buy_score_threshold=float(params["buy_score_threshold"]),
        sell_score_threshold=float(params["sell_score_threshold"]),
    )


def run_backtest(
    candles: list[Candle],
    signal_config: SignalConfig,
    symbol: str,
    optimisation_config: OptimisationConfig,
) -> BacktestResult:
    engine = SignalEngine(signal_config)
    backtester = Backtester(
        engine,
        BacktestConfig(starting_cash=optimisation_config.starting_cash),
    )
    return backtester.run(candles, symbol=symbol)


def save_best_parameters(
    best_params: dict[str, int | float],
    best_value: float,
    backtest_result: BacktestResult,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "best_params": best_params,
        "objective_value": best_value,
        "metrics": {
            "total_return_pct": backtest_result.total_return_pct,
            "max_drawdown_pct": backtest_result.max_drawdown_pct,
            "trade_count": len(backtest_result.trades),
            "win_rate": backtest_result.win_rate,
            "average_profit_per_trade": backtest_result.average_profit_per_trade,
        },
        "signal_config": asdict(signal_config_from_params(best_params)),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _load_optuna() -> Any:
    try:
        import optuna
    except ImportError as exc:
        raise RuntimeError(
            "Optuna is required for optimisation. Install it with "
            "`python -m pip install -r requirements.txt` or `python -m pip install optuna`."
        ) from exc
    return optuna
