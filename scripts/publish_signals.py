#!/usr/bin/env python3
"""Publish validated research watchlist JSON; never infer or fabricate securities."""
import argparse
import json
import os
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from validate_signals import validate

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent.parent


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".signal-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def unavailable(day: date) -> dict:
    return {
        "schema_version": "1.0",
        "status": "UNAVAILABLE",
        "market": "NSE",
        "timezone": "Asia/Kolkata",
        "session_date": day.isoformat(),
        "news_cutoff_at": datetime.combine(day, time(9, 0), IST).isoformat(),
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"),
        "execution_enabled": False,
        "signals": [],
        "reason": "No verified source report arrived in signals/incoming for this session."
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-date", help="Target YYYY-MM-DD; defaults to today's IST date")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    day = date.fromisoformat(args.session_date) if args.session_date else datetime.now(IST).date()
    root = args.root.resolve()
    incoming = root / "signals" / "incoming" / f"{day.isoformat()}.json"

    if incoming.exists():
        payload = json.loads(incoming.read_text(encoding="utf-8"))
        print(f"Received source report: {incoming}")
    else:
        payload = unavailable(day)
        print("Missing source report: publishing non-tradable UNAVAILABLE status")

    validate(payload, expected_date=day.isoformat())
    latest_path = root / "signals" / "latest.json"
    archive_path = root / "signals" / "archive" / f"{day.isoformat()}.json"
    atomic_json(archive_path, payload)
    atomic_json(latest_path, payload)
    print(f"Published {payload['status']} for {day.isoformat()}: {len(payload['signals'])} research candidates")


if __name__ == "__main__":
    main()
