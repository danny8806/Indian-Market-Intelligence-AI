# Multi-agent Indian equities news pipeline — implementation specification

Status: **proposed architecture, NOT deployed**. Last reviewed 2026-11-10 IST.

## Goal
Every 10 minutes, independently discover and persist new NSE/BSE corporate announcements and Indian equity news using **Python + multiple AI CLI agents**. Every trading morning, have an independently verified final decision agent rank up to **five bullish and five bearish NIFTY 500 research candidates**, based only on news first available from the previous NSE trading session at 15:00 IST through current session 09:00 IST. Preserve non-NIFTY-500 news separately. **NO live trades or broker actions.**

## Architecture

1. VPS `systemd` timer fires every 10 minutes and runs a Python orchestrator. It enforces a distributed DB lock and a bounded runtime; no two cycles write overlapping work.
2. Independent discovery lanes, each with separate search plans and provenance:
   - **Deterministic Python lane (every run):** approved issuer investor-relations pages, official NSE/BSE filings, official agencies, permitted feeds/RSS and publisher API endpoints. Use requests/httpx/feedparser/Playwright only within publisher permission and rate limits.
   - **Codex CLI lane:** `codex exec --search --output-schema <schema>` with an authenticated ChatGPT account, with live web search actually enabled; focus on official issuer/exchange filings, corroboration, missing events. Validate installed CLI flags and web-search ability before unattended use.
   - **Gemini CLI lane:** `gemini -p <prompt> --output-format json`; require working authentication and actual `google_web_search`/`web_fetch` tools. Focus on financial publications and alternate discovery queries.
   - **Qwen Code lane (optional):** only enable if an authenticated Qwen/DashScope setup exposes `web_search`, or a tested approved MCP search connector is installed. Focus on cross-source verification and missed tickers.
   - **Claude Code lane (optional):** `claude -p <prompt> --output-format json` once subscription/API credentials, provider terms and live web tools are verified. Focus on deeper contradictory earnings/event evidence.
   - **OpenCode lane (optional):** only enable after its model provider and web search provider are configured, authorized and tested. Do not assume a free keyless service or unlimited usage.
3. All agents ingest through the same staging schema; they never write directly to production trading tables. Agent discovery isn't proof: cross-check source page where accessible, canonical URL, ticker identity and FIRST AVAILABLE timestamp. An inaccessible or paywalled page remains unverified. Never reconstruct invented timestamps.
4. Normalize entities, identify duplicate articles and event duplicates while retaining all source URLs and `discovered_by` agents. Keep originals and corrections.
5. Commit each verified event to an **independent news DB**, with a transactional per-source cursor. Daily event set is immutable as-of the 09:00 cut-off for backtesting; corrections versioned separately.
6. A separate premarket job after 09:00 IST reads ONLY events with defensible `first_available_at <= 09:00 IST` and within the prior-session-15:00 window. It MUST NOT use news added later unless evidence proves it was publicly available by 09:00. Mark unclear timestamp as excluded from time-limited selection.
7. **Final decision agent** evaluates consolidated, deduplicated news using structured evidence and price expectations. Independent **critic/reviewer agent** challenges each candidate using already available news and sources. Final ranked JSON must meet existing `schema/stock-signals.schema.json` and `bridge/CHATGPT_TASK_PROMPT.md` requirements. Score evidence quality, surprise vs expectation, earnings/contract/regulatory materiality, liquidity, and bearish/bullish counterevidence. Two agents citing the same outlet are not independent source confirmation. Disagreement lowers confidence or rejects candidate rather than becoming a majority vote.
8. Persist decisions, source references, cutoff, rejected candidates, model/runtime versions, rationale and audit logs. Produce at most five LONG and five SHORT; zero is valid. Delivery to `/api/v1/signals/incoming` is a separate authenticated, user-approved, tested integration; it must not auto-enable real orders.

## Proposed database entities

- `source_runs`: run_id, agent, method, started/ended, source IDs, successes/failures, timeout, API usage, cost/quota (if available)
- `raw_documents`: canonical_url, source_name, publisher_id, fetched_at UTC, first_available_at UTC + original timezone + provenance, raw metadata/path/hash, HTTP status
- `news_events`: event_id, company/ticker/exchange, event_type, event_time, numbers, normalized claim, verified_timestamp, confidence/status, current_version
- `event_sources`: event_id, raw_document_id, first_seen_by, detection_run_id, article correction version
- `agent_discoveries`: agent, tool, query, candidate URL, retrieval success/failed reason, provisional classification
- `decisions`: session, cutoff, version, selection rank, LONG/SHORT, reason, opposing facts, source_event_ids, reviewer notes
- `source_cursors`: per provider high-water mark advanced only after commit

