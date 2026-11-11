#!/bin/sh
set -eu
# Reconstruct the SQL archive from persisted source JSONL only on first boot.
# If backfill fails, the container restarts instead of claiming a healthy DB.
marker=/app/news_collector/data/.db_backfill_completed
if [ ! -e "$marker" ]; then
    python -m news_collector.db_store --require-db --backfill-all
    : > "$marker"
fi
exec python -m news_collector.continuous_worker "$@"
