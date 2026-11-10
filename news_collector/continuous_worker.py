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
from news_collector.github_inbox_pull import pull_public_inbox
from news_collector.chatgpt_inbox_import import import_inbox

DATA_ROOT = ROOT / "data"
_SHUTDOWN = False


def _stop(_signal, _frame):
    global _SHUTDOWN
    _SHUTDOWN = True


def poll_interval_seconds(clock: datetime) -> int:
    """Ten-minute collection cadence around the clock."""
    return 10 * 60


def collect_and_store(engine, *, data_root: Path = DATA_ROOT,
                      now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    session = default_session(now)
    # The existing worker retrieves every configured public source. It writes
    # atomically to local JSONL before this database synchronization.
    result = collect_news(session, data_root)
    inbox = {"status": "SKIPPED_GITHUB_INBOX_PULL"}
    imported = {"status": "SKIPPED_GITHUB_INBOX_IMPORT"}
    if os.environ.get("ENABLE_PUBLIC_GITHUB_INBOX_PULL", "").strip().lower() == "true":
        try:
            inbox = pull_public_inbox(data_root.parent)
        except Exception as exc:
            inbox = {"status": "GITHUB_INBOX_PULL_FAILED",
                     "error_type": type(exc).__name__}
        try:
            imported = import_inbox(
                root=data_root.parent, now=now, session=session)
        except Exception as exc:
            imported = {"status": "CHATGPT_INBOX_IMPORT_FAILED",
                        "error_type": type(exc).__name__}
    ai = {}
    try:
        ai = collect_openai_links(session, data_root, now=now)
    except Exception as exc:
        # Do not suppress the important primary-source-to-DB step.
        # Do not log raw provider errors: network payloads may include secrets.
        ai = {"status": "OPENAI_DISCOVERY_FAILED",
              "error_type": type(exc).__name__}
    db = sync_session(engine, data_root, session)
    now_saved = datetime.now(IST)
    marker = data_root / "last_successful_db_sync.json"
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "sync_completed_at": now_saved.isoformat(), "session": session,
        "source_count": result["sources_configured"],
        "sources_with_items": result["sources_with_items"],
        "sources_failed": result["sources_failed"],
        "db_status": db["status"], "github_pull": inbox["status"],
        "inbox_import": imported["status"],
    }, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(marker)
    return {"session_date": session, "source_count": result["sources_configured"],
            "sources_with_items": result["sources_with_items"],
            "sources_failed": result["sources_failed"],
            "database": db["status"], "openai": ai.get("status"),
            "github_pull": inbox["status"], "inbox_import": imported["status"]}


def codex_slot(now: datetime, budget: int) -> int | None:
    """Only the first Python pass in each half hour can spend a discovery slot."""
    if now.minute % 30 >= 10:
        return None
    slots = 48
    slot = (now.hour * 60 + now.minute) // 30
    budget = max(0, min(slots, budget))
    return slot if slot * budget // slots > (slot - 1) * budget // slots else None


def collect_archive(engine, root: Path, *, clock=lambda: datetime.now(IST)) -> dict:
    from news_collector.agent_intake import ingest_inbox, lane_statuses
    from news_collector.archive import collect_batch, replay, stage
    from news_collector.codex_research import discover
    from uuid import uuid4

    started = clock().astimezone(IST)
    batch, nifty, universe = collect_batch(root, clock=clock)
    inbox = Path(os.getenv("NEWS_AGENT_INBOX", str(root / "agent_inbox")))
    batch["agent_lanes"] = lane_statuses(inbox)
    stage(root, batch)
    # Commit primary sources before optional CLI calls can run out of time.
    saved = replay(engine, root)
    now = clock().astimezone(IST)
    try:
        budget = int(os.getenv("NEWS_CODEX_DAILY_CALLS", "48"))
    except ValueError:
        budget = 0
    slot = codex_slot(started, budget)
    codex_status = "SKIPPED_BUDGET"
    if slot is not None:
        # Persist attempted slot before calling, so a service retry cannot spend twice.
        ledger = root / "last_codex_slot"
        slot_id = f"{started.date()}:half-hour:{slot}"
        if not ledger.is_file() or ledger.read_text(encoding="utf-8") != slot_id:
            temporary = ledger.with_suffix(".tmp")
            temporary.write_text(slot_id, encoding="utf-8")
            temporary.replace(ledger)
            try:
                codex_status, rows = discover(now, nifty, universe, clock=clock)
            except Exception as exc:
                codex_status, rows = f"DISCOVERY_FAILED_{type(exc).__name__}", []
            stage(root, {
                "batch_id": uuid4().hex, "session": now.date().isoformat(),
                "generated_at": clock().isoformat(), "records": rows,
                "sources_configured": 1, "sources_with_items": 0, "sources_failed": 0,
                "sources": [{"source": "Codex CLI", "status": codex_status,
                             "fetched_items": len(rows)}],
            })
    try:
        external_status = ingest_inbox(inbox, root, nifty, universe, clock=clock)
    except (OSError, ValueError) as exc:
        external_status = {"status": f"INTAKE_FAILED_{type(exc).__name__}"}
    saved += replay(engine, root)
    result = {
        "db_status": "DATABASE_SYNC_OK", "sync_completed_at": clock().isoformat(),
        "session": batch["session"], "source_count": batch["sources_configured"],
        "sources_with_items": batch["sources_with_items"],
        "sources_failed": batch["sources_failed"], "sources_blocked": batch["sources_blocked"],
        "codex": codex_status,
        "observations": len(batch["records"]), "batches_committed": saved,
        "external_cli": external_status,
        "pending_batches": sum(1 for _ in (root / "pending_batches").glob("*.json")),
    }
    marker = root / "last_successful_db_sync.json"
    temp = marker.with_suffix(".tmp")
    temp.write_text(json.dumps(result) + "\n", encoding="utf-8")
    temp.replace(marker)
    return result


def archive_once(engine, root: Path) -> dict:
    # The archive runs on the Ubuntu VPS. flock also covers concurrent
    # operator invocations against the same Docker volume.
    import fcntl

    root.mkdir(parents=True, exist_ok=True)
    with (root / "archive.lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "SKIPPED_ALREADY_RUNNING"}
        return collect_archive(engine, root)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--archive", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DATA_ROOT)
    args = parser.parse_args()
    url = os.getenv("NEWS_DATABASE_URL")
    if not url:
        raise SystemExit("NEWS_DATABASE_URL must be configured for continuous polling")
    db = engine_for_url(url)
    if args.archive:
        if not args.once:
            parser.error("--archive requires --once and an external scheduler")
        print(json.dumps(archive_once(db, args.data_dir)))
        return
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
