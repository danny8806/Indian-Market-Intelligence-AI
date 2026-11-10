# START HERE — Handoff for another AI / Codex agent: NIFTY 500 news collector

**Date:** 2026-11-10, Asia/Kolkata. **Planned working session:** morning of 2026-11-11. **Status:** PLANNED / NOT DEPLOYED. Saving this document is **not** permission to enable real-money orders.

## 1. Project and direct links

- **Source-access resilience and new OSS research agents:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/OPEN-SOURCE-AGENTS-SOURCE-ACCESS-RESILIENCE.md
- **Expanded open-source tools and agents catalog:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/EXTENDED-OPEN-SOURCE-NEWS-FETCHING-TOOLS-CATALOG.md
- **Main repository (source code):** https://github.com/danny8806/Indian-Market-Intelligence-AI
- **All news sources, free web tools, browser/MCP services and AI CLI roles:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/COMPLETE-SOURCES-TOOLS-MODELS-AI-OPERATING-PLAN.md
- **Main README:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/README.md
- **Complete tool inventory + free/limited-free notes + morning steps:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/FREE-TOOLS-NEWS-COLLECTOR-MORNING-PLAN.md
- **Multi-agent pipeline design:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/multi-agent-news-pipeline.md
- **Codex must itself fetch live news (10-minute instructions):** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/codex-news-collector-10min.md
- **Existing VPS deployment precautions:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/ops/README.md
- **Existing live-only service overview:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/live_desk/README.md
- **Live FastAPI dashboard/receiver source:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/live_desk/app.py
- **Bridge receiver source:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/bridge/app.py
- **Existing signal format schema:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/schema/stock-signals.schema.json
- **Signal delivery contract / ChatGPT task prompt:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/bridge/CHATGPT_TASK_PROMPT.md
- **Existing live Compose configuration:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/live_desk/compose.yaml
- **Current project plan / known blockers:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/plan/00-current-live-plan.md

Read the documents **before writing or deploying code**. The project includes an existing trading-monitoring environment; do not break or replace it.

## 2. Objective

Implement, test and subsequently deploy an **isolated news-only ingestion service** on the user's Ubuntu VPS that runs **every 10 minutes, 24/7**, prioritizing official NSE/BSE filings and NIFTY 500 constituents. Python and authenticated **Codex CLI must both independently fetch current news**. An optional Gemini CLI and other agents independently seek missed sources. The end result is an indexed news database with verifiable publication times, issuer/ticker mapping, sources, corrections, confidence and ingestion audit. A separate **final research model** can later select top 5 bullish and 5 bearish NIFTY 500 stocks using the last completed NSE trading session's 15:00 IST through current trading day 09:00 IST window. No live trades.

Target VPS reported by user: Ubuntu, **2 vCPU / 8 GB RAM / approximately 180 GB free disk**. Re-measure with `free -h`, `df -h /`, `nproc`, `docker stats --no-stream`; do not assume free RAM equals installed RAM. Limit browser concurrency to one and start with one AI CLI worker. Codex uses remote models but **consumes subscription quota**, so use bounded, quota-aware calls. No premium high-usage reasoning mode for routine 10-minute collection.

## 3. Sources and tools to use

**Tier 1, official:** NSE RSS/direct authorized feeds and company filings, BSE corporate announcements, issuer investor-relations pages, regulatory announcements and results PDFs. Preserve source dissemination/publication timestamps.

**Tier 2, news sites:** Economic Times Markets, Moneycontrol, Business Standard, Mint, NDTV Profit, CNBC-TV18, Reuters and other trustworthy financial publishers through permitted websites, RSS or paid API where authorized.

**Tier 3, discovery:** GDELT, self-hosted SearXNG, a configured Codex live-search tool, Gemini search tools, allowed MCP/browser search providers, and (optionally) Firecrawl/Tavily/Apify/Browserbase when their allowances and terms are checked.

**Free/open-source processing stack:** Python `httpx`, `feedparser`, `beautifulsoup4`, `trafilatura`, `Scrapy`, `Playwright`, `Crawl4AI`, `PyMuPDF`, `Docling`, `MarkItDown`, `pydantic`, `SQLAlchemy`, PostgreSQL/SQLite, `systemd`, optional Playwright MCP and Fetch MCP.

