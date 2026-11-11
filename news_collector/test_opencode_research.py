import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from news_collector import opencode_research as oc
from news_collector.continuous_worker import collect_archive, model_slot
from news_collector.engine import IST


def feed(name, url, *, kind="rss", provider="NSE", enabled=True):
    return {"name": name, "url": url, "kind": kind, "provider": provider,
            "authority": "official", "enabled": enabled}


class OpenCodeResearchTests(unittest.TestCase):
    def test_events_keep_text_and_live_fetch_evidence(self):
        stdout = "\n".join([
            json.dumps({"type": "tool_use", "part": {
                "tool": "webfetch", "id": "tool-1",
                "state": {"status": "completed",
                          "input": {"url": "https://nsearchives.nseindia.com/a"}}}}),
            json.dumps({"type": "text", "part": {
                "type": "text", "text": '{"urls":["https://nsearchives.nseindia.com/a.pdf"]}'}}),
        ])
        parsed = oc.parse_events(stdout)
        self.assertEqual(parsed["text"], '{"urls":["https://nsearchives.nseindia.com/a.pdf"]}')
        self.assertEqual(parsed["tools"][0]["tool"], "webfetch")
        self.assertEqual(parsed["tools"][0]["id"], "tool-1")

    def test_url_extraction_accepts_fenced_json_and_rejects_non_https(self):
        text = ("Here is the result:\n```json\n"
                '{"urls":["https://a.example/x","https://a.example/x",'
                '"http://b.example/y",'
                + json.dumps([f"https://c.example/{i}" for i in range(10)])[1:-1]
                + "]}\n```")
        urls = oc.extract_urls(text)
        self.assertEqual(urls[0], "https://a.example/x")
        self.assertNotIn("http://b.example/y", urls)
        self.assertLessEqual(len(urls), oc.MAX_URLS)
        self.assertEqual(len(urls), len(set(urls)))

    def test_config_denies_every_tool_before_allowing_source_fetches(self):
        config = oc.source_config("opencode/test", [
            feed("NSE", "https://nsearchives.nseindia.com/feed.xml"),
            feed("BSE", "https://www.bseindia.com/feed.xml", provider="BSE"),
        ])
        self.assertEqual(config["permissions"][0],
                         {"action": "*", "resource": "*", "effect": "deny"})
        allowed = [rule for rule in config["permissions"] if rule["effect"] == "allow"]
        self.assertTrue(all(rule["action"] == "webfetch" for rule in allowed))
        self.assertIn("https://nsearchives.nseindia.com/*",
                      {rule["resource"] for rule in allowed})
        self.assertIn("https://bseindia.com/*", {rule["resource"] for rule in allowed})

    def test_source_batches_rotate_through_every_eligible_source(self):
        sources = [feed(f"S{i}", f"https://example.com/{i}.xml") for i in range(10)]
        sources.append(feed("disabled", "https://example.com/off.xml", enabled=False))
        sources.append(feed("discovery", "https://news.google.com/rss", provider="Google"))
        sources[-1]["timestamp_provenance"] = "discovery"
        seen = set()
        for slot in range(4):
            seen.update(item["name"] for item in oc.source_batch(sources, slot, 3))
        self.assertEqual(seen, {f"S{i}" for i in range(10)})

    def test_discovery_only_fetches_sources_accessible_in_the_current_batch(self):
        now = datetime(2026, 11, 10, 8, 0, tzinfo=IST)
        allowed = feed("Allowed", "https://exchange.example/filings")
        blocked = feed("Blocked", "https://blocked.example/news")
        with patch("news_collector.opencode_research.run_opencode",
                   return_value=("QUOTA_LIMIT", None, {})) as run:
            status, _, _ = oc.discover(now, {}, {}, clock=lambda: now,
                                       sources=[allowed, blocked], batch_size=2,
                                       accessible_urls={allowed["url"]})
        self.assertEqual(status, "QUOTA_LIMIT")
        self.assertEqual(run.call_args.kwargs["sources"], [allowed])
        self.assertNotIn(blocked["url"], run.call_args.args[0])

    def test_preflight_maps_free_quota_to_retryable_limit(self):
        class Response:
            status_code = 429
            headers = {"Retry-After": "120"}
            def json(self):
                return {"error": {"message": "Free usage limit reached"}}

        with patch("news_collector.opencode_research.requests.post",
                   return_value=Response()):
            result = oc._preflight("opencode/deepseek-v4.1-flash-free")
        self.assertEqual(result["status"], "QUOTA_LIMIT")
        self.assertEqual(result["retry_after_seconds"], 120)
        self.assertIn("quota_reset_at", result)

    def test_missing_cli_is_not_configured(self):
        with patch("news_collector.opencode_research.executable", return_value=None):
            status, payload, audit = oc.run_opencode("prompt", sources=[])
        self.assertEqual((status, payload, audit["status"]),
                         ("NOT_CONFIGURED", None, "NOT_CONFIGURED"))

    def test_quota_preflight_skips_cli_execution(self):
        with patch("news_collector.opencode_research.executable", return_value="opencode"), \
             patch("news_collector.opencode_research._preflight",
                   return_value={"status": "QUOTA_LIMIT", "retry_after_seconds": 60}):
            status, payload, audit = oc.run_opencode("prompt", sources=[])
        self.assertEqual((status, payload, audit["status"]),
                         ("QUOTA_LIMIT", None, "QUOTA_LIMIT"))

    def test_opencode_runs_before_codex_and_quota_does_not_block_codex(self):
        calls = []
        batch = {"batch_id": "p", "session": "2026-11-10",
                 "generated_at": datetime(2026, 11, 10, 9, 31, tzinfo=IST).isoformat(),
                 "records": [], "sources_configured": 2, "sources_with_items": 1,
                 "sources_failed": 0, "sources_blocked": 0,
                 "sources": [
                     {"source": "NSE filings", "kind": "rss", "status": "OK",
                      "url": "https://exchange.example/filings", "fetched_items": 1},
                     {"source": "Blocked", "kind": "broker_html", "status": "BLOCKED_ROBOTS",
                      "url": "https://blocked.example/news", "fetched_items": 0},
                 ]}
        audit = {"model": "opencode/deepseek-v4.1-flash-free", "source_batch": [],
                 "preflight": {"status": "QUOTA_LIMIT", "message": "Free usage limit reached"}}

        def opencode(*_args, **kwargs):
            self.assertEqual(kwargs["accessible_urls"], {"https://exchange.example/filings"})
            calls.append("opencode")
            return "QUOTA_LIMIT", [], audit

        def codex(*_args, **_kwargs):
            calls.append("codex")
            return "OK", []

        with TemporaryDirectory() as folder, \
             patch("news_collector.archive.collect_batch", return_value=(batch, {}, {})), \
             patch("news_collector.archive.replay", return_value=0), \
             patch("news_collector.archive.stage"), \
             patch("news_collector.archive.prune_raw", return_value=0), \
             patch("news_collector.agent_intake.lane_statuses", return_value={}), \
             patch("news_collector.agent_intake.ingest_inbox", return_value={}), \
             patch("news_collector.db_store.prune_raw_documents", return_value=0), \
             patch("news_collector.opencode_research.discover", side_effect=opencode), \
             patch("news_collector.codex_research.discover", side_effect=codex):
            result = collect_archive(None, Path(folder),
                                     clock=lambda: datetime(2026, 11, 10, 9, 31, tzinfo=IST))
        self.assertEqual(calls, ["opencode", "codex"])
        self.assertEqual(result["opencode"], "QUOTA_LIMIT")
        self.assertEqual(result["codex"], "OK")
        self.assertEqual(result["db_status"], "DATABASE_SYNC_OK")

    def test_model_slot_is_bounded_to_first_pass_of_half_hour(self):
        self.assertEqual(model_slot(datetime(2026, 11, 10, 8, 0, tzinfo=IST), 48), 16)
        self.assertIsNone(model_slot(datetime(2026, 11, 10, 8, 10, tzinfo=IST), 48))
        self.assertEqual(model_slot(datetime(2026, 11, 10, 8, 30, tzinfo=IST), 48), 17)


if __name__ == "__main__":
    unittest.main()
