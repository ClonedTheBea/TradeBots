"""Alpaca paper-trading adapter.

This module intentionally supports paper trading only. There is no live-trading
mode or fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Any

from data.models import Candle


@dataclass(frozen=True)
class AlpacaConfig:
    api_key: str
    secret_key: str
    paper: bool


@dataclass(frozen=True)
class AlpacaPosition:
    symbol: str
    qty: float
    market_value: float | None


@dataclass(frozen=True)
class AlpacaOrderResult:
    order_id: str
    symbol: str
    side: str
    qty: float
    status: str
    raw: str


def load_alpaca_config(env_path: str | Path = ".env") -> AlpacaConfig:
    values = _read_env_file(env_path)
    api_key = values.get("ALPACA_API_KEY") or os.getenv("ALPACA_API_KEY")
    secret_key = values.get("ALPACA_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    paper_value = values.get("ALPACA_PAPER") or os.getenv("ALPACA_PAPER")

    if not api_key or not secret_key:
        raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env/environment.")
    if str(paper_value).strip().lower() != "true":
        raise RuntimeError("Refusing Alpaca access: ALPACA_PAPER must be true. Live trading is not supported.")

    return AlpacaConfig(api_key=api_key, secret_key=secret_key, paper=True)


class AlpacaPaperClient:
    def __init__(self, config: AlpacaConfig) -> None:
        if not config.paper:
            raise RuntimeError("AlpacaPaperClient only supports paper=True.")
        alpaca = _load_alpaca_modules()
        self._alpaca = alpaca
        self.trading_client = alpaca["TradingClient"](
            config.api_key,
            config.secret_key,
            paper=True,
        )
        self.data_client = alpaca["StockHistoricalDataClient"](
            config.api_key,
            config.secret_key,
        )

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "AlpacaPaperClient":
        return cls(load_alpaca_config(env_path))

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        lookback: int = 180,
    ) -> list[Candle]:
        if lookback <= 0:
            raise ValueError("lookback must be positive")

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(lookback * 2, lookback + 10))
        request = self._alpaca["StockBarsRequest"](
            symbol_or_symbols=symbol,
            timeframe=_parse_timeframe(timeframe, self._alpaca["TimeFrame"]),
            start=start,
            end=end,
            limit=lookback,
        )
        response = self.data_client.get_stock_bars(request)
        bars = _extract_symbol_bars(response, symbol)
        return [alpaca_bar_to_candle(bar) for bar in bars][-lookback:]

    def get_position(self, symbol: str) -> AlpacaPosition | None:
        try:
            position = self.trading_client.get_open_position(symbol)
        except Exception:
            return None
        return AlpacaPosition(
            symbol=str(getattr(position, "symbol", symbol)),
            qty=float(getattr(position, "qty", 0) or 0),
            market_value=_optional_float(getattr(position, "market_value", None)),
        )

    def submit_paper_order(self, symbol: str, qty: float, side: str) -> AlpacaOrderResult:
        normalized_side = side.upper()
        if qty <= 0:
            raise ValueError("qty must be positive")
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

        if normalized_side == "BUY" and self.get_position(symbol) is not None:
            raise RuntimeError("BUY refused: current position already exists.")
        if normalized_side == "SELL" and self.get_position(symbol) is None:
            raise RuntimeError("SELL refused: no current position.")

        order_request = self._alpaca["MarketOrderRequest"](
            symbol=symbol,
            qty=qty,
            side=self._alpaca["OrderSide"].BUY if normalized_side == "BUY" else self._alpaca["OrderSide"].SELL,
            time_in_force=self._alpaca["TimeInForce"].DAY,
        )
        order = self.trading_client.submit_order(order_data=order_request)
        return AlpacaOrderResult(
            order_id=str(getattr(order, "id", "")),
            symbol=str(getattr(order, "symbol", symbol)),
            side=str(getattr(order, "side", normalized_side)),
            qty=float(getattr(order, "qty", qty) or qty),
            status=str(getattr(order, "status", "")),
            raw=str(order),
        )


def alpaca_bar_to_candle(bar: Any) -> Candle:
    timestamp = getattr(bar, "timestamp", None)
    return Candle(
        timestamp=timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
        open=float(getattr(bar, "open")),
        high=float(getattr(bar, "high")),
        low=float(getattr(bar, "low")),
        close=float(getattr(bar, "close")),
        volume=float(getattr(bar, "volume", 0) or 0),
        is_synthetic=False,
    )


def _parse_timeframe(value: str, time_frame_cls: Any) -> Any:
    normalized = value.strip().lower()
    mapping = {
        "1day": time_frame_cls.Day,
        "day": time_frame_cls.Day,
        "1d": time_frame_cls.Day,
        "1hour": time_frame_cls.Hour,
        "hour": time_frame_cls.Hour,
        "1h": time_frame_cls.Hour,
        "1min": time_frame_cls.Minute,
        "1minute": time_frame_cls.Minute,
        "minute": time_frame_cls.Minute,
    }
    if normalized not in mapping:
        raise ValueError(f"Unsupported timeframe: {value}")
    return mapping[normalized]


def _extract_symbol_bars(response: Any, symbol: str) -> list[Any]:
    if hasattr(response, "data"):
        data = response.data
        if isinstance(data, dict):
            return list(data.get(symbol, []))
    if isinstance(response, dict):
        return list(response.get(symbol, []))
    return list(response)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _read_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _load_alpaca_modules() -> dict[str, Any]:
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
    except ImportError as exc:
        raise RuntimeError(
            "alpaca-py is required for Alpaca paper trading. Install it with "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    return {
        "MarketOrderRequest": MarketOrderRequest,
        "OrderSide": OrderSide,
        "StockBarsRequest": StockBarsRequest,
        "StockHistoricalDataClient": StockHistoricalDataClient,
        "TimeFrame": TimeFrame,
        "TimeInForce": TimeInForce,
        "TradingClient": TradingClient,
    }
