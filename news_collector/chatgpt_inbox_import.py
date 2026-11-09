"""Import ChatGPT Scheduled Task GitHub evidence into research-only discovery.

No OpenAI API calls, no publisher crawling, no order placement. Even articles
with an AI-reported time remain discovery-only until checked independently.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from news_collector.engine import (IST, ROOT, build_record, default_session,
                                   get_universe, merge_record, read_jsonl,
                                   write_jsonl)

INBOX = ROOT / "chatgpt_inbox"
MAX_FILE_BYTES = 250_000
MAX_ARTICLES = 75
MAX_AGE_DAYS = 8
SOURCE = {
    "name": "ChatGPT Scheduled web discovery",
    "kind": "index", "provider": "MEDIA", "authority": "secondary",
    "url": "https://chatgpt.com/",
}


def _safe_url(url: str) -> bool:
    if not isinstance(url, str) or len(url) > 2500:
        return False
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    return bool(parsed.scheme == "https" and host
                and "." in host and not host.endswith((".local", ".internal"))
                and host not in {"localhost", "127.0.0.1", "::1"})


def parse_inbox_file(path: Path) -> list[dict]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("ChatGPT inbox file exceeds 250 KB")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "chatgpt-news-discovery/v1":
        raise ValueError("Unsupported ChatGPT inbox schema")
    raw = payload.get("articles")
    if not isinstance(raw, list) or len(raw) > MAX_ARTICLES:
        raise ValueError("Invalid article batch size")
    rows = []
    for entry in raw:
        if not isinstance(entry, dict) or not _safe_url(entry.get("url")):
            continue
        title = " ".join(str(entry.get("headline") or "").split())[:550]
        if len(title) < 12:
            continue
        summary = " ".join(str(entry.get("evidence_note") or "").split())[:1800]
        rows.append({
            "headline": title, "summary": summary,
            "url": entry["url"], "raw_time": "",  # ALWAYS discovery-only.
            "provider_reported_time": str(entry.get("publisher_time_claim") or "")[:80],
        })
    return rows


def import_inbox(*, root: Path = ROOT, now: datetime | None = None,
                 session: str | None = None, universe: dict | None = None) -> dict:
    now = now or datetime.now(IST)
    now = now.astimezone(IST)
    session = session or default_session(now)
    from news_collector.engine import window_for
    start, end = window_for(session)
    target = root / "data" / session
    existing = read_jsonl(target / "undated_candidates.jsonl")
    manifest = target / "chatgpt_inbox_processed.json"
    processed = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    if not isinstance(processed, dict):
        raise ValueError("Invalid processed inbox manifest")
    if universe is None:
        universe, _ = get_universe(root / "data" / "universe_snapshot.csv")
    inbox_dir = root / "chatgpt_inbox"
    found = imported = rejected = 0
    for path in sorted(inbox_dir.glob("*.json")) if inbox_dir.exists() else []:
        if path.name in processed:
            continue
        # Do not reimport ancient inbox files to a new trading-day session.
        if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) < now.astimezone(timezone.utc) - timedelta(days=MAX_AGE_DAYS):
            continue
        found += 1
        try:
            items = parse_inbox_file(path)
        except (OSError, ValueError, json.JSONDecodeError):
            rejected += 1
            continue
        for item in items:
            state, record = build_record(item, SOURCE, universe, start, end, now)
            if state == "UNVERIFIED_TIMESTAMP" and record is not None:
                merge_record(existing, record)
                imported += 1
        processed[path.name] = now.isoformat()
    write_jsonl(target / "undated_candidates.jsonl", existing)
    target.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(processed, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    report = {
        "status": "CHATGPT_INBOX_IMPORTED", "session": session,
        "new_files": found, "accepted_discovery_links": imported,
        "invalid_files": rejected, "total_undated_candidates": len(existing),
        "all_imported_times_unverified": True,
    }
    (target / "chatgpt_inbox_audit.json").write_text(
        json.dumps({**report, "processed_at": now.isoformat()}, indent=2) + "\n",
        encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--session-date", default=None)
    args = p.parse_args()
    print(json.dumps(import_inbox(session=args.session_date)))


if __name__ == "__main__":
    main()
