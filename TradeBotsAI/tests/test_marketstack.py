import json
import tempfile
import unittest
from pathlib import Path

from providers.marketstack import (
    MarketStackClient,
    MarketStackConfig,
    marketstack_cache_key,
    marketstack_cache_path,
    marketstack_row_to_candle,
    marketstack_rows_to_candles,
)


EOD_FIXTURE = {
    "data": [
        {
            "symbol": "AAPL",
            "date": "2024-01-03T00:00:00+0000",
            "open": 184.22,
            "high": 185.88,
            "low": 183.43,
            "close": 184.67,
            "volume": 58414500,
        },
        {
            "symbol": "AAPL",
            "date": "2024-01-02T00:00:00+0000",
            "open": 187.15,
            "high": 188.44,
            "low": 183.89,
            "close": 185.64,
            "volume": 82488700,
        },
    ]
}


class FakeResponse:
    def __init__(self, payload, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return self.responses.pop(0)


class MarketStackTests(unittest.TestCase):
    def test_marketstack_response_parsing_sorts_rows_oldest_first(self):
        candles = marketstack_rows_to_candles(EOD_FIXTURE["data"], "AAPL")

        self.assertEqual([candle.timestamp for candle in candles], [
            "2024-01-02T00:00:00+0000",
            "2024-01-03T00:00:00+0000",
        ])
        self.assertEqual(candles[0].symbol, "AAPL")

    def test_marketstack_row_to_candle_converts_ohlcv(self):
        candle = marketstack_row_to_candle(EOD_FIXTURE["data"][0], "MSFT")

        self.assertEqual(candle.open, 184.22)
        self.assertEqual(candle.high, 185.88)
        self.assertEqual(candle.low, 183.43)
        self.assertEqual(candle.close, 184.67)
        self.assertEqual(candle.volume, 58414500.0)
        self.assertFalse(candle.is_synthetic)
        self.assertEqual(candle.symbol, "AAPL")

    def test_marketstack_cache_key_includes_request_parts(self):
        key = marketstack_cache_key("aapl", "intraday", "15min", "2024-01-01", "2024-01-31", 500)

        self.assertIn("AAPL_intraday_15min_2024-01-01_2024-01-31_500", key)
        self.assertTrue(key.endswith(".json"))
        self.assertNotEqual(
            key,
            marketstack_cache_key("aapl", "intraday", "5min", "2024-01-01", "2024-01-31", 500),
        )

    def test_fetch_eod_uses_cache_without_api_call(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MarketStackConfig(api_key="test", cache_dir=Path(tmpdir), cache_enabled=True)
            cache_path = marketstack_cache_path(config.cache_dir, "AAPL", "eod", None, None, None, 2)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(EOD_FIXTURE), encoding="utf-8")
            session = FakeSession([])
            client = MarketStackClient(config, session=session)

            candles = client.fetch_eod("AAPL", limit=2)

        self.assertEqual(len(candles), 2)
        self.assertEqual(session.calls, [])

    def test_fetch_eod_converts_mocked_api_response(self):
        session = FakeSession([FakeResponse(EOD_FIXTURE)])
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MarketStackConfig(api_key="test", cache_dir=Path(tmpdir), cache_enabled=False)
            client = MarketStackClient(config, session=session)

            candles = client.fetch_eod("AAPL", limit=2)

        self.assertEqual(len(candles), 2)
        self.assertEqual(session.calls[0]["url"], "https://api.marketstack.com/v2/eod")
        self.assertEqual(session.calls[0]["params"]["symbols"], "AAPL")
        self.assertEqual(candles[-1].close, 184.67)

    def test_clear_error_for_auth_failures(self):
        session = FakeSession([FakeResponse({}, status_code=401, text="bad key")])
        config = MarketStackConfig(api_key="test", cache_enabled=False)
        client = MarketStackClient(config, session=session)

        with self.assertRaisesRegex(RuntimeError, "MarketStack authentication failed"):
            client.fetch_eod("AAPL", limit=1)


if __name__ == "__main__":
    unittest.main()
