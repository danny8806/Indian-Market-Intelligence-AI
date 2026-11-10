# Codex thread automation — NSE/BSE news collector (every 10 minutes)

## Setup in Codex
Open this repository in the supported Codex/ChatGPT desktop app and create a **thread scheduled task / thread automation**. Request **every 10 minutes**, timezone **Asia/Kolkata**, continuously including holidays and weekends. Verify the Saved/Scheduled view actually confirms 10-minute intervals; do not silently fall back to hourly. Run once manually, inspect logs and database inserts, then enable unattended runs. On a local project, keep the application, network and computer running; if cloud execution is offered, configure and verify its network/secret access separately.

## Critical requirement: Codex must independently FETCH news

Codex is a **second primary source-discovery collector**, **not** merely an analyzer of the Python feed. On *every* eligible run it must carry out its own external search/retrieval, alongside the deterministic Python collectors:

- **Python lane:** poll permitted NSE/BSE feeds, exchange filings, issuer sites, legal RSS/APIs and financial media; persist raw responses and metadata.
- **Codex lane (independent):** use a **configured, tested live web-search/browser/MCP capability** or execute approved Python HTTP tools itself. Search official corporate announcements and financial news for missing material events, cross-source verification and ticker resolution. Use a source inventory and rotating search batches to avoid checking only the same publishers every run. Do not rely solely on Python's results or previous summaries.
- **Merge:** tag each discovery with `discovered_by=python` or `discovered_by=codex` and actual retrieval method. Submit both lanes through the same validation, provenance, idempotent upsert, corrections and source-ledger pipeline. Preserve multiple sources per event. Never claim DB persistence unless confirmed by read-back.
- **No search access = failed Codex retrieval:** if Codex lacks permitted external network or an enabled live web search/MCP tool, report `CODEX_FETCH_UNAVAILABLE`, with the exact missing capability. Do not pretend it searched the web or rephrase old cached content as current news.
- **Boundaries:** use read-only, least-privilege source access; obey robots/ToS and website rate limits; never bypass login/paywall/403 restrictions. Codex has no access to broker order tools, arm endpoints or broker secrets. No trading is permitted.
- **Timing:** the scheduler runs every 10 minutes, but skip/record overlapping agents; preserve unsuccessful-fetch windows for later catch-up; store verified publication time separately from discovery time.

### Codex operator prompt addition
> You are responsible for **directly fetching fresh NSE/BSE stock-related news yourself on this iteration**. Independently query the permitted live search and source-retrieval tools available in your Codex environment, open relevant primary sources, verify each report's first-publication time, source URL and ticker, and commit the verified results through the repository's news ingestion pipeline. Do not restrict yourself to summarizing articles fetched by Python. Search for news the Python fetchers could have missed and report exactly which sources/tools were accessed, what was found, and what was durably stored. If web access is unavailable, return CODEX_FETCH_UNAVAILABLE and the missing capability instead of claiming success. Never place orders.

### Prerequisite verification (on the actual VPS/Codex executor)
1. Confirm `codex login status` succeeds for the service account, and verify CLI version/actual flags using `codex exec --help`.
2. Confirm Codex can access the live web using an explicitly enabled, authorized retrieval tool; do **not** infer this from the existence of the Codex CLI. In an Agents API implementation, web_search is only enabled when explicitly configured; a CLI session requires its own verified tools/network setup.
3. Run one supervised fetch using a fresh official announcement, compare source contents/timestamps, and confirm a row was committed with `discovered_by=codex`.
4. Confirm Python and Codex report independent discoveries, duplicates merge correctly, and failures do not stop the other lane.
5. Only then enable the 10-minute scheduler. A GitHub commit alone does **not** activate the agent or demonstrate live source/database access.

## Automation prompt (paste into the Codex thread)

Act as an incremental Indian equity-news ingestion operator for this repository. On EACH scheduled invocation:

