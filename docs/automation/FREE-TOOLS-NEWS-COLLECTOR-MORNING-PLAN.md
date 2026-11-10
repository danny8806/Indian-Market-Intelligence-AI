# NIFTY 500 news collector — free tools inventory and morning implementation plan

**Prepared:** 2026-11-10 (Asia/Kolkata). **Target start:** next morning, 2026-11-11, when the operator begins setup. **Status:** DOCUMENTATION ONLY — nothing in this file installs software, activates a schedule, connects the VPS, or writes news records. Never infer deployment from a GitHub commit.

Actual tool probes, rejected options and untested catalog entries are recorded in
[`TOOL-TEST-LOG.md`](TOOL-TEST-LOG.md). That log distinguishes production
dependencies from disposable tests.

## Goal and constraints

Build a reliable **24/7, every-10-minute** news discovery system for current NSE NIFTY 500 constituents first, with separately tagged news for other NSE/BSE companies. Verify *first public availability* timestamps, company/ticker identity, source links, numbers and contradicting evidence, then persist source metadata and structured events. After the **09:00 IST** cutoff on each NSE trading day, an independent research decision/reviewer stage can produce up to **5 bullish and 5 bearish** symbols with weaker candidates rejected. Use the last NSE trading session's **15:00 IST through today's 09:00 IST** as-of window. **Research only: no broker orders, no trade arming, no model-to-broker direct access.**

Initial host **reported by operator**: Ubuntu VPS, **2 vCPU, 8 GB RAM, ~180 GB free disk** (reconfirm actual `df -h` before installing). Existing Kotak live-only dashboard must remain isolated, secure and disarmed.

### System design

```text
systemd 10-minute timer (Ubuntu VPS)
    |
    +---- Python primary: NSE/BSE RSS & authorized feeds / issuer IR / publisher APIs
    +---- Codex CLI independent live search + approved HTTP/MCP tools (quota-aware)
    +---- Gemini/other authenticated CLI independent search (quota-aware, optional)
    +---- Crawl4AI / Scrapy / Playwright / browser-agent (targeted permitted pages)
    +---- GDELT / SearXNG / third-party search (extra discovery, not fact authority)
    +---- PyMuPDF / Docling (filing PDF and table extraction)
    |
    v
staging + source ledger -> timestamp checks -> ticker mapping -> dedup / corrections
    |
    v
dedicated news PostgreSQL (or SQLite spool until DB is confirmed)
    |
    +---- run metrics, missed-source auditing, daily immutable 09:00 news snapshot
    |
    v
final research decision agent + independent critic
    |
    v
schema v1.0 top-5 LONG / top-5 SHORT watchlist (not executable orders)
```

**Do not instantiate every heavy worker at once.** On 2 vCPU / 8 GB, start with one headless browser and one AI CLI worker at a time, then measure memory/CPU. Use Python async HTTP for frequent retrieval; use AI searches selectively and monitor subscription quotas.

## A. Inventory — free, open-source / public data

These have **no mandatory software subscription** when locally self-hosted. **Free software does not mean free access to third-party content**, no provider rate limits, or no VPS computing cost. Some AI browser frameworks require a **separate model inference provider**.

