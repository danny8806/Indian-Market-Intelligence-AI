"""OpenAI web discovery must store citations, not invented timestamps."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from news_collector.openai_web_discovery import (
    approved_links, daily_budget, run, status,
)

IST = ZoneInfo("Asia/Kolkata")


class MockResponse:
    def model_dump(self):
        return {
            "output": [
                {"type": "web_search_call", "action": {"sources": [
                    {"url": "https://example.com/news/thermax",
                     "title": "Thermax Limited reports quarterly results"},
                    {"url": "http://unsafe.example.com/not-tls",
                     "title": "Untrusted source"},
                ]}},
                {"type": "message", "content": [{
                    "type": "output_text",
                    "annotations": [{"type": "url_citation", "url": "https://example.com/news/thermax",
                                     "title": "Thermax Limited reports quarterly results"}],
                }]},
            ]
        }


class FakeClient:
    def __init__(self):
        self.calls = []
        self.responses = self
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return MockResponse()


class OpenAIWebDiscoveryTests(unittest.TestCase):
    def test_citations_only_and_deduplicated(self):
        result = approved_links(MockResponse().model_dump())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], "https://example.com/news/thermax")

    def test_budget_bounds(self):
        for value in ("0", "-1", "49", "abc"):
            with self.assertRaises(ValueError):
                daily_budget(value)
        self.assertEqual(daily_budget("6"), 6)

    def test_skips_without_optin(self):
        with patch.dict(os.environ, {"ENABLE_OPENAI_WEB_RESEARCH": "",
                                     "OPENAI_API_KEY": "fake"}):
            self.assertEqual(status(), "SKIPPED_COST_GUARD")

    def test_collection_store_and_daily_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-11-11").mkdir()
            fake = FakeClient()
            now = datetime(2026, 11, 10, 4, 40, tzinfo=IST)
            with patch.dict(os.environ, {
                "ENABLE_OPENAI_WEB_RESEARCH": "true",
                "OPENAI_API_KEY": "not-real",
                "OPENAI_NEWS_MODEL": "gpt-5.6",
                "OPENAI_MAX_SEARCHES_PER_DAY": "1",
            }):
                with patch("news_collector.openai_web_discovery.get_universe",
                           return_value=({"THERMAX": "Thermax Limited"}, "MOCK_UNIVERSE")):
                    first = run("2026-11-11", root, now=now, client=fake)
                    second = run("2026-11-11", root, now=now, client=fake)
            self.assertEqual(first["status"], "DISCOVERY_COMPLETED")
            self.assertEqual(second["status"], "SKIPPED_DAILY_BUDGET")
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(fake.calls[0]["tools"][0]["type"], "web_search")
            data = [json.loads(line) for line in (
                root / "2026-11-11/undated_candidates.jsonl").read_text().splitlines()]
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["symbols"], ["THERMAX"])
            self.assertIsNone(data[0]["published_at"])
            self.assertEqual(data[0]["sources"], ["OpenAI Responses web_search"])

if __name__ == "__main__":
    unittest.main()