1. Inspect the repository's existing news fetchers, parsing rules, stock-symbol mapping, database schema, tests, and deployment configuration. Reuse and improve them rather than creating conflicting pipelines. Limit this task to **news collection and data quality**. Never generate broker orders, arm trading, modify risk rules, or deploy a trading system.
2. **Independently fetch fresh news yourself via enabled live search/browser/MCP or approved HTTP tooling, in parallel with Python fetchers. Do not merely analyze articles Python has already fetched.** Collect only newly published or updated NSE/BSE listed-company news since the last persisted successful source cursor, with a 30-minute overlap to catch delayed feeds. Prioritize official NSE and BSE corporate announcements/filings, issuer investor-relations releases, official regulatory sources, then reliable Indian financial press and legal RSS/API feeds (e.g. Reuters, Moneycontrol, ET Markets, Business Standard, Mint, CNBC-TV18, NDTV Profit) when access is permitted. Use other verified feeds when relevant. Do not assume every publisher supports anonymous scraping. Respect robots rules, provider terms, credentials, rate limits and 401/403 responses. Never evade paywalls or access controls.
3. Focus on current official NIFTY 500 constituents but retain other NSE/BSE issuers in a separately tagged universe. Verify the precise ticker / exchange / company identity. When multiple tickers are possible mark them unresolved and do not guess.
4. For each unique report store: source name, canonical source URL, source article/filing ID if available, title, neutral factual summary, listed ticker(s), company name, exchange, event category, first_published_at UTC, first_published_at IST, updated_at if known, fetched_at UTC, original publication timezone, material event date, source credibility tier, document reference, language, sentiment (bullish/bearish/mixed/neutral/unclear), numerical facts with units, and ingestion status. Use null for unverifiable timestamps and never fabricate publication times. Record how each time was verified, because 15:00-to-09:00 IST premarket eligibility depends on it.
5. Deduplicate across sources by canonical URL, source identifiers, and event fingerprint (ticker + event type + event date + normalized facts), while preserving source provenance and corrections. Make database writes idempotent using unique constraints/upserts and a persistent per-source high-water mark. Never mistake fetched_at for published_at.
6. Persist raw source metadata/links and the normalized records in the *configured existing* database on the user's VPS, but only after confirming the connection via approved secret storage and a read/write smoke test. Do NOT expose secrets in GitHub, logs, responses or commits. If the VPS database is not reachable or permissioned, produce a locally durable append-only JSONL/SQLite spool for later retry; do not falsely report database insertion. Never overwrite existing market data.
7. Log every source attempted, successes, 429/rate-limit, 401/403/404, network timeouts, parse errors, records discovered, duplicates, records actually committed, cursor advancement, duration, and unhandled exceptions. Advance each source's cursor only after successful durable commit. Retry transient errors with bounded exponential backoff, without hammering publishers.
8. Report a concise status: run started/finished (IST); number of sources attempted/succeeded/failed; new filings/articles; inserts/updates/duplicates; storage destination and confirmation; lag to latest verified report; and exceptions. Provide top material announcements with symbol, classification, publication time IST, and source URL. Avoid repeating old news in each report except for corrections.
9. Prefer incremental runs that can complete within the next interval; avoid overlapping writes with locks and transactions. If a preceding run is active, skip duplicate ingestion and record the reason. Implement checks/tests before relying on changes, and do not publish fabricated data.

**Research cutoff:** For a trading-day premarket report, compute the eligible window from the previous NSE trading session 15:00 IST through the present day's 09:00 IST; never include later-published news in a premarket backtest or recommendation. This automation itself runs throughout the day and retains all news, not just that window.

**Hard requirement:** This automation is data ingestion only and cannot assert that all websites were checked or that data was saved on a VPS without actual successful checks, confirmed database writes, and visible logs.

## Frequency and verification
- Requested: every 10 minutes (six invocations per hour).
- Verify actual task scheduling and execution in Codex's Scheduled/Automations interface.
- A file in GitHub does NOT create or activate a Codex scheduled task.
- ChatGPT's automation action available in this chat does not configure a Codex-specific 10-minute thread automation.
- No OpenAI API key is required for a Codex session signed in using an eligible ChatGPT account; other news services or database connections may require their own credentials.
