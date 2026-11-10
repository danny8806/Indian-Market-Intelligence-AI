# Isolated market news and option trade archive

The Compose project exposes no database port. The Kotak dashboard and option-selling
application retain their current services and volumes. Research reports are stored
with execution_enabled=false. The news service has no broker or bridge credentials.

## Scheduler and data flow

- market-news-collect.timer runs every ten minutes in Asia/Kolkata. The one-shot
  collector uses four HTTP workers and a shared lock. It commits staged batches
  transactionally to news_articles, news_article_revisions and news_archive_batches.
  A failed database write leaves the batch queued on the archive volume for replay.
- Codex discovery searches independently, then verifies returned links against
  configured original publisher metadata or the original exchange feed. Its
  default budget is 24 scheduled discovery slots per IST day. Set
  NEWS_CODEX_DAILY_CALLS from 0 to 144. The 09:00 slot is reserved for morning
  research. Missing authentication or retrieval failure is reported per attempt.
- market-news-morning.timer runs at 09:00 IST on weekdays. The job checks the
  NSE regular-session calendar, freezes evidence already committed before the
  cutoff, and stores the validated report in news_morning_reports. The analyst
  and critic run separately and receive only frozen evidence. Update the bundled
  2026 calendar before running morning research in the following year.
- market-news-trades.timer reads a consistent SQLite backup of the option-selling
  app every fifteen minutes and upserts trade_archive.option_trade_details.
  This is a read-only copy of the existing option paper ledger. The app continues
  to write its own option_trades table. Only the archive role can write the
  separate PostgreSQL trade schema.

## Rollout and checks

The GitHub deploy workflow is manual. The activation script validates the separate
Compose stack, runs a collection and trade archive smoke test, and starts the timers.
It needs approved VPS SSH and systemd access. The first deployment keeps the previous
stack available until verification. Preserve Docker volumes and back up any retired
container configuration before removal. Avoid Docker pruning.

On the VPS, check systemctl list-timers market-news-* and journalctl for the
individual services. Report actual timer timestamps, news counts, distinct
source failures, option archive row counts, disk and memory before cleanup.
Option-selling and Kotak dashboard health are separate rollout gates.

Provision Codex interactively using the dedicated named credential volume.
From the release root, use the pinned news Compose config and run the collector
service with --entrypoint codex and login --device-auth. Complete the login in
the operator browser. No login state is stored in the code or database.
