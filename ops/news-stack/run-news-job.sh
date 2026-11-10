#!/usr/bin/env bash
set -Eeuo pipefail
BASE=/home/jadhavdnyaneshwar701/market-news-db
COMPOSE=(docker compose -p market-news-db --env-file "$BASE/config/news.env"
         -f "$BASE/current/ops/news-stack/compose.yaml")
case "${1:-}" in
    collect)
        exec "${COMPOSE[@]}" run --rm --name market-news-collect-job --no-deps -T collector --archive --once
        ;;
    morning)
        exec "${COMPOSE[@]}" run --rm --name market-news-morning-job --no-deps -T \
            --entrypoint python collector -m news_collector.morning
        ;;
    *)
        exit 2
        ;;
esac
