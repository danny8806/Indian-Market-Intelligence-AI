"""Fair persisted source assignment; unfinished reads keep their place in line."""
import json
from datetime import datetime
from pathlib import Path

SOURCES_PER_PASS = 20
SEARCH_URL_LIMIT = 24


def read_ledger(root):
    if root is None:
        return {}
    try:
        value = json.loads((Path(root) / 'codex-source-coverage.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def source_batch(sources, ledger, *, size=SOURCES_PER_PASS):
    """Never-read and oldest actually attempted sources first, stable registry ties."""
    def age(source):
        previous = ledger.get(source['name'], {})
        if not isinstance(previous, dict) or previous.get('url', source['url']) != source['url']:
            return float('-inf')
        try:
            stamp = datetime.fromisoformat(previous['attempted_at'])
            return stamp.timestamp() if stamp.tzinfo is not None else float('-inf')
        except (KeyError, TypeError, ValueError, OverflowError):
            return float('-inf')
    return sorted(sources, key=age)[:size]


def record_checks(sources, ledger, checks, observed_at):
    result = {s['name']: dict(ledger.get(s['name'], {}))
              if isinstance(ledger.get(s['name']), dict) else {} for s in sources}
    for source in sources:
        row = result[source['name']]
        if row.get('url', source['url']) != source['url']:
            row.clear()
        row.update(source=source['name'], url=source['url'])
        row.setdefault('status', 'PENDING')
        row.setdefault('attempted_at', None)
    for check in checks:
        row = result[check['source']]
        row.update(check, attempted_at=check.get('observed_at') or observed_at)
        if check['status'] == 'OK':
            row['last_success_at'] = row['attempted_at']
    return result
