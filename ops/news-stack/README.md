# Isolated stock-market news

The Compose project exposes no database port. The stock dashboard keeps its own trading records. The news service has no access to option-selling data. Research reports are stored
with execution_enabled=false. The news service has no broker or bridge credentials.

## Scheduler and data flow

- market-news-collect.timer runs every ten minutes in Asia/Kolkata. The one-shot
  collector uses four HTTP workers and a shared lock. It commits staged batches
  transactionally to news_articles, news_article_revisions and news_archive_batches.
  A failed database write leaves the batch queued on the archive volume for replay.
- Codex discovery searches independently, then verifies returned links against
  configured original publisher metadata or the original exchange feed. Its
  default budget is 48 discovery slots per IST day, at :00 and :30. Set
  NEWS_CODEX_DAILY_CALLS from 0 to 48 to cap usage. Missing authentication
  or retrieval failure is reported per attempt.
- market-news-morning.timer starts research at 08:00 IST on weekdays, refreshes
  at 08:30 and 08:55, and locks the final research watchlist at 09:00. The job
  checks the NSE session calendar and reuses a completed draft only when it
  matches the verified evidence at lock time. The 09:00 job does not wait for
  another model call. It persists one report in news_morning_reports. Changed
  evidence or a missing reviewed draft produces UNAVAILABLE with no signals.
  Update the bundled 2026 calendar before running morning research in the
  following year.

## Broker coverage

Public broker news and research are stored as leads. The broker summary or analyst
opinion never provides a verified original timestamp. Retain the publisher and
exchange feeds to verify the underlying event. Source status distinguishes a
robots restriction, a failed request, and a reachable listing with no usable items.
These routes use no brokerage login or order APIs.

## Rollout and checks

The GitHub deploy workflow is manual. The activation script validates the separate
Compose stack, runs a news collection smoke test, and starts the timers.
It needs approved VPS SSH and systemd access. The first deployment keeps the previous
stack available until verification. Preserve Docker volumes and back up any retired
container configuration before removal. Avoid Docker pruning.

On the VPS, check systemctl list-timers market-news-* and journalctl for the
individual services. Report actual timer timestamps, news counts, distinct
source failures, disk and memory before cleanup. Verify the existing stock dashboard separately.

Provision Codex interactively using the dedicated named credential volume.
From the release root, use the pinned news Compose config and run the collector
service with --entrypoint codex and login --device-auth. Complete the login in
the operator browser. No login state is stored in the code or database.

See [Independent CLI discovery](CLI_AGENTS.md) for the additional agent lanes.
