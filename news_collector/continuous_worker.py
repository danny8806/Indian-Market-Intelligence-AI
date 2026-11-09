"""Unattended *research-only* news polling worker for an internet-connected VPS.

A persistent PostgreSQL DB is mandatory for unattended use. This module does
not import, modify, or trigger signal delivery or broker order execution.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import time
from datetime import datetime
from pathlib import Path

from news_collector.db_store import engine_for_url, sync_session
from news_collector.engine import IST, ROOT, default_session, run as collect_news
from news_collector.openai_web_discovery import run as collect_openai_links

DATA_ROOT = ROOT / "data"
_SHUTDOWN = False


def _stop(_signal, _frame):
    global _SHUTDOWN
    _SHUTDOWN = True


def poll_interval_seconds(clock: datetime) -> int:
    """Poll faster in the Indian overnight pre-open window."""
    local = clock.astimezone(IST)
    minutes = local.hour * 60 + local.minute
    # 15:00 to next 09:00 IST.
    return 600 if (minutes >= 15 * 60 or minutes < 9 * 60) else 1800


def collect_and_store(engine, *, data_root: Path = DATA_ROOT,
                      now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    session = default_session(now)
    # The existing worker retrieves every configured public source. It writes
    # atomically to local JSONL before this database synchronization.
    result = collect_news(session, data_root)
    ai = {}
    try:
        ai = collect_openai_links(session, data_root, now=now)
    except Exception as exc:
        # Do not suppress the important primary-source-to-DB step.
        # Do not log raw provider errors: network payloads may include secrets.
        ai = {"status": "OPENAI_DISCOVERY_FAILED",
              "error_type": type(exc).__name__}
    db = sync_session(engine, data_root, session)
    return {"session_date": session, "source_count": result["sources_configured"],
            "sources_with_items": result["sources_with_items"],
            "sources_failed": result["sources_failed"],
            "database": db["status"], "openai": ai.get("status")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DATA_ROOT)
    args = parser.parse_args()
    url = os.getenv("NEWS_DATABASE_URL")
    if not url:
        raise SystemExit("NEWS_DATABASE_URL must be configured for continuous polling")
    db = engine_for_url(url)
    if args.once:
        print(json.dumps(collect_and_store(db, data_root=args.data_dir)))
        return
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    while not _SHUTDOWN:
        started = time.monotonic()
        try:
            result = collect_and_store(db, data_root=args.data_dir)
            print(json.dumps({"time": datetime.now(IST).isoformat(), **result}),
                  flush=True)
        except Exception as exc:
            print(json.dumps({"time": datetime.now(IST).isoformat(),
                              "status": "NEWS_POLL_FAILED",
                              "error_type": type(exc).__name__}), flush=True)
        interval = poll_interval_seconds(datetime.now(IST))
        remaining = max(1.0, interval - (time.monotonic() - started))
        while remaining > 0 and not _SHUTDOWN:
            pause = min(remaining, 2)
            time.sleep(pause)
            remaining -= pause


if __name__ == "__main__":
    main()
