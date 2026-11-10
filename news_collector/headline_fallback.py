"""Build an auditable research fallback from verified, explicitly directional headlines."""
from collections import Counter, defaultdict
from datetime import datetime
import re

METRIC = r"\b(?:net profit|operating profit|net income|earnings|revenue|ebitda|sales)\b"
BETWEEN = r"(?:\s+(?:for Q[1-4]|year-on-year|quarter-on-quarter|unexpectedly|sharply|has|have|reportedly))?\s+"
UP = r"\b(?:ris(?:e|es)|rose|jump(?:s|ed)?|surge(?:s|d)?|grew|grows?|increase[sd]?|climb(?:s|ed)?)\b"
DOWN = r"\b(?:fall(?:s)?|fell|drop(?:s|ped)?|decline[sd]?|slid(?:e|es)?|contract(?:s|ed)?|decrease[sd]?|slump(?:s|ed)?)\b"
RULES = {
    "LONG": (
        (4, re.compile(r"\b(?:raises?|upgrades?|lifts?)\b[^.;]{0,30}\b(?:earnings|revenue|profit) guidance\b", re.I)),
        (3, re.compile(rf"{METRIC}{BETWEEN}{UP}", re.I)),
        (3, re.compile(rf"{METRIC}{BETWEEN}\b(?:beats?|tops?|exceeds?)\s+(?:market\s+)?estimates\b", re.I)),
        (3, re.compile(r"\b(?:returns? to profit|swings? to (?:a )?profit)\b", re.I)),
        (2, re.compile(r"\b(?:wins?|bags?|secures?)\b[^.;]{0,45}\b(?:order|contract)\b", re.I)),
    ),
    "SHORT": (
        (4, re.compile(r"\b(?:cuts?|lowers?|withdraws?)\b[^.;]{0,30}\b(?:earnings|revenue|profit) guidance\b", re.I)),
        (3, re.compile(rf"{METRIC}{BETWEEN}{DOWN}", re.I)),
        (3, re.compile(rf"{METRIC}{BETWEEN}\bmiss(?:es|ed)?\s+(?:market\s+)?estimates\b", re.I)),
        (3, re.compile(r"\b(?:swings? to (?:a )?loss|posts? (?:a )?(?:wider|net) loss)\b", re.I)),
        (2, re.compile(r"\b(?:cancels?|loses?|terminates?)\b[^.;]{0,45}\b(?:order|contract)\b", re.I)),
    ),
}
SPECULATION = re.compile(r"\?|(?:\bmay\b|\bcould\b|\bexpected to\b|\bforecast to\b|\brisks? of\b)", re.I)


def headline_direction(headline: str) -> tuple[str, int] | None:
    if SPECULATION.search(headline):
        return None
    matches = [(side, score) for side, rules in RULES.items() for score, pattern in rules
               if pattern.search(headline)]
    if len({side for side, _ in matches}) != 1:
        return None
    return max(matches, key=lambda match: match[1])


def fill_from_headlines(snapshot: dict, signals: list[dict]) -> list[dict]:
    """Fill open slots without changing reviewed candidates or reusing a symbol."""
    if not snapshot.get("recent_universe", snapshot["recent_coverage"]):
        return signals
    counts = Counter(item["side"] for item in signals)
    taken = {item["symbol"] for item in signals}
    by_symbol = defaultdict(list)
    for row in snapshot["items"]:
        if not row.get("verified_origin") or len(row["nifty_symbols"]) != 1:
            continue
        symbol = row["nifty_symbols"][0]
        direction = headline_direction(row["headline"])
        if direction is not None and symbol not in taken:
            side, score = direction
            by_symbol[symbol].append((side, score, datetime.fromisoformat(row["published_at"]), row))
    ranked = []
    for symbol, candidates in by_symbol.items():
        if len({item[0] for item in candidates}) == 1:
            side, score, published, source = max(candidates, key=lambda row: (row[1], row[2]))
            ranked.append((score, published, symbol, side, source))
    selected = list(signals)
    for _, _, symbol, side, source in sorted(ranked, key=lambda row: row[:3], reverse=True):
        if counts[side] >= 5:
            continue
        counts[side] += 1
        selected.append({
            "symbol": symbol, "side": side, "rank": counts[side],
            "reason": "Verified headline fallback. Review the source before relying on this candidate.",
            "news_summary": source["headline"],
            "first_available_at": source["published_at"],
            "sources": [{"url": source["url"], "title": source["headline"],
                         "published_at": source["published_at"]}],
        })
    return selected
