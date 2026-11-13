"""Registry tests: only verified official/issuer endpoints may be polled."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from news_collector import source_registry

ROOT = Path(__file__).resolve().parent


def sources_config() -> list[dict]:
    return json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["sources"]


def endpoints(registry: dict) -> list[dict]:
    return source_registry.flatten(registry)


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = source_registry.load()
        self.sources = sources_config()

    def test_repository_registry_is_valid_and_covers_every_official_source(self):
        result = source_registry.check()
        self.assertEqual(result["status"], "REGISTRY_OK", result["errors"])
        official_enabled = [source for source in self.sources
                            if source.get("authority") == "official"
                            and source.get("enabled", True)]
        active = {row['poll_source'] for row in endpoints(self.registry) if row['access_status']=='ACTIVE'}
        self.assertTrue({source['name'] for source in official_enabled} <= active)
        self.assertEqual(result['active_poll_sources'], len(active))
        self.assertTrue(active <= {source['name'] for source in self.sources if source.get('enabled',True)})
        self.assertGreaterEqual(result["organizations"], 15)

    def test_new_official_feeds_are_active_and_registered(self):
        expected = {
            "NSE insider trading RSS", "NSE circulars RSS",
            "NSE SAST regulation 29 RSS", "NSE SAST regulation 31 RSS",
            "NSE voting results RSS", "NSE daily buyback RSS",
            "NSE related party transactions RSS", "NSE investor complaints RSS",
            "NSE unitholding patterns RSS", "NSE statement of deviation RSS",
        }
        active = {row["poll_source"] for row in endpoints(self.registry)
                  if row["access_status"] == "ACTIVE"}
        self.assertTrue(expected <= active)
        enabled = {source["name"] for source in self.sources if source.get("enabled", True)}
        self.assertTrue(expected <= enabled)

    def test_blocked_and_registry_only_endpoints_are_not_polled(self):
        for row in endpoints(self.registry):
            if row["access_status"] == "ACTIVE":
                continue
            self.assertIsNone(row["poll_source"], row["id"])
        mca = next(row for row in endpoints(self.registry) if row["id"] == "mca-home")
        fda = next(row for row in endpoints(self.registry) if row["id"] == "fda-press")
        self.assertEqual(mca["access_status"], "BLOCKED")
        self.assertEqual(mca["evidence"]["http_status"], 403)
        self.assertEqual(fda["evidence"]["http_status"], 404)
        self.assertIn("not authorization", fda["reason"])

    def test_active_endpoint_without_poll_source_fails(self):
        broken = deepcopy(self.registry)
        endpoint = next(row for organization in broken["organizations"]
                        for row in organization["endpoints"]
                        if row["access_status"] == "ACTIVE")
        endpoint["poll_source"] = None
        errors = source_registry.validate(broken, self.sources)
        self.assertTrue(any("ACTIVE endpoint needs poll_source" in error for error in errors))

    def test_enabling_a_blocked_endpoint_fails(self):
        polluted = deepcopy(self.sources)
        blocked = next(row for row in endpoints(self.registry) if row["id"] == "mca-home")
        polluted.append({"name": blocked["name"], "url": blocked["url"], "kind": "html",
                         "provider": "MCA", "authority": "official", "enabled": True})
        errors = source_registry.validate(self.registry, polluted)
        self.assertTrue(any("non-active endpoint is enabled" in error for error in errors))

    def test_enabled_official_source_missing_from_registry_fails(self):
        polluted = deepcopy(self.sources)
        polluted.append({"name": "Unregistered official feed",
                         "url": "https://example.gov.in/feed.xml", "kind": "rss",
                         "provider": "MCA", "authority": "official", "enabled": True})
        errors = source_registry.validate(self.registry, polluted)
        self.assertTrue(any("missing from the registry" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
