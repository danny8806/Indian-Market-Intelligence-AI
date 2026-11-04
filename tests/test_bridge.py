import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from bridge.app import create_app


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        now = datetime(2026, 11, 4, 9, 5, tzinfo=ZoneInfo("Asia/Kolkata"))
        db = Path(self.temp.name) / "reports.db"
        self.app = create_app(database_url=f"sqlite:///{db.as_posix()}",
                              bearer_token="x" * 32, now_provider=lambda: now)
        self.addCleanup(self.app.state.engine.dispose)
        self.client = TestClient(self.app)
        self.headers = {"Authorization": "Bearer " + "x" * 32,
                        "Idempotency-Key": "2026-11-04-research-v1"}
        self.report = {"schema_version": "1.0", "status": "NO_TRADE", "market": "NSE",
                       "timezone": "Asia/Kolkata", "session_date": "2026-11-04",
                       "news_cutoff_at": "2026-11-04T09:00:00+05:30",
                       "generated_at": "2026-11-04T09:02:00+05:30",
                       "execution_enabled": False, "signals": [],
                       "reason": "No verified candidates today"}

    def test_auth_idempotency_and_current_session(self):
        url = "/api/v1/signals/incoming"
        self.assertEqual(self.client.post(url, json=self.report).status_code, 401)
        accepted = self.client.post(url, json=self.report, headers=self.headers)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["status"], "ACCEPTED")
        duplicate = self.client.post(url, json=self.report, headers=self.headers)
        self.assertEqual(duplicate.json()["status"], "DUPLICATE")
        self.assertEqual(self.client.get("/api/v1/signals/latest", headers=self.headers)
                         .json()["report"]["status"], "NO_TRADE")
        modified = dict(self.report, reason="Different report content")
        self.assertEqual(self.client.post(url, json=modified, headers=self.headers).status_code, 409)

    def test_stale_report_rejected(self):
        self.report["session_date"] = "2026-11-03"
        self.assertEqual(self.client.post("/api/v1/signals/incoming", json=self.report,
                                          headers=self.headers).status_code, 422)


if __name__ == "__main__":
    unittest.main()
