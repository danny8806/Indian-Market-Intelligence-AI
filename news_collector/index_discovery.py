"""Optional, read-only Serper indexed discovery for public announcement aggregators.

Search results are leads, NOT verified original publication-time evidence. Never
convert search engine "date" fields or relative ages into pre-market timestamps.
No aggregator pages are crawled and no broker/order actions occur here.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

import requests

SERPER_ENDPOINT = "https://google.serper.dev/search"
MAX_SEARCH_RESULTS = 25


def search_index_items(raw: bytes, source: dict) -> list[dict]:
    """Parse an indexed-search response; only allow URLs on the declared domains."""
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("organic"), list):
        raise ValueError("Unexpected Serper search schema")
    allowed = tuple(str(x).lower().strip(".") for x in source.get("allowed_domains", []))
    if not allowed:
        raise ValueError("Indexed source must declare allowed_domains")
    records = []
    seen = set()
    for hit in payload["organic"]:
        if not isinstance(hit, dict):
            continue
        url = str(hit.get("link") or "").strip()
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not any(
            host == domain or host.endswith("." + domain) for domain in allowed
        ):
            continue
        if url in seen:
            continue
        title = " ".join(str(hit.get("title") or "").split())
        if not 12 <= len(title) <= 550:
            continue
        seen.add(url)
        records.append({
            "headline": title[:550],
            "summary": " ".join(str(hit.get("snippet") or "").split())[:1800],
            "url": url,
            # Search-index dates reflect discovery/updates, not necessarily
            # the original publisher or exchange disclosure timestamp.
            "raw_time": "",
        })
        if len(records) >= MAX_SEARCH_RESULTS:
            break
    return records


def fetch_search_index(source: dict) -> bytes:
    """Fetch search metadata only; API key is read from the runner environment."""
    key = os.environ.get("SERPER_API_KEY", "").strip()
    if not key:
        raise ValueError("SERPER_API_KEY not configured")
    query = source.get("search_query", "").strip()
    if not query or len(query) > 300:
        raise ValueError("Missing or overlong search query")
    # The past-week filter can span the preceding regular session across
    # weekends and holidays. Window eligibility is never inferred from it.
    response = requests.post(
        SERPER_ENDPOINT,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "gl": "in", "hl": "en", "num": MAX_SEARCH_RESULTS,
              "tbs": "qdr:w"},
        timeout=15,
        allow_redirects=False,
    )
    response.raise_for_status()
    if len(response.content) > 1_000_000:
        raise ValueError("Search response too large")
    return response.content
