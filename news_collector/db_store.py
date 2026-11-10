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
                        inspect as sqlalchemy_inspect, select, text, update)

from news_collector.classification import classify_event

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
    Column("category", String(40), nullable=False, server_default="other"),
    Column("sentiment", String(16), nullable=False, server_default="UNCLEAR"),
    Column("sentiment_score", Integer, nullable=False, server_default="0"),
    Column("discoverer", String(40), nullable=False, server_default=""),
    Column("company_name", String(255), nullable=False, server_default=""),
    Column("isin", String(12), nullable=False, server_default=""),
    Column("verification_method", String(80), nullable=False, server_default=""),
    Column("financial_figures", JSON),
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
source_cursors = Table(
    "news_source_cursors", metadata,
    Column("source", String(255), primary_key=True),
    Column("status", String(40), nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("latest_item_at", DateTime(timezone=True)),
    Column("latest_item_url", Text, nullable=False),
    Column("consecutive_failures", Integer, nullable=False),
    Column("cursor_state", JSON, nullable=False),
)
raw_documents = Table(
    "news_raw_documents", metadata,
    Column("id", String(64), primary_key=True),
    Column("source", String(255), nullable=False),
    Column("url", Text, nullable=False),
    Column("content_type", String(120), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("byte_size", Integer, nullable=False),
    Column("storage_path", Text, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("details", JSON, nullable=False),
)
Index("ix_news_raw_documents_source", raw_documents.c.source,
      raw_documents.c.last_seen_at)
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



morning_drafts = Table(
    "news_morning_drafts", metadata,
    Column("session_date", String(10), primary_key=True),
    Column("evidence_sha256", String(64), primary_key=True),
    Column("completed_at", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False),
    Column("reason", Text, nullable=False),
    Column("signals", JSON, nullable=False),
)

# Additive columns introduced after the first deployed schema. create_all does
# not alter an existing table, so every writer applies this idempotent upgrade
# before inserting a batch. Nullable JSON columns stay nullable on purpose.
ARTICLE_COLUMN_UPGRADES = {
    "category": "VARCHAR(40) NOT NULL DEFAULT 'other'",
    "sentiment": "VARCHAR(16) NOT NULL DEFAULT 'UNCLEAR'",
    "sentiment_score": "INTEGER NOT NULL DEFAULT 0",
    "discoverer": "VARCHAR(40) NOT NULL DEFAULT ''",
    "company_name": "VARCHAR(255) NOT NULL DEFAULT ''",
    "isin": "VARCHAR(12) NOT NULL DEFAULT ''",
    "verification_method": "VARCHAR(80) NOT NULL DEFAULT ''",
    "financial_figures": "JSON",
}


def ensure_article_columns(conn) -> list[str]:
    """Apply the additive article-column migration and return added names."""
    existing = {column["name"] for column in
                sqlalchemy_inspect(conn).get_columns("news_articles")}
    added = []
    for name, ddl in ARTICLE_COLUMN_UPGRADES.items():
        if name in existing:
            continue
        conn.execute(text(f"ALTER TABLE news_articles ADD COLUMN {name} {ddl}"))
        added.append(name)
    return added



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
        category="other", sentiment="UNCLEAR", sentiment_score=0,
        discoverer=str(incoming.get("discoverer") or "")[:40],
        company_name=str(incoming.get("company_name") or "")[:255],
        isin=str(incoming.get("isin") or "")[:12],
        verification_method=str(incoming.get("verification_method") or "")[:80],
        financial_figures=incoming.get("financial_figures") or None,
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
        old_first = _normalize_sqlite_time(old["first_seen_at"])
        row["first_seen_at"] = _oldest(old_first, first)
        row["last_seen_at"] = _newest(old["last_seen_at"], last)
        for field in ("symbols", "sources", "providers", "authorities"):
            row[field] = _unique(old[field], row[field])
        for field in ("company_name", "isin", "verification_method"):
            if not row[field]:
                row[field] = old[field]
        # Provenance is write-once: the lane that first observed an article
        # stays its discoverer. Later lanes that re-observe the same URL are
        # recorded in article_revisions, not by rewriting this field. Only a
        # genuinely earlier observation may claim discovery.
        if old_first is None or not (first < old_first):
            row["discoverer"] = old["discoverer"] or row["discoverer"]
        elif not row["discoverer"]:
            row["discoverer"] = old["discoverer"]
        if row["financial_figures"] is None:
            row["financial_figures"] = old["financial_figures"]
    category, sentiment, score = classify_event(row["headline"], row["summary"])
    row.update(category=category, sentiment=sentiment, sentiment_score=score)
    if old:
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
        ensure_article_columns(conn)
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
        ensure_article_columns(conn)
        if conn.execute(select(archive_batches.c.batch_id).where(
                archive_batches.c.batch_id == batch["batch_id"])).first():
            return False
        for item in batch["records"]:
            _insert_or_update(conn, item, item["kind"], checked)
            fields = ("url", "headline", "summary", "published_at", "symbols",
                      "nifty_symbols", "sources", "providers", "verified_origin",
                      "discoverer", "category", "sentiment", "sentiment_score",
                      "company_name", "isin", "verification_method")
            evidence = {key: item.get(key) for key in fields}
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
        _sync_source_ledger(conn, batch, checked)
        _sync_raw_documents(conn, batch, checked)
        coverage = {key: value for key, value in batch.items()
                    if key not in {"records", "raw_documents"}}
        conn.execute(insert(archive_batches).values(
            batch_id=batch["batch_id"], checked_at=checked, coverage=coverage))
        conn.execute(insert(runs).values(
            session_date=batch.get("session") or checked.date().isoformat(),
            checked_at=checked, saved_at=datetime.now(timezone.utc),
            configured=int(batch.get("sources_configured") or len(batch.get("sources", []))),
            returning_items=int(batch.get("sources_with_items") or 0),
            failed=int(batch.get("sources_failed") or 0),
            total_articles_in_archive=len(batch.get("records", [])),
        ))
    return True


def _sync_source_ledger(conn, batch: dict, checked: datetime) -> None:
    """Upsert the latest source outcome and durable cursor for every batch."""
    for source in batch.get("sources", []):
        name = str(source.get("source") or "")[:255]
        if not name:
            continue
        status = str(source.get("status", "UNKNOWN"))[:40]
        fetched = int(source.get("fetched_items") or 0)
        kind = str(source.get("kind") or "ai_cli")[:35]
        error = str(source.get("error") or "")[:600]
        row = dict(status=status, checked_at=checked, fetched_items=fetched,
                   kind=kind, error=error)
        present = conn.execute(select(source_checks.c.source).where(
            source_checks.c.source == name)).first()
        if present:
            conn.execute(update(source_checks).where(
                source_checks.c.source == name).values(**row))
        else:
            conn.execute(insert(source_checks).values(source=name, **row))
        old = conn.execute(select(source_cursors).where(
            source_cursors.c.source == name)).mappings().first()
        failed = status in {"ERROR", "BLOCKED_ROBOTS", "TIMEOUT"}
        failures = (int(old["consecutive_failures"]) + 1 if old else 1) if failed else 0
        latest_at = aware(source.get("latest_item_at"))
        cursor = {
            "latest_raw_time": str(source.get("latest_raw_time") or "")[:80],
            "item_count": int(source.get("item_count") or fetched),
            "elapsed_seconds": source.get("elapsed_seconds"),
            "bytes": source.get("bytes"),
            "http_status": source.get("http_status"),
            "model": str(source.get("model") or "")[:120],
            "source_batch_count": source.get("source_batch_count"),
            "live_retrievals": source.get("live_retrievals"),
        }
        values = dict(status=status, checked_at=checked,
                      latest_item_at=latest_at,
                      latest_item_url=str(source.get("latest_item_url") or "")[:2048],
                      consecutive_failures=failures, cursor_state=cursor)
        if old:
            conn.execute(update(source_cursors).where(
                source_cursors.c.source == name).values(**values))
        else:
            conn.execute(insert(source_cursors).values(source=name, **values))


def _sync_raw_documents(conn, batch: dict, checked: datetime) -> None:
    for raw in batch.get("raw_documents", []):
        document_id = str(raw.get("id") or "")
        if not document_id:
            continue
        captured = aware(raw.get("captured_at")) or checked
        details = {"provider": raw.get("provider"), "authority": raw.get("authority"),
                   "kind": raw.get("kind"), "status": raw.get("status"),
                   "truncated": bool(raw.get("truncated"))}
        old = conn.execute(select(raw_documents.c.last_seen_at).where(
            raw_documents.c.id == document_id)).scalar_one_or_none()
        if old is None:
            conn.execute(insert(raw_documents).values(
                id=document_id[:64], source=str(raw.get("source") or "")[:255],
                url=str(raw.get("url") or "")[:2048],
                content_type=str(raw.get("content_type") or "")[:120],
                sha256=str(raw.get("sha256") or "")[:64],
                byte_size=int(raw.get("byte_size") or 0),
                storage_path=str(raw.get("storage_path") or "")[:2048],
                captured_at=captured, last_seen_at=captured, details=details))
        else:
            conn.execute(update(raw_documents).where(raw_documents.c.id == document_id).values(
                last_seen_at=_newest(old, captured),
                storage_path=str(raw.get("storage_path") or "")[:2048],
                byte_size=int(raw.get("byte_size") or 0), details=details))


def prune_raw_documents(engine, *, days: int = 30) -> int:
    """Remove raw-document index rows outside the retention window."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    with engine.begin() as conn:
        metadata.create_all(conn)
        result = conn.execute(raw_documents.delete().where(
            raw_documents.c.last_seen_at < cutoff))
        return int(result.rowcount or 0)


def backfill_article_fields(engine) -> dict:
    """Populate classification/discoverer columns for rows written by old releases."""
    scanned = updated = 0
    with engine.begin() as conn:
        metadata.create_all(conn)
        added = ensure_article_columns(conn)
        discoverers: dict[str, str] = {}
        for article_id, evidence in conn.execute(select(
                article_revisions.c.article_id, article_revisions.c.evidence)):
            if isinstance(evidence, str):
                try:
                    evidence = json.loads(evidence)
                except ValueError:
                    evidence = {}
            value = str((evidence or {}).get("discoverer") or "")[:40]
            if value and article_id not in discoverers:
                discoverers[article_id] = value
        rows = conn.execute(select(
            articles.c.id, articles.c.headline, articles.c.summary, articles.c.category,
            articles.c.sentiment, articles.c.sentiment_score, articles.c.published_at,
            articles.c.verification_method, articles.c.discoverer)).mappings().all()
        for row in rows:
            scanned += 1
            category, sentiment, score = classify_event(row["headline"], row["summary"])
            discoverer = row["discoverer"] or discoverers.get(row["id"], "")
            verification = row["verification_method"] or (
                "source_feed_timestamp" if row["published_at"]
                else "unverified_no_publication_time")
            if (category, sentiment, score, discoverer, verification) != (
                    row["category"], row["sentiment"], row["sentiment_score"],
                    row["discoverer"], row["verification_method"]):
                conn.execute(update(articles).where(articles.c.id == row["id"]).values(
                    category=category, sentiment=sentiment, sentiment_score=score,
                    discoverer=discoverer, verification_method=verification))
                updated += 1
    return {"status": "FIELDS_BACKFILLED", "scanned": scanned, "updated": updated,
            "columns_added": added}



def main() -> None:
    from news_collector.engine import ROOT, IST, default_session
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-date", default=None)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--require-db", action="store_true")
    parser.add_argument("--backfill-all", action="store_true",
                        help="Import existing saved session archives one time")
    parser.add_argument("--backfill-fields", action="store_true",
                        help="Fill category/sentiment/discoverer for existing DB rows")
    args = parser.parse_args()
    url = os.getenv("NEWS_DATABASE_URL", "")
    if not url:
        if args.require_db:
            raise SystemExit("NEWS_DATABASE_URL missing; database sync did not run")
        print(json.dumps({"status": "SKIPPED_NO_DB", "reason": "NEWS_DATABASE_URL not configured"}))
        return
    engine = engine_for_url(url)
    if args.backfill_fields:
        print(json.dumps(backfill_article_fields(engine)))
        return
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
