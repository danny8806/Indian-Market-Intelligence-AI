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
import os
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
from news_collector.broker_sources import allowed_by_robots, listing_items, research_json_items
from news_collector.matching import match_issuers
from news_collector.feed_resilience import rss_root, read_with_retry
from news_collector.provider_discovery import (
    fetch_provider_news, provider_api_items, provider_has_key,
)
from news_collector.index_discovery import fetch_search_index, search_index_items, search_index_available

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
MAX_BYTES = 14_000_000
MAX_ITEMS = 18_000
USER_AGENT = "IndianMarketResearchCollector/1.0 (public feeds; no login or bypass)"
UNIVERSE_URLS = (
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
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
    # Only parse fully stated date+clock+zone strings. Never fill a missing
    # year, clock or timezone from the fetch time.
    if (re.search(r'\b20\d{2}\b',val) and re.search(r'\d{1,2}:\d{2}',val)
            and re.search(r'\b(?:IST|UTC|GMT)\b|[+-]\d{2}:?\d{2}\s*$',val)):
        import dateparser
        parsed=dateparser.parse(re.sub(r'\bIST\b','+0530',val),settings={
            'STRICT_PARSING':True,'RETURN_AS_TIMEZONE_AWARE':True})
        if parsed is not None and parsed.tzinfo is not None:return parsed.astimezone(IST)
    if exchange in {"NSE", "BSE"}:
        for pattern in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
            try:
                return datetime.strptime(val, pattern).replace(tzinfo=IST)
            except ValueError:
                pass
    # A date without clock time is insufficient for 3 PM / 9 AM cutoff.
    return None


def regular_market_day(day) -> bool:
    """NSE regular cash session calendar, with published 2026 holiday list."""
    meta = json.loads((ROOT / "holidays_2026.json").read_text(encoding="utf-8"))
    return day.weekday() < 5 and day.isoformat() not in meta["holidays"]


def window_for(session_date: str) -> tuple[datetime, datetime]:
    day = datetime.strptime(session_date, "%Y-%m-%d").date()
    if not regular_market_day(day):
        raise ValueError(f"{session_date} is not a known regular NSE session")
    previous = day - timedelta(days=1)
    while not regular_market_day(previous):
        previous -= timedelta(days=1)
    return (datetime.combine(previous, dtime(15), IST),
            datetime.combine(day, dtime(9), IST))


def default_session(now: datetime) -> str:
    now = now.astimezone(IST)
    day = now.date()
    if now.time() >= dtime(15):
        day += timedelta(days=1)
    while not regular_market_day(day):
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
    deadline = time.monotonic() + timeout
    with requests.get(url, headers={"User-Agent": USER_AGENT,
                                     "Accept": "application/xml, application/rss+xml, text/html, text/csv, application/json, */*"},
                      timeout=(7, timeout), stream=True) as response:
        response.raise_for_status()
        length = int(response.headers.get("Content-Length") or 0)
        if length > MAX_BYTES:
            raise ValueError(f"Response too large: {length}")
        chunks, total = [], 0
        for chunk in response.iter_content(65536):
            # The requests read timeout applies per socket read. Enforce one
            # total wall-clock deadline so a slow-drip source cannot hold a
            # collector worker past the job budget.
            if time.monotonic() > deadline:
                raise requests.Timeout(f"Total fetch time exceeded {timeout}s")
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
    """Conservative alias-aware match for public headlines."""
    return match_issuers(title, summary, universe)


def rss_items(raw: bytes, source: dict) -> list[dict]:
    try:
        root = rss_root(raw, allow_truncated=bool(source.get("recover_truncated_rss", False)))
    except ET.ParseError:
        if not source.get("recover_malformed_rss", False):
            raise
        from news_collector.tool_extractors import complete_rss_items
        return complete_rss_items(raw, source, MAX_ITEMS)
    if local_name(root.tag) not in {"rss", "rdf", "feed"}:
        raise ValueError("Not RSS/Atom XML")
    if local_name(root.tag) == "feed":
        from news_collector.tool_extractors import atom_items
        return atom_items(raw, source, MAX_ITEMS)
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
            "scrip_code": fields.get("scripcode", ""),
            "filing_id": fields.get("filingid", ""),
            "original_time": bool(fields.get("pubdate") or fields.get("published") or fields.get("date")),
            "raw_time": ("" if source.get("timestamp_provenance") == "discovery"
                         else fields.get("pubdate") or fields.get("published") or fields.get("updated") or fields.get("date") or ""),
        })
        if len(found) >= MAX_ITEMS:
            break
    return found


ARTICLE_PATH = re.compile(
    r"/(?:news|markets/news|companies|industry|economy|earnings|stocks/news)/", re.I)
NAV_HEADLINES = {
    "read more", "view all", "click here", "sign in", "log in", "subscribe",
    "download app", "follow us", "share", "next", "previous",
}


