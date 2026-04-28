import tempfile
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


if __name__ == "__main__":
    unittest.main()