**AI CLI tools:** Codex CLI (ChatGPT sign-in), Gemini CLI (requires own auth), optional OpenCode/Qwen/Claude/Copilot CLI based on verified usage, model and live-search availability. Neither free CLI software nor a ChatGPT subscription guarantees free unlimited model calls. Self-hosted AI browser libraries may need a paid inference provider. Avoid multiple large local Ollama models on 8 GB RAM.

**Publisher policy:** Respect publisher rate limits, robots and terms. HTTP 401/403/paywalls are recorded as unavailable; **never bypass access restrictions**. Verify each source's actual accessibility, published date and URL; do not claim exhaustive coverage.

## 4. Minimum architecture

```text
Ubuntu systemd 10-minute timer
    |
    +-- Python RSS/API/filing fetcher (always)
    +-- Codex CLI live web discovery (independent, authenticated, quota-aware)
    +-- Optional Gemini and other CLI agents (independent search, budget caps)
    +-- Optional browser worker + document parser (limited concurrency)
    v
durable raw-documents and agent-discovery staging
    v
time provenance + NIFTY 500 ticker matching + dedupe + correction history
    v
separate persistent NEWS DB and per-source cursors, backed up
    v
frozen 09:00 IST research snapshot
    v
final ranking agent + independent critic
    v
existing schema v1.0 research JSON (up to 5 LONG / 5 SHORT)
    |
    +-- optional future authenticated delivery to existing signal receiver
    |   (only after approved separate smoke test)
    +-- NEVER to broker order endpoints
```

Data records need: verified company, NSE/BSE symbol, event category, headline, numbers, primary URLs, source name, original publication/dissemination timestamp with timezone and verification method, first public availability timestamp, fetch timestamp, updates/corrections, sentiment (including mixed/unclear), confidence, discovery agent/tool, HTTP/retrieval status and an idempotency key. Unknown publication times must stay **null/unverified**, never silently changed to `fetched_at`. Preserve original events and all sources when deduplicating.

Use source-run ledgers, unique constraints, transactional UPSERT and source cursors; don't advance a cursor when a write fails. If primary DB is down, stage to durable local SQLite/JSONL and replay after recovery. On historical tests freeze point-in-time index membership and prevent news and price leakage.

## 5. Implementation sequence — morning work order

**Phase 0 — inspect and protect existing project**

1. Clone/open the repo on an authorized development environment and review all docs above plus existing tests and deployment configuration.
2. Check system resources, existing dashboard/container health, Git branch and status; inventory existing news fetchers, storage connections and tasks. Avoid duplicate implementations.
3. Confirm private SSH access and trusted server host key. Do not echo secrets or publish credentials. Historical publicly exposed SSH password must be rotated through the VPS provider console.
4. Keep all broker credentials out of the collector, separate service user/network/DB rights, and `LIVE_ORDERS_ALLOWED=NO`. No trading configuration, model execution logic or orders should change.

**Phase 1 — reliable Python source ingestion first**

1. Create an isolated `news_collector/` Python package, requirements file, tests and documentation. Do not modify `live_desk` order code.
2. Implement official NSE/BSE and issuer feeds as permitted, with per-source access and timestamp verification. Add minimal authorized RSS/financial-media sources.
3. Add source-status ledger, structured raw documents, normalized events, ticker resolver, idempotent dedupe and correction/version tracking.
4. Use a temporary/test SQLite DB initially if PostgreSQL setup is not confirmed, then migrate to an isolated PostgreSQL schema; test full write/readback and restart recovery.
5. Run manually twice to confirm second run adds no duplicates; report actual network failures and measured data freshness.

**Phase 2 — Codex MUST fetch, not only analyze**

1. Install/verify Codex CLI in a separate non-root service account; authenticate once via approved ChatGPT device login. Check `codex --version`, `codex login status`, `codex exec --help`, `codex mcp list`. Never commit OAuth tokens/cookies.
2. Explicitly configure/test a live retrieval route (Codex web search, permitted HTTP fetcher, browser or MCP). Confirm a fresh official company filing was actually retrieved by Codex and its source URL/time checked.
3. Run Codex in noninteractive mode with a **strict JSON schema** for retrieved news, max runtime, and searchable source batches. Store `discovered_by=codex` plus true tool evidence. If no live search: return `CODEX_FETCH_UNAVAILABLE`, never hallucinate sources.
4. Add Gemini CLI as an independent discoverer only after its own headless login, tool and quota smoke test. Evaluate extra **unique verified events** discovered beyond Python/Codex. Add optional agents one at a time only if they improve coverage.

