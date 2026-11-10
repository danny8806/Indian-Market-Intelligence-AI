from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select

from news_collector.archive import observation, replay, stage
from news_collector.broker_sources import listing_items
from news_collector.codex_research import allowed_url
from news_collector.db_store import article_revisions, articles, sync_archive_batch
from news_collector.engine import IST
from news_collector.morning import run

FEED = {"provider": "NSE", "kind": "rss", "authority": "official",
        "url": "https://nsearchives.nseindia.com/feed.xml", "name": "NSE filings"}
NIFTY = {"THERMAX": "Thermax Limited"}


def at(hour, minute, day=11):
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


def record(observed, publication, *, headline="Thermax Limited profit announcement",
           name="one"):
    return observation({
        "url": f"https://nsearchives.nseindia.com/{name}.pdf", "headline": headline,
        "raw_time": publication.isoformat(), "original_time": True,
    }, FEED, observed, NIFTY, NIFTY, discoverer="python")


def batch(identity, checked, *records):
    return {"batch_id": identity, "generated_at": checked.isoformat(), "records": records,
            "sources_with_items": 1, "nifty_count": 500}


class NewsIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.db = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.db.dispose)

    def test_daytime_archive_dedupes_and_keeps_corrections(self):
        first = record(at(13, 40), at(13, 31))
        repeat = record(at(13, 50), at(13, 31))
        revised = record(at(14, 10), at(13, 31), headline="Thermax Limited amended results")
        self.assertTrue(sync_archive_batch(self.db, batch("a", at(13, 42), first)))
        self.assertFalse(sync_archive_batch(self.db, batch("a", at(13, 42), first)))
        sync_archive_batch(self.db, batch("b", at(14, 12), repeat, revised))
        with self.db.connect() as conn:
            self.assertEqual(len(conn.execute(select(articles)).all()), 1)
            self.assertEqual(len(conn.execute(select(article_revisions)).all()), 2)

    def test_failed_db_write_retains_spool_then_replays_once(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            file = stage(root, batch("b", at(8, 59), record(at(8, 55), at(8, 50))))
            with patch("news_collector.db_store.sync_archive_batch", side_effect=OSError):
                with self.assertRaises(OSError):
                    replay(self.db, root)
            self.assertTrue(file.is_file())
            self.assertEqual(replay(self.db, root), 1)
            self.assertFalse(file.exists())
            self.assertEqual(replay(self.db, root), 0)

    def test_snapshot_excludes_late_verification_and_is_immutable(self):
        good = record(at(8, 55), at(8, 50))
        late = record(at(9, 1), at(8, 49), name="late")
        boundary = record(at(9, 0), at(9, 0), name="boundary")
        sync_archive_batch(self.db, batch("a", at(8, 58), good))
        sync_archive_batch(self.db, batch("b", at(9, 2), late, boundary))
        calls = []
        with self.db.connect() as conn:
            identity = conn.execute(select(article_revisions.c.id).where(
                article_revisions.c.article_id == good["id"])).scalar_one()

        def analyst(prompt, schema, **options):
            self.assertNotIn("late.pdf", prompt)
            self.assertNotIn("boundary.pdf", prompt)
            self.assertFalse(options["search"])
            calls.append(prompt)
            return "OK", {"selections": [
                {"symbol": "THERMAX", "side": "LONG", "reason": "Higher profits than expected",
                 "news_summary": "Thermax announced higher profits", "evidence_ids": [identity]}
            ]}

        report = run(self.db, clock=lambda: at(9, 3), analyst=analyst)
        self.assertEqual(report["status"], "READY", report["reason"])
        self.assertFalse(report["execution_enabled"])
        self.assertEqual(len(report["signals"]), 1)
        self.assertEqual(run(self.db, clock=lambda: at(9, 4), analyst=analyst), report)
        self.assertEqual(len(calls), 2)

    def test_bse_only_scrip_identity_is_archived_without_nifty_qualification(self):
        feed = {**FEED, "provider": "BSE", "url": "https://www.bseindia.com/feed.xml"}
        row = observation({
            "url": "https://www.bseindia.com/filing.pdf",
            "headline": "Results announced", "raw_time": "11-Nov-2026 08:50:00",
            "scrip_code": "500123", "original_time": True,
        }, feed, at(8, 55), NIFTY, NIFTY, discoverer="python")
        self.assertEqual(row["symbols"], ["BSE:500123"])
        self.assertEqual(row["nifty_symbols"], [])
        self.assertTrue(row["verified_origin"])

    def test_discovery_host_boundary(self):
        known = {"www.nseindia.com"}
        self.assertTrue(allowed_url("https://www.nseindia.com/filing", known))
        self.assertFalse(allowed_url("https://www.nseindia.com@local/filing", known))
        self.assertFalse(allowed_url("https://www.nseindia.com:444/filing", known))

    def test_broker_discovery_excludes_navigation_and_external_links(self):
        source = {
            "url": "https://broker.example/market-news", "provider": "BROKER",
            "authority": "secondary", "kind": "broker_html", "name": "Broker",
            "article_path": r"/stocks/[^/]+/news", "shared_link": True,
            "headline_selector": "p",
        }
        html = b"""<a href="/about"><p>Broker Navigation and Account</p></a>
        <a href="https://elsewhere.example/stocks/thermax/news"><p>Not from broker</p></a>
        <a href="/stocks/thermax/news"><p>Thermax Limited raised its outlook</p><i>2 hours ago</i></a>
        <a href="/stocks/thermax/news"><p>Thermax Limited announced earnings</p><i>today</i></a>"""
        items = listing_items(html, source)
        self.assertEqual(len(items), 2)
        rows = [observation(item, source, at(8, 55), NIFTY, NIFTY,
                            discoverer="python") for item in items]
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])
        self.assertTrue(all(row["published_at"] is None and not row["verified_origin"]
                            for row in rows))

    def test_disallowed_broker_listing_is_never_fetched(self):
        from news_collector.engine import fetch_one

        source = {**FEED, "kind": "broker_html"}
        with patch("news_collector.engine.allowed_by_robots", return_value=(False, "restricted")):
            with patch("news_collector.engine.read_with_retry") as fetch:
                stats, items = fetch_one(source)
        self.assertEqual(stats["status"], "BLOCKED_ROBOTS")
        self.assertEqual(items, [])
        fetch.assert_not_called()

    def test_dhan_public_cards_use_the_deployed_selectors(self):
        import json
        from news_collector.engine import ROOT

        sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["sources"]
        dhan = next(source for source in sources if source["name"] == "Dhan Live Stock News")
        html = b"""<div class="w-full"><p>Unrelated price</p></div>
        <div class="w-full"><div><p>Thermax Limited posted its quarterly results</p></div>
        <div><p id="marketnewsdivweb1">Revenue changed.</p></div></div>"""
        items = listing_items(html, dhan)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["summary"], "Revenue changed.")
        self.assertTrue(items[0]["shared_broker_link"])
