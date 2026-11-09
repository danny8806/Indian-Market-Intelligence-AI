"""Offline tests: indexed discovery never asserts original publication time."""
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from news_collector.index_discovery import search_index_items, fetch_search_index
from news_collector.engine import build_record, fetch_one

SOURCE = {
    "name": "BazaarWatch indexed discovery",
    "url": "https://bazaarwatch.com/",
    "provider": "MEDIA",
    "authority": "secondary",
    "kind": "indexed_search",
    "enabled": True,
    "allowed_domains": ["bazaarwatch.com"],
    "search_query": "site:bazaarwatch.com NSE announcements",
}


class IndexDiscoveryTests(unittest.TestCase):
    def test_domain_filter_and_unverified_dates(self):
        blob = json.dumps({"organic": [
            {"title": "Thermax Limited corporate results announcement",
             "link": "https://bazaarwatch.com/announcements/thermax",
             "snippet": "Thermax posted results", "date": "9 Nov 2026"},
            {"title": "Unrelated finance headline announcement",
             "link": "https://attacker.example.org/story", "date": "9 Nov 2026"},
            {"title": "Thermax Limited corporate results announcement",
             "link": "https://bazaarwatch.com/announcements/thermax"},
        ]}).encode()
        hits = search_index_items(blob, SOURCE)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["raw_time"], "")
        ist = ZoneInfo("Asia/Kolkata")
        status, row = build_record(
            hits[0], SOURCE, {"THERMAX": "Thermax Limited"},
            datetime(2026, 11, 9, 15, tzinfo=ist),
            datetime(2026, 11, 11, 9, tzinfo=ist),
            datetime(2026, 11, 10, 4, tzinfo=ist),
        )
        self.assertEqual(status, "UNVERIFIED_TIMESTAMP")
        self.assertIsNone(row["published_at"])

    def test_reject_no_domains_or_invalid_schema(self):
        with self.assertRaises(ValueError):
            search_index_items(b'{"organic":[]}', {**SOURCE, "allowed_domains": []})
        with self.assertRaises(ValueError):
            search_index_items(b'{"articles":[]}', SOURCE)

    def test_missing_key_skips_and_never_fetches_page(self):
        with patch.dict("os.environ", {"SERPER_API_KEY": ""}):
            with patch("news_collector.engine.fetch_bytes") as direct:
                stat, items = fetch_one(SOURCE)
        self.assertEqual(stat["status"], "SKIPPED_NO_KEY")
        self.assertEqual(items, [])
        direct.assert_not_called()

    def test_search_api_only_and_no_domain_crawl(self):
        response = type("Response", (), {
            "content": b'{"organic":[]}',
            "raise_for_status": lambda self: None,
        })()
        with patch.dict("os.environ", {"SERPER_API_KEY": "test-key"}):
            with patch("news_collector.index_discovery.requests.post",
                       return_value=response) as post:
                self.assertEqual(fetch_search_index(SOURCE), b'{"organic":[]}')
        self.assertEqual(post.call_args.args[0], "https://google.serper.dev/search")
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(post.call_args.kwargs["headers"]["X-API-KEY"], "test-key")


if __name__ == "__main__":
    unittest.main()
