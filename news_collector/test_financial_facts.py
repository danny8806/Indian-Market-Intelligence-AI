"""No-network regression tests: explicit numeric provenance and time-safe candidate freeze."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from news_collector.financial_facts import extract_line, extract_facts, evidence_summary
from news_collector.candidates import build_snapshot, candidate_rows, run, write_atomic

IST = ZoneInfo("Asia/Kolkata")
SESSION = "2026-11-09"
START = datetime(2026, 11, 6, 15, tzinfo=IST)
CUTOFF = datetime(2026, 11, 9, 9, tzinfo=IST)


def event(first="2026-11-06T18:00:00+05:30"):
    return {
        "id": "a", "headline": "Anupam Rasayan India Limited",
        "summary": "Quarterly financial results announced",
        "symbols": ["ANURAS"], "providers": ["NSE"],
        "url": "https://nsearchives.nseindia.com/corporate/a.pdf",
        "published_at": "2026-11-06T16:00:00+05:30", "first_seen_at": first,
        "publication_time_status": "VERIFIED_FORMAT",
    }


def pdf_record(parsed_at="2026-11-09T08:44:00+05:30"):
    return {
        "id": "a", "url": "https://nsearchives.nseindia.com/corporate/a.pdf",
        "status": "EXTRACTED",
        "pdf_sha256": "a" * 64,
        "last_attempt_at": parsed_at,
        "financial_context_lines": [
            "Total Revenue for H1FY27 was Rs. 1,489 Cr compared with Rs. 1,230 Cr; up 21% YoY",
            "EBITDA for H1FY27 grew 38% YoY",
            "Net profit fell 12.5% QoQ",
            "Total Revenue 821 739 11% 1,489 1,230 21%",
        ],
    }


class FactsAndFreezeTests(unittest.TestCase):
    def test_extract_explicit_yoy_and_qoq(self):
        items = extract_facts(pdf_record())
        vals = {(x.get("metric"), x.get("basis")): x.get("reported_change_pct")
                for x in items if "reported_change_pct" in x}
        self.assertEqual(vals[("revenue", "YoY")], 21)
        self.assertEqual(vals[("ebitda", "YoY")], 38)
        self.assertEqual(vals[("pat", "QoQ")], -12.5)
        self.assertEqual(len(items), 3)

    def test_does_not_infer_table_columns(self):
        self.assertEqual(extract_line("Revenue 100 82 22% EBITDA 30 20 50%",
                                      source="x", doc_hash="h"), [])
        self.assertEqual(extract_line("PAT increased 28% without any time basis",
                                      source="x", doc_hash="h"), [])

    def test_negative_yoy_and_mixed_warning(self):
        a = extract_line("PAT declined by 17% YoY", source="x", doc_hash="h")
        b = extract_line("Revenue increased 10% YoY", source="x", doc_hash="h")
        self.assertEqual(a[0]["reported_change_pct"], -17)
        self.assertEqual(evidence_summary(a + b)["label"], "MIXED_REPORTED_FINANCIAL_EVIDENCE")

    def test_no_future_extraction_leakage(self):
        rows, docs = candidate_rows({"a": event()}, {"a": pdf_record(
            "2026-11-09T09:01:00+05:30")},
            start=START, cutoff=CUTOFF,
            as_of=datetime(2026, 11, 9, 8, 58, tzinfo=IST))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["explicit_financial_facts"], [])
        self.assertEqual(docs, [])

    def test_no_future_discovery_leakage(self):
        rows, _ = candidate_rows({"a": event("2026-11-09T09:01:00+05:30")}, {},
                                  start=START, cutoff=CUTOFF,
                                  as_of=datetime(2026, 11, 9, 8, 58, tzinfo=IST))
        self.assertEqual(rows, [])

    def test_preview_and_freeze_immutability(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            d = root / SESSION
            d.mkdir()
            (root / "universe_snapshot.csv").write_text(
                "Company Name,Symbol\n" + "".join(
                    f"Example Company {i:04d} Limited,EXM{i:04d}\n" for i in range(500)))
            (d / "events.jsonl").write_text(json.dumps(event()) + "\n")
            (d / "pdf_extraction.jsonl").write_text(json.dumps(pdf_record()) + "\n")
            (d / "coverage.json").write_text(json.dumps({
                "session": SESSION, "window_start_inclusive": START.isoformat(),
                "window_end_exclusive": CUTOFF.isoformat(),
                "universe_status": "OFFICIAL_FETCH:https://official.example/universe.csv",
                "generated_at": "2026-11-09T08:50:00+05:30",
                "sources_failed": 4,
            }))
            t = datetime(2026, 11, 9, 8, 57, tzinfo=IST)
            freeze = run(SESSION, data_root=root, freeze=True, as_of=t)
            self.assertEqual(freeze["status"], "CREATED_IMMUTABLE")
            payload = json.loads((d / "candidate_snapshot.json").read_text())
            self.assertEqual(payload["company_count"], 1)
            self.assertEqual(len(payload["candidates"][0]["explicit_financial_facts"]), 3)
            # Re-run cannot rewrite the originally frozen snapshot.
            self.assertEqual(run(SESSION, data_root=root, freeze=True, as_of=t)["status"],
                             "EXISTS_NOT_OVERWRITTEN")
            self.assertEqual(run(SESSION, data_root=root, freeze=True,
                                 as_of=datetime(2026, 11, 9, 9, 1, tzinfo=IST))["status"],
                             "FREEZE_REJECTED_OUTSIDE_PREMARKET_WINDOW")
            preview = run(SESSION, data_root=root,
                          as_of=datetime(2026, 11, 9, 9, 2, tzinfo=IST))
            self.assertEqual(preview["status"], "PREVIEW_ONLY")
            self.assertEqual(json.loads((d / "candidate_preview.json").read_text())["data_mode"],
                             "POST_CUTOFF_RESEARCH_PREVIEW_NOT_TRAINABLE")
            self.assertEqual(json.loads((d / "candidate_snapshot.json").read_text()), payload)

    def test_ineligible_no_official_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp) / SESSION
            d.mkdir()
            (d / "events.jsonl").write_text(json.dumps(event()) + "\n")
            (d / "coverage.json").write_text(json.dumps({
                "session": SESSION, "window_start_inclusive": START.isoformat(),
                "window_end_exclusive": CUTOFF.isoformat(),
                "universe_status": "CACHED_SNAPSHOT_STALENESS_UNKNOWN",
                "generated_at": "2026-11-09T08:50:00+05:30",
                "sources_failed": 0,
            }))
            r = run(SESSION, data_root=Path(temp), freeze=True,
                    as_of=datetime(2026, 11, 9, 8, 57, tzinfo=IST))
            self.assertEqual(r["status"], "FREEZE_REJECTED_NO_VERIFIED_UNIVERSE_OR_CANDIDATES")


if __name__ == "__main__":
    unittest.main()
