"""Offline regression tests for cross-repository news collector adaptations."""
from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import requests

from news_collector.engine import rss_items, run
from news_collector.feed_resilience import read_with_retry, rss_root
from news_collector.matching import match_issuers

IST = ZoneInfo("Asia/Kolkata")


class ReusedSourceTests(unittest.TestCase):
    def test_partial_rss_only_recovers_complete_items_when_opted_in(self):
        good = (b"<rss><channel><item><title>Thermax Limited quarterly results</title>"
                b"<link>https://example.org/a</link>"
                b"<pubDate>Mon, 09 Nov 2026 18:30:00 +0530</pubDate></item>")
        broken = good + b"<item><title>Interrupted"
        source = {"name": "NSE announcements RSS", "provider": "NSE",
                  "url": "https://example.org/rss", "recover_truncated_rss": True}
        rows = rss_items(broken, source)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["headline"], "Thermax Limited quarterly results")
        with self.assertRaises(ET.ParseError):
            rss_items(broken, {**source, "recover_truncated_rss": False})

    def test_rss_invalid_controls_cleaned_without_silent_xml_rewrite(self):
        root = rss_root(b"<rss><channel><item><title>Hi\\x01 ok</title>"
                        b"<link>https://example.org</link></item></channel></rss>")
        self.assertEqual(root.find(".//title").text, "Hi ok")
        with self.assertRaises(ET.ParseError):
            rss_root(b"<rss><channel><item><title>bad</title></channel></rss>",
                     allow_truncated=True)

    def test_retry_only_transient_errors(self):
        calls = []
        def flaky(url):
            calls.append(url)
            if len(calls) == 1:
                raise requests.Timeout("temporarily timed out")
            return b"OK"
        delays = []
        self.assertEqual(read_with_retry("https://example.org", flaky,
                                         max_attempts=2, sleep=delays.append), b"OK")
        self.assertEqual(len(calls), 2)
        self.assertEqual(delays, [1])

    def test_no_retry_for_forbidden(self):
        calls = []
        def forbidden(url):
            calls.append(url)
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError("Forbidden", response=response)
        with self.assertRaises(requests.HTTPError):
            read_with_retry("https://example.org", forbidden, max_attempts=3,
                            sleep=lambda _: self.fail("Must not retry 403"))
        self.assertEqual(len(calls), 1)

    def test_strict_issuer_matching_bank_containment(self):
        companies = {"BANKINDIA": "Bank of India",
                     "UNIONBANK": "Union Bank of India"}
        self.assertEqual(match_issuers(
            "Union Bank of India (532477) quarterly results", "", companies,
            official_filing=True), ["UNIONBANK"])
        self.assertEqual(match_issuers(
            "Bank of India (532149) quarterly results", "", companies,
            official_filing=True), ["BANKINDIA"])
        self.assertEqual(set(match_issuers(
            "Union Bank of India and Bank of India issue a joint statement",
            "", companies, official_filing=False)), {"BANKINDIA", "UNIONBANK"})

    def test_macro_context_never_becomes_stock_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "sources.json"
            cfg.write_text(json.dumps({"sources": [{
                "name": "RBI official press releases",
                "url": "https://rbi.org.in/pressreleases_rss.xml",
                "kind": "rss", "provider": "RBI", "authority": "official",
                "market_context": True, "enabled": True
            }]}), encoding="utf-8")
            csv = root / "universe.csv"
            csv.write_text("Company Name,Symbol\\n" + "".join(
                f"Example Company {i:03d} Limited,SYM{i:03d}\\n"
                for i in range(500)), encoding="utf-8")
            def fixture(_src):
                return ({"source": "RBI official press releases", "status": "OK",
                         "kind": "rss", "authority": "official", "provider": "RBI",
                         "fetched_items": 1, "verified_in_window": 0,
                         "nifty500_matched": 0, "out_of_window": 0, "undated_items": 0},
                        [{"headline": "RBI announces policy liquidity guidance",
                          "summary": "Banking system liquidity",
                          "url": "https://rbi.org.in/releases/liquidity-20261109",
                          "raw_time": "Mon, 09 Nov 2026 20:00:00 +0530"}])
            with patch("news_collector.engine.fetch_one", fixture):
                data = run("2026-11-11", root / "data", config=cfg, universe_csv=csv)
            self.assertEqual(data["stored_macro_context_urls"], 1)
            self.assertEqual(data["stored_unique_matched_urls"], 0)
            self.assertIn("RBI", (root / "data/2026-11-11/macro_context.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()
