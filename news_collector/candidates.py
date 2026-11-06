"""Point-in-time NIFTY 500 research candidate dataset, not an order signal.

Create repeatable previews, and freeze ONCE before 09:00 IST.
If no timely freeze exists, training must not infer a historical snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from news_collector.engine import ROOT, default_session, read_jsonl
from news_collector.financial_facts import extract_facts, evidence_summary
from news_collector.reconcile import MATERIAL, event_kind

IST = ZoneInfo("Asia/Kolkata")
SCHEMA = "research-candidates/1.0"


def aware(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value)
        return t.astimezone(IST) if t.tzinfo else None
    except ValueError:
        return None


def eligible_event(row: dict, *, start: datetime, cutoff: datetime, as_of: datetime) -> bool:
    pub, first = aware(row.get("published_at")), aware(row.get("first_seen_at"))
    return bool(pub and first and start <= pub < cutoff and first <= as_of
                and first < cutoff and row.get("publication_time_status") == "VERIFIED_FORMAT")


def candidate_rows(events: dict[str, dict], pdfs: dict[str, dict],
                   *, start: datetime, cutoff: datetime, as_of: datetime) -> tuple[list[dict], list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    docs = []
    for row in events.values():
        if not eligible_event(row, start=start, cutoff=cutoff, as_of=as_of):
            continue
        for symbol in row.get("symbols", []):
            grouped[symbol].append(row)
        record = pdfs.get(row["id"])
        # Critical leakage gate: even a genuine filing dated before 09:00 is
        # not eligible as extracted text if our PDF parser ran after cutoff.
        parsed_at = aware(record.get("last_attempt_at")) if record else None
        if (record and record.get("status") == "EXTRACTED" and parsed_at
                and parsed_at <= as_of and parsed_at < cutoff):
            facts = extract_facts(record)
            docs.append({
                "id": row["id"], "url": row["url"], "symbols": sorted(row.get("symbols", [])),
                "published_at": row["published_at"], "first_seen_at": row["first_seen_at"],
                "parsed_at": record["last_attempt_at"],
                "document_sha256": record.get("pdf_sha256"),
                "facts": facts, "extraction_status": "EXPLICIT_FACTS" if facts else "NO_EXPLICIT_COMPARABLE_FACTS",
            })
    by_doc = {d["id"]: d for d in docs}
    out = []
    for symbol in sorted(grouped):
        rows = grouped[symbol]
        seen_categories = sorted({event_kind(r.get("headline", ""), r.get("summary", ""))
                                  for r in rows})
        material_events = [r for r in rows
                           if event_kind(r.get("headline", ""), r.get("summary", "")) in MATERIAL]
        facts = []
        source_urls = []
        earliest = min(aware(r["first_seen_at"]) for r in rows)
        official = 0
        for r in rows:
            if set(r.get("providers", [])) & {"NSE", "BSE"}:
                official += 1
            if len(source_urls) < 25 and r["url"] not in source_urls:
                source_urls.append(r["url"])
            if r["id"] in by_doc:
                facts.extend(by_doc[r["id"]]["facts"])
        # Cap duplicated assertions across mirrored PDFs and periods. Conflicting
        # values remain marked in evidence_summary for human review.
        unique_facts, found = [], set()
        for fact in facts:
            key = (fact.get("metric"), fact.get("basis"), fact.get("reported_change_pct"),
                   fact.get("reported_period"), fact.get("reported_value_text"))
            if key not in found:
                found.add(key)
                unique_facts.append(fact)
        evidence = evidence_summary(unique_facts)
        # Discovery priority only. No price direction, P&L, success probability
        # or post-09:00 features are used in this ordering.
        priority = (min(len(material_events), 4) * 3
                    + min(official, 4) * 2
                    + min(evidence["yoy_metrics_with_direction"], 3) * 3)
        out.append({
            "symbol": symbol, "first_seen_at": earliest.isoformat(),
            "articles": len(rows), "official_filing_count": official,
            "material_event_count": len(material_events),
            "categories": seen_categories,
            "review_priority": priority,
            "evidence_summary": evidence,
            "explicit_financial_facts": unique_facts[:18],
            "source_urls": source_urls,
            "headline_samples": [r.get("headline", "")[:180] for r in rows[:8]],
            "not_a_trade_signal": True,
        })
    out.sort(key=lambda r: (-r["review_priority"], r["symbol"]))
    return out, docs


def build_snapshot(session: str, *, data_root: Path = ROOT / "data",
                   as_of: datetime | None = None) -> dict:
    folder = data_root / session
    coverage = json.loads((folder / "coverage.json").read_text(encoding="utf-8"))
    if coverage["session"] != session:
        raise ValueError("Coverage session mismatch")
    now = (as_of or datetime.now(IST)).astimezone(IST)
    start = aware(coverage.get("window_start_inclusive"))
    cutoff = aware(coverage.get("window_end_exclusive"))
    if not (start and cutoff):
        raise ValueError("Coverage missing time-zone-aware window")
    # Never report a future cutoff as complete just because the feed says so.
    rows, docs = candidate_rows(
        read_jsonl(folder / "events.jsonl"),
        read_jsonl(folder / "pdf_extraction.jsonl"),
        start=start, cutoff=cutoff, as_of=now)
    return {
        "schema_version": SCHEMA, "session_date": session,
        "as_of": now.isoformat(), "cutoff_exclusive": cutoff.isoformat(),
        "news_window_start": start.isoformat(),
        "data_mode": "FROZEN_PREMARKET" if now < cutoff else "POST_CUTOFF_RESEARCH_PREVIEW_NOT_TRAINABLE",
        "universe_status": coverage.get("universe_status", "UNKNOWN"),
        "collector_last_poll_at": coverage.get("generated_at"),
        "source_failures_last_poll": coverage.get("sources_failed"),
        "company_count": len(rows), "documents_with_eligible_text": len(docs),
        "candidates": rows,
        "doc_evidence_register": docs,
        "training_allowed_only_if_immutable_and_before_cutoff": True,
        "execution_enabled": False,
        "cautions": [
            "A filing's publication before cutoff does NOT prove our system saw it before cutoff.",
            "A PDF parsed after cutoff is never used as a premarket feature.",
            "Figures are reported assertions; table period alignment and consensus surprises are NOT verified.",
            "Priority is an evidence discovery score, not a learned probability or trading direction.",
            "Preview created after cutoff is unsuitable for historical model evaluation.",
            "Premarket frozen snapshot includes collector_last_poll_at; intervening minutes may contain uncollected news.",
        ],
    }


def write_atomic(path: Path, data: dict, *, only_if_absent: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    if only_if_absent:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("schema_version") != SCHEMA:
                raise ValueError("Conflicting existing immutable candidate snapshot")
            return "EXISTS_NOT_OVERWRITTEN"
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
        return "CREATED_IMMUTABLE"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".tmp-", delete=False) as f:
        tmp = f.name
        f.write(text)
    os.replace(tmp, path)
    return "UPDATED_PREVIEW"


def run(session: str, *, data_root: Path = ROOT / "data",
        freeze: bool = False, as_of: datetime | None = None) -> dict:
    now = (as_of or datetime.now(IST)).astimezone(IST)
    payload = build_snapshot(session, data_root=data_root, as_of=now)
    folder = data_root / session
    if freeze:
        cutoff = aware(payload["cutoff_exclusive"])
        # Only after 08:50 and strictly before 09:00; no retroactive snapshots.
        if not (cutoff and cutoff.date() == now.date()
                and time(8, 50) <= now.timetz().replace(tzinfo=None) < time(9, 0)
                and now < cutoff):
            return {"session": session, "status": "FREEZE_REJECTED_OUTSIDE_PREMARKET_WINDOW",
                    "as_of": now.isoformat(), "company_count": payload["company_count"]}
        last_poll = aware(payload.get("collector_last_poll_at"))
        if not last_poll or not (0 <= (now - last_poll).total_seconds() <= 15 * 60):
            return {"session": session, "status": "FREEZE_REJECTED_STALE_COLLECTOR",
                    "as_of": now.isoformat(), "last_poll_at": payload.get("collector_last_poll_at")}
        if payload["company_count"] == 0 or not payload["universe_status"].startswith("OFFICIAL_FETCH:"):
            return {"session": session, "status": "FREEZE_REJECTED_NO_VERIFIED_UNIVERSE_OR_CANDIDATES",
                    "as_of": now.isoformat(), "company_count": payload["company_count"]}
        result = write_atomic(folder / "candidate_snapshot.json", payload, only_if_absent=True)
        return {"session": session, "status": result, "company_count": payload["company_count"],
                "as_of": now.isoformat()}
    write_atomic(folder / "candidate_preview.json", payload)
    return {"session": session, "status": "PREVIEW_ONLY", "company_count": payload["company_count"],
            "as_of": now.isoformat(), "eligible_doc_count": payload["documents_with_eligible_text"]}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--session-date")
    p.add_argument("--data-dir", type=Path, default=ROOT / "data")
    p.add_argument("--freeze", action="store_true")
    args = p.parse_args()
    print(json.dumps(run(args.session_date or default_session(datetime.now(IST)),
                         data_root=args.data_dir, freeze=args.freeze), indent=2))


if __name__ == "__main__":
    main()
