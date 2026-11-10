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
command -v systemctl >/dev/null || { echo "BLOCKED: systemd missing"; exit 3; }
SYSTEM_INSTALL=(install)
SYSTEMCTL=(systemctl)
if [[ "$EUID" != 0 ]]; then
  sudo -n true || { echo "BLOCKED: approved sudo required to install systemd units"; exit 3; }
  SYSTEM_INSTALL=(sudo -n install)
  SYSTEMCTL=(sudo -n systemctl)
fi
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
echo "Building isolated PostgreSQL and ten-minute news collector..."
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
if ! grep -q '^TRADE_ARCHIVE_PASSWORD=' "$ENV"; then
  printf 'TRADE_ARCHIVE_PASSWORD=%s\n' "$(openssl rand -hex 32)" >> "$ENV"
fi
{
  sed -n 's/^TRADE_ARCHIVE_PASSWORD=//p' "$ENV"
  cat "$RELEASE/ops/news-stack/init-trade-archive.sql"
} | run_compose exec -T postgres sh -ec '
  IFS= read -r TRADE_ARCHIVE_PASSWORD
  export TRADE_ARCHIVE_PASSWORD
  exec psql -U news_admin -d market_news -q -v ON_ERROR_STOP=1
'
run_compose build collector

# Stop only the previous persistent collector in this Compose project. If the
# first one-shot fails, restart that exact previous container.
OLD_COLLECTOR="$(docker ps --filter label=com.docker.compose.project=market-news-db \
  --filter label=com.docker.compose.service=collector \
  --filter label=com.docker.compose.oneoff=False --format '{{.ID}}')"
[[ "$OLD_COLLECTOR" != *$'\n'* ]] || { echo "BLOCKED: multiple prior collectors"; exit 5; }
if [[ -n "$OLD_COLLECTOR" ]]; then docker stop "$OLD_COLLECTOR"; fi
if ! run_compose run --rm --no-deps -T collector --archive --once; then
  if [[ -n "$OLD_COLLECTOR" ]]; then docker start "$OLD_COLLECTOR"; fi
  echo "BLOCKED: PostgreSQL collection smoke test failed"
  exit 5
fi
run_compose run --rm --no-deps -T --entrypoint python collector -m news_collector.healthcheck
ARTICLES="$(run_compose exec -T postgres psql -U news_admin -d market_news -Atqc \
  "select count(*) from news_articles;")"
echo "DB VERIFIED: news_articles count=$ARTICLES"

# Install the units before switching the stable release pointer. Keep prior
# releases and all volumes so rollback does not require restoring a database.
for unit in market-news-{collect,morning,trades}.{service,timer}; do
  "${SYSTEM_INSTALL[@]}" -m 644 "$RELEASE/ops/news-stack/$unit" "/etc/systemd/system/$unit"
done
bash "$RELEASE/ops/news-stack/archive-option-trades.sh"
ln -sfn "$RELEASE" "$BASE/current.new"
mv -Tf "$BASE/current.new" "$BASE/current"
"${SYSTEMCTL[@]}" daemon-reload
"${SYSTEMCTL[@]}" enable --now market-news-collect.timer market-news-morning.timer market-news-trades.timer
"${SYSTEMCTL[@]}" is-active market-news-collect.timer market-news-morning.timer market-news-trades.timer
printf '%s\n' "$SHA" > "$BASE/last_verified_news_commit"
