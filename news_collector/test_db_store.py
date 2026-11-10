"""Tests for point-in-time DB persistence; SQLite stands in for PostgreSQL."""
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text

from news_collector.db_store import (
    articles, article_symbols, aware, backfill_article_fields, engine_for_url, runs,
    source_checks, sync_session,
)

LEGACY_ARTICLES = """
CREATE TABLE news_articles (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    url TEXT NOT NULL, headline TEXT NOT NULL, summary TEXT NOT NULL,
    record_kind VARCHAR(32) NOT NULL, time_status VARCHAR(80) NOT NULL,
    published_at DATETIME, first_seen_at DATETIME NOT NULL,
    last_seen_at DATETIME NOT NULL, ingested_at DATETIME NOT NULL,
    symbols JSON NOT NULL, sources JSON NOT NULL, providers JSON NOT NULL,
    authorities JSON NOT NULL, provider_reported_time_unverified TEXT NOT NULL
)
"""
NEW_COLUMNS = {"category", "sentiment", "sentiment_score", "discoverer",
               "company_name", "isin", "verification_method", "financial_figures"}


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
            "headline": "Thermax Limited Q2 results: net profit rose 20%",
            "summary": "Q2 result", "symbols": ["THERMAX"], "sources": ["NSE"],
            "providers": ["NSE"], "authorities": ["official"],
            "first_seen_at": now, "last_seen_at": now,
            "publication_time_status": "VERIFIED_FORMAT",
            "discoverer": "python", "company_name": "Thermax Limited",
            "verification_method": "official_exchange_feed_timestamp",
            "isin": "INE152A01029",
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
            self.assertEqual(rows[0]["category"], "financial_results")
            self.assertEqual(rows[0]["sentiment"], "BULLISH")
            self.assertEqual(rows[0]["sentiment_score"], 3)
            self.assertEqual(rows[0]["discoverer"], "python")
            self.assertEqual(rows[0]["company_name"], "Thermax Limited")
            self.assertEqual(rows[0]["isin"], "INE152A01029")
            self.assertEqual(rows[0]["verification_method"],
                             "official_exchange_feed_timestamp")
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

    def test_later_lane_cannot_overwrite_first_discoverer(self):
        sync_session(self.database, self.folder.parent, "2026-11-11")
        later = dict(self.verified, discoverer="codex",
                     first_seen_at="2026-11-10T04:40:00+05:30",
                     last_seen_at="2026-11-10T04:40:00+05:30")
        self._write("undated_candidates.jsonl", "")
        self._write("events.jsonl", json.dumps(later) + "\n")
        sync_session(self.database, self.folder.parent, "2026-11-11")
        with self.database.connect() as conn:
            row = conn.execute(select(articles)).mappings().one()
            self.assertEqual(row["discoverer"], "python")

    def test_earlier_observation_can_claim_discovery(self):
        sync_session(self.database, self.folder.parent, "2026-11-11")
        earlier = dict(self.verified, discoverer="codex",
                       first_seen_at="2026-11-09T23:00:00+05:30",
                       last_seen_at="2026-11-09T23:00:00+05:30")
        self._write("undated_candidates.jsonl", "")
        self._write("events.jsonl", json.dumps(earlier) + "\n")
        sync_session(self.database, self.folder.parent, "2026-11-11")
        with self.database.connect() as conn:
            row = conn.execute(select(articles)).mappings().one()
            self.assertEqual(row["discoverer"], "codex")

    def test_reject_naive_timestamp_and_missing_session(self):
        with self.assertRaises(ValueError):
            aware("2026-11-09T15:30:00")
        with self.assertRaises(FileNotFoundError):
            sync_session(self.database, self.folder.parent, "2026-11-12")
        with self.assertRaises(ValueError):
            engine_for_url("mysql://localhost/db")

    def test_legacy_article_table_is_upgraded_in_place(self):
        legacy = create_engine("sqlite+pysqlite:///:memory:")
        with legacy.begin() as conn:
            conn.execute(text(LEGACY_ARTICLES))
        sync_session(legacy, self.folder.parent, "2026-11-11")
        with legacy.connect() as conn:
            names = {column["name"] for column in
                     inspect(conn).get_columns("news_articles")}
            self.assertTrue(NEW_COLUMNS <= names, NEW_COLUMNS - names)
            row = conn.execute(select(articles)).mappings().one()
            self.assertEqual(row["category"], "financial_results")
            self.assertEqual(row["sentiment"], "BULLISH")
        sync_session(legacy, self.folder.parent, "2026-11-11")  # idempotent upgrade

    def test_backfill_restores_classification_and_discoverer(self):
        sync_session(self.database, self.folder.parent, "2026-11-11")
        with self.database.begin() as conn:
            conn.execute(articles.update().values(
                category="other", sentiment="UNCLEAR", sentiment_score=0,
                discoverer="", verification_method=""))
        result = backfill_article_fields(self.database)
        self.assertEqual(result["status"], "FIELDS_BACKFILLED")
        self.assertEqual(result["updated"], 1)
        with self.database.connect() as conn:
            row = conn.execute(select(articles)).mappings().one()
            self.assertEqual(row["category"], "financial_results")
            self.assertEqual(row["sentiment"], "BULLISH")
            self.assertEqual(row["verification_method"], "source_feed_timestamp")
        self.assertEqual(backfill_article_fields(self.database)["updated"], 0)

    def test_no_db_provided_cli_skips_cleanly(self):
        from news_collector.db_store import main
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", ["db_store"]):
                main()


if __name__ == "__main__":
    unittest.main()
