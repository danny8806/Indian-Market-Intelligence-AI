"""Tests for point-in-time DB persistence; SQLite stands in for PostgreSQL."""
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select

from news_collector.db_store import (
    articles, article_symbols, aware, engine_for_url, runs,
    source_checks, sync_session,
)


class DBTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "2026-11-11"
        self.folder.mkdir()
        self.database = create_engine("sqlite+pysqlite:///:memory:")
        now = "2026-11-10T04:30:00+05:30"
        common = {
            "id": "abc123", "url": "https://example.com/thermax",
            "headline": "Thermax Limited announces results", "summary": "Q2 result",
            "symbols": ["THERMAX"], "sources": ["NSE"],
            "providers": ["NSE"], "authorities": ["official"],
            "first_seen_at": now, "last_seen_at": now,
            "publication_time_status": "VERIFIED_FORMAT",
        }
        unverified = dict(common, published_at=None, sources=["Google News"],
                          providers=["MEDIA"], authorities=["secondary"])
        verified = dict(common, published_at="2026-11-09T18:30:00+05:30")
        self.unverified = unverified
        self.verified = verified
        self._write("coverage.json", json.dumps({
            "session": "2026-11-11",
            "generated_at": "2026-11-10T04:30:00+05:30",
            "sources_configured": 80, "sources_with_items": 1,
            "sources_failed": 1,
            "sources": [
                {"source": "NSE announcements RSS", "status": "OK", "kind": "rss",
                 "fetched_items": 2},
                {"source": "Publisher blocked", "status": "ERROR", "kind": "html",
                 "fetched_items": 0, "error": "HTTP 403"},
            ],
        }))
        self._write("undated_candidates.jsonl", json.dumps(unverified) + "\n")
        self._write("events.jsonl", json.dumps(verified) + "\n")

    def _write(self, name, value):
        (self.folder / name).write_text(value, encoding="utf-8")

    def test_idempotent_upsert_prefers_parsed_source_time(self):
        first = sync_session(self.database, self.folder.parent, "2026-11-11")
        second = sync_session(self.database, self.folder.parent, "2026-11-11")
        self.assertEqual(first["status"], "DATABASE_SYNC_OK")
        self.assertEqual(second["status"], "DATABASE_SYNC_OK")
        with self.database.connect() as conn:
            rows = conn.execute(select(articles)).mappings().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["record_kind"], "timestamped_stock")
            self.assertEqual(rows[0]["published_at"].hour, 13)  # UTC
            self.assertIn("NSE", rows[0]["sources"])
            self.assertIn("Google News", rows[0]["sources"])
            self.assertEqual(conn.execute(select(article_symbols)).all()[0].symbol,
                             "THERMAX")
            self.assertEqual(len(conn.execute(select(runs)).all()), 2)
            self.assertEqual(len(conn.execute(select(source_checks)).all()), 2)

    def test_unverified_discovery_does_not_promote_to_published(self):
        self._write("events.jsonl", "")
        sync_session(self.database, self.folder.parent, "2026-11-11")
        with self.database.connect() as conn:
            row = conn.execute(select(articles)).mappings().one()
            self.assertIsNone(row["published_at"])
            self.assertEqual(row["record_kind"], "discovery_only")
            self.assertEqual(row["time_status"], "DISCOVERY_TIME_ONLY")

    def test_previous_verified_timestamp_not_downgraded(self):
        sync_session(self.database, self.folder.parent, "2026-11-11")
        self._write("events.jsonl", "")
        sync_session(self.database, self.folder.parent, "2026-11-11")
        with self.database.connect() as conn:
            row = conn.execute(select(articles)).mappings().one()
            self.assertEqual(row["record_kind"], "timestamped_stock")
            self.assertIsNotNone(row["published_at"])

    def test_reject_naive_timestamp_and_missing_session(self):
        with self.assertRaises(ValueError):
            aware("2026-11-09T15:30:00")
        with self.assertRaises(FileNotFoundError):
            sync_session(self.database, self.folder.parent, "2026-11-12")
        with self.assertRaises(ValueError):
            engine_for_url("mysql://localhost/db")

    def test_no_db_provided_cli_skips_cleanly(self):
        from news_collector.db_store import main
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", ["db_store"]):
                main()


if __name__ == "__main__":
    unittest.main()
