import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select

from news_collector.agent_intake import assignment, ingest_inbox, validate_report
from news_collector.archive import observation, replay, stage
from news_collector.broker_sources import listing_items
from news_collector.codex_research import allowed_url, publisher_article
from news_collector.continuous_worker import codex_slot
from news_collector.db_store import archive_batches, article_revisions, articles, sync_archive_batch
from news_collector.engine import IST
from news_collector.morning import run, select_candidates
from news_collector.headline_fallback import fill_from_headlines, headline_direction

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
        late = record(at(9, 6), at(8, 49), name="late")
        boundary = record(at(9, 5), at(9, 5), name="boundary")
        sync_archive_batch(self.db, batch("a", at(8, 58), good))
        sync_archive_batch(self.db, batch("b", at(9, 7), late, boundary))
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

        draft = run(self.db, clock=lambda: at(8, 59), analyst=analyst)
        self.assertEqual(draft, {"status": "DRAFT_SAVED", "draft_status": "READY", "signals": 1})
        report = run(self.db, clock=lambda: at(9, 5), analyst=analyst)
        self.assertEqual(report["status"], "READY", report["reason"])
        self.assertEqual(report["news_cutoff_at"], at(9, 5).isoformat())
        self.assertFalse(report["execution_enabled"])
        self.assertEqual(len(report["signals"]), 1)
        self.assertEqual(run(self.db, clock=lambda: at(9, 8), analyst=analyst), report)
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

    def test_external_cli_reports_without_search_proof_fail_closed(self):
        now = at(8, 50)
        job = assignment("claude-code", now)
        payload = {**job, "finished_at": now.isoformat(), "status": "RETRIEVED",
                   "urls": ["https://www.nseindia.com/filing"]}
        with self.assertRaises(ValueError):
            validate_report(payload, "claude-code", now)
        payload["status"] = "AUTH_REQUIRED"
        with self.assertRaises(ValueError):
            validate_report(payload, "claude-code", now)

    def test_cli_intake_stores_verified_provenance_and_failure_status(self):
        now = at(8, 50)
        with TemporaryDirectory() as folder:
            root = Path(folder)
            inbox = root / "inbox"
            for provider, status in [("claude-code", "RETRIEVED"), ("cursor-cli", "QUOTA_LIMIT")]:
                job = assignment(provider, now)
                target = inbox / provider
                target.mkdir(parents=True)
                payload = {**job, "status": status, "finished_at": now.isoformat()}
                if status == "RETRIEVED":
                    payload.update(urls=["https://www.nseindia.com/filing"],
                                   retrieval_event={"kind": "web_search", "id": "trace-1"})
                (target / (job["assignment_id"] + ".json")).write_text(
                    json.dumps(payload), encoding="utf-8")
            observed = record(now, at(8, 45))
            observed["discoverer"] = "claude-code"
            with patch("news_collector.agent_intake.verify_links",
                       return_value=("VERIFIED", [observed])) as verify:
                status = ingest_inbox(inbox, root, NIFTY, NIFTY, clock=lambda: now)
            self.assertEqual(status["claude-code"], "VERIFIED")
            self.assertEqual(status["cursor-cli"], "QUOTA_LIMIT")
            self.assertEqual(verify.call_args.kwargs["discoverer"], "claude-code")
            self.assertEqual(replay(self.db, root), 2)
            with self.db.connect() as conn:
                rows = conn.execute(select(archive_batches.c.coverage)).scalars().all()
            self.assertEqual({row["sources"][0]["status"] for row in rows},
                             {"VERIFIED", "QUOTA_LIMIT"})

    def test_morning_batches_review_all_frozen_evidence_and_source_status(self):
        template = record(at(8, 55), at(8, 50))
        items = [{**template, "evidence_id": f"evidence-{index}"}
                 for index in range(101)]
        calls = []

        def analyst(prompt, _schema, **_options):
            calls.append(prompt)
            return "OK", {"selections": []}

        status, _, _ = select_candidates(
            {"items": items, "recent_coverage": True, "source_health": {"qwen-code": "QUOTA_LIMIT"}},
            analyst=analyst)
        self.assertEqual(status, "NO_TRADE")
        self.assertEqual(len(calls), 3)
        self.assertNotIn('"evidence-100"', calls[0])
        self.assertIn('"evidence-100"', calls[1])
        self.assertIn('"evidence-100"', calls[2])
        self.assertIn("QUOTA_LIMIT", calls[2])

    def test_finalization_reranks_when_verified_evidence_changes(self):
        early = record(at(8, 40), at(8, 35))
        sync_archive_batch(self.db, batch("a", at(8, 45), early))

        def analyst(_prompt, _schema, **_options):
            return "OK", {"selections": []}

        draft = run(self.db, clock=lambda: at(8, 55), analyst=analyst)
        self.assertEqual(draft["draft_status"], "NO_TRADE")
        extra = record(at(9, 3), at(9, 2), name="last-minute")
        sync_archive_batch(self.db, batch("b", at(9, 4), extra))
        with patch("news_collector.morning.select_candidates",
                   return_value=("NO_TRADE", "No qualified stock", [])) as call:
            report = run(self.db, clock=lambda: at(9, 5))
            self.assertTrue(any("last-minute.pdf" in item["url"]
                                for item in call.call_args.args[0]["items"]))
        self.assertEqual(report["status"], "NO_TRADE")
        self.assertEqual(report["signals"], [])

    def test_late_draft_cannot_become_locked_watchlist(self):
        sync_archive_batch(self.db, batch("a", at(8, 53), record(at(8, 51), at(8, 50))))
        clock = iter([at(8, 55), at(9, 5)]).__next__
        result = run(self.db, clock=clock, analyst=lambda *_a, **_k: ("OK", {"selections": []}))
        self.assertEqual(result["status"], "DRAFT_FINISHED_AFTER_LOCK")
        report = run(self.db, clock=lambda: at(9, 10))
        self.assertEqual(report["status"], "UNAVAILABLE")

    def test_codex_discovery_stays_on_half_hour_slots(self):
        self.assertEqual(codex_slot(at(8, 0), 48), 16)
        self.assertIsNone(codex_slot(at(8, 10), 48))
        self.assertIsNone(codex_slot(at(8, 20), 48))
        self.assertEqual(codex_slot(at(8, 30), 48), 17)
        self.assertEqual(codex_slot(at(9, 0), 48), 18)
        self.assertIsNone(codex_slot(at(8, 30), 0))

    def test_finalization_retry_uses_same_cutoff_and_locks_only_once(self):
        sync_archive_batch(self.db, batch("a", at(8, 53), record(at(8, 51), at(8, 50))))
        with patch("news_collector.morning.select_candidates",
                   return_value=("UNAVAILABLE", "Temporary quota issue", [])):
            result = run(self.db, clock=lambda: at(9, 5))
        self.assertEqual(result["status"], "REVIEW_PENDING")
        late = record(at(9, 6), at(9, 4), name="post-cutoff-verification")
        sync_archive_batch(self.db, batch("b", at(9, 7), late))
        with patch("news_collector.morning.select_candidates",
                   return_value=("NO_TRADE", "No qualified stock", [])) as call:
            report = run(self.db, clock=lambda: at(9, 8))
            self.assertEqual(len(call.call_args.args[0]["items"]), 1)
        self.assertEqual(report["generated_at"], at(9, 8).isoformat())
        self.assertEqual(run(self.db, clock=lambda: at(9, 10)), report)
        self.assertEqual(run(self.db, clock=lambda: at(9, 12))["status"],
                         "OUTSIDE_RESEARCH_WINDOW")

    def test_nine_am_is_still_a_draft_and_exchange_holiday_skips(self):
        sync_archive_batch(self.db, batch("a", at(8, 59), record(at(8, 57), at(8, 56))))
        with patch("news_collector.morning.select_candidates",
                   return_value=("NO_TRADE", "No qualified stock", [])) as call:
            self.assertEqual(run(self.db, clock=lambda: at(9, 5, day=10)), {"status": "CLOSED"})
            call.assert_not_called()
            self.assertEqual(run(self.db, clock=lambda: at(9, 0))["status"], "DRAFT_SAVED")

    def test_analysis_finishing_at_hard_deadline_cannot_lock(self):
        sync_archive_batch(self.db, batch("a", at(9, 4), record(at(9, 3), at(9, 2))))
        clock = iter([at(9, 8), at(9, 12)]).__next__
        with patch("news_collector.morning.select_candidates",
                   return_value=("NO_TRADE", "No qualified stock", [])):
            self.assertEqual(run(self.db, clock=clock), {"status": "FINALIZATION_DEADLINE_ELAPSED"})


    def test_headline_fallback_fills_five_each_without_repeating_symbols(self):
        rows = []
        for side, metric in (("LONG", "net profit rises"), ("SHORT", "net profit falls")):
            for index in range(6):
                symbol = f"{side}{index}"
                rows.append({
                    "verified_origin": True, "nifty_symbols": [symbol],
                    "headline": f"{symbol} quarterly {metric} 20 percent",
                    "published_at": at(8, 30 + index).isoformat(),
                    "url": f"https://example.com/{symbol}",
                })
        reviewed = {"symbol": "LONG5", "side": "LONG", "rank": 1}
        output = fill_from_headlines({"items": rows, "recent_coverage": False, "recent_universe": True}, [reviewed])
        self.assertEqual(output[0], reviewed)
        self.assertEqual(len({row["symbol"] for row in output}), 10)
        for side in ("LONG", "SHORT"):
            self.assertEqual([row["rank"] for row in output if row["side"] == side],
                             [1, 2, 3, 4, 5])

    def test_fallback_rejects_unknown_and_conflicting_news(self):
        row = {"verified_origin": True, "nifty_symbols": ["KNOWN"],
               "headline": "Known Company net profit falls while shares rise",
               "published_at": at(8, 52).isoformat(), "url": "https://example.com/one"}
        self.assertEqual(headline_direction(row["headline"]), ("SHORT", 3))
        self.assertIsNone(headline_direction("Known revenue rises but net profit falls"))
        output = fill_from_headlines({"recent_coverage": True, "items": [
            row, {**row, "headline": "Known Company net profit rises"},
            {**row, "nifty_symbols": []}, {**row, "nifty_symbols": ["ONE", "TWO"]},
            {**row, "nifty_symbols": ["UNVERIFIED"], "verified_origin": False},
        ]}, [])
        self.assertEqual(output, [])

    def test_unavailable_review_locks_verified_headline_fallback(self):
        news = record(at(8, 57), at(8, 56), headline="Thermax Limited net profit rises 25 percent")
        sync_archive_batch(self.db, batch("a", at(8, 59), news))
        with patch("news_collector.morning.select_candidates",
                   return_value=("UNAVAILABLE", "Temporary quota issue", [])):
            pending = run(self.db, clock=lambda: at(9, 5))
        self.assertEqual(pending["status"], "REVIEW_PENDING")
        report = run(self.db, clock=lambda: at(9, 10))
        self.assertEqual(report["status"], "READY", report["reason"])
        self.assertEqual(report["signals"][0]["symbol"], "THERMAX")
        self.assertIn("fallback", report["signals"][0]["reason"])
        self.assertFalse(report["execution_enabled"])


    def test_fallback_can_use_explicit_direction_in_verified_excerpt(self):
        row = {"verified_origin": True, "nifty_symbols": ["KNOWN"],
               "headline": "Known company files quarterly results",
               "summary": "Profit after tax (PAT) of 21.97 crore in Q2 FY27 as against "
                          "49.19 crore in Q2 FY26, a reduction of 55.3 per cent year-on-year.",
               "published_at": at(8, 52).isoformat(), "url": "https://example.com/news"}
        snapshot = {"items": [row], "recent_coverage": True}
        output = fill_from_headlines(snapshot, [])
        self.assertEqual(output[0]["side"], "SHORT")
        self.assertEqual(output[0]["news_summary"], row["summary"])
        row["headline"] = "Known net profit rises"
        self.assertEqual(fill_from_headlines(snapshot, []), [])

    def test_publisher_structured_data_uses_only_matching_original_publication(self):
        page = b"""
            <script type="application/ld+json">{"@graph":[
              {"@type":"NewsArticle","url":"https://example.com/other",
               "headline":"Unrelated headline","datePublished":"2026-11-11T08:45:00+05:30"},
              {"@type":"NewsArticle","mainEntityOfPage":{"@id":"https://example.com/actual"},
               "headline":"Company net profit rises","datePublished":"2026-11-11T08:30:00+05:30",
               "dateModified":"2026-11-11T08:55:00+05:30"}]}</script>
        """
        from unittest.mock import MagicMock
        with patch("news_collector.codex_research.requests.get") as get:
            response = MagicMock(status_code=200, headers={"Content-Type": "text/html"})
            response.iter_content.return_value = [page]
            get.return_value.__enter__.return_value = response
            article = publisher_article("https://example.com/actual")
        self.assertEqual(article["headline"], "Company net profit rises")
        self.assertEqual(article["raw_time"], "2026-11-11T08:30:00+05:30")