**Phase 3 — supplemental web, browser and PDF tools**

1. Add targeted Playwright/Crawl4AI on approved JS sites; use at most one browser worker due to 2-vCPU/8-GB VPS.
2. Add GDELT/SearXNG as discovery feeds, with original-publisher verification for every candidate. Use Scrapy/Trafilatura for scalable extraction.
3. Parse official PDFs with PyMuPDF; add Docling only for genuinely difficult tables and CPU-capacity permitting.
4. Keep optional Firecrawl/Tavily/Apify/Browserbase disabled until quotas, value and terms are checked.

**Phase 4 — scheduler and monitoring**

1. Add `systemd` service/timer for **every 10 minutes** and use a single-flight lock. Avoid overlapping runs; don't start until supervised end-to-end tests pass.
2. Enforce per-source rate limits, timeout/bounded retries, backoff and durable catch-up cursors. Continue Python collection when AI quotas are exceeded.
3. Log each source checked, success/blocked/errors, latency, dedup rate, actual DB insert/update counts, model usage and last publication time.
4. Test two actual timer activations and persistent database rows after a restart. No assumption that merely saving workflow files means collection is running.
5. Verify backup and alerting for failed runs. Keep server resource headroom for the existing live dashboard.

**Phase 5 — final research decisions (separate process)**

1. On an NSE trading day, freeze the **15:00 previous trading session to 09:00 current trading day IST** as-of source snapshot (holiday/weekend aware). Exclude unverified first-publication times and post-cutoff news.
2. Run one capable analysis model plus independent critic: rank no more than 5 LONG and 5 SHORT NIFTY 500 candidates; incorporate materiality, surprise, financial impact and conflicting evidence. Fewer/zero are acceptable.
3. Validate the exact existing `schema/stock-signals.schema.json`. Maintain `execution_enabled=false`. Store non-selected and counterevidence to audit missed news.
4. Only after explicit approval, validate an authenticated *research report* delivery to existing `POST /api/v1/signals/incoming` with idempotency and received acknowledgment. This is **not** trading authorization and must never enable order placement.
5. After market close, compare the direction of each selection against actual open-to-close movement, audit false positives/missed events and improve source coverage (no lookahead).

## 6. Definition of done

**Never report 'deployed' or 'working' without these:** verified source URLs and timestamps; actual Python and Codex independent live retrieval; source failure handling; successful idempotent DB write/read-back; service restart recovery; two 10-minute timer activations; a separate frozen 09:00 snapshot; valid top-5 research JSON or `NO_TRADE`; real measured CPU/RAM, quotas and source error counts; dashboard unchanged and trading disabled. Explicitly document blockers rather than claiming complete source coverage.

## 7. Copy-paste agent instruction

> You are the implementing engineering agent for https://github.com/danny8806/Indian-Market-Intelligence-AI. Read this handoff and every linked project plan, then inspect all relevant code before editing. Implement the isolated NIFTY 500 24/7 news collection project in phases. Python and Codex CLI must independently fetch live permitted news. Prefer free self-hosted tools; only use optional providers after confirming allowance and authentication. Verify published-at times, ticker identity, per-source provenance, idempotent news DB, 10-minute systemd timer, optional Gemini and browser/MCP collection, and a separately time-locked 09:00 IST research decision stage. Do not assume code is installed or deployed simply because a GitHub commit exists. Avoid changing the existing Kotak/Dhan trading service and keep live orders disabled. Run tests, provide exact commits, verified timer/service logs, source coverage statistics, database insert/readback evidence, resource usage, and clearly disclose anything incomplete or blocked. Never send orders.

## 8. Useful commands (read-only audit, not an automatic deployment script)

```bash
git clone https://github.com/danny8806/Indian-Market-Intelligence-AI.git
cd Indian-Market-Intelligence-AI
git status --short
free -h
df -h /
nproc
docker stats --no-stream
python3 --version
codex --version || true
codex login status || true
codex exec --help || true
```

**Important:** This document was created and verified in GitHub. It is an implementation handoff; it does not imply that SSH access, CLI agent authentication, external source access, VPS database write, or scheduling has actually occurred.
