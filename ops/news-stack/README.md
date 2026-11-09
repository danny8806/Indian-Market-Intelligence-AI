# Continuous no-OpenAI-API market-news stack

This is a **research-only collector and durable PostgreSQL archive**. It must
not submit broker orders or turn search-index leads into verified filing times.

## Schedules and roles

- **VPS Docker collector**: every 20 minutes, 24/7, restarting after crashes.
  It retrieves the configured feeds and polls the repository's public ChatGPT
  inbox. It writes into local Docker volumes and PostgreSQL transactionally.
- **GitHub Actions fallback**: `17,37,57 * * * *` UTC (every 20 minutes).
  Also preserves high-priority pre-market jobs. Actions runs are best effort
  and may start late. These runs save JSONL to GitHub even when VPS is offline.
- **ChatGPT scheduled research**: hourly, its shortest supported recurrence.
  Each run writes cited URL leads to `news_collector/chatgpt_inbox/*.json`.
  Its outputs have NULL `published_at` until verified from an original source.
- **Codex**: configure a separate Codex Cloud or supported desktop automation
  with repository access for deep audit/repair. Codex scheduling is **not**
  created merely by committing these files. Use the prompt below and select
  the fastest supported cadence in Codex. Do not claim it runs every 20 minutes
  unless its actual scheduling UI confirms it.

OpenAI API web search, paid news APIs and Serper are **OFF** in the automated
20-minute pipeline. ChatGPT/Codex subscription usage does not become
OpenAI API credentials.

## VPS deployment

The GitHub workflow `.github/workflows/deploy-news-vps.yml` attempts the
deployment when this research-only code or stack changes. It requires four
GitHub Actions secrets: `VPS_HOST`, `VPS_USER`,
`VPS_SSH_PRIVATE_KEY`, and `VPS_SSH_KNOWN_HOSTS`. Secret values are never
logged and the SSH host key is pinned. If any are absent, the deployment
fails clearly; the cloud news-collection fallback still runs.

The deploy script uploads ONLY `news_collector` and `ops/news-stack` into
`/home/jadhavdnyaneshwar701/market-news-db/releases/<SHA>`. It does not
alter, stop or share any Kotak service, trading order mode, old dashboard or
existing PostgreSQL container. No externally reachable port is published.

An isolated `market-news-db` Docker Compose project starts:
- private `postgres:16-alpine` database in a persistent Docker volume;
- `newsbot` Python collector with source archive and inbox Docker volumes;
- 20-minute SQL sync + `last_successful_db_sync.json` health marker.

On first deployment the server generates three strong passwords using
`openssl rand` in a 0600 configuration file. The PostgreSQL admin, writer and
reader roles are separate. Only the news writer can add news records, while
`news_reader` can SELECT news tables. The database is on an internal Docker
network; the collection worker has a second, outbound network for public
web/news access. No database passwords enter Git or GitHub Actions logs.

The collector bootstrap backfills existing session JSONL files from the
GitHub repository image. On later polls it reads public GitHub inbox files
without an authentication token, validates the inbox JSON, marks links
*discovery only*, and stores them. The collector also writes source success/
failure counts and run history, with UTC DB timestamps and separate
publisher/first-seen/ingestion clocks.

### Confirm deployment

In GitHub Actions, open **Deploy isolated news PostgreSQL and 20-minute
collector to VPS**. A success result must include both:
- `DB VERIFIED: 4 tables present; news_articles count=N`, and
- `COLLECTOR VERIFIED` after a fresh SQL-backed collector heartbeat.

Without both checks, do not call the VPS database deployed. The cloud
collector can still be successful without a VPS DB.

### Read-only decision model

A downstream model running on the VPS can join the network named
`market-news-private` and use the separate `news_reader` role, without
opening port 5432 on the internet. Build any network bridge with TLS and
authorization if the model is outside the VPS. Never expose SQL publicly.

The model must filter the overnight event window using `published_at` and
`first_seen_at`, restrict to `timestamped_stock`, and verify the original
disclosure, NIFTY 500 ticker, financial figures and novelty. Search-discovered
items are not automatically actionable.

## Codex task prompt

In the authorized `danny8806/Indian-Market-Intelligence-AI` repository,
audit the most recent 20-minute collector and VPS database health logs.
Compare verified NSE/BSE disclosures with public publisher searches and the
ChatGPT discovery inbox. Quantify source failures, event time ambiguity,
ticker mismatches and missed disclosures without treating a search engine
index timestamp as original publication. Run the complete offline unit tests.
If a collector defect is reproducible, propose a minimal PR with tests.
Never enable OpenAI API billing, scrape 401/403-restricted pages, modify trade
orders or change the frozen stock-selection outputs. Report link counts, DB
row-count changes and verified-versus-unverified evidence distinctly.

## Limitations and maintenance

No software system can guarantee uninterrupted operation or complete coverage
of all publishers. Check 20-minute cron runs, VPS heartbeat age, container
health, backups and permissions; retry transient errors only. GitHub Actions
schedules can be delayed. ChatGPT scheduled tasks may pause when usage or
account settings require action. Source terms and exchange licenses still
apply. The managed cloud server itself has hosting costs.