| Tool / method | Category | Priority | Cost and conditions | Job |
|---|---|---|---|---|
| Python `httpx` / `requests` | HTTP | P0 | Open-source/free | Async polls of permitted APIs, RSS and pages |
| `feedparser` | RSS/Atom | P0 | Open-source/free | Read syndication feeds, source IDs/times |
| NSE official RSS feeds | Publisher source | P0 | Publicly available; usage rules still apply | Corporate announcements, results, meetings, actions, insider trading |
| BSE official announcements / feeds | Publisher source | P0 | Verify available authorized endpoints and terms | Primary filings and timestamps |
| `BeautifulSoup` | HTML parser | P0 | Open-source/free | Parse known page fields |
| `Trafilatura` | Article extraction | P0 | Open-source/free | Main story text + metadata |
| `Scrapy` | Crawler | P1 | Open-source/free | Structured crawling across approved sites |
| `Playwright` | Browser | P1 | Open-source/free; uses more RAM/CPU | JS-rendered publisher or issuer sites |
| `Playwright MCP` | Browser MCP | P1 | Open-source/free; same browser costs | Browser navigation for a CLI agent |
| `Crawl4AI` | AI-ready crawling | P1 | Open-source/self-hosted | HTML-to-Markdown, targeted site crawl |
| `SearXNG` | Metasearch | P1 | Open-source/self-hosted; upstream engine may block/throttle | Alternative discovery; verify each original page |
| `GDELT` | News index | P1 | Public data, fair use / rate limits | Discover global articles and indexed stories |
| `PyMuPDF` | PDF extraction | P1 | Open-source; check license for deployment | Text, page coordinates and PDF metadata |
| `Docling` | Document/PDF conversion | P2 | Open-source; CPU/RAM cost | Tables and structured filing documents |
| `MarkItDown` | Document conversion | P2 | Open-source; check supported formats | Normalize downloadable documents |
| `Browser Use` | Agentic browser | P2 | Open-source software, LLM calls may cost | Complex authorized browser journeys |
| `Stagehand` | Agentic browser | P2 | Open-source library, model calls may cost | LLM-assisted browser extraction |
| Fetch MCP / approved HTTP MCP server | Tool interface | P1 | Often self-hosted/free | Fetch public web pages for Codex |
| `systemd` timers / Python scheduler | VPS automation | P0 | Included/free | 10-minute execution, retries, watchdog logs |
| `n8n` self-hosted community edition | Workflow orchestration | P2 | Free under applicable license, hosting cost | Optional visual workflows |
| PostgreSQL / SQLite, SQLAlchemy | Storage | P0 | Open-source/free | Durable news, source provenance, idempotent inserts |

**Priority definitions:** P0 = begin tomorrow; P1 = second phase after a working end-to-end test; P2 = install only if meaningful incremental value. For all sources, verify legal permissions, robots guidance, documented APIs and site usage policies; do not bypass paywalls, CAPTCHAs or 401/403 blocks.

## B. Free tier / usage-capped cloud services (optional)

These are **not unlimited free tools**. Plans, rates and included credits change; verify provider pricing on the day of activation. Never rely on free cloud quotas to guarantee 144 full-search cycles per day.

| Service / MCP | Free status / limitation | Role | Current provider info |
|---|---|---|---|
| Firecrawl + Firecrawl MCP | Free starter credits or limited calls where offered; pricing changes | Hosted search, scraping, extraction, change monitoring | https://www.firecrawl.dev/pricing |
| Tavily + Tavily MCP | Free plan currently advertises **1,000 API credits/month**, subject to change | AI web search/extract | https://www.tavily.com/pricing |
| Apify / Apify MCP | Free plan currently advertises **$5 platform allowance**; usage varies | Cloud Actors and specialized crawlers | https://apify.com/pricing |
| Browserbase / Browserbase MCP | Free plan currently advertises **1 browser hour** and capped requests | Offloaded cloud browser | https://www.browserbase.com/pricing |
| TinyFish ChatGPT integration | Requires user connection; eligibility/pricing to verify | ChatGPT-connected cloud browser/search | Check integration/account terms |
| Firecrawl ChatGPT integration | Requires user connection; separate from VPS MCP install | ChatGPT-side search/extraction | Check integration/account terms |
| Exa or other AI search APIs | Provider key / account / free allowances vary | Backup indexed discovery | Verify official pricing before adding |

**Caution:** A connected ChatGPT integration does **not** automatically add an MCP server to Codex or install a tool on Ubuntu. Treat those as independent configurations, each requiring confirmed access.

## C. AI CLI agents (use selectively, do not assume unlimited access)

