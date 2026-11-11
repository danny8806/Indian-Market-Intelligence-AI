"""Small deterministic extraction helpers; no network, model or stock selection."""
import feedparser
from bs4 import BeautifulSoup
import trafilatura


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
        return ''  # Optional text extraction never blocks a dated publisher record.
    return ' '.join((text or '').split())[:1800]

