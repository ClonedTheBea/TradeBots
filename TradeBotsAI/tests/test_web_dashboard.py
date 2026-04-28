import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - depends on optional web deps in local env.
    TestClient = None

from web.server import create_app


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed")
class WebDashboardTests(unittest.TestCase):
    def test_index_page_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(db_path=str(Path(tmp) / "test.sqlite"))
            client = TestClient(app)

            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("TradeBotsAI", response.text)

    def test_status_endpoint_returns_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(db_path=str(Path(tmp) / "test.sqlite"))
            client = TestClient(app)

            response = client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("scheduler", body)
        self.assertIn("risk", body)

    def test_logs_endpoint_returns_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(db_path=str(Path(tmp) / "test.sqlite"))
            app.state.dashboard.logs.append("hello")
            client = TestClient(app)

            response = client.get("/api/logs")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("hello" in line for line in response.json()["logs"]))

    def test_validation_endpoint_returns_quickly_and_writes_logs(self):
        release_validation = threading.Event()

        def fake_validation(_settings, _db_path, on_line):
            on_line("Train Return: +1.00%")
            release_validation.wait(5)
            on_line("Validation Return: +0.50%")
            return 0

        with tempfile.TemporaryDirectory() as tmp, patch("web.server._run_validation_command", side_effect=fake_validation):
            app = create_app(db_path=str(Path(tmp) / "test.sqlite"))
            client = TestClient(app)

            started_at = time.monotonic()
            response = client.post("/api/validate", json={"symbol": "AMZN", "trials": 1})
            elapsed = time.monotonic() - started_at
            release_validation.set()
            self._wait_for_validation_status(client, "completed")
            logs = client.get("/api/logs").json()["logs"]

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["started"])
        self.assertLess(elapsed, 1.0)
        self.assertTrue(any("Starting validation for AMZN" in line for line in logs))
        self.assertTrue(any("Train Return" in line for line in logs))

    def test_duplicate_validation_is_rejected_while_running(self):
        release_validation = threading.Event()

        def fake_validation(_settings, _db_path, on_line):
            on_line("Running validation")
            release_validation.wait(5)
            return 0

        with tempfile.TemporaryDirectory() as tmp, patch("web.server._run_validation_command", side_effect=fake_validation):
            app = create_app(db_path=str(Path(tmp) / "test.sqlite"))
            client = TestClient(app)

            first = client.post("/api/validate", json={"symbol": "AMZN", "trials": 1})
            second = client.post("/api/validate", json={"symbol": "MSFT", "trials": 1})
            release_validation.set()
            self._wait_for_validation_status(client, "completed")

        self.assertTrue(first.json()["started"])
        self.assertFalse(second.json()["started"])
        self.assertEqual(second.json()["message"], "Validation already running.")

    def test_scheduler_cannot_start_twice(self):
        with tempfile.TemporaryDirectory() as tmp, patch("web.server._run_scheduler_cycle") as run_cycle:
            app = create_app(db_path=str(Path(tmp) / "test.sqlite"))
            run_cycle.side_effect = lambda *_args, **_kwargs: app.state.dashboard._stop_event.wait(5) or 0
            client = TestClient(app)
            payload = {
                "symbols": "AAPL",
                "interval_minutes": 15,
                "confidence_threshold": 0.65,
            }

            first = client.post("/api/scheduler/start", json=payload)
            second = client.post("/api/scheduler/start", json=payload)
            client.post("/api/scheduler/stop")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.json()["ok"])
        self.assertFalse(second.json()["ok"])

    def test_validation_does_not_stop_scheduler(self):
        release_scheduler = threading.Event()
        release_validation = threading.Event()

        def fake_scheduler(*_args, **_kwargs):
            release_scheduler.wait(5)
            return 0

        def fake_validation(_settings, _db_path, on_line):
            on_line("Validation Return: +0.50%")
            release_validation.wait(5)
            return 0

        with tempfile.TemporaryDirectory() as tmp, patch("web.server._run_scheduler_cycle", side_effect=fake_scheduler), patch(
            "web.server._run_validation_command",
            side_effect=fake_validation,
        ):
            app = create_app(db_path=str(Path(tmp) / "test.sqlite"))
            client = TestClient(app)
            scheduler_payload = {
                "symbols": "AAPL",
                "interval_minutes": 15,
                "confidence_threshold": 0.65,
            }

            scheduler = client.post("/api/scheduler/start", json=scheduler_payload)
            validation = client.post("/api/validate", json={"symbol": "AMZN", "trials": 1})
            status = client.get("/api/status").json()
            release_validation.set()
            self._wait_for_validation_status(client, "completed")
            still_running = client.get("/api/status").json()
            client.post("/api/scheduler/stop")
            release_scheduler.set()

        self.assertTrue(scheduler.json()["ok"])
        self.assertTrue(validation.json()["started"])
        self.assertTrue(status["scheduler"]["running"])
        self.assertTrue(still_running["scheduler"]["running"])

    def _wait_for_validation_status(self, client, status):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            jobs = client.get("/api/jobs").json()["jobs"]
            if jobs and jobs[0]["status"] == status:
                return jobs[0]
            time.sleep(0.05)
        self.fail(f"validation job did not reach {status}")


if __name__ == "__main__":
    unittest.main()