| Agent | Access path | Proposed job | Gate before automation |
|---|---|---|---|
| **Codex CLI** | ChatGPT account login supported; usage varies by plan | Independently find official announcements and missed news; verify live source URLs | `codex login status`; `codex exec --help`; one real network retrieval and structured output |
| **Gemini CLI** | Google account / provider auth; available quota may vary | Independent Google-backed search and publisher discovery | Confirm current authentication, search tools and CLI terms |
| **OpenCode** | Open-source CLI; model/search backend can be paid or capped | Alternative discovery, corroboration | Prove actual live tool + subscription allowance |
| **Qwen Code** | Open-source CLI; model/search access depends on provider | Additional source checks | Confirm available authenticated web-search tool |
| **Claude Code** | Requires authorized account / provider access and plan | Secondary fact review | Verify headless availability, rate caps and web access |
| **GitHub Copilot CLI / other agents** | Plan-specific included allowance | Optional independent investigation | Confirm quota and genuine external search |
| **Ollama local models** | No per-call model fee, but local compute | Cheap categorization after collection | Do **not** start large local models on this host initially; measure capacity |

**Model routing:** deterministic Python every cycle; Codex as *independent web discoverer*, not merely a summarizer; Gemini optional independent discoverer; final strong-model decision once each trading morning; independent critic checks conflicting information. Monitor model usage; skip or fall back when quota exhausts. Reserve expensive premium reasoning modes rather than calling them 144 times per day.

### Key accuracy rule

A search-result snippet is only a *lead*. Preserve original publisher URL and verified published/dissemination timestamp where available. Store `first_available_at`, `fetched_at`, `verified_at` separately; never infer first-publication time from retrieval time. Classify reports as `verified`, `time_unknown`, `source_blocked`, `needs_review`, etc. A run must state precisely what it could and could not fetch.

## D. Financial/news source plan

**Primary:** NSE corporate announcements RSS, results, board meetings, official filing documents; BSE announcements/filings; SEBI/regulatory releases; issuer investor-relations releases.

**Secondary:** Moneycontrol, Economic Times Markets, Mint, Business Standard, CNBC-TV18, NDTV Profit, Reuters, company pressrooms and other trustworthy financial outlets — only official RSS, search snippets and approved/API-accessible webpages when permitted.

**Coverage enrichment:** GDELT and SearXNG/approved web-search providers; compare with primary disclosure. Maintain a per-source coverage dashboard: last success, first-publication latency, new unique events, HTTP failures, blocked access, missing symbols, retries, and cost.

**Do not claim that every site was successfully scraped.** If HTTP 401/403 occurs, log it and switch to authorized feeds/alternate original sources; do not attempt to bypass controls.

## E. Tomorrow-morning implementation checklist (2026-11-11 IST)

**Phase 0 — VPS safety/resource audit (first, read-only):**

```bash
date -Is
free -h
df -h /
nproc
docker stats --no-stream
python3 --version
which codex || true
```

Confirm host fingerprint/SSH access through trusted channels; rotate any historically exposed VPS password. Keep broker keys and trading apps separate; **do not change `LIVE_ORDERS_ALLOWED=NO`**, bind addresses, Nginx routes or old dashboard processes.

**Phase 1 — Minimum viable Python fetching and storage:**

1. Inspect existing repo modules, tests and deployment scripts; avoid duplicating collectors or breaking the live desk.
2. Create a dedicated `news_collector/` package + `requirements-news.txt` + test fixtures. Use a **new isolated service account and isolated database**, not the broker process environment.
3. Start with `httpx`, `feedparser`, `bs4`, `trafilatura`, `pydantic`, `SQLAlchemy` and PostgreSQL (or durable SQLite spool for initial test).
4. Verify accessible official NSE RSS, BSE/issuer sources; record fresh examples with original timestamps, source URL, ticker match and document link. Note source failures without bypass.
5. Build `raw_documents`, `news_events`, `event_sources`, `source_runs`, `agent_discoveries`, `source_cursors`, and `decisions` tables with uniqueness and correction history; stage unverified data separately.
6. Run a manual collector twice against a safe test DB and prove idempotent inserts and read-back.

**Phase 2 — Codex (and other agents) really FETCH news:**

1. Verify Codex installation and headless account login from the actual service account using `codex --version`, `codex login status`, `codex exec --help`, and `codex mcp list`. Never paste/share the auth cache.
2. Configure only permitted retrieval tools (e.g. Playwright MCP, Fetch MCP or a confirmed live search provider); test with a real company/filing and save provenance `discovered_by=codex`.
3. Add a strict JSON result schema, one-source-per-citation fields and timeout limits. **No web tool** must produce `CODEX_FETCH_UNAVAILABLE`, not fictional news.
4. Verify Gemini CLI separately with its own live searches. Benchmark *unique additional verified events*, not article count or model self-confidence.
5. Add Crawl4AI and targeted one-browser Playwright use only where authorized, and only after CPU/RAM baseline is measured. Add SearXNG/GDELT next for missed-story discovery.
6. Do not add optional paid MCPs until a source coverage gap justifies their account quota.

