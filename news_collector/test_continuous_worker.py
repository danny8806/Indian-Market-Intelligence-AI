"""Deterministic continuous worker tests, no network or broker orders."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine

from news_collector.continuous_worker import (
    collect_and_store, poll_interval_seconds,
)

IST = ZoneInfo("Asia/Kolkata")


class WorkerTests(unittest.TestCase):
    def test_overnight_and_daytime_cadence(self):
        self.assertEqual(poll_interval_seconds(
            datetime(2026, 11, 9, 16, tzinfo=IST)), 600)
        self.assertEqual(poll_interval_seconds(
            datetime(2026, 11, 10, 8, 30, tzinfo=IST)), 600)
        self.assertEqual(poll_interval_seconds(
            datetime(2026, 11, 10, 11, tzinfo=IST)), 1800)

    def test_primary_data_persists_even_if_optional_ai_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            from news_collector.db_store import articles
            from sqlalchemy import select
            import json
            root = Path(tmp)
            def fake_collect(session, data_root):
                target = data_root / session
                target.mkdir(exist_ok=True)
                (target / "events.jsonl").write_text(
                    json.dumps({
                        "id": "news-one", "url": "https://example.com/thermax",
                        "headline": "Thermax Limited Q2 results",
                        "published_at": "2026-11-09T18:30:00+05:30",
                        "first_seen_at": "2026-11-10T04:30:00+05:30",
                        "last_seen_at": "2026-11-10T04:30:00+05:30",
                        "symbols": ["THERMAX"], "sources": ["NSE"],
                        "providers": ["NSE"], "authorities": ["official"],
                    }) + "\n", encoding="utf-8")
                (target / "coverage.json").write_text(
                    json.dumps({
                        "session": session, "generated_at":
                        "2026-11-10T04:30:00+05:30",
                        "sources_configured": 80, "sources_with_items": 51,
                        "sources_failed": 12, "sources": []
                    }), encoding="utf-8")
                return {"sources_configured": 80,
                        "sources_with_items": 51, "sources_failed": 12}
            db = create_engine("sqlite+pysqlite:///:memory:")
            with patch("news_collector.continuous_worker.collect_news",
                       side_effect=fake_collect):
                with patch("news_collector.continuous_worker.collect_openai_links",
                           side_effect=TimeoutError("mock")):
                    result = collect_and_store(
                        db, data_root=root, now=datetime(2026, 11, 10, 4, 30, tzinfo=IST))
            self.assertEqual(result["database"], "DATABASE_SYNC_OK")
            self.assertEqual(result["openai"], "OPENAI_DISCOVERY_FAILED")
            with db.connect() as conn:
                self.assertEqual(len(conn.execute(select(articles)).all()), 1)


if __name__ == "__main__":
    unittest.main()
