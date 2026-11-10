import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select

from news_collector.agent_intake import (ASSIGNMENTS, assignment, ingest_inbox,
                                         validate_report)
from news_collector.archive import observation, replay, stage
from news_collector.broker_sources import listing_items
from news_collector.codex_research import allowed_url, publisher_article
from news_collector.continuous_worker import codex_slot
from news_collector.db_store import (archive_batches, article_revisions, articles,
                                     morning_reports, raw_documents, runs, source_checks,
                                     source_cursors, sync_archive_batch)
from news_collector.engine import IST
from news_collector.morning import review_candidates, run, select_candidates
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

    def test_archive_batch_updates_source_ledger_cursors_raw_docs_and_runs(self):
        checked = at(13, 42)
        current = batch("ledger", checked, record(at(13, 40), at(13, 31)))
        current.update({
            "session": "2026-11-11", "sources_configured": 2,
            "sources": [
                {"source": "NSE filings", "kind": "rss", "status": "OK",
                 "fetched_items": 4, "latest_raw_time": "2026-11-11T13:30:00+05:30",
                 "latest_item_url": "https://nsearchives.nseindia.com/one.pdf"},
                {"source": "OpenCode CLI", "kind": "ai_cli", "status": "QUOTA_LIMIT",
                 "fetched_items": 0, "error": "Free usage limit reached",
                 "model": "opencode/deepseek-v4.1-flash-free"},
            ],
            "raw_documents": [{
                "id": "raw-1", "source": "NSE filings",
                "url": "https://nsearchives.nseindia.com/feed.xml",
                "content_type": "application/xml", "sha256": "a" * 64,
                "byte_size": 120, "storage_path": "raw/2026-11-11/feed.gz",
                "captured_at": checked.isoformat(), "provider": "NSE",
                "authority": "official", "kind": "rss", "status": "OK",
                "truncated": False,
            }],
        })
        self.assertTrue(sync_archive_batch(self.db, current))
        self.assertFalse(sync_archive_batch(self.db, current))
        with self.db.connect() as conn:
            checks = {row.source: row for row in conn.execute(select(source_checks)).all()}
            self.assertEqual(checks["OpenCode CLI"].status, "QUOTA_LIMIT")
            self.assertEqual(checks["NSE filings"].fetched_items, 4)
            cursor = conn.execute(select(source_cursors).where(
                source_cursors.c.source == "NSE filings")).one()
            self.assertEqual(cursor.consecutive_failures, 0)
            self.assertEqual(cursor.latest_item_url,
                             "https://nsearchives.nseindia.com/one.pdf")
            self.assertEqual(len(conn.execute(select(runs)).all()), 1)
            raw = conn.execute(select(raw_documents)).one()
            self.assertEqual(raw.storage_path, "raw/2026-11-11/feed.gz")

    def test_collect_batch_captures_bounded_raw_responses_and_prunes(self):
        import gzip
        from news_collector.archive import collect_batch, prune_raw

        with TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / "sources.json"
            config.write_text(json.dumps({"sources": [
                {"name": "NSE A", "url": "https://nsearchives.nseindia.com/a.xml",
                 "kind": "rss", "provider": "NSE", "authority": "official",
                 "enabled": True},
                {"name": "NSE B", "url": "https://nsearchives.nseindia.com/b.xml",
                 "kind": "rss", "provider": "NSE", "authority": "official",
                 "enabled": True},
            ]}), encoding="utf-8")

            def fake_fetch(source, *, raw_sink=None):
                raw_sink(source, b"<rss><item>Thermax net profit rises</item></rss>", {})
                return ({"source": source["name"], "kind": "rss",
                         "authority": "official", "provider": "NSE",
                         "url": source["url"], "status": "OK", "fetched_items": 1},
                        [{"url": "https://nsearchives.nseindia.com/filing.pdf",
                          "headline": "Thermax Limited net profit rises", "summary": "",
                          "raw_time": "11-Nov-2026 08:50:00", "original_time": True}])

            with patch("news_collector.archive.load_universes",
                       return_value=(NIFTY, NIFTY, True)), \
                 patch("news_collector.archive.fetch_one", side_effect=fake_fetch):
                batch, _, _ = collect_batch(root, clock=lambda: at(13, 0), config=config)

            self.assertEqual(len(batch["raw_documents"]), 2)
            self.assertEqual({doc["status"] for doc in batch["raw_documents"]}, {"OK"})
            self.assertEqual({doc["source"] for doc in batch["raw_documents"]},
                             {"NSE A", "NSE B"})
            for doc in batch["raw_documents"]:
                path = root / doc["storage_path"]
                self.assertTrue(path.is_file())
                with gzip.open(path, "rb") as handle:
                    self.assertIn(b"Thermax", handle.read())

            old = root / "raw" / "2026-01-01"
            old.mkdir(parents=True)
            (old / "x.gz").write_bytes(b"x")
            self.assertEqual(prune_raw(root, days=30, today=at(13, 0).date()), 1)
            self.assertFalse(old.exists())

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
            calls.append("analyst")
            return "OK", {"selections": [
                {"symbol": "THERMAX", "side": "LONG", "reason": "Higher profits than expected",
                 "news_summary": "Thermax announced higher profits", "evidence_ids": [identity]}
            ]}

        def critic(prompt, schema, **options):
            self.assertNotIn("late.pdf", prompt)
            self.assertNotIn("boundary.pdf", prompt)
            self.assertFalse(options["search"])
            calls.append("critic")
            return "OK", {"selections": [
                {"symbol": "THERMAX", "side": "LONG", "reason": "Higher profits than expected",
                 "news_summary": "Thermax announced higher profits", "evidence_ids": [identity]}
            ]}

        draft = run(self.db, clock=lambda: at(8, 59), analyst=analyst)
        self.assertEqual(draft, {"status": "DRAFT_SAVED", "draft_status": "READY", "signals": 1})
        report = run(self.db, clock=lambda: at(9, 5), analyst=analyst, critic=critic)
        self.assertEqual(report["status"], "READY", report["reason"])
        self.assertEqual(report["news_cutoff_at"], at(9, 0).isoformat())
        self.assertFalse(report["execution_enabled"])
        self.assertEqual(len(report["signals"]), 1)
        self.assertEqual(run(self.db, clock=lambda: at(9, 8), analyst=analyst, critic=critic), report)
        self.assertEqual(calls, ["analyst", "critic"])

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

    def test_news18_listing_uses_publisher_timestamp_verification(self):
        from news_collector.engine import ROOT

        sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["sources"]
        news18 = next(source for source in sources if source["name"] == "News18 Business")
        self.assertEqual(news18["kind"], "html")
        self.assertTrue(news18["verify_article"])

    def test_only_listing_sources_may_fetch_publisher_articles(self):
        from news_collector.engine import ROOT

        sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["sources"]
        for source in sources:
            if source.get("verify_article"):
                self.assertIn(source["kind"], {"html", "broker_html"}, source["name"])

    def test_every_external_provider_has_a_valid_schedule(self):
        now = at(8, 50)
        for provider in ASSIGNMENTS:
            with self.subTest(provider=provider):
                job = assignment(provider, now)
                self.assertEqual(job["provider"], provider)
                self.assertIn("Search independently", job["prompt"])
                self.assertRegex(job["assignment_id"], rf"^{provider}-\d{{8}}T\d{{4}}$")

    def test_gemini_lane_requires_independent_search_evidence(self):
        now = at(8, 50)
        job = assignment("gemini", now)
        self.assertIn("Google web search", job["prompt"])
        payload = {**job, "finished_at": now.isoformat(), "status": "RETRIEVED",
                   "urls": ["https://www.nseindia.com/filing"]}
        with self.assertRaises(ValueError):
            validate_report(payload, "gemini", now)
        payload["retrieval_event"] = {"kind": "web_search", "id": "gemini-trace-1"}
        report = validate_report(payload, "gemini", now)
        self.assertEqual(report["status"], "RETRIEVED")
        self.assertEqual(report["retrieval_event"]["id"], "gemini-trace-1")

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
        analyst_calls = []

        def analyst(prompt, _schema, **_options):
            analyst_calls.append(prompt)
            return "OK", {"selections": []}

        status, _, shortlist = select_candidates(
            {"items": items, "recent_coverage": True, "source_health": {"qwen-code": "QUOTA_LIMIT"}},
            analyst=analyst)
        self.assertEqual(status, "NO_TRADE")
        self.assertEqual(shortlist, [])
        self.assertEqual(len(analyst_calls), 2)
        self.assertNotIn('"evidence-100"', analyst_calls[0])
        self.assertIn('"evidence-100"', analyst_calls[1])

        critic_calls = []

        def critic(prompt, _schema, **_options):
            critic_calls.append(prompt)
            self.assertIn('"evidence-100"', prompt)
            self.assertIn("QUOTA_LIMIT", prompt)
            return "OK", {"selections": []}

        status, _, selected, audit = review_candidates(
            {"items": items, "recent_coverage": True,
             "source_health": {"qwen-code": "QUOTA_LIMIT"}},
            [{"symbol": "THERMAX", "side": "LONG", "reason": "Supported",
              "news_summary": "Supported by evidence", "evidence_ids": ["evidence-0"]}],
            critic=critic)
        self.assertEqual(status, "NO_TRADE")
        self.assertEqual(selected, [])
        self.assertEqual(audit["status"], "REJECTED_ALL")

    def test_finalization_reuses_only_reviewed_symbols_with_unchanged_evidence(self):
        early = record(at(8, 40), at(8, 35))
        sync_archive_batch(self.db, batch("a", at(8, 45), early))
        with self.db.connect() as conn:
            first_id = conn.execute(select(article_revisions.c.id).where(
                article_revisions.c.article_id == early["id"])).scalar_one()
        shortlist = [{
            "symbol": "THERMAX", "side": "LONG",
            "reason": "Completed analyst review supports the candidate",
            "news_summary": "Existing verified report supported the candidate",
            "evidence_ids": [first_id],
        }]

        def echo_critic(_prompt, _schema, **_options):
            return "OK", {"selections": shortlist}

        with patch("news_collector.morning.select_candidates",
                   return_value=("READY", "Shortlist", shortlist)) as call:
            self.assertEqual(run(self.db, clock=lambda: at(8, 55))["status"], "DRAFT_SAVED")
        call.assert_called_once()
        extra = record(at(8, 58), at(8, 57), name="last-minute",
                       headline="Other net profit rises 20 percent")
        extra.update(symbols=["OTHER"], nifty_symbols=["OTHER"])
        sync_archive_batch(self.db, batch("b", at(8, 59), extra))
        with patch("news_collector.morning.select_candidates") as call:
            report = run(self.db, clock=lambda: at(9, 5), critic=echo_critic)
            call.assert_not_called()
        self.assertEqual(report["signals"][0]["symbol"], "THERMAX")
        self.assertEqual(report["signals"][0]["rank"], 1)
        self.assertEqual(report["signals"][1]["symbol"], "OTHER")
        self.assertEqual(report["signals"][1]["rank"], 2)
        self.assertNotIn("_reviewed_evidence", report["signals"][0])
        with self.db.connect() as conn:
            frozen = conn.execute(select(morning_reports.c.evidence)).scalar_one()
        self.assertEqual(frozen["review_audit"]["critic"]["status"], "OK")
        self.assertFalse(frozen["review_audit"]["critic"]["independent"])
        self.assertIn("critic=echo_critic:OK", report["reason"])

    def test_critic_can_reject_stale_pick_and_fallback_uses_current_evidence(self):
        early = record(at(8, 40), at(8, 35))
        sync_archive_batch(self.db, batch("a", at(8, 45), early))
        with self.db.connect() as conn:
            first_id = conn.execute(select(article_revisions.c.id).where(
                article_revisions.c.article_id == early["id"])).scalar_one()
        shortlist = [{
            "symbol": "THERMAX", "side": "LONG", "reason": "Initial analyst view",
            "news_summary": "Initial analyst summary", "evidence_ids": [first_id],
        }]
        with patch("news_collector.morning.select_candidates",
                   return_value=("READY", "Shortlist", shortlist)):
            run(self.db, clock=lambda: at(8, 55))
        contrary = record(at(8, 58), at(8, 57), name="contrary",
                          headline="Thermax Limited net profit falls 25 percent")
        sync_archive_batch(self.db, batch("b", at(8, 59), contrary))
        with patch("news_collector.morning.select_candidates") as call:
            report = run(self.db, clock=lambda: at(9, 5),
                         critic=lambda *_a, **_k: ("OK", {"selections": []}))
            call.assert_not_called()
        self.assertEqual([(row["symbol"], row["side"]) for row in report["signals"]],
                         [("THERMAX", "SHORT")])
        self.assertIn("fallback", report["signals"][0]["reason"])

    def test_draft_started_before_cutoff_can_finish_after_cutoff(self):
        news = record(at(8, 51), at(8, 50))
        sync_archive_batch(self.db, batch("a", at(8, 53), news))
        with self.db.connect() as conn:
            first_id = conn.execute(select(article_revisions.c.id).where(
                article_revisions.c.article_id == news["id"])).scalar_one()
        shortlist = [{
            "symbol": "THERMAX", "side": "LONG",
            "reason": "Pre-cutoff evidence supports the candidate",
            "news_summary": "Pre-cutoff evidence supported the candidate",
            "evidence_ids": [first_id],
        }]
        clock = iter([at(8, 55), at(9, 2)]).__next__
        result = run(self.db, clock=clock,
                     analyst=lambda *_a, **_k: ("OK", {"selections": shortlist}))
        self.assertEqual(result, {"status": "DRAFT_SAVED", "draft_status": "READY", "signals": 1})
        report = run(self.db, clock=lambda: at(9, 10),
                     critic=lambda *_a, **_k: ("OK", {"selections": shortlist}))
        self.assertEqual(report["status"], "READY", report["reason"])
        self.assertEqual(report["news_cutoff_at"], at(9, 0).isoformat())

    def test_post_cutoff_evidence_cannot_enter_review(self):
        pre = record(at(8, 55), at(8, 50))
        snapshot = {"items": [{**pre, "evidence_id": "pre"}],
                    "recent_coverage": True, "source_health": {}}
        shortlist = [{
            "symbol": "THERMAX", "side": "LONG",
            "reason": "Post-cutoff evidence should be rejected",
            "news_summary": "Post-cutoff evidence should be rejected",
            "evidence_ids": ["post-cutoff"],
        }]
        status, _, selected, audit = review_candidates(
            snapshot, shortlist,
            critic=lambda *_a, **_k: ("OK", {"selections": shortlist}))
        self.assertEqual(status, "NO_TRADE")
        self.assertEqual(selected, [])
        self.assertEqual(audit["status"], "REJECTED_ALL")

    def test_codex_discovery_stays_on_half_hour_slots_outside_reserved_review(self):
        self.assertEqual(codex_slot(at(7, 0), 48), 14)
        self.assertIsNone(codex_slot(at(7, 10), 48))
        self.assertIsNone(codex_slot(at(7, 20), 48))
        self.assertEqual(codex_slot(at(7, 30), 48), 15)
        for hour, minute in [(8, 0), (8, 30), (9, 0)]:
            self.assertIsNone(codex_slot(at(hour, minute), 48))
        self.assertEqual(codex_slot(at(9, 30), 48), 19)
        self.assertEqual(codex_slot(at(8, 0, day=10), 48), 16)
        self.assertIsNone(codex_slot(at(9, 30), 0))

    def test_finalization_locks_only_once_and_excludes_post_cutoff_verification(self):
        news = record(at(8, 51), at(8, 50), headline="Thermax Limited net profit rises")
        late = record(at(9, 6), at(9, 4), name="post-cutoff-verification",
                      headline="Thermax Limited net profit falls")
        sync_archive_batch(self.db, batch("a", at(8, 53), news))
        sync_archive_batch(self.db, batch("b", at(9, 7), late))
        with patch("news_collector.morning.select_candidates") as call:
            report = run(self.db, clock=lambda: at(9, 5))
            call.assert_not_called()
        self.assertEqual(report["signals"][0]["side"], "LONG")
        self.assertEqual(report["generated_at"], at(9, 5).isoformat())
        self.assertEqual(run(self.db, clock=lambda: at(9, 10)), report)
        self.assertEqual(run(self.db, clock=lambda: at(9, 12))["status"],
                         "OUTSIDE_RESEARCH_WINDOW")

    def test_nine_am_is_still_a_draft_and_exchange_holiday_skips(self):
        sync_archive_batch(self.db, batch("a", at(8, 59), record(at(8, 57), at(8, 56))))
        with patch("news_collector.morning.select_candidates",
                   return_value=("NO_TRADE", "No qualified stock", [])) as call:
            self.assertEqual(run(self.db, clock=lambda: at(9, 5, day=10)), {"status": "CLOSED"})
            call.assert_not_called()
            self.assertEqual(run(self.db, clock=lambda: at(8, 59))["status"], "DRAFT_SAVED")

    def test_nine_am_freezes_evidence_and_waits_for_late_draft(self):
        sync_archive_batch(self.db, batch("a", at(8, 58), record(at(8, 57), at(8, 56))))
        self.assertEqual(run(self.db, clock=lambda: at(9, 0)),
                         {"status": "EVIDENCE_FROZEN_AWAITING_DRAFT"})
        with self.db.connect() as conn:
            frozen = conn.execute(select(morning_reports)).mappings().one()
            expected = conn.execute(select(article_revisions.c.id)).scalar_one()
        self.assertIsNone(frozen["report"])
        self.assertEqual(len(frozen["evidence"]["items"]), 1)
        self.assertEqual(frozen["evidence"]["items"][0]["evidence_id"], expected)

    def test_finalization_reaching_hard_deadline_cannot_lock(self):
        sync_archive_batch(self.db, batch("a", at(9, 4), record(at(9, 3), at(9, 2))))
        clock = iter([at(9, 8), at(9, 12)]).__next__
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
            run(self.db, clock=lambda: at(8, 59))
        report = run(self.db, clock=lambda: at(9, 5))
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