**Phase 3 — Scheduling and resilience:**

1. Add `systemd` service + **10-minute timer** `OnCalendar=*:0/10` or equivalent validated expression; enable only after successful end-to-end manual run.
2. Lock the pipeline so runs cannot overlap. Use bounded timeouts, source-level cursors with a 30-minute overlap, queued catch-up, 429 handling, rollback on failed writes, and no ingestion gaps.
3. Expose local health / run metrics without exposing secrets or publishing unrestricted database ports. Log fetched/inserted/duplicate/failed counts and data lag.
4. Test a complete cycle with no browser/login session on your PC. Verify actual VPS rows, timer history, log output, RAM load and recovery after failed source / DB outage.

**Phase 4 — Final model decision and research-only handoff:**

1. At the NSE trading day's **09:00 IST** cutoff, freeze a point-in-time snapshot. Do not include after-cutoff sources unless evidence establishes earlier public availability. Do not use current NIFTY 500 membership for historical membership tests.
2. Rank up to 5 LONG and 5 SHORT candidates, with an independent critic and factual supporting/rejecting evidence. Uncertain candidates must be excluded.
3. Validate against the existing `schema/stock-signals.schema.json` and record `NO_TRADE` / `UNAVAILABLE` on insufficient evidence.
4. Direct `/api/v1/signals/incoming` delivery is a **separate authorized integration** needing confirmed authentication, idempotency, arrival deadline and an actual receiver response. Keep live orders disabled.
5. After the session, record open-to-close direction, source news lag and missed-news audits for continuous quality improvement; do not misstate backtest/prediction accuracy.

## F. Minimal acceptance tests

- [ ] VPS host/login verified and free RAM/disk measured
- [ ] Existing dashboard remains healthy and trading-disabled
- [ ] At least one real NSE/issuer filing retrieved with correct URL and publication evidence
- [ ] Python lane: verified source, durable DB row, second-run dedupe
- [ ] Codex lane: **independent live URL retrieval**, working search tool and DB provenance
- [ ] Gemini or other CLI (if enabled): independent live retrieval and usage quota measured
- [ ] At least one source failure handled without stopping collection
- [ ] 10-minute systemd schedule actually fires twice, with no overlapping writes
- [ ] Database survives restart; uncommitted rows/cursors recover safely
- [ ] 09:00 cutoff excludes future news and ambiguous timestamps
- [ ] No production broker write paths or credentials accessible to news agents
- [ ] End-to-end summary reports **attempted sources, successful sources, blocked sources, inserted events and failed writes** accurately

## G. References and companion repo plans

- Existing system design: [multi-agent-news-pipeline.md](multi-agent-news-pipeline.md)
- Codex fetcher requirement: [codex-news-collector-10min.md](codex-news-collector-10min.md)
- Existing live desk architecture: [../../live_desk/README.md](../../live_desk/README.md)
- Existing VPS deployment policy: [../../ops/README.md](../../ops/README.md)
- Daily stock-watchlist contract: [../../bridge/CHATGPT_TASK_PROMPT.md](../../bridge/CHATGPT_TASK_PROMPT.md)
- NSE RSS categories: https://www.nseindia.com/static/rss-feed
- Official Codex account authentication: https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- Codex CLI reference: https://learn.chatgpt.com/docs/cli/reference
- Codex device login / token security: https://learn.chatgpt.com/docs/auth
- Current optional provider free-tier references: https://www.tavily.com/pricing ; https://apify.com/pricing ; https://www.browserbase.com/pricing ; https://www.firecrawl.dev/pricing

**Deployment status at preparation:** No setup, installation, timer activation, model authentication or database smoke test performed by writing this plan. Complete the acceptance checklist before describing the pipeline as live.
