"""Bounded, read-only text extraction for public NSE/BSE corporate filing PDFs.

No paywall/CAPTCHA bypass, no OCR, no generated stock directions and no broker code.
Only short text excerpts and derived diagnostics are committed to public GitHub.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from pypdf import PdfReader

from news_collector.engine import ROOT, default_session, read_jsonl, write_jsonl
from news_collector.reconcile import event_kind, write_gap_audit

IST = ZoneInfo("Asia/Kolkata")
PDF_MAX_BYTES = 9_000_000
PDF_MAX_PAGES = 10
PDF_MAX_TEXT = 70_000
RETRIES = 2
MATERIAL = {"financial_results", "orders_contracts", "regulatory",
            "acquisition", "fundraising"}
OFFICIAL_HOSTS = {
    "nsearchives.nseindia.com", "archives.nseindia.com",
    "www.bseindia.com", "bseindia.com",
}


def allowed_filing_pdf(url: str, providers: list[str] | None = None) -> bool:
    """An official filing link, not a redirected arbitrary news or internal URL."""
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and u.hostname in OFFICIAL_HOSTS
                and u.port in {None, 443} and not u.username and not u.password
                and u.path.lower().endswith(".pdf")
                and bool(set(providers or []) & {"NSE", "BSE"}))
    except ValueError:
        return False


def pdf_bytes(url: str) -> bytes:
    if not allowed_filing_pdf(url, ["NSE", "BSE"]):
        raise ValueError("Disallowed PDF host or path")
    headers = {"User-Agent": "IndianMarketResearchCollector/1.0",
               "Accept": "application/pdf"}
    # Do not follow redirects: no arbitrary-host fetching.
    with requests.get(url, headers=headers, stream=True, allow_redirects=False,
                      timeout=(6, 19)) as response:
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            raise ValueError("Redirect not followed")
        if int(response.headers.get("Content-Length") or 0) > PDF_MAX_BYTES:
            raise ValueError("PDF exceeds 9MB size cap")
        chunks, length = [], 0
        for block in response.iter_content(65536):
            length += len(block)
            if length > PDF_MAX_BYTES:
                raise ValueError("PDF exceeds 9MB size cap")
            chunks.append(block)
        payload = b"".join(chunks)
        if not payload.startswith(b"%PDF-"):
            raise ValueError("Downloaded response is not a PDF")
        return payload


def extract_pdf_text(data: bytes, *, pages: int = PDF_MAX_PAGES) -> dict:
    if len(data) > PDF_MAX_BYTES:
        raise ValueError("PDF exceeds size limit")
    if not data.startswith(b"%PDF-"):
        raise ValueError("Not a PDF")
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF")
    total = len(reader.pages)
    selected = min(total, max(1, pages))
    page_text = []
    errors = 0
    for p in range(selected):
        try:
            raw = reader.pages[p].extract_text(extraction_mode="plain") or ""
        except Exception:
            raw = ""
            errors += 1
        if not raw.strip():
            from news_collector.tool_capabilities import fallback_pdf_page
            raw = fallback_pdf_page(data, p)
        page_text.append(raw)
    joined = "\n".join(page_text)
    truncated = len(joined) > PDF_MAX_TEXT
    joined = joined[:PDF_MAX_TEXT]
    # Preserve a short excerpt and context lines, never bulk-redistribute PDFs.
    excerpt = re.sub(r"\s+", " ", joined).strip()[:1800]
    metric_lines = []
    for line in joined.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if 8 <= len(clean) <= 240 and re.search(
                r"\b(?:revenue|sales|ebitda|profit|loss|order\s+book|"
                r"contract\s+value|turnover|net\s+worth|margin)\b", clean, re.I):
            if clean not in metric_lines:
                metric_lines.append(clean)
            if len(metric_lines) >= 12:
                break
    return {
        "pdf_pages": total, "pages_read": selected, "page_extract_errors": errors,
        "text_chars_read": len(joined), "text_sample": excerpt,
        "financial_context_lines": metric_lines,
        "truncated_text": truncated or selected < total,
        "text_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "status": "EXTRACTED" if excerpt else "NO_EXTRACTABLE_TEXT",
    }


def priority(item: dict) -> tuple[int, str, str]:
    tag = event_kind(item.get("headline", ""), item.get("summary", ""))
    score = 0
    if tag == "financial_results": score += 40
    if tag == "orders_contracts": score += 35
    if tag == "regulatory": score += 30
    if tag in {"acquisition", "fundraising"}: score += 25
    if re.search(r"\b(?:board\s+meeting\s+outcome|quarterly|results|order|penalt)\b",
                 item.get("summary", ""), re.I):
        score += 10
    return (-score, item.get("published_at") or "", item["id"])


def attempt_pdf(item: dict, *, fetcher=pdf_bytes, parser=extract_pdf_text) -> dict:
    now = datetime.now(IST).isoformat()
    out = {
        "id": item["id"], "url": item["url"], "symbols": item.get("symbols", []),
        "published_at": item.get("published_at"),
        "first_seen_at": item.get("first_seen_at"),
        "last_attempt_at": now,
        "classification": event_kind(item.get("headline", ""), item.get("summary", "")),
        "attempts": 1, "status": "FETCH_ERROR",
    }
    try:
        if not allowed_filing_pdf(item["url"], item.get("providers", [])):
            raise ValueError("Only official HTTPS NSE/BSE PDF URLs are eligible")
        data = fetcher(item["url"])
        out.update(parser(data))
        out["pdf_sha256"] = hashlib.sha256(data).hexdigest()
        out["pdf_bytes"] = len(data)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:220]}"
        out["status"] = "NOT_PDF_OR_UNSAFE" if isinstance(e, ValueError) else "FETCH_ERROR"
    return out


def enrich(session_date: str, *, base: Path = ROOT / "data", max_docs: int = 20,
           workers: int = 4, fetcher=pdf_bytes, parser=extract_pdf_text) -> dict:
    """Retry bounded official PDFs and save audit of potential news-source gaps."""
    folder = base / session_date
    events_path = folder / "events.jsonl"
    coverage_path = folder / "coverage.json"
    if not events_path.exists() or not coverage_path.exists():
        raise FileNotFoundError("Collector events and coverage must exist before enrichment")
    events = read_jsonl(events_path)
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    if coverage["session"] != session_date:
        raise ValueError("Coverage session mismatch")
    gaps = write_gap_audit(folder / "source_gap_audit.json", list(events.values()), coverage)
    previous = read_jsonl(folder / "pdf_extraction.jsonl")
    all_pdfs = [r for r in events.values() if allowed_filing_pdf(r.get("url", ""), r.get("providers", []))
                and r.get("published_at")]
    all_pdfs.sort(key=priority)
    to_fetch = [e for e in all_pdfs
                if previous.get(e["id"], {}).get("status") not in {
                    "EXTRACTED", "NO_EXTRACTABLE_TEXT", "NOT_PDF_OR_UNSAFE"}
                and int(previous.get(e["id"], {}).get("attempts", 0)) < RETRIES]
    chosen = to_fetch[:max(0, min(max_docs, 100))]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 5))) as pool:
        results = list(pool.map(lambda e: attempt_pdf(e, fetcher=fetcher, parser=parser), chosen))
    for e, record in zip(chosen, results):
        old = previous.get(e["id"], {})
        record["attempts"] += int(old.get("attempts", 0))
        previous[e["id"]] = record
    write_jsonl(folder / "pdf_extraction.jsonl", previous)
    last = Counter(r["status"] for r in previous.values())
    cutoff = datetime.fromisoformat(coverage["window_end_exclusive"])
    eligible_before_cutoff = 0
    for e in all_pdfs:
        try:
            if datetime.fromisoformat(e["first_seen_at"]) < cutoff:
                eligible_before_cutoff += 1
        except (ValueError, KeyError, TypeError):
            pass
    report = {
        "session": session_date, "checked_at": datetime.now(IST).isoformat(),
        "pdf_candidates_total": len(all_pdfs),
        "pdf_candidates_seen_before_cutoff": eligible_before_cutoff,
        "pdf_candidates_late_discovery_or_unknown": len(all_pdfs) - eligible_before_cutoff,
        "attempted_this_poll": len(chosen), "completed_document_records": len(previous),
        "status_counts": dict(sorted(last.items())),
        "unattempted_or_retryable": max(0, len(to_fetch) - len(chosen)),
        "source_gap_groups": gaps["category_counts"],
        "note": ("Official publicly available PDF text extracted by pypdf with bounded alternate page extractors. Only a bounded excerpt "
                 "and context lines are stored. No OCR on scanned documents, no AI classification, "
                 "no inference of price direction. PDF retrieval after 09:00 is not proof that "
                 "its contents were known to the prediction system before 09:00."),
    }
    (folder / "enrichment_summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--session-date")
    p.add_argument("--data-dir", type=Path, default=ROOT / "data")
    p.add_argument("--max-docs", type=int, default=20)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    target = args.session_date or default_session(datetime.now(IST))
    print(json.dumps(enrich(target, base=args.data_dir,
                            max_docs=args.max_docs, workers=args.workers), indent=2))


if __name__ == "__main__":
    main()
