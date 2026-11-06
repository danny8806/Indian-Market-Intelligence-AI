"""No-network regression tests for NIFTY 500 mover news-coverage audits."""
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from learning.mover_audit import review_market_day, run, signed_evidence

DAY = date(2026, 11, 6)
IST = ZoneInfo("Asia/Kolkata")


def universe():
    return {"X%04d" % i: "Example Company %04d Limited" % i for i in range(500)}


def prices():
    p = {}
    for i in range(500):
        op = 100.
        cl = 100.
        if i == 1: cl = 108.0
        if i == 2: cl = 95.0
        if i == 3: cl = 104.0
        p[f"X{i:04d}"] = {
            "PREV_CLOSE": 100., "OPEN_PRICE": op,
            "HIGH_PRICE": max(op, cl) + 1,
            "LOW_PRICE": min(op, cl) - 1,
            "CLOSE_PRICE": cl, "TTL_TRD_QNTY": 1000.,
        }
    return p


def snapshot():
    return {"candidates": [
        {"symbol": "X0001", "review_priority": 12,
         "source_urls": ["https://example.org/one"],
         "evidence_summary": {"positive_metrics": ["revenue"], "negative_metrics": [],
                              "conflicting_metrics": []}},
        {"symbol": "X0004", "review_priority": 3,
         "source_urls": ["https://example.org/two"],
         "evidence_summary": {"positive_metrics": [], "negative_metrics": ["pat"],
                              "conflicting_metrics": []}},
    ]}


class MoverAuditTests(unittest.TestCase):
    def test_top_up_down_coverage(self):
        r = review_market_day(DAY, prices(), universe(), snapshot=snapshot(),
                              snapshot_status="VALIDATED_FROZEN_09AM_SNAPSHOT",
                              official_price_url="NSE_SAMPLE")
        self.assertEqual(r["priced_count"], 500)
        self.assertEqual(r["headline_only_market_top_10_gainers"][0]["symbol"], "X0001")
        self.assertEqual(r["headline_only_market_top_10_losers"][0]["symbol"], "X0002")
        three = r["mover_capture_by_threshold"]["3.0"]
        self.assertEqual(three["movers_in_priced_universe"], 3)
        self.assertEqual(three["in_frozen_candidate_pool"], 1)
        self.assertEqual(three["without_frozen_candidate"], 2)
        self.assertEqual(three["uncovered_symbol_examples"], ["X0002", "X0003"])
        self.assertEqual(r["status"], "COMPARED_TO_FROZEN_NEWS_POOL")
        self.assertEqual(r["evidence_direction_diagnostic"]["agreement_pct"], 100.0)

    def test_no_snapshot_is_not_assumed_no_news(self):
        r = review_market_day(DAY, prices(), universe(), snapshot=None,
                              snapshot_status="NO_FROZEN_09AM_SNAPSHOT",
                              official_price_url="NSE_SAMPLE")
        self.assertEqual(r["status"], "MARKET_ONLY_NO_VERIFIABLE_PREOPEN_BASELINE")
        self.assertIsNone(r["mover_capture_by_threshold"]["3.0"]["candidate_coverage_pct"])
        self.assertIsNone(r["headline_only_market_top_10_gainers"][0]
                          ["has_frozen_preopen_news_candidate"])
        self.assertEqual(r["mover_capture_by_threshold"]["3.0"]["uncovered_symbol_examples"], [])

    def test_anomaly_excluded_not_fabricated(self):
        p = prices()
        p["X0001"]["CLOSE_PRICE"] = 201.
        p["X0001"]["HIGH_PRICE"] = 202.
        r = review_market_day(DAY, p, universe(), snapshot=snapshot(),
                              snapshot_status="VALIDATED_FROZEN_09AM_SNAPSHOT",
                              official_price_url="NSE_SAMPLE")
        self.assertEqual(r["priced_count"], 499)
        self.assertEqual(r["excluded_anomalies"][0]["symbol"], "X0001")

    def test_missing_price_counts_visible(self):
        p = prices()
        del p["X0002"]
        r = review_market_day(DAY, p, universe(), snapshot=None,
                              snapshot_status="NO_FROZEN_09AM_SNAPSHOT",
                              official_price_url="NSE_SAMPLE")
        self.assertEqual(r["missing_prices"], ["X0002"])
        self.assertEqual(r["priced_count"], 499)

    def test_evidence_mixed_not_direction_assumed(self):
        c = {"evidence_summary": {
            "positive_metrics": ["ebitda"], "negative_metrics": ["pat"], "conflicting_metrics": []}}
        self.assertEqual(signed_evidence(c), "MIXED")
        self.assertEqual(signed_evidence({}), "NONE")

    def test_market_only_report_saved_without_frozen_history(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            members = root / "news_collector/data/universe_snapshot.csv"
            members.parent.mkdir(parents=True)
            members.write_text("Company Name,Symbol\n" + "".join(
                f"Example Company {i:04d} Limited,X{i:04d}\n" for i in range(500)))
            result = run(DAY, root=root,
                         price_loader=lambda date_: (prices(), "NSE_TEST"),
                         now=datetime(2026, 11, 7, 13, tzinfo=IST))
            self.assertEqual(result["status"], "MARKET_ONLY_NO_VERIFIABLE_PREOPEN_BASELINE")
            saved = root / "learning/data/mover_reports/2026-11-06.json"
            self.assertTrue(saved.exists())
            self.assertEqual(json.loads(saved.read_text())["priced_count"], 500)

    def test_not_after_close(self):
        r = run(DAY, root=Path("/not/used"), now=datetime(2026, 11, 6, 11, tzinfo=IST))
        self.assertEqual(r["status"], "NOT_AFTER_MARKET_CLOSE")

    def test_small_universe_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unverified"):
            review_market_day(DAY, prices(), {"A": "Fake"}, snapshot=None,
                              snapshot_status="NO_FROZEN_09AM_SNAPSHOT",
                              official_price_url="NSE_SAMPLE")


if __name__ == "__main__":
    unittest.main()
