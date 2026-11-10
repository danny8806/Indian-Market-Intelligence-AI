"""Copy option-selling trade details from a read-only SQLite database or backup."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import sqlite3

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from news_collector.db_store import engine_for_url

metadata = MetaData()
trades = Table(
    "option_trade_details", metadata,
    Column("source", String(80), primary_key=True),
    Column("trade_id", String(200), primary_key=True),
    Column("underlying", String(80), nullable=False, index=True),
    Column("status", String(32), nullable=False, index=True),
    Column("entry_time", String(80), nullable=False, index=True),
    Column("exit_time", String(80)),
    Column("details", JSON, nullable=False),
    Column("archived_at", DateTime(timezone=True), nullable=False),
    schema="trade_archive",
)


def sync_option_trades(source_file: Path, engine, *, source="mcx-option-selling-demo") -> int:
    uri = source_file.resolve(strict=True).as_uri() + "?mode=ro"
    now = datetime.now(timezone.utc)
    with closing(sqlite3.connect(uri, uri=True)) as db, engine.begin() as conn:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM option_trades ORDER BY trade_id")
        if conn.dialect.name == "sqlite":
            conn = conn.execution_options(schema_translate_map={"trade_archive": None})
            insert = sqlite_insert
        else:
            insert = pg_insert
        metadata.create_all(conn)
        count = 0
        for row in rows:
            trade = dict(row)
            statement = insert(trades).values(
                source=source, trade_id=trade["trade_id"], underlying=trade["underlying"],
                status=trade["status"], entry_time=trade["entry_time"],
                exit_time=trade.get("exit_time"), details=trade, archived_at=now)
            conn.execute(statement.on_conflict_do_update(
                index_elements=[trades.c.source, trades.c.trade_id],
                set_={key: getattr(statement.excluded, key) for key in (
                    "underlying", "status", "entry_time", "exit_time", "details", "archived_at",
                )}))
            count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source_db", type=Path)
    args = parser.parse_args()
    engine = engine_for_url(os.environ["TRADE_ARCHIVE_DATABASE_URL"])
    print(json.dumps({"trade_details_synced": sync_option_trades(args.source_db, engine)}))
