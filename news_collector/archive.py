"""Collect around the clock without using the morning research window as a filter."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path
from uuid import uuid4

import requests

from news_collector.engine import (
    IST, ROOT, build_record, fetch_bytes, fetch_one, get_universe, parse_universe_csv,
)

NSE_MASTER = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"


def equity_master(body: str) -> dict[str, str]:
    reader = csv.DictReader(io.StringIO(body))
    result = {}
    for raw in reader:
        row = {key.strip().upper(): (value or "").strip() for key, value in raw.items() if key}
        symbol = row.get("SYMBOL", "").upper()
        if (re.fullmatch(r"[A-Z0-9&._-]{2,30}", symbol)
                and re.fullmatch(r"IN[A-Z0-9]{10}", row.get("ISIN NUMBER", ""))
                and row.get("NAME OF COMPANY")):
            result[symbol] = row["NAME OF COMPANY"]
    return result


def load_universes(root: Path, now: datetime) -> tuple[dict, dict, bool]:
    root.mkdir(parents=True, exist_ok=True)
    master_path = root / "nse_equities.csv"
    nifty_path = root / "universe_snapshot.csv"
    verified_path = root / "nifty_snapshot_verified"

    def fresh(path):
        return path.is_file() and 0 <= now.timestamp() - path.stat().st_mtime < 86400

    verified = fresh(verified_path) and nifty_path.is_file()
    if verified:
        nifty = parse_universe_csv(nifty_path.read_text(encoding="utf-8"))
    else:
        nifty, status = get_universe(nifty_path)
        verified = status.startswith("OFFICIAL_FETCH:")
        if verified:
            verified_path.write_text(status + "\n", encoding="utf-8")
    broader = {}
    if not fresh(master_path):
        try:
            body = fetch_bytes(NSE_MASTER, timeout=10).decode("utf-8-sig")
            if len(equity_master(body)) >= 1000:
                master_path.write_text(body, encoding="utf-8")
        except (requests.RequestException, UnicodeError, ValueError):
            pass
    if master_path.is_file():
        broader = equity_master(master_path.read_text(encoding="utf-8"))
    return nifty, {**broader, **nifty}, verified


def trusted_origin(source: dict, url: str) -> bool:
    from urllib.parse import urlsplit

    if source["kind"] != "rss" or source.get("timestamp_provenance") == "discovery":
        return False
    feed = (urlsplit(source["url"]).hostname or "").removeprefix("www.")
    origin = (urlsplit(url).hostname or "").removeprefix("www.")
    if not origin or urlsplit(url).scheme != "https":
        return False
    if source["provider"] in {"NSE", "BSE"}:
        domain = "nseindia.com" if source["provider"] == "NSE" else "bseindia.com"
        return origin == domain or origin.endswith("." + domain)
    return origin == feed


def observation(item: dict, source: dict, observed: datetime, universe: dict,
                nifty: dict, *, discoverer: str) -> dict | None:
    # Accept historical records exposed by the source without conflating a
    # rolling archive with the separately enforced premarket cutoff.
    _, row = build_record(item, source, universe, datetime(1970, 1, 1, tzinfo=IST),
                          observed + timedelta(minutes=2), observed)
    if row is None:
        return None
    filing_id = item.get("filing_id")
    if filing_id and source["provider"] in {"NSE", "BSE"}:
        row["id"] = hashlib.sha256(
            f'{source["provider"]}:{filing_id}'.encode()).hexdigest()[:24]
    # The original BSE RSS explicitly identifies each issuer by scrip code.
    # Store that exchange identity even if the company has no NSE listing.
    code = item.get("scrip_code", "")
    if source["provider"] == "BSE" and re.fullmatch(r"[0-9]{6}", code):
        row["symbols"] = sorted({*row["symbols"], f"BSE:{code}"})
    if item.get("shared_broker_link"):
        row["id"] = hashlib.sha256(
            f'{row["url"]}:{row["headline"]}'.encode()).hexdigest()[:24]
    row["discoverer"] = discoverer
    row["nifty_symbols"] = sorted(set(row["symbols"]) & nifty.keys())
    row["verified_origin"] = bool(
        row["published_at"] and (item.get("origin_verified") or
            (item.get("original_time") and trusted_origin(source, row["url"]))))
    if not row["published_at"]:
        row["kind"] = "discovery_only"
    elif row["symbols"]:
        row["kind"] = "timestamped_stock"
    else:
        row["kind"] = "macro_context"
    return row


def collect_batch(root: Path, *, clock=lambda: datetime.now(IST), config=ROOT / "sources.json"):
    started = clock()
    nifty, universe, verified = load_universes(root, started)
    sources = json.loads(config.read_text(encoding="utf-8"))["sources"]
    rows, checks = [], []

    def retrieve(source):
        stats, items = fetch_one(source)
        return stats, items, clock()

    with ThreadPoolExecutor(max_workers=4) as pool:
        for source, (stats, items, observed) in zip(sources, pool.map(retrieve, sources)):
            checks.append(stats)
            for item in items:
                row = observation(item, source, observed, universe, nifty if verified else {},
                                  discoverer="python")
                if row and (row["published_at"] or row["symbols"] or source["kind"] == "broker_html"):
                    rows.append(row)
    return {
        "batch_id": uuid4().hex,
        "session": started.astimezone(IST).date().isoformat(),
        "generated_at": clock().isoformat(),
        "sources_configured": len(checks),
        "sources_with_items": sum(check["status"] == "OK" for check in checks),
        "sources_failed": sum(check["status"] == "ERROR" for check in checks),
        "sources_blocked": sum(check["status"] == "BLOCKED_ROBOTS" for check in checks),
        "sources": checks,
        "records": rows,
        "nifty_count": len(nifty) if verified else 0,
        "nifty_membership_verified": verified,
        "listed_count": len(universe),
    }, (nifty if verified else {}), universe


def stage(root: Path, batch: dict) -> Path:
    queue = root / "pending_batches"
    queue.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.fromisoformat(batch["generated_at"]).strftime("%Y%m%d%H%M%S%f")
    path = queue / f'{timestamp}-{batch["batch_id"]}.json'
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as output:
        json.dump(batch, output, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    temp.replace(path)
    return path


def replay(engine, root: Path) -> int:
    from news_collector.db_store import sync_archive_batch

    total = 0
    for path in sorted((root / "pending_batches").glob("*.json")):
        if total >= 12:
            break
        sync_archive_batch(engine, json.loads(path.read_text(encoding="utf-8")))
        path.unlink()
        total += 1
    return total
