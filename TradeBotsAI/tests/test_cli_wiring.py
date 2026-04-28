import sys
import unittest
from unittest.mock import patch

from app import main as app_main


class CliWiringTests(unittest.TestCase):
    def test_validate_symbol_passes_default_db_path(self):
        argv = [
            "app.main",
            "validate-symbol",
            "--symbol",
            "BB",
            "--timeframe",
            "1Day",
            "--lookback",
            "365",
            "--trials",
            "100",
        ]
        with patch.object(sys, "argv", argv), patch.object(
            app_main,
            "run_validate_symbol",
            return_value=0,
        ) as run_validate:
            exit_code = app_main.main()

        self.assertEqual(exit_code, 0)
        run_validate.assert_called_once_with("BB", "1Day", 365, 0.7, 100, 3, False, "tradebots_ai.sqlite")


if __name__ == "__main__":
    unittest.main()
