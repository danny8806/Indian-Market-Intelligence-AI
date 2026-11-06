"""Deterministic, offline PDF/alias/source-gap tests. No external calls."""
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pypdf import PdfWriter

from news_collector.matching import match_issuers
from news_collector.reconcile import event_kind, source_reconciliation
from news_collector.enrich import (
    allowed_filing_pdf, extract_pdf_text, enrich,
)

IST = ZoneInfo("Asia/Kolkata")
UNIVERSE = {
    "TITAN": "Titan Company Limited",
    "NYKAA": "FSN E-Commerce Ventures Limited",
    "BEL": "Bharat Electronics Limited",
    "THERMAX": "Thermax Limited",
}


def event(event_id, symbol, provider, title, summary, url):
    return {
        "id": event_id, "symbols": [symbol], "providers": [provider],
        "headline": title, "summary": summary, "url": url,
        "published_at": "2026-11-06T17:05:00+05:30",
        "first_seen_at": "2026-11-06T17:35:00+05:30",
    }


class SourceUpgradeTests(unittest.TestCase):
    def test_manual_alias_and_official_universe_gate(self):
        self.assertEqual(match_issuers("Nykaa reports Q2 earnings", "", UNIVERSE), ["NYKAA"])
        self.assertEqual(match_issuers("Nykaa reports Q2 earnings", "",
                                       {"BEL": "Bharat Electronics Limited"}), [])
        self.assertEqual(match_issuers("Titan Company posts earnings", "", UNIVERSE), ["TITAN"])

    def test_explicit_ticker_and_ambiguous_short_name(self):
        self.assertEqual(match_issuers("NSE:BEL profit up", "", UNIVERSE), ["BEL"])
        self.assertEqual(match_issuers("Bell announces order", "", UNIVERSE), [])
        self.assertEqual(match_issuers("BEL profit up", "", UNIVERSE), [])

    def test_exchange_issuer_does_not_inherit_mentioned_company(self):
        self.assertEqual(match_issuers("Thermax Limited", "Titan Company Limited is our vendor",
                                       UNIVERSE, official_filing=True), ["THERMAX"])
        self.assertEqual(match_issuers("Thermax Limited", "Titan Company Limited is our vendor",
                                       UNIVERSE, official_filing=False), ["THERMAX", "TITAN"])

    def test_pdf_allowlist_redirect_protection(self):
        self.assertTrue(allowed_filing_pdf(
            "https://nsearchives.nseindia.com/corporate/demo.pdf", ["NSE"]))
        self.assertTrue(allowed_filing_pdf(
            "https://www.bseindia.com/xml-data/corpfiling/AttachLive/demo.pdf", ["BSE"]))
        self.assertFalse(allowed_filing_pdf("http://www.bseindia.com/doc.pdf", ["BSE"]))
        self.assertFalse(allowed_filing_pdf("https://evil.example/secret.pdf", ["NSE"]))
        self.assertFalse(allowed_filing_pdf("https://www.bseindia.com/doc.pdf", ["MEDIA"]))
        self.assertFalse(allowed_filing_pdf("https://www.bseindia.com@evil.example/doc.pdf", ["BSE"]))

    def test_pdf_extract_blank_real_structure(self):
        buffer = io.BytesIO()
        p = PdfWriter()
        p.add_blank_page(width=612, height=792)
        p.write(buffer)
        x = extract_pdf_text(buffer.getvalue())
        self.assertEqual(x["pdf_pages"], 1)
        self.assertEqual(x["status"], "NO_EXTRACTABLE_TEXT")
        self.assertEqual(x["pages_read"], 1)

    def test_pdf_bad_magic_and_large_rejected(self):
        with self.assertRaisesRegex(ValueError, "Not a PDF"):
            extract_pdf_text(b"not a PDF")
        with self.assertRaisesRegex(ValueError, "size limit"):
            extract_pdf_text(b"%PDF-" + b"0" * (9_000_000 + 1))

    def test_event_reconciliation_not_false_certification(self):
        events = [
            event("1", "THERMAX", "NSE", "Thermax Limited",
                  "Financial results for quarter", "https://nse.example/a"),
            event("2", "THERMAX", "BSE", "Thermax Limited",
                  "Consolidated profit Q2 results", "https://bse.example/b"),
            event("3", "NYKAA", "BSE", "FSN E-Commerce Ventures Limited",
                  "Financial results announced", "https://bse.example/c"),
            event("4", "TITAN", "MEDIA", "Titan Company Limited",
                  "Order contract worth 200 crore", "https://media.example/d"),
        ]
        report = source_reconciliation(events, as_of="2026-11-06T18:00:00+05:30",
                                       session="2026-11-09")
        classes = report["category_counts"]
        self.assertEqual(classes["BOTH_EXCHANGES_SAME_ISSUER_CATEGORY_NOT_CONFIRMED_SAME_EVENT"], 1)
        self.assertEqual(classes["SINGLE_EXCHANGE_CANDIDATE_REVIEW_NOT_CONFIRMED_MISS"], 1)
        self.assertEqual(classes["MEDIA_ONLY_CANDIDATE_REVIEW_NOT_CONFIRMED_MISS"], 1)
        self.assertNotIn("CONFIRMED_MISS", classes)

    def test_meeting_transcript_not_results(self):
        self.assertEqual(event_kind("Thermax", "Earnings call transcript for Q2 results"),
                         "analyst_meetings")
        self.assertEqual(event_kind("Thermax", "Financial results for September 2026"),
                         "financial_results")

    def test_enrichment_archives_results_no_second_fetch(self):
        pdf = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(pdf)
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "2026-11-09"
            folder.mkdir(parents=True)
            row = event("file1", "THERMAX", "NSE", "Thermax Limited",
                        "Q2 financial results", "https://nsearchives.nseindia.com/corporate/demo.pdf")
            (folder / "events.jsonl").write_text(json.dumps(row) + "\n")
            (folder / "coverage.json").write_text(json.dumps({
                "session": "2026-11-09",
                "generated_at": "2026-11-06T18:30:00+05:30",
                "window_end_exclusive": "2026-11-09T09:00:00+05:30",
                "sources": [{"source": "NSE", "status": "OK"}],
            }))
            calls = []
            def fake_download(url):
                calls.append(url)
                return pdf.getvalue()
            x = enrich("2026-11-09", base=Path(td), fetcher=fake_download)
            y = enrich("2026-11-09", base=Path(td), fetcher=fake_download)
            self.assertEqual(x["status_counts"]["NO_EXTRACTABLE_TEXT"], 1)
            self.assertEqual(y["attempted_this_poll"], 0)
            self.assertEqual(len(calls), 1)
            self.assertTrue((folder / "source_gap_audit.json").exists())
            self.assertTrue((folder / "enrichment_summary.json").exists())

    def test_preopen_discovery_marker(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "2026-11-09"
            folder.mkdir(parents=True)
            row = event("file2", "THERMAX", "NSE", "Thermax Limited",
                        "Financial results", "https://nsearchives.nseindia.com/corporate/demo.pdf")
            row["first_seen_at"] = "2026-11-09T09:15:00+05:30"
            (folder / "events.jsonl").write_text(json.dumps(row) + "\n")
            (folder / "coverage.json").write_text(json.dumps({
                "session": "2026-11-09", "generated_at": "2026-11-09T09:20:00+05:30",
                "window_end_exclusive": "2026-11-09T09:00:00+05:30", "sources": []}))
            x = enrich("2026-11-09", base=Path(td), max_docs=0)
            self.assertEqual(x["pdf_candidates_late_discovery_or_unknown"], 1)
            self.assertEqual(x["pdf_candidates_seen_before_cutoff"], 0)


if __name__ == "__main__":
    unittest.main()
