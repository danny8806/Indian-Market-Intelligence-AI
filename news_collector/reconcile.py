"""Research-only source-gap audit: reconciliation candidates, never proof of omissions."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

KEYWORDS = (
    ("regulatory", r"\b(?:sebi|gst\s+(?:notice|demand|penalty)|penalt(?:y|ies)|drug\s+regulator|fda|show.cause|litigation|regulatory)\b"),
    ("financial_results", r"\b(?:financial\s+results|quarterly\s+results|q[1-4]\s+results|standalone\s+(?:profit|loss)|consolidated\s+(?:profit|loss)|ebitda|earnings\s+(?:release|result)|profit\s+(?:rose|fell|down|up)|results\s+for\s+the\s+period)\b"),
    ("orders_contracts", r"\b(?:purchase\s+order|work\s+order|contract\s+(?:award|win|receive)|order\s+book|order\s+worth|letter\s+of\s+award|project\s+awarded)\b"),
    ("fundraising", r"\b(?:fundraise|fund.rais|qip|preferential\s+issu|issue\s+of\s+securities|debt\s+raising|rights\s+issue)\b"),
    ("acquisition", r"\b(?:acquisition|merger|amalgamation|stake\s+purchase|business\s+transfer|acquires)\b"),
    ("management", r"\b(?:change\s+in\s+directors|appointment\s+of\s+director|resignation|change\s+in\s+kmp)\b"),
    ("analyst_meetings", r"\b(?:analyst\s+meet|investor\s+meet|concall|conference\s+call\s+transcript|transcript\s+of\s+(?:meeting|earnings))\b"),
    ("corporate_actions", r"\b(?:dividend|record\s+date|stock\s+split|buyback|bonus\s+issue)\b"),
)


def event_kind(headline: str, summary: str = "") -> str:
    text = (headline + " " + summary).lower()
    # Standalone analyst materials are not fresh results.
    if re.search(r"\b(?:earnings?\s+call\s+transcript|conference\s+call\s+transcript|investor\s+meet|analyst\s+meet)\b", text):
        return "analyst_meetings"
    for label, pattern in KEYWORDS:
        if re.search(pattern, text):
            return label
    return "other"


MATERIAL = frozenset({"financial_results", "orders_contracts", "regulatory",
                       "fundraising", "acquisition"})


def source_reconciliation(events: list[dict], *, as_of: str, session: str,
                          source_status: list[dict] | None = None) -> dict:
    """Corroborate issuer AND event category, but never claim exact announcement identity.

    Two different filings by the same issuer/category may be unrelated. Both-venue
    appearances are only a *potential* match, not evidence of identical documents.
    """
    groups: dict[tuple[str, str], dict] = {}
    for e in events:
        kind = event_kind(e.get("headline", ""), e.get("summary", ""))
        if kind not in MATERIAL:
            continue
        for sym in e.get("symbols", []):
            key = (sym, kind)
            target = groups.setdefault(key, {
                "symbol": sym, "event_category": kind, "exchanges": set(),
                "media_count": 0, "nse_count": 0, "bse_count": 0,
                "filing_examples": [], "media_examples": []})
            providers = set(e.get("providers", []))
            for venue in ("NSE", "BSE"):
                if venue in providers:
                    target["exchanges"].add(venue)
                    target[venue.lower() + "_count"] += 1
            if "MEDIA" in providers:
                target["media_count"] += 1
            item = {"headline": e.get("headline", "")[:180],
                    "url": e.get("url"), "published_at": e.get("published_at")}
            if providers & {"NSE", "BSE"} and len(target["filing_examples"]) < 3:
                target["filing_examples"].append(item)
            elif "MEDIA" in providers and len(target["media_examples"]) < 2:
                target["media_examples"].append(item)
    rows, counters = [], Counter()
    for key, g in sorted(groups.items()):
        ex = g.pop("exchanges")
        if ex == {"NSE", "BSE"}:
            state = "BOTH_EXCHANGES_SAME_ISSUER_CATEGORY_NOT_CONFIRMED_SAME_EVENT"
        elif ex:
            state = "SINGLE_EXCHANGE_CANDIDATE_REVIEW_NOT_CONFIRMED_MISS"
        else:
            state = "MEDIA_ONLY_CANDIDATE_REVIEW_NOT_CONFIRMED_MISS"
        g["state"] = state
        g["exchanges_seen"] = sorted(ex)
        counters[state] += 1
        rows.append(g)
    source_status = source_status or []
    failures = [{"source": s.get("source"), "status": s.get("status"), "error": s.get("error")}
                for s in source_status if s.get("status") not in {"OK", "EMPTY"}]
    return {
        "session": session, "generated_at": as_of,
        "method": "Symbol + material category presence; NOT event-ID or issuer ISIN reconciliation",
        "category_counts": dict(sorted(counters.items())),
        "groups": rows[:1500],
        "groups_truncated": len(rows) > 1500,
        "failed_or_disabled_sources": failures,
        "limitations": [
            "Single-exchange does not mean missing: an issuer may file differently on different exchanges.",
            "Two items in the same category can be distinct events; no exact event match is asserted.",
            "Unmatched media stories may be independent journalism, not exchange disclosures.",
            "RSS feeds, publication timestamps and issuer matches are not verified against a complete licensed disclosure log.",
            "Source failures may hide events. Treat all gaps as investigation leads, never automatically as negative/positive predictions."
        ],
    }


def write_gap_audit(output_path: Path, events: list[dict], coverage: dict) -> dict:
    report = source_reconciliation(
        events, as_of=coverage["generated_at"], session=coverage["session"],
        source_status=coverage.get("sources", []))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
