#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
BASE=/home/jadhavdnyaneshwar701/market-news-db
ENV="$BASE/config/news.env"
PASS="$(sed -n 's/^TRADE_ARCHIVE_PASSWORD=//p' "$ENV")"
[[ "$PASS" =~ ^[a-f0-9]{64}$ ]] || { echo "Trade archive credentials unavailable"; exit 3; }
MOUNT="$(docker volume inspect -f '{{.Mountpoint}}' mcx_option_selling_db)"
SOURCE="$MOUNT/option_paper_trading.db"
[[ -f "$SOURCE" ]] || { echo "Option-selling trade database unavailable"; exit 4; }
TEMP_DB="$(mktemp -d)"
trap 'rm -f "$TEMP_DB/trades.db"; rmdir "$TEMP_DB"' EXIT
python3 - "$SOURCE" "$TEMP_DB/trades.db" <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
source, backup = map(Path, sys.argv[1:])
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
    with closing(sqlite3.connect(backup)) as copy:
        db.backup(copy)
PY
chmod 644 "$TEMP_DB/trades.db"
IMAGE="$(docker compose -p market-news-db --env-file "$ENV" \
    -f "$BASE/current/ops/news-stack/compose.yaml" config --images | grep -Fx 'market-news-db-collector')"
export TRADE_ARCHIVE_DATABASE_URL="postgresql+psycopg://trade_archive_writer:$PASS@postgres:5432/market_news"
docker run --rm --name market-news-trade-job --network market-news-private \
    --memory 256m --cpus 0.25 --mount "type=bind,src=$TEMP_DB/trades.db,dst=/trade-source.db,readonly" \
    -e TRADE_ARCHIVE_DATABASE_URL --entrypoint python "$IMAGE" \
    -m news_collector.trade_archive /trade-source.db
