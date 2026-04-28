import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from broker.alpaca_client import alpaca_bar_to_candle, load_alpaca_config


class FakeBar:
    timestamp = datetime(2026, 4, 28, tzinfo=timezone.utc)
    open = 10
    high = 12
    low = 9
    close = 11
    volume = 1000


class AlpacaClientTests(unittest.TestCase):
    def test_load_alpaca_config_requires_paper_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "ALPACA_API_KEY=key\nALPACA_SECRET_KEY=secret\nALPACA_PAPER=false\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "ALPACA_PAPER must be true"):
                load_alpaca_config(env_path)

    def test_load_alpaca_config_reads_paper_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "ALPACA_API_KEY=key\nALPACA_SECRET_KEY=secret\nALPACA_PAPER=true\n",
                encoding="utf-8",
            )

            config = load_alpaca_config(env_path)

        self.assertEqual(config.api_key, "key")
        self.assertEqual(config.secret_key, "secret")
        self.assertTrue(config.paper)
        self.assertEqual(config.data_feed, "iex")

    def test_load_alpaca_config_reads_sip_feed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "ALPACA_API_KEY=key\nALPACA_SECRET_KEY=secret\nALPACA_PAPER=true\nALPACA_DATA_FEED=sip\n",
                encoding="utf-8",
            )

            config = load_alpaca_config(env_path)

        self.assertEqual(config.data_feed, "sip")

    def test_load_alpaca_config_rejects_unknown_feed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "ALPACA_API_KEY=key\nALPACA_SECRET_KEY=secret\nALPACA_PAPER=true\nALPACA_DATA_FEED=boats\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "ALPACA_DATA_FEED"):
                load_alpaca_config(env_path)

    def test_alpaca_bar_to_candle(self):
        candle = alpaca_bar_to_candle(FakeBar())

        self.assertEqual(candle.open, 10.0)
        self.assertEqual(candle.high, 12.0)
        self.assertEqual(candle.low, 9.0)
        self.assertEqual(candle.close, 11.0)
        self.assertEqual(candle.volume, 1000.0)
        self.assertFalse(candle.is_synthetic)


if __name__ == "__main__":
    unittest.main()
