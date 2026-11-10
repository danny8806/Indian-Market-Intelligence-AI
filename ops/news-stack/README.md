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
- market-news-morning.timer starts research at 08:00 IST on weekdays and
  refreshes at 08:30, 08:55 and 09:00. At 09:05 the job freezes the news
  evidence from 15:00 on the previous regular NSE session.
  It reuses a matching completed draft or ranks the frozen evidence in the
  finalization window. The 09:10
  job locks an empty UNAVAILABLE report if no review has completed, and the
  09:12 deadline prevents publishing a late result. One final research
  watchlist is persisted in news_morning_reports. Update the bundled 2026
  calendar before running morning research in the following year.

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
