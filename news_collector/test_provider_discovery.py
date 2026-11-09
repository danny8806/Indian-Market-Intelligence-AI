"""Offline API adapter tests: schema, secret safety, discovery-only timestamps."""
import json
import unittest
from unittest.mock import patch

from news_collector.engine import build_record, fetch_one
from news_collector.provider_discovery import (
    PROVIDERS, fetch_provider_news, provider_api_items, provider_has_key,
)

SAMPLES = {
    "tavily": {"results": [{"title": "Thermax Limited reports financial results",
                           "url": "https://example.com/tavily", "content": "earnings"}]},
    "exa": {"results": [{"title": "Thermax Limited reports financial results",
                        "url": "https://example.com/exa", "publishedDate": "2026-11-09"}]},
    "brave": {"results": [{"title": "Thermax Limited reports financial results",
                          "url": "https://example.com/brave"}]},
    "marketaux": {"data": [{"title": "Thermax Limited reports financial results",
                            "url": "https://example.com/marketaux",
                            "published_at": "2026-11-09T18:30:00Z"}]},
    "gnews": {"articles": [{"title": "Thermax Limited reports financial results",
                           "url": "https://example.com/gnews",
                           "publishedAt": "2026-11-09T18:30:00Z"}]},
    "newsdata": {"results": [{"title": "Thermax Limited reports financial results",
                            "link": "https://example.com/newsdata",
                            "pubDate": "2026-11-09 18:30:00"}]},
    "newsapi": {"articles": [{"title": "Thermax Limited reports financial results",
                             "url": "https://example.com/newsapi",
                             "publishedAt": "2026-11-09T18:30:00Z"}]},
}


class ProviderTests(unittest.TestCase):
    def source(self, provider):
        return {"name": provider, "api_provider": provider, "url": PROVIDERS[provider][1],
                "kind": "provider_api", "enabled": True,
                "provider": "MEDIA", "authority": "secondary",
                "search_query": "India NSE BSE corporate announcements"}

    def test_all_provider_schemas_are_discovery_only(self):
        for provider, fixture in SAMPLES.items():
            with self.subTest(provider=provider):
                hits = provider_api_items(json.dumps(fixture).encode(), self.source(provider))
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["raw_time"], "")
                self.assertIn("Thermax", hits[0]["headline"])
                self.assertTrue(hits[0]["url"].startswith("https://"))

    def test_bad_json_schema_and_domain_rejected(self):
        with self.assertRaises(ValueError):
            provider_api_items(b'{"unrelated":[]}', self.source("exa"))
        fake = {"results": [{"title": "Thermax Limited reports results",
                              "url": "http://insecure.example.com/file"}]}
        self.assertEqual(provider_api_items(json.dumps(fake).encode(), self.source("exa")), [])

    def test_all_seven_providers_skip_without_optin(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                with patch.dict("os.environ", {"ENABLE_PAID_NEWS_APIS": ""}):
                    with patch("news_collector.provider_discovery.requests.post") as post:
                        with patch("news_collector.provider_discovery.requests.get") as get:
                            status, rows = fetch_one(self.source(provider))
                self.assertEqual(status["status"], "SKIPPED_COST_GUARD")
                self.assertEqual(rows, [])
                post.assert_not_called()
                get.assert_not_called()

    def test_optin_without_key_is_never_reported_as_success(self):
        for provider in PROVIDERS:
            envkey = PROVIDERS[provider][0]
            with patch.dict("os.environ", {"ENABLE_PAID_NEWS_APIS": "true", envkey: ""}):
                status, rows = fetch_one(self.source(provider))
            self.assertEqual(status["status"], "SKIPPED_NO_KEY")
            self.assertEqual(rows, [])

    def test_auth_and_error_redaction(self):
        class Response:
            status_code = 429
            content = b'{"error":"rate limited"}'
        provider = "marketaux"
        with patch.dict("os.environ", {"MARKETAUX_API_TOKEN": "SUPER-SECRET-TOKEN"}):
            with patch("news_collector.provider_discovery.requests.get", return_value=Response()) as call:
                with self.assertRaises(RuntimeError) as error:
                    fetch_provider_news(self.source(provider))
        self.assertIn("429", str(error.exception))
        self.assertNotIn("SUPER-SECRET", str(error.exception))
        self.assertEqual(call.call_args.kwargs["params"]["api_token"], "SUPER-SECRET-TOKEN")
        self.assertFalse(call.call_args.kwargs["allow_redirects"])

    def test_unknown_api_provider_fails_closed(self):
        with self.assertRaises(ValueError):
            provider_has_key({"api_provider": "unsafe_api"})

if __name__ == "__main__":
    unittest.main()
