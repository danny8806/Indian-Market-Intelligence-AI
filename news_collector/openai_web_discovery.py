"""Opt-in OpenAI Responses web-search discovery for stock news.

Only cited source URLs are saved. The model's publication times, summaries and
directional claims are not promoted to verified event facts. Keep this service
separate from all trading and ranking logic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from news_collector.engine import (IST, ROOT, canonical_url, default_session,
                                   get_universe, read_jsonl, write_jsonl)
from news_collector.matching import match_issuers

DEFAULT_MODEL = "gpt-5.6"
MAX_DAILY_SEARCHES = 48


def approved_links(response: dict) -> list[dict]:
    """Extract links only from web_search tool source objects and URL citations."""
    links = {}
    for output in response.get("output", []):
        if not isinstance(output, dict):
            continue
        sources = ((output.get("action") or {}).get("sources") or [])
        for source in sources:
            if isinstance(source, dict):
                url = source.get("url")
                title = source.get("title") or "Source discovered by web search"
                _add(links, url, title)
        for content in output.get("content") or []:
            if not isinstance(content, dict):
                continue
            for annotation in content.get("annotations") or []:
                if not isinstance(annotation, dict):
                    continue
                data = annotation.get("url_citation") or annotation
                if annotation.get("type") == "url_citation" or "url_citation" in annotation:
                    _add(links, data.get("url"), data.get("title"))
    return list(links.values())[:50]


def _add(links: dict, url: str | None, title: str | None):
    from news_collector.engine import canonical_url
    u = canonical_url(url or "")
    if not u or urlsplit(u).scheme != "https":
        return
    host = urlsplit(u).hostname or ""
    if host in {"openai.com", "chatgpt.com"}:
        return
    links[u] = {"url": u, "title": " ".join((title or "").split())[:550]}


def status() -> str:
    if os.getenv("ENABLE_OPENAI_WEB_RESEARCH", "").strip().lower() != "true":
        return "SKIPPED_COST_GUARD"
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return "SKIPPED_NO_KEY"
    if not os.getenv("OPENAI_NEWS_MODEL", DEFAULT_MODEL).strip():
        return "SKIPPED_NO_MODEL"
    return "READY"


def daily_budget(value: str | None) -> int:
    try:
        limit = int(value or "6")
    except ValueError:
        raise ValueError("OPENAI_MAX_SEARCHES_PER_DAY must be integer") from None
    if not 1 <= limit <= MAX_DAILY_SEARCHES:
        raise ValueError("OPENAI_MAX_SEARCHES_PER_DAY must be 1..48")
    return limit


def search_once(client, *, model: str, prompt: str) -> list[dict]:
    response = client.responses.create(
        model=model,
        tools=[{"type": "web_search", "search_context_size": "low"}],
        tool_choice="required",
        include=["web_search_call.action.sources"],
        max_output_tokens=500,
        input=prompt,
    )
    data = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(data, dict):
        raise ValueError("Unexpected Responses API result")
    return approved_links(data)


def run(session_date: str, data_root: Path = ROOT / "data",
        *, now: datetime | None = None, client=None) -> dict:
    if status() != "READY":
        return {"status": status(), "provider": "OpenAI Responses web_search"}
    from news_collector.engine import window_for
    start, end = window_for(session_date)
    now = (now or datetime.now(IST)).astimezone(IST)
    limit = daily_budget(os.getenv("OPENAI_MAX_SEARCHES_PER_DAY"))
    data_root.mkdir(parents=True, exist_ok=True)
    budget_path = data_root / ("openai_web_budget_" + now.date().isoformat() + ".json")
    state = json.loads(budget_path.read_text(encoding="utf-8")) if budget_path.exists() else {}
    if int(state.get("attempts", 0)) >= limit:
        return {"status": "SKIPPED_DAILY_BUDGET", "attempts": state["attempts"],
                "daily_limit": limit}
    # Record the attempt *before* invoking a billable API. Do not blindly
    # retry an ambiguous timeout, which might have incurred a charge.
    count = int(state.get("attempts", 0)) + 1
    budget_path.write_text(json.dumps({
        "day_ist": now.date().isoformat(), "attempts": count,
        "limit": limit, "last_attempt_at": now.isoformat(),
    }, indent=2) + "\n", encoding="utf-8")
    if client is None:
        from openai import OpenAI
        client = OpenAI(timeout=45.0, max_retries=0)
    prompt = (
        "Use web search to locate NEW publicly indexed Indian listed-company "
        "corporate announcements, earnings, large orders, regulatory actions and "
        "significant financial news between " + start.isoformat()
        + " and " + min(now, end).isoformat()
        + ". Find source links rather than making forecasts. Focus on independent "
        "stories and official NSE/BSE disclosures. Cite source URLs for each "
        "result. If access is blocked, look for an official filing or issuer "
        "release for the same event. Do not invent publication times or assert "
        "that this is exhaustive."
    )
    links = search_once(client, model=os.getenv("OPENAI_NEWS_MODEL", DEFAULT_MODEL),
                        prompt=prompt)
    universe, universe_status = get_universe(data_root / "universe_snapshot.csv")
    target = data_root / session_date
    pending_path = target / "undated_candidates.jsonl"
    existing = read_jsonl(pending_path)
    for hit in links:
        url = hit["url"]
        heading = hit["title"] or urlsplit(url).hostname or "Search citation"
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        matched = match_issuers(heading, "", universe)
        row = {
            "id": key, "url": url, "headline": heading, "summary": "",
            "published_at": None, "first_seen_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "publication_time_status": "UNVERIFIED",
            "symbols": matched, "sources": ["OpenAI Responses web_search"],
            "providers": ["MEDIA"], "authorities": ["secondary"],
            "provider_reported_time_unverified": "",
        }
        if key in existing:
            original = existing[key]
            for field in ("sources", "symbols", "providers", "authorities"):
                row[field] = sorted(set(row[field]) | set(original.get(field) or []))
            row["first_seen_at"] = original.get("first_seen_at", row["first_seen_at"])
        existing[key] = row
    write_jsonl(pending_path, existing)
    result = {"status": "DISCOVERY_COMPLETED", "cited_urls_seen": len(links),
              "candidates_in_archive": len(existing),
              "matched_this_search": sum(bool(match_issuers(h["title"], "", universe))
                                         for h in links),
              "universe_status": universe_status, "attempts_today": count}
    (target / "openai_web_audit.json").write_text(
        json.dumps({**result, "checked_at": now.isoformat()}, indent=2) + "\n",
        encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--session-date")
    p.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = p.parse_args()
    session = args.session_date or default_session(datetime.now(IST))
    try:
        result = run(session, args.data_dir)
    except Exception as exc:
        # Optional provider errors must never stop core feeds/DB synchronization.
        # Do not log raw exception strings that might contain credentials.
        result = {"status": "OPENAI_DISCOVERY_FAILED",
                  "error_type": type(exc).__name__}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
