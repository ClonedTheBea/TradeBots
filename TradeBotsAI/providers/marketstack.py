"""MarketStack market data provider.

This module converts provider-specific OHLCV responses into the shared Candle
model so strategy and backtesting code can stay provider-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is listed, this keeps tests importable before install.
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

from data.models import Candle


DEFAULT_BASE_URL = "https://api.marketstack.com/v2"
DEFAULT_LIMIT = 500
DEFAULT_CACHE_DIR = Path("data/cache/marketstack")
SUPPORTED_INTRADAY_INTERVALS = {"1min", "5min", "10min", "15min", "30min", "1hour"}
_LAST_INTRADAY_FETCH_AT: float | None = None


@dataclass(frozen=True)
class MarketStackConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    default_limit: int = DEFAULT_LIMIT
    cache_enabled: bool = True
    cache_dir: Path = DEFAULT_CACHE_DIR


def load_marketstack_config(env_path: str | Path = ".env") -> MarketStackConfig:
    load_dotenv(env_path)
    api_key = os.getenv("MARKETSTACK_API_KEY", "").strip()
    base_url = os.getenv("MARKETSTACK_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    default_limit = _positive_int(os.getenv("MARKETSTACK_DEFAULT_LIMIT"), DEFAULT_LIMIT)
    cache_enabled = os.getenv("MARKETSTACK_CACHE_ENABLED", "true").strip().lower() != "false"

    if not api_key:
        raise RuntimeError("Missing MARKETSTACK_API_KEY in .env/environment.")

    return MarketStackConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        default_limit=default_limit,
        cache_enabled=cache_enabled,
    )


class MarketStackClient:
    def __init__(
        self,
        config: MarketStackConfig,
        session: Any | None = None,
    ) -> None:
        self.config = config
        self.session = session or _new_requests_session()

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "MarketStackClient":
        return cls(load_marketstack_config(env_path))

    def fetch_eod(
        self,
        symbol: str,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = DEFAULT_LIMIT,
        refresh: bool = False,
    ) -> list[Candle]:
        payload = self._fetch(
            endpoint="eod",
            symbol=symbol,
            interval=None,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            refresh=refresh,
        )
        return marketstack_rows_to_candles(payload.get("data", []), symbol)

    def fetch_intraday(
        self,
        symbol: str,
        interval: str = "15min",
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = DEFAULT_LIMIT,
        refresh: bool = False,
    ) -> list[Candle]:
        normalized_interval = interval.strip().lower()
        if normalized_interval not in SUPPORTED_INTRADAY_INTERVALS:
            raise ValueError(
                f"Unsupported MarketStack intraday interval: {interval}. "
                f"Supported intervals: {', '.join(sorted(SUPPORTED_INTRADAY_INTERVALS))}."
            )
        _warn_if_repeated_intraday_fetch()
        payload = self._fetch(
            endpoint="intraday",
            symbol=symbol,
            interval=normalized_interval,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            refresh=refresh,
        )
        return marketstack_rows_to_candles(payload.get("data", []), symbol)

    def _fetch(
        self,
        endpoint: str,
        symbol: str,
        interval: str | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
        refresh: bool,
    ) -> dict[str, Any]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        normalized_symbol = symbol.upper()
        cache_path = marketstack_cache_path(
            self.config.cache_dir,
            normalized_symbol,
            endpoint,
            interval,
            date_from,
            date_to,
            limit,
        )
        if self.config.cache_enabled and cache_path.exists() and not refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        params: dict[str, Any] = {
            "access_key": self.config.api_key,
            "symbols": normalized_symbol,
            "limit": limit,
        }
        if interval:
            params["interval"] = interval
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        response_payload = self._request_with_retries(f"{self.config.base_url}/{endpoint}", params)
        if self.config.cache_enabled:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(response_payload, indent=2, sort_keys=True), encoding="utf-8")
        return response_payload

    def _request_with_retries(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        max_attempts = 3
        for attempt in range(max_attempts):
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code == 429 and attempt < max_attempts - 1:
                retry_after = _retry_after_seconds(response)
                print(
                    "MarketStack rate limit reached (429). "
                    f"Retrying in {retry_after:.1f} seconds."
                )
                time.sleep(retry_after)
                continue
            if response.status_code in {401, 403, 429}:
                raise RuntimeError(_marketstack_error_message(response))
            if response.status_code >= 400:
                raise RuntimeError(f"MarketStack request failed with HTTP {response.status_code}: {response.text}")
            payload = response.json()
            if isinstance(payload, dict) and "error" in payload:
                raise RuntimeError(f"MarketStack error: {payload['error']}")
            if not isinstance(payload, dict):
                raise RuntimeError("MarketStack response was not a JSON object.")
            return payload
        raise RuntimeError("MarketStack request failed after retrying rate-limit responses.")


def marketstack_rows_to_candles(rows: list[dict[str, Any]], fallback_symbol: str) -> list[Candle]:
    candles = [marketstack_row_to_candle(row, fallback_symbol) for row in rows]
    return sorted(candles, key=lambda candle: candle.timestamp)


def marketstack_row_to_candle(row: dict[str, Any], fallback_symbol: str) -> Candle:
    timestamp = row.get("date") or row.get("timestamp")
    if not timestamp:
        raise ValueError("MarketStack row is missing date/timestamp.")
    symbol = str(row.get("symbol") or fallback_symbol).upper()
    return Candle(
        timestamp=str(timestamp),
        open=_required_float(row, "open"),
        high=_required_float(row, "high"),
        low=_required_float(row, "low"),
        close=_required_float(row, "close"),
        volume=float(row.get("volume") or 0),
        is_synthetic=False,
        symbol=symbol,
    )


def marketstack_cache_key(
    symbol: str,
    endpoint: str,
    interval: str | None,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> str:
    key_data = {
        "symbol": symbol.upper(),
        "endpoint": endpoint,
        "interval": interval or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
        "limit": limit,
    }
    raw_key = json.dumps(key_data, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
    readable = "_".join(
        [
            key_data["symbol"],
            endpoint,
            key_data["interval"] or "none",
            key_data["date_from"] or "none",
            key_data["date_to"] or "none",
            str(limit),
        ]
    )
    safe_readable = "".join(char if char.isalnum() or char in "._-" else "-" for char in readable)
    return f"{safe_readable}_{digest}.json"


def marketstack_cache_path(
    cache_dir: str | Path,
    symbol: str,
    endpoint: str,
    interval: str | None,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> Path:
    return Path(cache_dir) / marketstack_cache_key(symbol, endpoint, interval, date_from, date_to, limit)


def _warn_if_repeated_intraday_fetch() -> None:
    global _LAST_INTRADAY_FETCH_AT
    now = datetime.now(timezone.utc).timestamp()
    if _LAST_INTRADAY_FETCH_AT is not None and now - _LAST_INTRADAY_FETCH_AT < 60:
        print(
            "Warning: repeated intraday MarketStack fetch requested within 60 seconds. "
            "Use cached data where possible and avoid wasteful polling."
        )
    _LAST_INTRADAY_FETCH_AT = now


def _required_float(row: dict[str, Any], field: str) -> float:
    value = row.get(field)
    if value is None:
        raise ValueError(f"MarketStack row is missing {field}.")
    return float(value)


def _positive_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    parsed = int(value)
    if parsed <= 0:
        raise RuntimeError("MARKETSTACK_DEFAULT_LIMIT must be positive.")
    return parsed


def _new_requests_session() -> Any:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "requests is required for MarketStack data access. Install it with "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return requests.Session()


def _retry_after_seconds(response: Any) -> float:
    value = response.headers.get("Retry-After", "2")
    try:
        return min(max(float(value), 0.5), 10.0)
    except ValueError:
        return 2.0


def _marketstack_error_message(response: Any) -> str:
    messages = {
        401: "MarketStack authentication failed (401). Check MARKETSTACK_API_KEY.",
        403: "MarketStack request forbidden (403). Check your plan permissions and endpoint access.",
        429: "MarketStack rate limit reached (429). Wait before retrying or use cached data.",
    }
    detail = response.text.strip()
    return f"{messages[response.status_code]} Details: {detail}" if detail else messages[response.status_code]