def _fallback_listing_items(soup: BeautifulSoup, source: dict) -> list[dict]:
    """Recover plain article-card links on vetted listing pages.

    Some publishers do not wrap cards in ``article``/heading elements. This
    fallback is opt-in through ``verify_article`` because those same pages are
    allowed to fetch the publisher article and prove its publication time.
    Links without a real timestamp remain discovery-only and cannot become a
    signal on their own.
    """
    source_host = (urllib.parse.urlsplit(source["url"]).hostname or "").removeprefix("www.")
    found, seen = [], set()
    for a in soup.select("a[href]")[:2000]:
        headline = a.get_text(" ", strip=True)
        words = headline.split()
        if not 30 <= len(headline) <= 250 or len(words) < 5:
            continue
        if headline.casefold().strip(" .:") in NAV_HEADLINES:
            continue
        url = urllib.parse.urljoin(source["url"], a.get("href") or "")
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").removeprefix("www.")
        if (parsed.scheme not in {"http", "https"} or host != source_host
                or not ARTICLE_PATH.search(parsed.path)):
            continue
        canonical = canonical_url(url)
        if not canonical or canonical in seen or canonical == canonical_url(source["url"]):
            continue
        seen.add(canonical)
        bucket = a.find_parent(["article", "li", "div"])
        timestamp = bucket.find("time") if bucket else None
        raw_time = timestamp.get("datetime", "") if timestamp else ""
        summary = bucket.get_text(" ", strip=True)[:1800] if bucket else ""
        found.append({"headline": headline, "summary": summary, "url": url,
                      "raw_time": raw_time})
        if len(found) >= 150:
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
    if not found and source.get("verify_article"):
        found = _fallback_listing_items(soup, source)
    return found


def html_table_items(raw: bytes, source: dict) -> list[dict]:
    """Read a dated official HTML table using explicit column configuration.

    The publication time must come from the table's own timestamp column. Date-only
    values stay unverified and are never replaced with fetch time.
    """
    limit = source.get('max_items', 150)
    if type(limit) is not int or not 1 <= limit <= MAX_ITEMS:
        raise ValueError('Invalid public table item limit')
    soup = BeautifulSoup(raw, "html.parser")
    table = soup.select_one(source["table_selector"])
    if table is None:
        raise ValueError("Configured table not found")
    headers = [th.get_text(" ", strip=True) for th in table.select("thead th")]
    if not headers:
        raise ValueError("Configured table has no header row")
    positions = {name: index for index, name in enumerate(headers)}
    headline_columns = source.get("headline_columns") or []
    url_column = source.get("url_column", "")
    timestamp_column = source.get("timestamp_column", "")
    timestamp_format = source.get("timestamp_format", "")
    summary_columns = source.get("summary_columns") or []
    for column in [*headline_columns, url_column, timestamp_column]:
        if column and column not in positions:
            raise ValueError(f"Configured column missing: {column}")
    found = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < len(headers):
            continue

        def value(column: str) -> str:
            index = positions.get(column)
            return cells[index].get_text(" ", strip=True) if index is not None else ""

        headline = " - ".join(part for part in (value(column)
                                                for column in headline_columns) if part)
        link = cells[positions[url_column]].find("a", href=True) if url_column else None
        url = urllib.parse.urljoin(source["url"], link["href"]) if link else ""
        if not headline or not url:
            continue
        raw_time = ""
        if timestamp_column and timestamp_format:
            try:
                raw_time = datetime.strptime(
                    value(timestamp_column), timestamp_format).replace(tzinfo=IST).isoformat()
            except ValueError:
                raw_time = ""
        summary = " | ".join(part for part in (value(column)
                                               for column in summary_columns) if part)
        found.append({"headline": headline[:550], "summary": summary[:1800],
                      "url": url, "raw_time": raw_time})
        if len(found) >= limit:
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


