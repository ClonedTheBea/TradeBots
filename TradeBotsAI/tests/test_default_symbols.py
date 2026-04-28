import tempfile
import unittest
from pathlib import Path

from app.default_symbols import DEFAULT_SYMBOLS, load_default_symbols


class DefaultSymbolsTests(unittest.TestCase):
    def test_loading_symbols_from_file_normalizes_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch_symbols.txt"
            path.write_text("# defaults\n aapl \n\nMSFT\nAAPL\nbb\n", encoding="utf-8")

            symbols = load_default_symbols(path)

        self.assertEqual(symbols, ["AAPL", "MSFT", "BB"])

    def test_missing_file_falls_back_to_hardcoded_defaults(self):
        symbols = load_default_symbols("does-not-exist/batch_symbols.txt")

        self.assertEqual(symbols, DEFAULT_SYMBOLS)

    def test_empty_file_falls_back_to_hardcoded_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch_symbols.txt"
            path.write_text("# nothing here\n\n", encoding="utf-8")

            symbols = load_default_symbols(path)

        self.assertEqual(symbols, DEFAULT_SYMBOLS)


if __name__ == "__main__":
    unittest.main()
