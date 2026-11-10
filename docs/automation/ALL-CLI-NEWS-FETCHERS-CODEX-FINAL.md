# All AI CLIs independently fetch news; Codex also makes the final stock decision

Status: **DESIGN / IMPLEMENTATION HANDOFF — NOT DEPLOYED OR TESTED ON VPS**. Updated 2026-11-10 (Asia/Kolkata).

## Non-negotiable instruction

**EVERY configured, authenticated and web-capable CLI is a first-stage, independently searching news collector, including Codex CLI.** No CLI should merely summarize the Python collector. After all news is joined into a shared, verified, time-locked snapshot, a **separate Codex CLI invocation** is the **sole final stock-ranking/decision model**. Codex cannot substitute old article snippets for independent fresh searches.

This extends, not replaces, the existing news_collector engine, PostgreSQL/SQLite archive, NIFTY 500 mapping, source health, daily evidence snapshots and signal JSON schema. It neither arms broker execution nor places trades.

## Workflow

1. A reliable VPS scheduler invokes the deterministic Python collector and all *enabled* CLI collectors. Python continues every cycle even when AI quotas or auth fail.
2. Each CLI makes its OWN fresh external searches/fetches; uses distinct issuer groups, topics, publishers, official filings, and rotating gap queries; and returns verifiable original URLs plus retrieval evidence. Codex is in this collection pool.
3. The ingestion service validates external documents, checks exact company identity/ISIN where available, original disclosure time, corrections and source provenance; writes both accepted and unresolved records, errors and quotas to a dedicated news DB. No CLI writes directly into production trading tables.
4. A scheduled 09:00 IST freeze creates an immutable as-of snapshot, containing only news credibly available from the prior regular NSE session at 15:00 IST until **before 09:00 IST** on the current regular trading day. Late discovered or unverifiable timestamps are excluded, with gap reports.
5. Codex FINAL (a *new separate invocation*, not the collector's response) reads the unified frozen snapshot, coverage/quality report and full candidate evidence. It may independently search for a missed fact, but **newly discovered post-cutoff evidence never becomes retrospectively eligible**.
6. Codex ranks up to five LONG/bullish and five SHORT/bearish NIFTY 500 research candidates; a separate, independent critic reviews contradictory facts; Codex revises/rejects candidates and writes a schema-valid research-only decision. Zero candidates / NO_TRADE is valid.
7. Publish source-linked results and audit logs; optional future handoff to the existing signal receiver requires a separately reviewed, explicit approval. **Never touch broker endpoints or auto-order capabilities.**

## First-stage independent collectors

| Lane | Agent | Independent discovery responsibility | Activation condition |
| --- | --- | --- | --- |
| 00 | Python core | NSE/BSE allowed feeds, official filings, issuer IR, authorized publisher RSS/APIs; PDF extraction | Always |
| 01 | **Codex CLI — FETCH** | New official announcements, high-materiality gap checks, filings and media | Authenticated + verified live web/approved HTTP/MCP |
| 02 | Google Antigravity or supported Gemini CLI | Alternate live search, indexed financial media, regional publisher sources | Supported command, auth, true web retrieval |
| 03 | Claude Code | Deep contradictory reports, earnings releases, corporate governance | Eligible provider access and search tools |
| 04 | Qwen Code | Independent issuer/topic sweep and overlooked events | Verified web backend |
| 05 | OpenCode | Alternate-model search and missing-symbol search | Configured model AND web provider |
| 06 | Kimi Code | Chinese/international coverage where Indian equities are affected | Permitted live web tools |
| 07 | Mistral Vibe | Corporate release or macro/regulatory discovery | Supported web tool/config |
| 08 | AWS Kiro | Targeted issuer cross-checks | Headless CLI, web access and quota verified |
| 09 | GitHub Copilot CLI | Additional independent source discovery | Supported noninteractive mode and web tools |
| 10 | Grok Build CLI | Market/news discovery and source comparison | Valid subscription and search integration |
| 11 | Cursor CLI | Secondary issuer and source-gap scan | Supported noninteractive mode and web tools |
| 12 | Optional local models/Ollama | Classification of already retrieved articles only; not called an independent fetcher without an actual retrieval tool | Memory/performance tested |

**Eligibility matters more than the number of binaries installed.** If a CLI cannot autonomously retrieve *current source documents* in unattended mode, report SEARCH_UNAVAILABLE, AUTH_FAILED, QUOTA_EXHAUSTED or UNSUPPORTED rather than fabricating coverage. Enable any other compatible CLI through the same contract after validation. Open-source software is not equivalent to free model inference or permission to scrape publishers.

## Required independent search strategy

- Python stays broad and systematic: exchange filings/results/announcements, issuer sites, regulator sources, approved publisher feeds and search-index discovery.
- Assign EACH AI lane a different rotating batch of NIFTY 500 companies, earnings/orders/regulatory/brokerage categories and publisher sources every run. Avoid every lane asking the same generic headline question.
- Every CLI independently performs actual live search/retrieval; it can additionally compare its findings against existing event IDs to seek omissions. Do not send only a digest of Python news as its input.
- Prioritize primary NSE/BSE/issuer disclosures. Publisher stories and search snippets are leads until original publication time and claims are verified.
- Keep discovery for the whole NSE/BSE universe separately; only verified point-in-time NIFTY 500 constituents are eligible for the ranked top five.
- Respect robots, licenses, paywalls and access controls; never bypass a 401/403. Treat publisher restrictions as logged coverage gaps.

## Collector output contract (all lanes including Codex FETCH)

Each run has a unique run_id, agent_id, model/version, config_hash, started_at, finished_at, status, query log, retrieved source IDs, tools actually used, successes, failures, timeouts, and quota/cost if known.

Each candidate record has:
- event_id / original exchange filing identifier where available
- article_url and canonical_url; original publisher and source tier
- title and factual summary; company, symbol, exchange, ISIN if known
- event_type, numeric material_facts with period/unit, sentiment hypothesis
- **published_at**, **first_publicly_available_at**, **fetched_at**, **first_seen_by_our_system_at**, **verified_at**, and original timezone (different fields, nullable where unknown)
- source-time proof/extraction method, verifying evidence URLs, discovery tool, agents that found it
- verification_status: VERIFIED, SOURCE_TIME_ONLY, TIME_UNKNOWN, SOURCE_BLOCKED, CONFLICTED or NEEDS_REVIEW

A search-index timestamp is not the publisher time. An agent assertion alone is not timestamp verification. Never rewrite a prior observed first_seen time from a late rerun. Deduplicate by canonical URL + filing ID + event fingerprint, retain correction history and *all* sources and discoverers.

DB writes are idempotent/transactional. Advance source cursors only after commit + readback. If PostgreSQL is unavailable, store a durable local spool and retry without claiming success.

## Schedule and resource limits

- VPS: user-reported Ubuntu 2 vCPU / 8 GB RAM / ~180 GB free; measure actual before use.
- Python: continuous deterministic polling, target every 10 minutes when healthy.
- CLI collection: attempt each **enabled/eligible** lane on a rotating or quota-aware cadence; not all 11 CLIs concurrently on an 8 GB host. Initial max concurrent AI workers = 1 and browser workers = 1; enforce watchdog/timeout and deduplicated backlog. Every run records SKIPPED if not attempted.
- Final Codex: after 09:00 IST for each regular trading session with sufficient time to validate before trading. It reads only an immutable 09:00 evidence snapshot. Reserve its model quota so fetch cycles never consume its decision budget.
- Independent critic: optional second model/CLI but review must be from evidenced snapshots and no post-cutoff leakage.
- Schedule via VPS systemd/containers, not only a GUI thread schedule; test while workstation is offline. If subscriptions disallow unattended use, disable the lane and use permitted API/service or deterministic fetcher.

## Codex FINAL decision requirements

Codex FINAL receives: immutable session/as-of cutoff, all verified stock news and original URLs, material fact extraction, financial comparison periods, contrary news, macro context, source freshness/coverage warnings, actual historical learning metrics **from dates before the decision**, point-in-time NIFTY 500 list, and model/data versions.

For every candidate Codex must:
1. Validate symbol, timestamp and direct-source evidence; reject stale/undated or unresolved items.
2. Analyze earnings surprise versus expectations where reliable data exists, revenue/profit/EBITDA/margins, order size relative to company scale, guidance, regulatory events, block deals, market and sector context.
3. Consider conflicting news, anticipated/priced-in announcements, historic signal errors, liquidity, no guaranteed return, and whether an announcement could plausibly affect *open-to-close* movement.
4. Explain bullish/short rationale, confidence with uncertainty, source links, event IDs, and why close competitors were rejected.
5. Produce at most 5 LONG and 5 SHORT; reject weak signals. A critic should flag any missing evidence before finalizing.

Use the existing schema/stock-signals.schema.json as the **published research-output contract**. It requires execution_enabled=false. Keep richer decision audit metadata in separate internal records, not as extra schema fields. Status is READY, NO_TRADE or UNAVAILABLE. No attempt at direct live trade execution or broker interaction.

## Integration with existing repository

**Reuse:** news_collector/engine.py, news_collector/continuous_worker.py, news_collector/db_store.py, news_collector/sources.json, news_collector/matching.py, news_collector/enrich.py, news_collector/candidates.py, ops/news-stack/compose.yaml, schema/stock-signals.schema.json, docs/automation/codex-news-collector-10min.md, learning/feedback.py.

**Implement in order:**
1. New separate CLI-agent registry and safe subprocess runner with per-provider explicit executable/argv, no shell interpolation, restricted credentials, read-only code checkout, individual spool directories, output JSON-schema validation, and no broker environment variables.
2. SQL migrations for source_runs, agent_discoveries, raw_documents, event_sources, event versions and premarket snapshots, without destroying existing tables; tests for duplicate and contradictory agents.
3. A rotating planner for independent per-CLI source assignments and a model-agnostic search/retrieval adapter. Probe live search tools from actual CLI versions; do not assume CLI-name means live search.
4. Ingestion into the shared DB, commit/readback and source-gap reports; fail-closed cutoff and historical-as-of tests.
5. Distinct CLI job profiles: **codex-fetch** and **codex-final** with different prompts, permissions, quotas, inputs and logs. Collector Codex must not be allowed to make/broadcast final decisions.
6. Final Codex ranker validates research schema, records rejected candidates and critic review, and outputs a research JSON file only. Do not modify existing signal delivery or Kotak credentials.
7. Container/VPS systemd unit & scheduler, health dashboard metrics, source coverage alarms, replay tests and quota tests. Enable individual CLI lanes only after proving live discovery, durable storage and no brokerage capability.

**Acceptance test:** With two enabled independent CLI lanes plus Python, identify a real fresh NSE/BSE source in each CLI's tool logs; ingest deduplicated event retaining all discoverers and source URLs; prove source/time provenance; freeze cutoff with no lookahead; execute a separate Codex FINAL run on the snapshot; produce schema-valid up-to-5/up-to-5 research JSON; verify missing auth/quota/browser/DB fail independently; demonstrate broker order count exactly zero. Do not describe system as deployed until VPS logs, actual database rows and scheduler evidence confirm it.

## Links

- Existing repository: https://github.com/danny8806/Indian-Market-Intelligence-AI
- Existing multi-agent plan: docs/automation/multi-agent-news-pipeline.md
- Existing Codex fetch instructions: docs/automation/codex-news-collector-10min.md
- Existing deployment: ops/news-stack/README.md
- Source schema: schema/stock-signals.schema.json

**This document is an implementation spec, not proof that any AI CLI has been installed, authenticated or continuously collecting news.**