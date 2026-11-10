"""Idempotent database archive for the existing read-only NIFTY 500 news collector.

This stores the collector's source evidence, not trade recommendations. Search
index timestamps are not promoted to original publisher/exchange timestamps.
Uses SQLite for local tests and PostgreSQL for deployment. Requires an explicit
NEWS_DATABASE_URL to write outside a local test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer,
                        MetaData, String, Table, Text, create_engine, insert,
                        select, text, update)

metadata = MetaData()
articles = Table(
    "news_articles", metadata,
    Column("id", String(64), primary_key=True),
    Column("url", Text, nullable=False),
    Column("headline", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("record_kind", String(32), nullable=False),
    Column("time_status", String(80), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("symbols", JSON, nullable=False),
    Column("sources", JSON, nullable=False),
    Column("providers", JSON, nullable=False),
    Column("authorities", JSON, nullable=False),
    Column("provider_reported_time_unverified", Text, nullable=False),
)
Index("ix_news_articles_published", articles.c.published_at)
Index("ix_news_articles_first_seen", articles.c.first_seen_at)
Index("ix_news_articles_kind", articles.c.record_kind)

article_symbols = Table(
    "news_article_symbols", metadata,
    Column("article_id", String(64), ForeignKey("news_articles.id"), primary_key=True),
    Column("symbol", String(40), primary_key=True),
)
Index("ix_news_article_symbols_symbol", article_symbols.c.symbol)

source_checks = Table(
    "news_source_checks", metadata,
    Column("source", String(255), primary_key=True),
    Column("status", String(40), nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("fetched_items", Integer, nullable=False),
    Column("error", Text, nullable=False),
    Column("kind", String(35), nullable=False),
)
runs = Table(
    "news_ingest_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_date", String(10), nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("saved_at", DateTime(timezone=True), nullable=False),
    Column("configured", Integer, nullable=False),
    Column("returning_items", Integer, nullable=False),
    Column("failed", Integer, nullable=False),
    Column("total_articles_in_archive", Integer, nullable=False),
)
Index("ix_news_runs_session", runs.c.session_date, runs.c.checked_at)

archive_batches = Table(
    "news_archive_batches", metadata,
    Column("batch_id", String(32), primary_key=True),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("coverage", JSON, nullable=False),
)
article_revisions = Table(
    "news_article_revisions", metadata,
    Column("id", String(64), primary_key=True),
    Column("article_id", String(64), ForeignKey("news_articles.id"), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("verified_origin", Boolean, nullable=False),
    Column("evidence", JSON, nullable=False),
)
Index("ix_news_revisions_cutoff", article_revisions.c.verified_origin,
      article_revisions.c.published_at, article_revisions.c.observed_at)
morning_reports = Table(
    "news_morning_reports", metadata,
    Column("session_date", String(10), primary_key=True),
    Column("frozen_at", DateTime(timezone=True), nullable=False),
    Column("evidence", JSON, nullable=False),
    Column("report", JSON),
)



def aware(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("News timestamps must include timezone")
    return dt.astimezone(timezone.utc)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def engine_for_url(url: str):
    if not url.startswith(("postgresql://", "postgresql+psycopg://", "sqlite://")):
        raise ValueError("Only PostgreSQL or SQLite database URLs are allowed")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, pool_pre_ping=True)


def _unique(existing: list, incoming: list) -> list:
    return sorted(set(existing or []) | set(incoming or []))


def _normalize_sqlite_time(value: datetime | None):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _oldest(left: datetime | None, right: datetime | None):
    left = _normalize_sqlite_time(left)
    right = _normalize_sqlite_time(right)
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _newest(left: datetime | None, right: datetime | None):
    left = _normalize_sqlite_time(left)
    right = _normalize_sqlite_time(right)
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _kind_rank(kind: str) -> int:
    return {"discovery_only": 0, "macro_context": 1, "timestamped_stock": 2}[kind]


def _insert_or_update(connection, incoming: dict, kind: str, checked_at: datetime):
    identity = str(incoming.get("id") or "")
    if not identity or len(identity) > 64:
        raise ValueError("Invalid article id")
    first = aware(incoming.get("first_seen_at"))
    last = aware(incoming.get("last_seen_at"))
    if first is None or last is None:
        raise ValueError("Missing article discovery times")
    pub = aware(incoming.get("published_at"))
    if kind == "discovery_only":
        pub = None  # NEVER trust search index or API metadata as publication time.
    if kind == "timestamped_stock" and (pub is None or not incoming.get("symbols")):
        raise ValueError("Timestamped stock record needs source time and symbol")
    row = dict(
        url=str(incoming["url"]), headline=str(incoming["headline"])[:550],
        summary=str(incoming.get("summary") or "")[:1800],
        record_kind=kind,
        time_status=("SOURCE_TIME_PARSED_NOT_INDEPENDENTLY_VERIFIED"
                     if pub is not None else "DISCOVERY_TIME_ONLY"),
        published_at=pub, first_seen_at=first, last_seen_at=last,
        ingested_at=checked_at,
        symbols=sorted(set(incoming.get("symbols") or [])),
        sources=sorted(set(incoming.get("sources") or [])),
        providers=sorted(set(incoming.get("providers") or [])),
        authorities=sorted(set(incoming.get("authorities") or [])),
        provider_reported_time_unverified=str(
            incoming.get("provider_reported_time_unverified") or "")[:80],
    )
    old = connection.execute(select(articles).where(articles.c.id == identity)).mappings().first()
    if old:
        old_kind = old["record_kind"]
        if _kind_rank(old_kind) > _kind_rank(kind):
            row["record_kind"] = old_kind
            row["published_at"] = old["published_at"]
            row["time_status"] = old["time_status"]
            row["headline"] = old["headline"]
            row["summary"] = old["summary"]
        elif old_kind == kind and old["published_at"] is not None:
            row["published_at"] = _oldest(old["published_at"], pub)
        row["first_seen_at"] = _oldest(old["first_seen_at"], first)
        row["last_seen_at"] = _newest(old["last_seen_at"], last)
        for field in ("symbols", "sources", "providers", "authorities"):
            row[field] = _unique(old[field], row[field])
        connection.execute(update(articles).where(articles.c.id == identity).values(**row))
    else:
        connection.execute(insert(articles).values(id=identity, **row))
    for symbol in row["symbols"]:
        if not connection.execute(select(article_symbols.c.symbol).where(
                (article_symbols.c.article_id == identity) &
                (article_symbols.c.symbol == symbol))).first():
            connection.execute(insert(article_symbols).values(
                article_id=identity, symbol=symbol))


def sync_session(connection_engine, data_dir: Path, session_date: str) -> dict:
    """Transactionally upsert saved collector evidence and per-source health."""
    folder = data_dir / session_date
    coverage_file = folder / "coverage.json"
    if not coverage_file.is_file():
        raise FileNotFoundError(f"No coverage file for {session_date}")
    coverage = json.loads(coverage_file.read_text(encoding="utf-8"))
    if coverage.get("session") != session_date:
        raise ValueError("Coverage session/date mismatch")
    checked_at = aware(coverage["generated_at"])
    records = [
        ("discovery_only", read_jsonl(folder / "undated_candidates.jsonl")),
        ("macro_context", read_jsonl(folder / "macro_context.jsonl")),
        ("timestamped_stock", read_jsonl(folder / "events.jsonl")),
    ]
    saved_at = datetime.now(timezone.utc)
    with connection_engine.begin() as conn:
        metadata.create_all(conn)
        for kind, items in records:
            for item in items:
                _insert_or_update(conn, item, kind, saved_at)
        for source in coverage.get("sources", []):
            name = str(source.get("source") or "")[:255]
            if not name:
                continue
            row = dict(status=str(source.get("status", "UNKNOWN"))[:40],
                       checked_at=checked_at,
                       fetched_items=int(source.get("fetched_items") or 0),
                       kind=str(source.get("kind") or "")[:35],
                       error=str(source.get("error") or "")[:600])
            present = conn.execute(select(source_checks.c.source).where(
                source_checks.c.source == name)).first()
            if present:
                conn.execute(update(source_checks).where(
                    source_checks.c.source == name).values(**row))
            else:
                conn.execute(insert(source_checks).values(source=name, **row))
        conn.execute(insert(runs).values(
            session_date=session_date, checked_at=checked_at, saved_at=saved_at,
            configured=int(coverage.get("sources_configured") or 0),
            returning_items=int(coverage.get("sources_with_items") or 0),
            failed=int(coverage.get("sources_failed") or 0),
            total_articles_in_archive=sum(len(rows) for _, rows in records),
        ))
    return {
        "status": "DATABASE_SYNC_OK", "session_date": session_date,
        "files_read": {kind: len(items) for kind, items in records},
        "sources_checked": len(coverage.get("sources", [])),
        "source_status_is_not_complete_coverage": True,
    }


def sync_archive_batch(engine, batch: dict) -> bool:
    """Commit one durable spool batch once, including its evidence and source checks."""
    checked = aware(batch["generated_at"])
    if checked is None:
        raise ValueError("Archive batch needs a timestamp")
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(73518416)"))
        metadata.create_all(conn)
        if conn.execute(select(archive_batches.c.batch_id).where(
                archive_batches.c.batch_id == batch["batch_id"])).first():
            return False
        for item in batch["records"]:
            _insert_or_update(conn, item, item["kind"], checked)
            fields = ("url", "headline", "summary", "published_at", "symbols",
                      "nifty_symbols", "sources", "providers", "verified_origin", "discoverer")
            evidence = {key: item[key] for key in fields}
            identity = hashlib.sha256(json.dumps(
                [item["id"], evidence], sort_keys=True).encode()).hexdigest()
            seen = aware(item["first_seen_at"])
            old = conn.execute(select(article_revisions.c.observed_at).where(
                article_revisions.c.id == identity)).scalar_one_or_none()
            if old is None:
                conn.execute(insert(article_revisions).values(
                    id=identity, article_id=item["id"], observed_at=seen,
                    published_at=aware(item["published_at"]),
                    verified_origin=item["verified_origin"], evidence=evidence))
            elif seen < _normalize_sqlite_time(old):
                conn.execute(update(article_revisions).where(
                    article_revisions.c.id == identity).values(observed_at=seen))
        coverage = {key: value for key, value in batch.items() if key != "records"}
        conn.execute(insert(archive_batches).values(
            batch_id=batch["batch_id"], checked_at=checked, coverage=coverage))
    return True


def main() -> None:
    from news_collector.engine import ROOT, IST, default_session
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-date", default=None)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--require-db", action="store_true")
    parser.add_argument("--backfill-all", action="store_true",
                        help="Import existing saved session archives one time")
    args = parser.parse_args()
    url = os.getenv("NEWS_DATABASE_URL", "")
    if not url:
        if args.require_db:
            raise SystemExit("NEWS_DATABASE_URL missing; database sync did not run")
        print(json.dumps({"status": "SKIPPED_NO_DB", "reason": "NEWS_DATABASE_URL not configured"}))
        return
    engine = engine_for_url(url)
    if args.backfill_all:
        sessions = sorted(p.name for p in args.data_dir.iterdir()
                          if p.is_dir() and (p / "coverage.json").is_file())
        results = [sync_session(engine, args.data_dir, day) for day in sessions]
        print(json.dumps({"status": "BACKFILL_OK", "sessions": len(results),
                          "session_dates": sessions}))
        return
    session = args.session_date or default_session(datetime.now(IST))
    # Never print the database URL (may contain credentials).
    print(json.dumps(sync_session(engine, args.data_dir, session)))


if __name__ == "__main__":
    main()