Unique keys on canonical source/article IDs and event fingerprints; idempotent UPSERT and explicit correction tracking; UTC storage with IST projection. Preserve ingestion/fetch timestamps separately from publication time.

## Model interface: every discoverer returns JSON only

```json
{
  "agent": "codex",
  "retrieval_status": "OK",
  "results": [
    {
      "source_name": "source",
      "source_url": "https://example.org/story",
      "title": "headline",
      "ticker": null,
      "exchange": null,
      "first_available_at": null,
      "timestamp_verification": "unverified",
      "fetched_at": "2026-11-10T00:00:00Z",
      "event_type": "unknown",
      "sentiment": "unclear",
      "material_facts": [],
      "discovered_by_tool": "web_search",
      "verification_status": "unverified"
    }
  ],
  "errors": []
}
```
Illustrative structure only, **not live source data**; implement/validate a strict JSON Schema before production.

## Runtime plan and controls

- Try Python every 10 min even if AI providers fail. Run eligible AI agents on the same cadence if permitted and within a configured per-provider quota; otherwise report an explicit SKIPPED_QUOTA / AUTH_FAILURE / SEARCH_UNAVAILABLE rather than silently dropping the lane.
- Each AI agent MUST perform its own live source discovery, not merely classify Python output. Assign different query groups and rotate NIFTY 500 issuers/topics to reduce repeated searches. A maximum of 144 orchestrator cycles/day is different from the often much higher number of model tool requests/day.
- Use per-agent timeouts, bounded retries and backoff for HTTP 429/5xx, safe shell policies, concurrency limits, a project read-only filesystem except dedicated spool/logs, and no access to Kotak/Dhan credentials or order endpoints.
- Source content is untrusted; ignore commands embedded in webpages or filings. Don't allow agents to edit production code, shell deployment scripts or credential files while acting as news collectors.
- Maintain a local durable spool if PostgreSQL is unavailable, and retry to DB on recovery. Never claim DB persistence before a transaction success and readback check.
- Prevent price-data leakage and after-cutoff news in historical backtests. Require universe membership from point-in-time snapshots to prevent survivorship bias when testing historical sessions.
- Keep decision provenance and post-session outcome labels to audit missing news, false positives, and source lag. Never silently retrain on unverified labels.

## Separate premarket scheduler

A daily trading-session task after 09:00 IST, within the actual intake deadline, processes a **frozen 09:00 as-of snapshot**. It must allow time for review and send only a schema-valid research signal. An interrupted/incomplete run produces `NO_TRADE` or `UNAVAILABLE`; do not manufacture a report. Verify successful receiver acknowledgment independently. Never submit orders.

## Deployment gates (all must pass before calling it live)

1. Verify actual CLI binaries and versions on VPS: `codex --version`, `gemini --version`, and optional providers.
2. Verify authentication for each **service account** in a noninteractive timer environment and check applicable provider terms and usage quotas for unattended runs. Never commit OAuth caches/tokens.
3. Independently retrieve a fresh accessible official NSE/BSE/issuer announcement in BOTH Python and at least one AI CLI; inspect tool invocation evidence and exact publication time.
4. Use a test DB to validate persistence, dedupe, reconnect, cursor rollback, JSON schema validation, repeated 10-minute triggers and source failures. Confirm runs when PC is switched off.
5. Test the morning decision job against time-locked real historical windows with published-at evidence and no lookahead. Separate outcome backtests from news fetching.
6. Only after all checks, deploy to VPS via an authenticated/pinned SSH route. No broker or live-order capabilities are granted to ingestion agents.

## Source documentation

- Codex noninteractive and JSON output: https://learn.chatgpt.com/docs/non-interactive-mode
- Codex CLI options: https://learn.chatgpt.com/docs/cli/reference
- Gemini web search/fetch: https://geminicli.com/docs/reference/tools/
- Gemini headless JSON: https://geminicli.com/docs/cli/headless/
- Qwen Code web search: https://qwenlm.github.io/qwen-code-docs/en/developers/tools/web-search/
- OpenCode web search: https://opencode.ai/v2/docs/websearch/
- Claude CLI print mode: https://docs.anthropic.com/en/docs/claude-code/cli-usage

This document records architecture only. It does **not** mean any CLI agent has been installed, authenticated, scheduled or proven to save news to the VPS.