def fetch_one(source: dict, *, raw_sink=None) -> tuple[dict, list[dict]]:
    began = time.monotonic()
    base = {"source": source["name"], "kind": source["kind"], "authority": source["authority"],
            "provider": source["provider"], "url": source["url"], "status": "ERROR",
            "fetched_items": 0, "verified_in_window": 0, "nifty500_matched": 0,
            "undated_items": 0, "out_of_window": 0}
    if not source.get("enabled", True):
        return ({**base, "status": "DISABLED"}, [])
    if source["kind"] == "indexed_search" and not search_index_available():
        return ({**base, "status": "SKIPPED_NO_KEY", "error": "Indexed-search backend not configured"}, [])
    if source["kind"] == "provider_api":
        if os.environ.get("ENABLE_PAID_NEWS_APIS", "").lower().strip() != "true":
            return ({**base, "status": "SKIPPED_COST_GUARD", "error": "Opt-in required via ENABLE_PAID_NEWS_APIS"}, [])
        if not provider_has_key(source):
            return ({**base, "status": "SKIPPED_NO_KEY", "error": "Provider key not configured"}, [])
    try:
        if source["kind"] in {"broker_html", "broker_json", "html_table"}:
            allowed, reason = allowed_by_robots(source["url"], USER_AGENT)
            if not allowed:
                return ({**base, "status": "BLOCKED_ROBOTS", "error": reason}, [])
        raw = (fetch_search_index(source) if source["kind"] == "indexed_search"
               else fetch_provider_news(source) if source["kind"] == "provider_api"
               else read_with_retry(source["url"],
                                    (lambda url: __import__('news_collector.transports',fromlist=['fetch']).fetch(url,source['transport'])) if source.get('transport') else fetch_bytes,
                                    max_attempts=source.get("max_attempts", 1)))
        if raw_sink is not None:
            try:
                raw_sink(source, raw, base)
            except Exception:
                # Raw-document capture must never discard the parsed evidence.
                pass
        if source["kind"] == "rss":
            items = rss_items(raw, source)
        elif source["kind"] == "html":
            items = html_items(raw, source)
        elif source["kind"] == "html_table":
            items = html_table_items(raw, source)
        elif source["kind"] == "broker_html":
            items = listing_items(raw, source)
        elif source["kind"] == "broker_json":
            items = research_json_items(raw, source)
        elif source["kind"] == "api":
            items = api_items(raw, source)
        elif source["kind"] == "indexed_search":
            items = search_index_items(raw, source)
        elif source["kind"] == "provider_api":
            items = provider_api_items(raw, source)
        else:
            raise ValueError("Unsupported source kind")
        if source.get('kind') in {'html','broker_html','html_table','rss'}:
            try:
                from news_collector.tool_router import enqueue_source
                enqueue_source(Path(os.getenv('NEWS_ARCHIVE_DIR',str(ROOT/'data'))),source,raw,items)
            except (OSError,ValueError):pass
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
    # Exchange filings belong to the company named in the filing title;
    # third-party mentions in its description must not become issuer signals.
    symbols = match_issuers(headline, item.get("summary", ""), universe,
                            official_filing=source["provider"] in {"NSE", "BSE"})
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
                    "provider_reported_time_unverified": item.get("provider_reported_time", ""),
                    "isin": str(item.get("isin") or "")[:12],
                    "financial_figures": item.get("financial_figures") or None,
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
    macro_context = read_jsonl(target / "macro_context.jsonl")
    # Revalidate persisted issuer matches when rules change; never leave stale
    # secondary-company mentions attached to exchange filings.
    if universe:
        for key in list(events):
            if set(events[key].get("providers", [])) & {"NSE", "BSE"}:
                issuer_symbols = match_issuers(events[key]["headline"], "", universe,
                                              official_filing=True)
                if issuer_symbols:
                    events[key]["symbols"] = issuer_symbols
                else:
                    del events[key]
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
                    elif row and src.get("market_context"):
                        # Macro/regulator records are research context, never stock signals.
                        merge_record(macro_context, row)
            summaries.append(stat)
    write_jsonl(target / "events.jsonl", events)
    write_jsonl(target / "undated_candidates.jsonl", pending)
    write_jsonl(target / "macro_context.jsonl", macro_context)
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
        "holiday_calendar": "NSE official regular-session holidays verified for 2026 only",
        "sources_configured": len(cfg), "sources_with_items": sum(s["status"] == "OK" for s in summaries),
        "sources_failed": sum(s["status"] == "ERROR" for s in summaries),
        "in_window_raw_items": sum(s["verified_in_window"] for s in summaries),
        "nifty500_matched_raw_items": sum(s["nifty500_matched"] for s in summaries),
        "stored_unique_matched_urls": len(events),
        "stored_undated_candidate_urls": len(pending),
        "stored_macro_context_urls": len(macro_context),
        "distinct_matched_symbols": len(by_symbol),
        "cross_source_symbol_presence_NOT_event_level_reconciliation": discrep,
        "sources": summaries,
        "limitations": [
            "Best-effort RSS/HTML/API collection; cannot guarantee all websites or full NSE/BSE filings.",
            "Date parsing validates format, not original publisher provenance.",
            "Search-index results are discovery-only without original publication timestamps.",
            "All optional API discovery is opt-in, metadata only, and not trade-eligible without primary-source timestamp verification.",
            "Unmatched regulator/global RSS items are separate macro context, not NIFTY 500 signals.",
            "HTML article links without reliable publication timestamps stay unverified.",
            "NSE/BSE records are not reconciled by ISIN/event ID; exchange_only is NOT proof of a missed story.",
            "Unknown, stale or unverified constituent snapshots prevent claims of complete NIFTY 500 coverage.",
            "NSE regular-session holiday table covers 2026 only; update before 2027 and account for exceptional special sessions.",
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
