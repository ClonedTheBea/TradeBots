import sys
import unittest
from io import StringIO
from contextlib import redirect_stdout
from unittest.mock import patch

from app import main as app_main
from app.risk import RiskSettings


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

    def test_batch_optimise_passes_defaults(self):
        argv = [
            "app.main",
            "batch-optimise",
            "--symbols",
            "AAPL,MSFT",
        ]
        with patch.object(sys, "argv", argv), patch.object(
            app_main,
            "run_batch_optimise_command",
            return_value=0,
        ) as run_batch:
            exit_code = app_main.main()

        self.assertEqual(exit_code, 0)
        run_batch.assert_called_once_with(
            "AAPL,MSFT",
            "config/batch_symbols.txt",
            "1Day",
            365,
            2000,
            0.7,
            False,
            False,
            "reports/batch_optimise",
            "tradebots_ai.sqlite",
        )

    def test_run_scheduler_uses_default_symbols_when_omitted(self):
        argv = [
            "app.main",
            "run-scheduler",
            "--interval-minutes",
            "15",
            "--confidence-threshold",
            "0.65",
        ]
        with patch.object(sys, "argv", argv), patch.object(
            app_main,
            "run_scheduler",
            return_value=0,
        ) as run_scheduler:
            exit_code = app_main.main()

        self.assertEqual(exit_code, 0)
        self.assertIsNone(run_scheduler.call_args.args[0])

    def test_run_scheduler_loads_default_symbols_when_symbols_text_is_none(self):
        output = StringIO()
        with patch.object(app_main, "load_default_symbols", return_value=["BB", "MSFT"]), patch(
            "broker.alpaca_client.AlpacaPaperClient.from_env",
            return_value=object(),
        ), redirect_stdout(output):
            exit_code = app_main.run_scheduler(
                None,
                15,
                0.65,
                1.0,
                "1Day",
                180,
                False,
                False,
                False,
                RiskSettings(),
                "tradebots_ai.sqlite",
                max_cycles=0,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Starting scheduler for BB, MSFT", output.getvalue())


if __name__ == "__main__":
    unittest.main()
