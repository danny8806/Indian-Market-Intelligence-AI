"""Evidence-first financial fact extraction. No LLM and no financial advice.

Only extract percent changes explicitly labeled as YoY/QoQ in a statement;
unlabeled financial tables and unsupported claims are never interpreted as growth.
"""
from __future__ import annotations

import hashlib
import re

METRICS = (
    ("ebitda", r"\b(?:EBITDA|operating\s+profit)\b"),
    ("pat", r"\b(?:profit\s+after\s+tax|net\s+profit|PAT)\b"),
    ("revenue", r"\b(?:revenue\s+from\s+operations|total\s+revenue|revenue|sales)\b"),
    ("order_book", r"\border\s+book\b"),
)
CHANGE = re.compile(
    r"\b(?P<verb>increased?|grew|grown|rose|risen|up|higher|jumped|surged|"
    r"declined?|fell|fallen|decreased?|down|lower|dropped|reduced)\s*"
    r"(?:by|to|of|approximately|about|around|nearly)?\s*"
    r"(?P<amount>[0-9]{1,3}(?:\.[0-9]{1,2})?)\s*%\s*"
    r"(?P<basis>YoY|year.on.year|Y.o.Y|QoQ|quarter.on.quarter)\b", re.I
)
PERIOD = re.compile(r"\b(?:(?:Q[1-4]|H[12])\s*FY\s?\d{2,4}|FY\s?\d{2,4})\b", re.I)
FINANCIAL_WORDS = re.compile(
    r"\b(?:profit|pat|ebitda|revenue|sales|contract|order\s+book|turnover)\b", re.I
)
ORDER_VALUE = re.compile(
    r"\b(?:contract|purchase\s+order|work\s+order|order\s+(?:worth|value)|"
    r"letter\s+of\s+award)\b.{0,95}?"
    r"(?P<raw>(?:₹|Rs\.?|INR)\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*"
    r"(?:crore|cr\.?|lakh|million|billion))\b", re.I
)
POSITIVE_VERBS = {"increase", "increased", "grew", "grown", "rose", "risen",
                  "up", "higher", "jumped", "surged"}
NEGATIVE_VERBS = {"decline", "declined", "fell", "fallen", "decrease", "decreased",
                  "down", "lower", "dropped", "reduced"}


def extract_line(line: str, *, source: str, doc_hash: str) -> list[dict]:
    """Extract isolated percent assertions with explicit basis and a nearby metric."""
    clean = re.sub(r"\s+", " ", line).strip()
    if not (16 <= len(clean) <= 460):
        return []
    found = []
    for m in CHANGE.finditer(clean):
        earlier = clean[max(0, m.start() - 210):m.start()]
        candidates = []
        for metric, pattern in METRICS:
            mentions = list(re.finditer(pattern, earlier, re.I))
            if mentions:
                candidates.append((mentions[-1].end(), metric))
        if not candidates:
            continue
        nearest_end, metric = max(candidates)
        # Avoid bridging unrelated bullet points or two different sentences.
        intervening = earlier[nearest_end:]
        if re.search(r"[!?]\s+|\.\s+[A-Z][a-z]{2,}", intervening):
            continue
        direction = m.group("verb").lower()
        if direction in POSITIVE_VERBS:
            signed = float(m.group("amount"))
        elif direction in NEGATIVE_VERBS:
            signed = -float(m.group("amount"))
        else:
            continue
        basis = "YoY" if re.search(r"yoy|year.on.year|y.o.y", m.group("basis"), re.I) else "QoQ"
        period = PERIOD.search(clean)
        found.append({
            "metric": metric, "basis": basis, "reported_change_pct": signed,
            "reported_period": period.group(0).replace(" ", "") if period else None,
            "evidence_text": clean[:300], "source": source,
            "document_sha256": doc_hash, "verification": "ASSERTION_NOT_ARITHMETICALLY_VERIFIED",
        })
    return found


def extract_facts(record: dict) -> list[dict]:
    """Records from pdf_extraction.jsonl with explicitly annotated source evidence."""
    if record.get("status") != "EXTRACTED":
        return []
    lines = list(record.get("financial_context_lines") or [])
    # The 1,800-char sample can include narrative YoY assertions; sentence split
    # only, never silently treat a multiple-column table as a coherent narrative.
    excerpt = record.get("text_sample") or ""
    lines.extend(re.split(r"(?<=[.!?])\s+(?=[A-Z])", excerpt))
    facts, seen = [], set()
    for line in lines:
        for fact in extract_line(line, source=record.get("url", ""),
                                 doc_hash=record.get("pdf_sha256", "")):
            key = (fact["metric"], fact["basis"], fact["reported_change_pct"],
                   fact["reported_period"], fact["document_sha256"])
            if key not in seen:
                seen.add(key)
                facts.append(fact)
    # Keep order value literal, never silently convert millions to crores or
    # mistake routine CAPEX / issuance into order value.
    for line in lines:
        clean = re.sub(r"\s+", " ", line).strip()
        if len(clean) > 460:
            continue
        m = ORDER_VALUE.search(clean)
        if m and record.get("classification") == "orders_contracts":
            raw = m.group("raw")
            key = ("order_value", raw, record.get("pdf_sha256"))
            if key not in seen:
                seen.add(key)
                facts.append({
                    "metric": "order_value", "reported_value_text": raw,
                    "basis": None, "reported_period": None,
                    "evidence_text": clean[:300], "source": record.get("url", ""),
                    "document_sha256": record.get("pdf_sha256", ""),
                    "verification": "VALUE_ASSERTION_NEEDS_MANUAL_REVIEW",
                })
    return facts[:32]


def evidence_summary(facts: list[dict]) -> dict:
    """Summarize without probabilities or trade recommendations."""
    signs = {}
    for f in facts:
        if f.get("basis") != "YoY" or "reported_change_pct" not in f:
            continue
        metric = f["metric"]
        sign = 1 if f["reported_change_pct"] > 0 else -1 if f["reported_change_pct"] < 0 else 0
        signs.setdefault(metric, set()).add(sign)
    positive = sorted(m for m, vals in signs.items() if vals == {1})
    negative = sorted(m for m, vals in signs.items() if vals == {-1})
    conflicting = sorted(m for m, vals in signs.items() if len(vals) > 1)
    if positive and negative or conflicting:
        label = "MIXED_REPORTED_FINANCIAL_EVIDENCE"
    elif positive:
        label = "POSITIVE_REPORTED_FINANCIAL_EVIDENCE"
    elif negative:
        label = "NEGATIVE_REPORTED_FINANCIAL_EVIDENCE"
    else:
        label = "INSUFFICIENT_EXPLICIT_YOY_EVIDENCE"
    return {
        "label": label, "positive_metrics": positive,
        "negative_metrics": negative, "conflicting_metrics": conflicting,
        "yoy_metrics_with_direction": len(signs),
        "not_a_price_prediction": True,
    }
