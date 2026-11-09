# Continuous NIFTY 500 news collection: PostgreSQL and OpenAI

This is a research collector, not a trading model or broker bridge.

## Methods

- The existing news_collector.engine reads all configured, authorized sources, records errors, and saves JSONL news records.
- The optional OpenAI Responses web_search module saves cited URLs as discovery leads, WITHOUT inventing original publication times.
- news_collector.db_store stores news records in PostgreSQL or SQLite, with separate article, symbol, source-health, and polling-run tables.
- news_collector.continuous_worker runs on a VPS every 10 minutes during 15:00–09:00 IST and every 30 minutes outside the window.
- The decision model must use a separate read-only database account and only news actually collected before its decision cutoff.

## News schema

news_articles contains: id (URL hash), url, headline, summary, record_kind (timestamped_stock, discovery_only or macro_context), time_status, published_at, first_seen_at, last_seen_at, ingested_at, symbols, sources, providers, authorities, provider_reported_time_unverified.

All database datetimes are UTC. First_seen_at represents when the collector observed the item, whereas published_at is the original feed's declared publication time when parseable. An indexed search result always has NULL published_at. The time_status SOURCE_TIME_PARSED_NOT_INDEPENDENTLY_VERIFIED means format is correct, NOT that the publisher time has been independently corroborated. The downstream model must verify original publisher timing and ticker mapping.

news_article_symbols holds article-to-stock links. news_source_checks stores latest source status/count/error. news_ingest_runs stores each collection cycle. Repeated polls upsert the same document; they should not create duplicate articles.

Caveat: URL-based identity cannot reliably distinguish separate exchange filings sharing a listing URL; exact ISIN/disclosure-ID reconciliation remains required.

## PostgreSQL activation

Provision an independent PostgreSQL database and a least-privilege news-writer user. Never use the trading signal database credentials. Configure environment variables on an internet-enabled VPS:

NEWS_DATABASE_URL=postgresql+psycopg://news_writer:YOUR_PASSWORD@YOUR_HOST:5432/newsdb?sslmode=require
ENABLE_OPENAI_WEB_RESEARCH=false
OPENAI_MAX_SEARCHES_PER_DAY=6
OPENAI_NEWS_MODEL=gpt-5.6

Set ENABLE_OPENAI_WEB_RESEARCH=true and OPENAI_API_KEY only when you have reviewed OpenAI API pricing and authorized additional API billing. Search calls are capped by the daily budget file, and inactive by default.

Run one test:

    python -m pip install -r news_collector/requirements.txt
    python -m unittest discover -s news_collector -p 'test_*.py' -v
    python -m news_collector.continuous_worker --once

To import existing session archives to a fresh PostgreSQL database one time:

    python -m news_collector.db_store --require-db --backfill-all

For continuous VPS service, create a dedicated newsbot system user, a writable news_collector/data folder, a Python virtual environment, and /etc/market-news.env with mode 0600. Install ops/market-news-collector.service as /etc/systemd/system/market-news-collector.service, adjust paths, then run:

    sudo systemctl daemon-reload
    sudo systemctl enable --now market-news-collector
    sudo systemctl status market-news-collector

This repo contains the deployment configuration, but it does not deploy it to the user's VPS without access to a configured server/database.

The existing GitHub Actions overnight-news-collector workflow syncs data when the repository Actions secret NEWS_DATABASE_URL is configured; otherwise it prints SKIPPED_NO_DB and keeps JSONL results. Set OPENAI_API_KEY as a GitHub Actions secret and ENABLE_OPENAI_WEB_RESEARCH=true as a GitHub Actions variable to enable optional OpenAI web searches. This does not turn on live trades.

## Downstream pre-open query

The decision model must compare BOTH published_at and first_seen_at with the market cutoff, and only use timestamped_stock records after independent evidence validation. Example PostgreSQL:

    SELECT a.url, a.headline, s.symbol, a.published_at, a.first_seen_at
    FROM news_articles a
    JOIN news_article_symbols s ON s.article_id = a.id
    WHERE a.record_kind = 'timestamped_stock'
      AND a.published_at >= TIMESTAMPTZ '2026-11-09 15:00:00+05:30'
      AND a.published_at < TIMESTAMPTZ '2026-11-11 09:00:00+05:30'
      AND a.first_seen_at < TIMESTAMPTZ '2026-11-11 09:00:00+05:30';

Late-discovered news must not be backfilled into past decisions. Inspect news_ingest_runs and news_source_checks for errors, and ensure publisher/source collection permissions are satisfied. GitHub Actions scheduled jobs can be delayed: use the VPS service for reliable ongoing collection.
