"""Frozen-candidate learning checks: no live network, no post-cutoff leakage."""
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from learning.candidate_outcomes import audit, load_snapshot, price_csv_reader
from learning.train_candidates import train

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 9)


def frozen():
    return {
        "schema_version": "research-candidates/1.0",
        "session_date": "2026-11-09",
        "cutoff_exclusive": "2026-11-09T09:00:00+05:30",
        "as_of": "2026-11-09T08:58:00+05:30",
        "data_mode": "FROZEN_PREMARKET",
        "universe_status": "OFFICIAL_FETCH:https://www.niftyindices.com/official.csv",
        "company_count": 2, "execution_enabled": False,
        "candidates": [
            {"symbol": sym, "first_seen_at": "2026-11-06T17:00:00+05:30",
             "articles": 2, "official_filing_count": 1, "material_event_count": 1,
             "review_priority": 9, "categories": ["financial_results"],
             "headline_samples": [sym + " financial results"],
             "source_urls": ["https://example.org/source"],
             "evidence_summary": {
                 "positive_metrics": ["revenue"], "negative_metrics": [],
                 "conflicting_metrics": []}}
            for sym in ["TITAN", "THERMAX"]
        ],
    }


def bars(symbol, session):
    end = 110 if symbol == "TITAN" else 90
    return [
        {"date": "2026-11-06", "open": 100, "high": 103, "low": 98,
         "close": 100, "volume": 1234, "split": 0},
        {"date": "2026-11-09", "open": 100, "high": 112, "low": 88,
         "close": end, "volume": 1234, "split": 0},
    ]


class CandidateOutcomeTests(unittest.TestCase):
    def test_never_label_post_market_research_preview(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "candidate_snapshot.json"
            data = frozen()
            data["data_mode"] = "POST_CUTOFF_RESEARCH_PREVIEW_NOT_TRAINABLE"
            p.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_snapshot(p, DAY)

    def test_all_candidate_outcomes_append_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "news_collector/data/2026-11-09/candidate_snapshot.json"
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps(frozen()))
            today = datetime(2026, 11, 9, 17, tzinfo=IST)
            x = audit(DAY, root=root, price_reader=bars, as_of=today)
            self.assertEqual(x["status"], "COMPLETE_NOT_NSE_VERIFIED")
            self.assertEqual(x["positive_count"], 1)
            self.assertEqual(x["priced"], 2)
            y = audit(DAY, root=root, price_reader=bars, as_of=today)
            self.assertEqual(y["status"], "COMPLETE_NOT_NSE_VERIFIED")
            self.assertEqual(y["new_labeled_candidates"], 0)
            path = root / "learning/data/candidate_outcomes.csv"
            self.assertEqual(len(path.read_text().splitlines()), 3)

    def test_one_missing_stock_disallows_training(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "news_collector/data/2026-11-09/candidate_snapshot.json"
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps(frozen()))
            def reader(sym, session):
                if sym == "THERMAX":
                    raise ValueError("unavailable")
                return bars(sym, session)
            x = audit(DAY, root=root, price_reader=reader,
                      as_of=datetime(2026, 11, 9, 17, tzinfo=IST))
            self.assertEqual(x["status"], "PARTIAL_NO_TRAINING_ROWS")
            self.assertFalse((root / "learning/data/candidate_outcomes.csv").exists())

    def test_never_label_intraday(self):
        with tempfile.TemporaryDirectory() as td:
            x = audit(DAY, root=Path(td), price_reader=bars,
                      as_of=datetime(2026, 11, 9, 14, tzinfo=IST))
            self.assertEqual(x["status"], "UNAVAILABLE")

    def test_training_refuses_insufficient_history(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(train(Path(td) / "missing.csv",
                                   Path(td) / "out")["status"], "INSUFFICIENT_DATA")

    def test_csv_loader_requires_fields(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "prices.csv"
            p.write_text("symbol,date,open,high,low,close,volume,split\n"
                         "TITAN,2026-11-06,100,103,98,100,1000,0\n"
                         "TITAN,2026-11-09,100,110,99,109,1000,0\n")
            r = price_csv_reader(p)
            self.assertEqual(len(r("TITAN", DAY)), 2)
            with self.assertRaisesRegex(ValueError, "absent"):
                r("THERMAX", DAY)


if __name__ == "__main__":
    unittest.main()
