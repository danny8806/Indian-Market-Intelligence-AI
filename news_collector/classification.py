"""Deterministic, auditable event classification for archived news records.

This is a keyword classifier, not a model prediction. It records a category and
an explicitly directional headline reading so the article table does not lose
information that the morning report already derives. Ambiguous or speculative
headlines are never forced into a direction.
"""
from __future__ import annotations

from news_collector.headline_fallback import directional_matches
from news_collector.reconcile import event_kind

SENTIMENT_SCORE = {"BULLISH": 1, "BEARISH": -1, "MIXED": 0, "UNCLEAR": 0}


def classify_event(headline: str, summary: str = "") -> tuple[str, str, int]:
    """Return (event category, sentiment label, directional strength)."""
    category = event_kind(headline, summary)
    text = f"{headline} {summary}".strip()
    matches = directional_matches(text)
    if not matches:
        return category, "UNCLEAR", 0
    sides = {side for side, _ in matches}
    if len(sides) > 1:
        return category, "MIXED", 0
    side, score = max(matches, key=lambda match: match[1])
    return category, ("BULLISH" if side == "LONG" else "BEARISH"), int(score)
