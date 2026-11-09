"""Credential-gated licensed/search news provider discovery.

Discovery-only: provider publication fields are NOT trusted original disclosure
timestamps; no returned hit enters pre-open trade-eligible events without
independent verification. Only metadata, short snippets and URLs are retained.
No publisher page crawling and no exchange/broker order access.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

import requests

MAX_RESULTS = 50
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_QUERY = "India NSE BSE listed companies quarterly results orders contracts regulatory news"

PROVIDERS = {
    "tavily": ("TAVILY_API_KEY", "https://api.tavily.com/search"),
    "exa": ("EXA_API_KEY", "https://api.exa.ai/search"),
    "brave": ("BRAVE_SEARCH_API_KEY", "https://api.search.brave.com/res/v1/news/search"),
    "marketaux": ("MARKETAUX_API_TOKEN", "https://api.marketaux.com/v1/news/all"),
    "gnews": ("GNEWS_API_KEY", "https://gnews.io/api/v4/search"),
    "newsdata": ("NEWSDATA_API_KEY", "https://newsdata.io/api/1/latest"),
    "newsapi": ("NEWSAPI_API_KEY", "https://newsapi.org/v2/everything"),
}


def provider_has_key(source: dict) -> bool:
    p = str(source.get("api_provider", "")).lower()
    if p not in PROVIDERS:
        raise ValueError("Unknown news API provider")
    return bool(os.environ.get(PROVIDERS[p][0], "").strip())


def _api_request(source: dict, key: str):
    provider = source["api_provider"].lower()
    endpoint = PROVIDERS[provider][1]
    query = (source.get("search_query") or DEFAULT_QUERY).strip()
    if not 5 <= len(query) <= 190:
        raise ValueError("News search query outside 5-190 characters")
    headers = {"Accept": "application/json"}
    kw = {"timeout": (6, 15), "allow_redirects": False}
    if provider == "tavily":
        headers["Authorization"] = "Bearer " + key
        kw["json"] = {"query": query, "search_depth": "basic", "max_results": 20,
                      "include_answer": False, "include_raw_content": False}
        method = requests.post
    elif provider == "exa":
        headers["x-api-key"] = key
        kw["json"] = {"query": query, "type": "auto", "numResults": 20}
        method = requests.post
    elif provider == "brave":
        headers["X-Subscription-Token"] = key
        kw["params"] = {"q": query, "country": "IN", "search_lang": "en", "count": 20}
        method = requests.get
    elif provider == "marketaux":
        kw["params"] = {"api_token": key, "search": query, "language": "en", "limit": 20}
        method = requests.get
    elif provider == "gnews":
        kw["params"] = {"apikey": key, "q": query, "lang": "en", "country": "in", "max": 10}
        method = requests.get
    elif provider == "newsdata":
        kw["params"] = {"apikey": key, "q": query, "language": "en",
                        "country": "in"}
        method = requests.get
    elif provider == "newsapi":
        kw["params"] = {"apiKey": key, "q": query, "language": "en",
                        "pageSize": 20, "sortBy": "publishedAt"}
        method = requests.get
    else:
        raise ValueError("Unrecognized news API provider")
    kw["headers"] = headers
    # Never expose raw requests errors: GET error strings can include API keys.
    try:
        response = method(endpoint, **kw)
        if response.status_code != 200:
            raise RuntimeError("NEWS_API_HTTP_" + str(response.status_code))
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ValueError("NEWS_API_RESPONSE_TOO_LARGE")
        return response.content
    except requests.RequestException as exc:
        raise RuntimeError("NEWS_API_NETWORK_" + type(exc).__name__) from None


def fetch_provider_news(source: dict) -> bytes:
    p = str(source.get("api_provider", "")).lower()
    if p not in PROVIDERS:
        raise ValueError("Unknown news API provider")
    key = os.environ.get(PROVIDERS[p][0], "").strip()
    if not key:
        raise ValueError("MISSING_NEWS_API_KEY")
    return _api_request(source, key)


def provider_api_items(raw: bytes, source: dict) -> list[dict]:
    provider = str(source.get("api_provider", "")).lower()
    if provider not in PROVIDERS:
        raise ValueError("Unknown news API provider")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("News API schema must be JSON object")
    if provider in {"tavily", "exa", "brave", "newsdata"}:
        arr = obj.get("results")
    elif provider == "marketaux":
        arr = obj.get("data")
    else:
        arr = obj.get("articles")
    if not isinstance(arr, list):
        raise ValueError("Unexpected news API articles schema")
    seen, result = set(), []
    for entry in arr[:MAX_RESULTS * 2]:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or entry.get("link") or "").strip()
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or url in seen:
            continue
        title = " ".join(str(entry.get("title") or "").split())
        if not 12 <= len(title) <= 550:
            continue
        summary = " ".join(str(
            entry.get("description") or entry.get("snippet") or entry.get("content") or ""
        ).split())
        seen.add(url)
        result.append({
            "headline": title[:550], "summary": summary[:1200], "url": url,
            "raw_time": "",  # Search metadata is not an original filing timestamp.
            "provider_reported_time": str(
                entry.get("published_at") or entry.get("publishedAt")
                or entry.get("publishedDate") or entry.get("pubDate")
                or entry.get("pubDateTZ") or ""
            )[:80],
        })
        if len(result) >= MAX_RESULTS:
            break
    return result
