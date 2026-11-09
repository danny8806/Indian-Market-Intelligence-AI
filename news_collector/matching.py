"""Conservative NIFTY 500 company/ticker matching for public financial news.

Never assume a mentioned issuer is the issuer of an exchange filing.
Aliases must be explicitly curated and are activated only if the official
NIFTY 500 membership snapshot contains the target symbol.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NON_DISTINCTIVE = {"india", "indian", "group", "financial", "services",
                   "industries", "international", "investment", "company",
                   "bank", "enterprises", "limited", "holdings", "corporation"}


def normalized(text: str) -> str:
    text = (text or "").casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [w for w in text.split() if w not in {"ltd", "limited", "pvt", "private", "co", "the"}]
    return " ".join(words)


@lru_cache(maxsize=1)
def curated_aliases() -> dict[str, list[str]]:
    return json.loads((ROOT / "aliases.json").read_text(encoding="utf-8"))["aliases"]


def safe_needle(phrase: str) -> bool:
    pieces = phrase.split()
    return len(phrase) >= 5 and bool(pieces) and not all(p in NON_DISTINCTIVE for p in pieces)


def bounded_phrase(haystack: str, needle: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack))


def match_issuers(title: str, summary: str, universe: dict[str, str],
                  *, official_filing: bool = False,
                  aliases: dict[str, list[str]] | None = None) -> list[str]:
    """Use title-only for exchange issuers; title+summary for media mentions.

    Bare ticker matches are permitted only with explicit stock/exchange
    notation, not free words such as BEL, LIC or MCX in a headline.
    """
    if not universe:
        return []
    text = title if official_filing else (title + " " + summary)
    normalized_text = normalized(text)
    result: set[str] = set()
    for symbol, company in universe.items():
        name = normalized(company)
        if safe_needle(name) and bounded_phrase(normalized_text, name):
            result.add(symbol)

    for symbol, variants in (aliases if aliases is not None else curated_aliases()).items():
        if symbol not in universe:
            continue
        for alias in variants:
            phrase = normalized(alias)
            if safe_needle(phrase) and bounded_phrase(normalized_text, phrase):
                result.add(symbol)
                break

    if official_filing and len(result) > 1:
        # A headline headed "Union Bank of India" should not also attach
        # "Bank of India": prefer a longer, explicitly matched legal name.
        # Keep independent companies when their names do not contain one another.
        matches = {}
        variants_by_symbol = aliases if aliases is not None else curated_aliases()
        for symbol in result:
            all_names = [universe[symbol], *variants_by_symbol.get(symbol, [])]
            matches[symbol] = {
                p for phrase in all_names
                if (p := normalized(phrase)) and safe_needle(p)
                and bounded_phrase(normalized_text, p)
            }
        contained = {
            symbol for symbol, phrases in matches.items()
            if phrases and all(
                any(symbol != other and len(longer) > len(phrase)
                    and bounded_phrase(longer, phrase)
                    for other, other_phrases in matches.items()
                    for longer in other_phrases)
                for phrase in phrases)
        }
        result.difference_update(contained)

    # Explicit NSE symbol notation is evidence even for short ticker symbols.
    for candidate in re.findall(
        r"(?<!\w)(?:NSE\s*(?:SYMBOL|TICKER)?|TICKER)\s*[:：]\s*([A-Z][A-Z0-9&._-]{1,30})\b",
        text, flags=re.I,
    ):
        if candidate.upper() in universe:
            result.add(candidate.upper())

    for candidate in re.findall(r"(?<!\w)\$([A-Z][A-Z0-9&._-]{1,30})\b", text):
        if candidate in universe:
            result.add(candidate)
    return sorted(result)
