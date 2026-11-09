"""ChatGPT GitHub inbox is discovery-only, safe to replay, no OpenAI API."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from news_collector.chatgpt_inbox_import import import_inbox, parse_inbox_file
from news_collector.engine import read_jsonl


class ChatGPTInboxTests(unittest.TestCase):
    def test_import_dedupes_and_preserves_unverified_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "chatgpt_inbox"
            inbox.mkdir()
            (inbox / "2026-11-10T050000IST.json").write_text(json.dumps({
                "schema": "chatgpt-news-discovery/v1",
                "captured_at_ist": "2026-11-10T05:00:00+05:30",
                "articles": [
                    {"headline": "Thermax Limited reports stronger quarterly earnings",
                     "url": "https://example.org/thermax",
                     "publisher": "Example News",
                     "publisher_time_claim": "2026-11-09T20:30:00+05:30"},
                    {"headline": "Thermax Limited reports stronger quarterly earnings",
                     "url": "https://example.org/thermax?utm_source=ai"},
                    {"headline": "Thermax Limited annual report",
                     "url": "http://insecure.example.org/annual"},
                ],
            }), encoding="utf-8")
            now = datetime.now(ZoneInfo("Asia/Kolkata"))
            a = import_inbox(root=root, session="2026-11-11", now=now,
                             universe={"THERMAX": "Thermax Limited"})
            b = import_inbox(root=root, session="2026-11-11", now=now,
                             universe={"THERMAX": "Thermax Limited"})
            self.assertEqual(a["new_files"], 1)
            self.assertEqual(a["accepted_discovery_links"], 2)
            self.assertEqual(b["new_files"], 0)
            stored = read_jsonl(root / "data/2026-11-11/undated_candidates.jsonl")
            self.assertEqual(len(stored), 1)
            row = next(iter(stored.values()))
            self.assertIsNone(row["published_at"])
            self.assertEqual(row["symbols"], ["THERMAX"])
            self.assertEqual(row["publication_time_status"], "UNVERIFIED")
            self.assertEqual(row["sources"], ["ChatGPT Scheduled web discovery"])

    def test_untrusted_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed.json"
            path.write_text(json.dumps({"schema": "unsupported", "articles": []}))
            with self.assertRaises(ValueError):
                parse_inbox_file(path)
            path.write_text(json.dumps({
                "schema": "chatgpt-news-discovery/v1", "articles": [{}] * 76
            }))
            with self.assertRaises(ValueError):
                parse_inbox_file(path)

if __name__ == "__main__":
    unittest.main()
