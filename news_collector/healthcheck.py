"""Container health: fail if SQL-backed news archive was not updated recently."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

MARKER = Path(__file__).resolve().parent / "data" / "last_successful_db_sync.json"


def healthy(marker: Path = MARKER, *, now: datetime | None = None) -> bool:
    if not marker.is_file():
        return False
    try:
        report = json.loads(marker.read_text(encoding="utf-8"))
        if report.get("db_status") != "DATABASE_SYNC_OK":
            return False
        checked = datetime.fromisoformat(report["sync_completed_at"])
        if checked.tzinfo is None or checked.utcoffset() is None:
            return False
        current = now or datetime.now(timezone.utc)
        age = (current - checked).total_seconds()
        return -120 <= age <= 80 * 60
    except (ValueError, KeyError, OSError, TypeError):
        return False


if __name__ == "__main__":
    sys.exit(0 if healthy() else 1)
