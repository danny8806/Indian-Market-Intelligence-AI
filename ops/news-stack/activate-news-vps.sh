#!/usr/bin/env bash
# Run only inside an authorized VPS SSH session.
# Isolated Postgres/collector compose project; does not touch Kotak or old stacks.
set -Eeuo pipefail
umask 077

BASE="$1"
SHA="$2"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid release SHA"; exit 2; }
[[ "$BASE" == "/home/jadhavdnyaneshwar701/market-news-db" ]] || {
  echo "Unexpected VPS base"; exit 2;
}
RELEASE="$BASE/releases/$SHA"
ENV="$BASE/config/news.env"
COMPOSE="$RELEASE/ops/news-stack/compose.yaml"

command -v docker >/dev/null || { echo "BLOCKED: Docker missing"; exit 3; }
docker compose version >/dev/null || { echo "BLOCKED: Compose missing"; exit 3; }
command -v openssl >/dev/null || { echo "BLOCKED: openssl missing"; exit 3; }
[[ -f "$COMPOSE" && -f "$RELEASE/news_collector/engine.py" ]] || {
  echo "BLOCKED: required research-only release files missing"; exit 3;
}
mkdir -p "$BASE/config"

if [[ ! -e "$ENV" ]]; then
  # Secrets exist on the VPS only, never in a GitHub commit or GitHub output.
  ADMIN="$(openssl rand -hex 32)"
  WRITER="$(openssl rand -hex 32)"
  READER="$(openssl rand -hex 32)"
  printf 'NEWS_ADMIN_PASSWORD=%s\nNEWS_WRITER_PASSWORD=%s\nNEWS_READER_PASSWORD=%s\n' \
      "$ADMIN" "$WRITER" "$READER" > "$ENV.tmp"
  chmod 600 "$ENV.tmp"
  mv "$ENV.tmp" "$ENV"
  unset ADMIN WRITER READER
  echo "Created private VPS-only database credentials."
fi

[[ "$(stat -c %a "$ENV")" == "600" ]] || {
  echo "BLOCKED: private news DB environment file must be mode 600"; exit 3;
}
run_compose() {
  docker compose -p market-news-db --env-file "$ENV" -f "$COMPOSE" "$@"
}

run_compose config -q
echo "Building isolated market-news Postgres and 20-minute research collector..."
run_compose up -d --build --no-deps postgres
for attempt in $(seq 1 60); do
  if run_compose exec -T postgres pg_isready -U news_admin -d market_news >/dev/null 2>&1; then
    break
  fi
  sleep 4
done
run_compose exec -T postgres pg_isready -U news_admin -d market_news >/dev/null || {
  echo "BLOCKED: private PostgreSQL did not become ready"; exit 4;
}
run_compose up -d --build --no-deps collector

# Real E2E signal: collector's SQL-backed sync heartbeat must be fresh.
verified=0
for attempt in $(seq 1 100); do
  if run_compose exec -T collector python -m news_collector.healthcheck >/dev/null 2>&1; then
    verified=1
    break
  fi
  sleep 5
done
[[ "$verified" == "1" ]] || {
  echo "BLOCKED: collector failed to persist its news batch to PostgreSQL"; exit 5;
}
TABLES="$(run_compose exec -T postgres psql -U news_admin -d market_news -Atqc \
  "select count(*) from information_schema.tables where table_schema='public' and table_name in ('news_articles','news_ingest_runs','news_source_checks','news_article_symbols');")"
[[ "$TABLES" == "4" ]] || {
  echo "BLOCKED: news database tables incomplete"; exit 6;
}
ARTICLES="$(run_compose exec -T postgres psql -U news_admin -d market_news -Atqc \
  "select count(*) from news_articles;")"
echo "DB VERIFIED: 4 tables present; news_articles count=$ARTICLES"
echo "COLLECTOR VERIFIED: private 20-minute research-only worker, no OpenAI API calls."
echo "DATABASE IS PRIVATE: no host listener or public PostgreSQL port configured."
ln -sfn "$RELEASE" "$BASE/current.new"
mv -Tf "$BASE/current.new" "$BASE/current"
printf '%s\n' "$SHA" > "$BASE/last_verified_news_commit"
