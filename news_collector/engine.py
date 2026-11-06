"""Read-only, best-effort overnight NIFTY 500 news collection.

Does not trade or rank stocks. Invalid/missing publication timestamps never become
eligible overnight signals. Public endpoints only; obey source terms/robots.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, time as dtime
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
MAX_BYTES = 14_000_000
MAX_ITEMS = 18_000
USER_AGENT = "IndianMarketResearchCollector/1.0 (public feeds; no login or bypass)"
UNIVERSE_URLS = (
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
)
FINANCE_TERMS = re.compile(
    r"\b(results?|earnings|profit|loss|revenue|ebitda|margin|order|contract|"
    r"acquisition|merger|approval|penalty|gst|sebi|fda|stake|buyback|dividend|"
    r"guidance|resignation|investor|capacity|ipo|q[1-4]|quarter|regulat)\b", re.I
)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_timestamp(value: str, *, exchange: str = "") -> datetime | None:
    """Accept timezone-aware ISO/RFC and official exchange local timestamps only."""
    val = (value or "").strip()
    if not val:
        return None
    try:
        t = parsedate_to_datetime(val)
        if t is not None and t.tzinfo is not None:
            return t.astimezone(IST)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        t = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if t.tzinfo is not None and ("T" in val or " " in val):
            return t.astimezone(IST)
    except ValueError:
        pass
    if exchange in {"NSE", "BSE"}:
        try:
            return datetime.strptime(val, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
        except ValueError:
            pass
    # A date without clock time is insufficient for 3 PM / 9 AM cutoff.
    return None


def window_for(session_date: str) -> tuple[datetime, datetime]:
    day = datetime.strptime(session_date, "%Y-%m-%d").date()
    previous = day - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return (datetime.combine(previous, dtime(15), IST),
            datetime.combine(day, dtime(9), IST))


def default_session(now: datetime) -> str:
    now = now.astimezone(IST)
    day = now.date()
    if now.time() >= dtime(15):
        day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def canonical_url(url: str) -> str:
    try:
        u = urllib.parse.urlsplit(url.strip())
        if u.scheme not in ("http", "https") or not u.netloc:
            return ""
        query = urllib.parse.parse_qsl(u.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
        return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc.lower(),
                    re.sub(r"/+$", "", u.path) or "/", urllib.parse.urlencode(sorted(query)), ""))
    except ValueError:
        return ""


def norm_name(name: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", name or "")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    s = re.sub(r"\b(the|ltd|limited|company|co|private|pvt)\b", " ", s)
    return " ".join(s.split())


def parse_universe_csv(body: str) -> dict[str, str]:
    rd = csv.DictReader(io.StringIO(body.lstrip("\ufeff")))
    if not rd.fieldnames or "Symbol" not in rd.fieldnames or "Company Name" not in rd.fieldnames:
        raise ValueError("CSV lacks official Symbol and Company Name columns")
    found = {}
    for row in rd:
        sym = (row.get("Symbol") or "").strip().upper()
        name = (row.get("Company Name") or "").strip()
        if re.fullmatch(r"[A-Z0-9&._-]{2,32}", sym) and name:
            found[sym] = name
    if not 450 <= len(found) <= 550:
        raise ValueError(f"Constituent count {len(found)} outside expected range")
    return found


def fetch_bytes(url: str, *, timeout: int = 23) -> bytes:
    """Polite single GET, no authentication/bypass; never follow arbitrary link crawls."""
    with requests.get(url, headers={"User-Agent": USER_AGENT,
                                     "Accept": "application/xml, application/rss+xml, text/html, text/csv, application/json, */*"},
                      timeout=(7, timeout), stream=True) as response:
        response.raise_for_status()
        length = int(response.headers.get("Content-Length") or 0)
        if length > MAX_BYTES:
            raise ValueError(f"Response too large: {length}")
        chunks, total = [], 0
        for chunk in response.iter_content(65536):
            total += len(chunk)
            if total > MAX_BYTES:
                raise ValueError("Response exceeded size cap")
            chunks.append(chunk)
        return b"".join(chunks)


def get_universe(cache_path: Path) -> tuple[dict[str, str], str]:
    """Use a fresh official snapshot; fallback only to an explicitly stored snapshot."""
    for url in UNIVERSE_URLS:
        try:
            b = fetch_bytes(url, timeout=14)
            text = b.decode("utf-8-sig")
            universe = parse_universe_csv(text)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
            return universe, f"OFFICIAL_FETCH:{url}"
        except (requests.RequestException, UnicodeError, ValueError):
            continue
    if cache_path.exists():
        return parse_universe_csv(cache_path.read_text(encoding="utf-8")), "CACHED_SNAPSHOT_STALENESS_UNKNOWN"
    return {}, "UNAVAILABLE_NO_VERIFIED_CONSTITUENTS"


def universe_match(title: str, summary: str, universe: dict[str, str]) -> list[str]:
    """Exact company-name or explicitly labeled ticker matching; no fuzzy guessing."""
    if not universe:
        return []
    text = f"{title} {summary}"
    norm = norm_name(text)
    title_norm = norm_name(title)
    exact = {norm_name(company): ticker for ticker, company in universe.items()
             if len(norm_name(company)) >= 5}
    names = set()
    if title_norm in exact:
        names.add(exact[title_norm])
    for company_name, ticker in exact.items():
        if len(company_name) >= 8 and re.search(r"(?<!\w)" + re.escape(company_name) + r"(?!\w)", norm):
            names.add(ticker)
    for symbol in re.findall(r"\b(?:NSE|NSE SYMBOL)\s*:\s*([A-Z0-9&._-]{2,32})\b", text):
        if symbol in universe:
            names.add(symbol)
    # BSE RSS title is often "Company ltd (123456)"; company-name match above applies.
    return sorted(names)


def rss_items(raw: bytes, source: dict) -> list[dict]:
    root = ET.fromstring(raw)
    if local_name(root.tag) not in {"rss", "rdf", "feed"}:
        raise ValueError("Not RSS/Atom XML")
    found = []
    for entry in root.iter():
        if local_name(entry.tag) not in {"item", "entry"}:
            continue
        fields = {}
        for c in entry:
            k = local_name(c.tag)
            value = (c.text or "").strip()
            if k == "link" and not value:
                value = c.attrib.get("href", "")
            if k not in fields and value:
                fields[k] = value
        headline = fields.get("title", "")
        url = fields.get("link", "")
        if not headline or not url:
            continue
        found.append({
            "headline": headline[:550],
            "summary": BeautifulSoup(fields.get("description", ""), "html.parser").get_text(" ", strip=True)[:1800],
            "url": url,
            "raw_time": fields.get("pubdate") or fields.get("published") or fields.get("updated") or fields.get("date") or "",
        })
        if len(found) >= MAX_ITEMS:
            break
    return found


def html_items(raw: bytes, source: dict) -> list[dict]:
    """Extract candidate article links, but require per-article <time datetime> to qualify."""
    soup = BeautifulSoup(raw, "html.parser")
    found, seen = [], set()
    for a in soup.select("article a[href], h2 a[href], h3 a[href], h4 a[href]")[:500]:
        headline = a.get_text(" ", strip=True)
        url = urllib.parse.urljoin(source["url"], a.get("href") or "")
        if not 22 <= len(headline) <= 350 or not canonical_url(url) or url in seen:
            continue
        seen.add(url)
        ancestor = a.find_parent("article")
        timestamp = ancestor.find("time") if ancestor else None
        raw_time = timestamp.get("datetime", "") if timestamp else ""
        summary = ancestor.get_text(" ", strip=True)[:1800] if ancestor else ""
        found.append({"headline": headline, "summary": summary, "url": url, "raw_time": raw_time})
        if len(found) >= 150:
            break
    return found


def api_items(raw: bytes, source: dict) -> list[dict]:
    d = json.loads(raw)
    arr = d.get("articles", []) if isinstance(d, dict) else []
    if not isinstance(arr, list):
        raise ValueError("Unexpected JSON schema")
    # GDELT seendate is discovery date, not original article publication time.
    return [{"headline": i.get("title", ""), "summary": "", "url": i.get("url", ""), "raw_time": ""}
            for i in arr[:500] if isinstance(i, dict)]


def fetch_one(source: dict) -> tuple[dict, list[dict]]:
    began = time.monotonic()
    base = {"source": source["name"], "kind": source["kind"], "authority": source["authority"],
            "provider": source["provider"], "url": source["url"], "status": "ERROR",
            "fetched_items": 0, "verified_in_window": 0, "nifty500_matched": 0,
            "undated_items": 0, "out_of_window": 0}
    if not source.get("enabled", True):
        return ({**base, "status": "DISABLED"}, [])
    try:
        raw = fetch_bytes(source["url"])
        if source["kind"] == "rss":
            items = rss_items(raw, source)
        elif source["kind"] == "html":
            items = html_items(raw, source)
        elif source["kind"] == "api":
            items = api_items(raw, source)
        else:
            raise ValueError("Unsupported source kind")
        base.update(status="OK" if items else "EMPTY", fetched_items=len(items), bytes=len(raw))
        return (base, items)
    except Exception as e:
        base["error"] = f"{type(e).__name__}: {str(e)[:180]}"
        return (base, [])
    finally:
        base["elapsed_seconds"] = round(time.monotonic() - began, 2)


def read_jsonl(path: Path) -> dict[str, dict]:
    rows = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["id"]] = row
    return rows


def write_jsonl(path: Path, rows: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                           for r in sorted(rows.values(), key=lambda x: x["id"])),
                   encoding="utf-8")
    tmp.replace(path)


def build_record(item: dict, source: dict, universe: dict[str, str],
                 start: datetime, end: datetime, fetched_at: datetime) -> tuple[str, dict | None]:
    url = canonical_url(item.get("url", ""))
    headline = item.get("headline", "").strip()
    if not url or not headline:
        return "INVALID", None
    timestamp = parse_timestamp(item.get("raw_time", ""), exchange=source["provider"])
    symbols = universe_match(headline, item.get("summary", ""), universe)
    status = ("UNVERIFIED_TIMESTAMP" if timestamp is None
              else "OUT_OF_WINDOW" if not start <= timestamp < end
              else "IN_WINDOW")
    if status == "OUT_OF_WINDOW":
        return status, None
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return status, {"id": digest, "url": url, "headline": headline, "summary": item.get("summary", "")[:1800],
                    "published_at": timestamp.isoformat() if timestamp else None,
                    "first_seen_at": fetched_at.isoformat(), "last_seen_at": fetched_at.isoformat(),
                    "publication_time_status": "VERIFIED_FORMAT" if timestamp else "UNVERIFIED",
                    "symbols": symbols,
                    "sources": [source["name"]], "providers": [source["provider"]],
                    "authorities": [source["authority"]]}


def merge_record(rows: dict[str, dict], item: dict) -> None:
    prev = rows.get(item["id"])
    if prev is None:
        rows[item["id"]] = item
        return
    for field in ("symbols", "sources", "providers", "authorities"):
        prev[field] = sorted(set(prev[field]) | set(item[field]))
    if item["published_at"] and (not prev["published_at"] or item["published_at"] < prev["published_at"]):
        prev["published_at"] = item["published_at"]
        prev["publication_time_status"] = "VERIFIED_FORMAT"
    prev["last_seen_at"] = item["last_seen_at"]


def run(session: str, output_dir: Path, *, config: Path = ROOT / "sources.json",
        universe_csv: Path | None = None, workers: int = 4) -> dict:
    begin, end = window_for(session)
    now = datetime.now(IST)
    if universe_csv is not None:
        universe = parse_universe_csv(universe_csv.read_text(encoding="utf-8"))
        universe_status = f"PROVIDED_SNAPSHOT:{universe_csv.name}"
    else:
        universe, universe_status = get_universe(output_dir / "universe_snapshot.csv")
    cfg = json.loads(config.read_text(encoding="utf-8"))["sources"]
    target = output_dir / session
    events = read_jsonl(target / "events.jsonl")
    pending = read_jsonl(target / "undated_candidates.jsonl")
    summaries = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 6))) as pool:
        results = pool.map(fetch_one, cfg)
        for src, (stat, entries) in zip(cfg, results):
            for entry in entries:
                state, row = build_record(entry, src, universe, begin, end, now)
                if state == "OUT_OF_WINDOW":
                    stat["out_of_window"] += 1
                elif state == "UNVERIFIED_TIMESTAMP":
                    stat["undated_items"] += 1
                    if row and row["symbols"]:
                        merge_record(pending, row)
                elif state == "IN_WINDOW":
                    stat["verified_in_window"] += 1
                    if row and row["symbols"]:
                        stat["nifty500_matched"] += 1
                        merge_record(events, row)
            summaries.append(stat)
    write_jsonl(target / "events.jsonl", events)
    write_jsonl(target / "undated_candidates.jsonl", pending)
    by_symbol = defaultdict(set)
    for row in events.values():
        for symbol in row["symbols"]:
            by_symbol[symbol].update(row["providers"])
    discrep = {"exchange_only": [], "media_only": [], "exchange_and_media": []}
    for symbol, providers in sorted(by_symbol.items()):
        official = bool(providers & {"NSE", "BSE"})
        media = "MEDIA" in providers
        bucket = ("exchange_and_media" if official and media else
                  "exchange_only" if official else "media_only")
        discrep[bucket].append(symbol)
    coverage = {
        "session": session, "generated_at": now.isoformat(),
        "window_start_inclusive": begin.isoformat(), "window_end_exclusive": end.isoformat(),
        "universe_status": universe_status, "nifty500_count": len(universe),
        "sources_configured": len(cfg), "sources_with_items": sum(s["status"] == "OK" for s in summaries),
        "sources_failed": sum(s["status"] == "ERROR" for s in summaries),
        "in_window_raw_items": sum(s["verified_in_window"] for s in summaries),
        "nifty500_matched_raw_items": sum(s["nifty500_matched"] for s in summaries),
        "stored_unique_matched_urls": len(events),
        "stored_undated_candidate_urls": len(pending),
        "distinct_matched_symbols": len(by_symbol),
        "cross_source_symbol_presence_NOT_event_level_reconciliation": discrep,
        "sources": summaries,
        "limitations": [
            "Best-effort RSS/HTML/API collection; cannot guarantee all websites or full NSE/BSE filings.",
            "Date parsing validates format, not original publisher provenance.",
            "HTML article links without reliable publication timestamps stay unverified.",
            "NSE/BSE records are not reconciled by ISIN/event ID; exchange_only is NOT proof of a missed story.",
            "Unknown, stale or unverified constituent snapshots prevent claims of complete NIFTY 500 coverage.",
            "Weekdays used for automatic previous-session inference; override session on NSE holidays.",
            "No stock direction, trading orders, position sizing or portfolio execution."
        ],
    }
    target.mkdir(parents=True, exist_ok=True)
    (target / "coverage.json").write_text(json.dumps(coverage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (target / "polls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"checked_at": now.isoformat(), "sources_ok": coverage["sources_with_items"],
                    "sources_failed": coverage["sources_failed"], "unique_urls": len(events)}) + "\n")
    return coverage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-date", help="Target NSE session YYYY-MM-DD")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--universe-csv", type=Path)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    day = args.session_date or default_session(datetime.now(IST))
    report = run(day, args.data_dir, universe_csv=args.universe_csv, workers=args.workers)
    print(json.dumps({k: v for k, v in report.items() if k not in ("sources", "limitations",
                      "cross_source_symbol_presence_NOT_event_level_reconciliation")}, indent=2))
    if not report["nifty500_count"]:
        print("WARNING: NIFTY 500 universe unavailable; no matched stocks can be certified", file=sys.stderr)


if __name__ == "__main__":
    main()
