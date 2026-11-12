"""Small deterministic extraction helpers; no network, model or stock selection."""
import feedparser
import re
from bs4 import BeautifulSoup
import trafilatura


def complete_rss_items(raw: bytes, source: dict, limit: int) -> list[dict]:
    """Opt-in tolerant decoding of complete RSS items; retain stated times only."""
    prefix = raw[:4096].lstrip(b'\xef\xbb\xbf \t\r\n')
    prefix = re.sub(rb'^<\?xml[^>]*\?>\s*', b'', prefix, flags=re.I)
    opening = re.match(rb'<rss\b[^>]*>', prefix, flags=re.I)
    if opening is None or re.search(rb'<!\s*(?:DOCTYPE|ENTITY)\b', raw, flags=re.I):
        raise ValueError('Malformed-feed fallback requires plain RSS without entities')
    items = re.findall(rb'<item(?:\s[^>]*)?>.*?</item\s*>', raw, flags=re.I | re.S)
    if not items:
        raise ValueError('Malformed RSS contains no complete items')
    bounded = opening.group(0) + b'<channel>' + b''.join(items[:limit]) + b'</channel></rss>'
    return atom_items(bounded, source, limit)


def atom_items(raw: bytes, source: dict, limit: int) -> list[dict]:
    """Called only after the existing strict XML/root validation has succeeded."""
    feed = feedparser.parse(raw)
    rows = []
    for entry in feed.entries:
        title, url = entry.get('title', ''), entry.get('link', '')
        if not isinstance(title, str) or not isinstance(url, str) or not title or not url:
            continue
        published = entry.get('published', '')
        updated = entry.get('updated', '')
        # Keep the source's actual string. No parsed-date guess or fetch-time substitution.
        raw_time = published or updated
        if not isinstance(raw_time, str):
            raw_time = ''
        summary = entry.get('summary', '')
        if not isinstance(summary, str):
            summary = ''
        rows.append({
            'headline': title[:550], 'url': url,
            'summary': BeautifulSoup(summary, 'lxml').get_text(' ', strip=True)[:1800],
            'scrip_code': '', 'filing_id': '', 'original_time': bool(published),
            'raw_time': '' if source.get('timestamp_provenance') == 'discovery' else raw_time,
        })
        if len(rows) >= limit:
            break
    return rows


def article_summary(raw: bytes, existing: str) -> str:
    """Extract bounded visible text only when publisher summary metadata is absent."""
    if existing:
        return existing
    try:
        text = trafilatura.extract(raw[:512000], no_fallback=False,
                                   include_comments=False, include_tables=False,
                                   include_links=False, include_images=False)
    except Exception:
        text = ''
    text = ' '.join((text or '').split())[:1800]
    if text:
        return text
    from news_collector.tool_capabilities import fallback_article_text
    return fallback_article_text(raw)
