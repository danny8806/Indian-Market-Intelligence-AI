"""Deterministic tests for overnight news ingestion: no network and no trading."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from news_collector.engine import (
    build_record, canonical_url, default_session, html_items, merge_record,
    norm_name, parse_timestamp, parse_universe_csv, rss_items, run, universe_match,
    window_for,
)
IST = ZoneInfo("Asia/Kolkata")
UNIVERSE = {f"SYM{i:03d}": f"Example Company {i:03d} Limited" for i in range(500)}
UNIVERSE["THERMAX"] = "Thermax Limited"
UNIVERSE["TITAN"] = "Titan Company Limited"


def sample_source(provider="NSE", kind="rss"):
    return {"name": "Test NSE", "provider": provider, "authority": "official",
            "url": "https://example.org/feed.xml", "kind": kind, "enabled": True}


def sample_item(title="Thermax Limited", when="05-Nov-2026 18:02:00", url="https://example.org/a"):
    return {"headline": title, "summary": "Quarterly results profit fell despite revenue growth",
            "raw_time": when, "url": url}


class CollectorUnitTests(unittest.TestCase):
    def test_official_ist_date_format(self):
        self.assertEqual(parse_timestamp("05-Nov-2026 18:02:00", exchange="NSE").hour, 18)
        self.assertEqual(parse_timestamp("05-Nov-2026 18:02:00", exchange="BSE").hour, 18)
        self.assertIsNone(parse_timestamp("05-Nov-2026 18:02:00", exchange="MEDIA"))

    def test_rfc_utc_ist_and_missing_clock(self):
        self.assertEqual(parse_timestamp("Thu, 05 Nov 2026 18:02:00 +0530").hour, 18)
        self.assertEqual(parse_timestamp("2026-11-05T12:32:00Z").hour, 18)
        self.assertIsNone(parse_timestamp("06 Nov, 2026 +0530"))

    def test_cutoff_end_exclusive(self):
        start, end = window_for("2026-11-06")
        a = sample_source()
        status, row = build_record(sample_item(when="05-Nov-2026 15:00:00"), a, UNIVERSE, start, end, start)
        self.assertEqual(status, "IN_WINDOW")
        self.assertEqual(row["symbols"], ["THERMAX"])
        for when in ["05-Nov-2026 14:59:59", "06-Nov-2026 09:00:00"]:
            state, _ = build_record(sample_item(when=when), a, UNIVERSE, start, end, start)
            self.assertEqual(state, "OUT_OF_WINDOW")

    def test_weekend_window(self):
        start, end = window_for("2026-11-09")
        self.assertEqual(start.isoformat(), "2026-11-06T15:00:00+05:30")
        self.assertEqual(default_session(datetime(2026, 11, 6, 16, tzinfo=IST)), "2026-11-09")
        self.assertEqual(default_session(datetime(2026, 11, 7, 10, tzinfo=IST)), "2026-11-09")

    def test_verified_nse_holiday_skipped(self):
        self.assertEqual(default_session(datetime(2026, 11, 10, 8, tzinfo=IST)), "2026-11-11")
        with self.assertRaisesRegex(ValueError, "not a known regular NSE session"):
            window_for("2026-11-10")
        self.assertEqual(window_for("2026-11-11")[0].date().isoformat(), "2026-11-09")

    def test_universe_fail_closed(self):
        self.assertEqual(universe_match("Thermax Limited", "", {}), [])
        self.assertEqual(universe_match("Thermax Limited", "", UNIVERSE), ["THERMAX"])
        self.assertEqual(universe_match("Unrelated company", "", UNIVERSE), [])

    def test_csv_validation(self):
        text = "Company Name,Industry,Symbol,Series,ISIN Code\n"
        text += "".join(f"Example Company {i:03d} Limited,Test,SYM{i:03d},EQ,INE000000001\n" for i in range(500))
        parsed = parse_universe_csv(text)
        self.assertEqual(len(parsed), 500)
        with self.assertRaises(ValueError):
            parse_universe_csv("Company Name,Symbol\nFoo,FOO\n")

    def test_rss_nse(self):
        raw = b"<rss><channel><item><title>Thermax Limited</title><link>https://example.org/a</link>" \
              b"<description>Quarterly results</description><pubDate>05-Nov-2026 18:02:00</pubDate>" \
              b"</item></channel></rss>"
        items = rss_items(raw, sample_source())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["raw_time"], "05-Nov-2026 18:02:00")

    def test_google_news_discovery_timestamp_is_not_original_publication(self):
        source = {**sample_source(provider="MEDIA"), "timestamp_provenance": "discovery"}
        xml = b"""<rss><channel><item><title>Thermax Limited quarterly results announced</title>
        <link>https://news.example.org/thermax</link>
        <pubDate>Mon, 09 Nov 2026 18:30:00 +0530</pubDate>
        </item></channel></rss>"""
        rows = rss_items(xml, source)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw_time"], "")

    def test_html_without_time_is_unverified(self):
        raw = b'<html><article><h2><a href="/test">Thermax quarterly results announced</a></h2></article></html>'
        items = html_items(raw, sample_source(kind="html"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["raw_time"], "")

    def test_event_url_dedupe(self):
        rows = {}
        start, end = window_for("2026-11-06")
        first = sample_item(url="https://example.org/a?utm_source=hi")
        second = sample_item(url="https://example.org/a?utm_source=other")
        _, a = build_record(first, sample_source(), UNIVERSE, start, end, start)
        _, b = build_record(second, {**sample_source(), "name": "Other NSE"}, UNIVERSE, start, end, start)
        merge_record(rows, a)
        merge_record(rows, b)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(next(iter(rows.values()))["sources"]), 2)

    def test_exchange_only_primary_issuer_not_mentioned_issuer(self):
        begin, end = window_for("2026-11-06")
        item = sample_item()
        item["summary"] = "Thermax Limited filing mentions Titan Company Limited"
        state, row = build_record(item, sample_source(), UNIVERSE, begin, end, begin)
        self.assertEqual(state, "IN_WINDOW")
        self.assertEqual(row["symbols"], ["THERMAX"])

    def test_undated_never_promoted(self):
        begin, end = window_for("2026-11-06")
        state, event = build_record(sample_item(when=""), sample_source(), UNIVERSE, begin, end, begin)
        self.assertEqual(state, "UNVERIFIED_TIMESTAMP")
        self.assertIsNone(event["published_at"])

    def test_pipeline_persistence_with_mock_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = base / "sources.json"
            config.write_text('{"sources": [{"name":"Test NSE","kind":"rss","provider":"NSE","authority":"official",'
                              '"url":"https://example.org/feed.xml","enabled":true}]}')
            universe = base / "index.csv"
            universe.write_text("Company Name,Symbol\n" +
                                "".join(f"Example Company {i:03d} Limited,SYM{i:03d}\n" for i in range(500)) +
                                "Thermax Limited,THERMAX\n")
            def fake_fetch(_):
                return ({"source":"Test NSE", "kind":"rss", "provider":"NSE", "authority":"official",
                         "status":"OK", "fetched_items":2,"verified_in_window":0,"nifty500_matched":0,
                         "undated_items":0,"out_of_window":0},
                        [sample_item(), sample_item(url="https://example.org/a?utm_source=x")])
            with patch("news_collector.engine.fetch_one", fake_fetch):
                report = run("2026-11-06", base/"data", config=config, universe_csv=universe)
                again = run("2026-11-06", base/"data", config=config, universe_csv=universe)
            self.assertEqual(report["stored_unique_matched_urls"], 1)
            self.assertEqual(again["stored_unique_matched_urls"], 1)
            self.assertTrue((base/"data/2026-11-06/coverage.json").exists())
            self.assertEqual(len((base/"data/2026-11-06/polls.jsonl").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
