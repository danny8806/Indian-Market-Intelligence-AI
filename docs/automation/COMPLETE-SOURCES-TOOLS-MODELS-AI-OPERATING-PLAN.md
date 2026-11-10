# Complete financial news sources, fetching tools, AI models and operating plan

**Prepared:** 2026-11-10 IST. **Status:** implementation instructions — NOT installed, running, or VPS-tested. **Audience:** another AI engineering agent working on this repository.

**Source code:** https://github.com/danny8806/Indian-Market-Intelligence-AI
**Start-here handoff:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/START-HERE-OTHER-AI-HANDOFF.md
**Free-tools checklist:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/FREE-TOOLS-NEWS-COLLECTOR-MORNING-PLAN.md
**Multi-agent architecture:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/multi-agent-news-pipeline.md
**Codex independent-fetching plan:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/docs/automation/codex-news-collector-10min.md
**Existing live API:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/bridge/app.py
**Existing schema:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/schema/stock-signals.schema.json
**VPS and security rules:** https://github.com/danny8806/Indian-Market-Intelligence-AI/blob/main/ops/README.md

## 1. Target
Build a news-only service running every 10 minutes, 24/7 on a reported 2-vCPU/8-GB Ubuntu VPS, covering current NIFTY 500 constituents as priority with other NSE/BSE issuers separately. Every AI collector must **actually fetch independent live sources**, not merely classify news supplied by Python. Preserve primary URLs, independently evidenced first-public-availability times and ingestion logs. Research-only final model ranks up to 5 LONG and 5 SHORT at 09:00 IST using previous NSE trading session 15:00 IST through current trading day 09:00 IST, with independent review and explicit NO_TRADE/UNAVAILABLE fallbacks. Never activate, submit or authorize broker orders.

## 2. Official/primary news SOURCE INVENTORY (priority P0)
| Source | Link | News types | Fetch path |
|---|---|---|---|
| NSE official RSS directory | https://www.nseindia.com/static/rss-feed | Corporate announcements, results, board meetings, corporate actions, shareholding, insider dealing, circulars | Feedparser + authorized official document downloads; verify exchange dissemination time |
| NSE corporate filings | https://www.nseindia.com/companies-listing/corporate-filings-announcements | Original issuer documents and announcements | Authorized NSE webpage/feed access; avoid inventing unofficial API endpoints |
| BSE corporate filings | https://www.bseindia.com/corporates.html | Company announcements, results and governance | Approved BSE website/download flows, only if accessible |
| SEBI | https://www.sebi.gov.in/ | Orders, circulars, enforcement, regulatory news | Site index/official press releases/PDF |
| RBI | https://www.rbi.org.in/ | Bank/NBFC actions, rates, financial regulation | Press releases and notifications |
| PIB / Government of India | https://pib.gov.in/ | Policy, sector approvals, ministries | Government press release pages |
| Ministry of Corporate Affairs | https://www.mca.gov.in/ | Corporate/insolvency governance | Authorized published notices, no login bypass |
| Competition Commission of India | https://www.cci.gov.in/ | Merger and competition decisions | Official orders/releases |
| CDSCO | https://cdsco.gov.in/ | India pharma regulatory notices | Official alerts/public documents |
| US FDA | https://www.fda.gov/ | Pharma warning letters, approvals, recalls, import alerts | Official pages and releases; match actual issuer subsidiary/facility |
| Ministry of Defence | https://mod.gov.in/ | Defence procurement and policy | Releases and government notifications |
| DGFT / Ministry of Commerce | https://www.dgft.gov.in/ | Export/import restrictions and policies | Published notifications |
| Individual issuer investor-relations sites | Issuer-maintained official URLs, store in registry | Results, investor decks, press releases, orders, monthly sales | Company-specific RSS/sitemaps/public IR pages and PDFs |

**Primary authority:** A newspaper report is not equivalent to an original exchange filing. Resolve duplicate syndicated articles to one corporate event while keeping all source links. Maintain verified point-in-time NSE ticker-to-issuer/ISIN mapping.

## 3. Financial publications and supplementary sources (P1/P2; access varies)
| Category | Sources | Purpose and access rule |
|---|---|---|
| Indian financial media | Moneycontrol https://www.moneycontrol.com/ ; ET Markets https://economictimes.indiatimes.com/markets ; Business Standard https://www.business-standard.com/ ; Mint https://www.livemint.com/ ; NDTV Profit https://www.ndtvprofit.com/ ; CNBC-TV18 https://www.cnbctv18.com/ | Independent reporting, broker reactions, context; official RSS/API or permitted public pages only |
| International financial media | Reuters https://www.reuters.com/ ; Bloomberg https://www.bloomberg.com/ ; Financial Times https://www.ft.com/ | Global cues, multinational issuer news, commodity and FX; licensing/paywalls often apply |
| Indian market/business portals | Economic Times, Financial Express https://www.financialexpress.com/ ; The Hindu BusinessLine https://www.thehindubusinessline.com/ ; Zee Business https://www.zeebiz.com/ ; India Today Business https://www.indiatoday.in/business | Supplement discovery and corroboration; check each publisher's terms |
| Market/filing intelligence portals | Trendlyne https://trendlyne.com/ ; Screener https://www.screener.in/ ; StockEdge https://stockedge.com/ | Fundamentals, earnings context, consensus; may require accounts/licensing; not primary timestamp proof |
| Broker research/news | Kotak Neo https://www.kotaksecurities.com/ ; Zerodha https://zerodha.com/ ; Upstox https://upstox.com/ ; Motilal Oswal https://www.motilaloswal.com/ ; ICICI Direct https://www.icicidirect.com/ ; HDFC Securities https://www.hdfcsec.com/ | Broker reports and market context; only authorized feeds and licensed/public pages |
| International sector regulators | US FDA, US SEC https://www.sec.gov/ , other country regulator releases | Pharma, overseas subsidiaries, international regulatory actions |
| Discoverability-only | Google News links/RSS where legitimate, GDELT, SearXNG, search indexes, company YouTube channels | Find missed events; never treat snippet or video upload time as proven original event time |

Build a source registry: source_id, category, RSS/API/page, terms status, credentials requirements, poll cadence, last successful publication, time-verification rule, rate limits, 401/403/429 failures, cost/usage, parser version and data freshness. Explicitly report blocked or unavailable providers; never bypass access controls.

## 4. FREE SELF-HOSTED fetching, parsing, browser, PDF and database tools
| Tool | Category | What it does / when to use | Cost model |
|---|---|---|---|
| Python httpx / requests | APIs and HTTP | Light parallel polling of permitted sources and official documents | Free library |
| feedparser | RSS/Atom | First-line official and publisher feed retrieval | Free library |
| Beautiful Soup / lxml | HTML parser | Extract precise fields from ordinary pages | Free library |
| Trafilatura | Article parser | Clean body, title and metadata from permitted pages | Free library |
| Scrapy | Crawler | Crawl many approved known sites with pipelines, throttling and retries | Open source |
| scrapy-playwright | Browser connector | JS rendering only on pages that need it | Open source; CPU/RAM cost |
| Playwright | Browser automation | One Chromium worker for JS pages, permitted navigations | Open source; CPU/RAM cost |
| Crawl4AI | LLM-ready crawler | Structured Markdown/JSON for extraction | Self-host open source; optional hosted credits |
| Browser Use | AI browser | Complex authorized interactions if basic browser is inadequate | Library open source; model inference may cost |
| Stagehand | AI-assisted browser | Schema-oriented extraction on permitted sites | Library open source; model inference may cost |
| SearXNG | Search engine aggregator | Secondary discovery index; does NOT guarantee publisher access | Self-host open source; engines may throttle |
| GDELT | News discovery index | Finds further international indexed stories | Public data; service limits apply |
| PyMuPDF | PDF text | Cheap text-first earnings/filing PDF parsing | Open source; check applicable licensing |
| Docling | PDF tables/layout | Complex results and investor presentation table extraction | Open source; more compute |
| MarkItDown | Document converter | Normalize HTML, documents and other formats | Open source |
| Pydantic / JSON Schema | Validation | Type-safe agent output and timestamp field checks | Open source |
| PostgreSQL / SQLite / SQLAlchemy | Storage | Durable source ledger, event dedupe, offline spool and DB access | Open source |
| systemd timers / flock | Scheduler | 10-min on-VPS triggers, avoid overlaps | Included/free on Ubuntu |
| n8n self-hosted community edition | Workflow engine (optional) | Visual orchestration, retries and alerting | No required software fee for qualifying self-hosted use |

## 5. External search, scrape and MCP tools (optional, typically metered)
| Service / interface | What it adds | Auth / cost expectation |
|---|---|---|
| Codex native live search | Model performs real current-web discovery | ChatGPT/Codex authenticated, quota limited; explicitly enable search |
| Gemini google_web_search + web_fetch | Independent Google discovery and URL extraction | Auth, terms, model/tool quotas |
| Playwright MCP / Scrapy MCP | Expose local browser and crawler to AI clients | Open-source, local resources |
| Fetch/HTTP MCP | Read approved public URLs | Self-hosted server may be free; verify permissions |
| Firecrawl MCP | Web search, scrape, structured extraction, PDF/browser | Account/keyless tier limits or paid credits; https://mcp.firecrawl.dev/ |
| Tavily MCP | Web search and extraction | API plan/credit limits; https://www.tavily.com/ |
| Exa | Search/indexing/retrieval | API quotas; https://exa.ai/ |
| Apify MCP/Actors | Hosted marketplace scrapers | API/account and usage-based limits; https://mcp.apify.com/ |
| Browserbase MCP | Cloud browser rather than local RAM | API/account and limited tier; https://www.browserbase.com/mcp |
| Serper / Brave Search API / other search APIs | Additional independent search index | Keys/quotas/terms vary; https://serper.dev/ ; https://brave.com/search/api/ |
| Firecrawl and TinyFish ChatGPT apps | ChatGPT-side web fetch/cloud browser | Require user connection; **not** automatically installed on VPS |

Do not promise any particular free-credit amount until verified against provider pricing at setup. A free MCP client/package does not mean its downstream search or browser service is unlimited.

## 6. AI models and CLIs — what EACH should do
| Agent | Retrieval responsibility | AI decision responsibility | Constraints |
|---|---|---|---|
| Codex CLI (preferred primary agent) | Independently search live official issuers, NSE/BSE announcements and missed media; fetch source URLs with enabled tools | Strong event extraction and cross-check | Auth via ChatGPT; exact available models and remaining usage must be checked in the account; CLI is not general ChatGPT CLI |
| Gemini CLI (independent secondary agent) | google_web_search and web_fetch on different query/topic batches | Summarize source facts and contradictory reporting | Confirm currently supported auth, model, search permissions and headless quotas |
| OpenCode | Independently retrieve through configured model + search backend | Optional review or batch labeling | Open-source CLI, provider access may be paid/free-capped |
| Qwen Code | Retrieve via enabled web-search/MCP or explicit Python tools | Optional second opinion on extraction | Do not assume unrestricted free OAuth or built-in news coverage |
| Claude Code | Retrieve through authorized web tools/MCP | Deep analysis and contradiction review | Account/plan and CLI access may cost |
| GitHub Copilot CLI | Optional distinct investigation queries using available tools | Review source parsers or verification | Plan quota and web search availability must be tested |
| Ollama/local small model | **Not an independent live news source**; can only use separately fetched content | Local classification/dedup support | 8 GB VPS too limited for simultaneous large local models |
| Final Codex or other capable model | Reads frozen verified database; optionally independently checks already-public source facts | Rank up to 5 LONG / 5 SHORT, include uncertainty and counterevidence | Run ONCE daily or on exceptional event; premium models off by default |
| Independent reviewer | Re-fetch/check primary evidence or read verified record; challenge confidence | Reject weak signals, unresolved symbols and time violations | No majority-vote shortcut; independent evidence is key |

**Quota budget:** 10-minute timer means 144 cycles/day, ~4,320 cycles per 30 days. Python runs every cycle. Codex/Gemini only run when authorized, available and within caps; schedule topic batches/rotate companies. On 2 vCPU/8 GB use at most one concurrent AI CLI worker and one browser instance initially. Save actual model version, tokens/usage where available, tool calls, wall time and rate-limit events.

## 7. Operational workflow and temporal integrity
1. At each :00/:10/:20/:30/:40/:50 IST, one systemd job gets a lock and loads per-source cursors; re-poll with overlap for delayed publication. Poll authorized NSE/BSE/issuer feeds first; independently send diverse current-source discovery queries to Codex/Gemini if quota permits.
2. Each fetcher returns original URL, document id, headline, issuer symbols, captured HTML/PDF checksum, original published/disseminated time and timezone, retrieved UTC timestamp, method/tool and HTTP status. Never guess missing timestamps.
3. Extract PDF text normally before attempting expensive document layout/OCR. Parse results, order wins, regulatory news, stake transactions, brokerage opinions, block/bulk deals, sales and contract announcements. Track numeric facts, period, units and actual impact.
4. Normalize issuer identity (ISIN, NSE/BSE ticker, aliases, subsidiaries). Distinguish new corporate events from reprints, corrections and old stories. Deduplicate using canonical URL/source ID + event fingerprint while preserving source-level provenance.
5. Validate independent primary confirmation, timestamp authenticity, first publicly available time and source access; mark unknown/blocked explicitly. Save source run failures. Commit idempotently to a **separate news database**; advance source cursor only after write success.
6. At NSE trading-day 09:00 IST freeze the eligible news as-of time using previous NSE trading session 15:00 to today 09:00, accounting for weekends/holidays and publication evidence (NOT fetch time). No future earnings, after-cutoff reports or future price moves.
7. Final decision agent assesses expected-vs-actual earnings, surprise, materiality, liquidity, sell-side commentary, regulatory severity and counterevidence; critic independently challenges. Output max 5 bullish and 5 bearish from NIFTY 500, or fewer/zero, in existing strict JSON v1.0 research schema with execution_enabled=false.
8. Preserve all reasons, source documents, rejected candidates, model versions and raw verification evidence. After market close compare open-to-close direction and process error/missed-news audits; never change frozen historic inputs.

## 8. Persistence specification
Create separate (not broker) tables: source_registry, source_run, raw_document, document_company, news_event, event_source, agent_discovery, source_cursor, news_snapshot_0900, model_decision, decision_source, prediction_outcome, run_alert. Keep time fields in UTC with Asia/Kolkata display. Raw records must include first_available_at, timestamp_evidence, published_at, fetched_at, revised_at, retrieval_tool, retrieval_status, source URL, sha256, company/ISIN/ticker, event category, numerical evidence and confidence. Never replace published_at with fetched_at. Use unique constraints, idempotent UPSERT, retention policies and backups. If DB unavailable spool durably to SQLite then retry without losing records.

## 9. Phased work for the other implementing AI
**Phase A — audit:** Inspect README, docs, live_desk, bridge, schema, tests, existing deployment; check VPS RAM, free disk, systemd/Docker status. Keep the trading dashboard and LIVE_ORDERS_ALLOWED=NO unchanged.
**Phase B — Python MVP:** Implement official source ingestion, source ledger, validated time fields, idempotent persistence and tests; verify a real NSE/BSE document with source, clock and DB readback; test duplicate second run.
**Phase C — AI independent fetching:** Authenticate Codex; verify live search enabled and real tool trace. Run one direct NSE/BSE fetch, storing discovered_by=codex; add Gemini when its own live search succeeds. Compare unique verified events found.
**Phase D — browser/MCP/source expansion:** Only after initial stability add single Playwright or Crawl4AI worker, Trafilatura/Scrapy, GDELT/SearXNG and targeted PDF parsers. Add paid providers only when their incremental value justifies cost.
**Phase E — schedule and resilience:** Enable 10-minute systemd timer after manual tests; use locking, timeouts, 429 handling, source cursors, catch-up and backup/alert. Prove two real timer runs with actual DB rows and no overlapping writes.
**Phase F — research-only final model:** Freeze 09:00 window, run final model + critic, verify existing JSON schema. No live orders. External bridge delivery is a separate approved and independently tested action.

## 10. Acceptance tests and reporting
- For every source: attempted, succeeded, access denied, parse failed, last successful publication time, total events discovered, truly new events, duplicates and delayed articles.
- For each AI: exact authenticated model name, live retrieval proof, unique non-duplicate events, missing timestamps, quota used, latency and errors; do not equate an LLM summary with fetched source proof.
- Verify DB write success/readback, duplicate run behavior, source cursor rollback, recovery after outage, archive snapshot immutability and 09:00 cutoff with no-lookahead test.
- Confirm server under expected CPU/RAM, no more than one browser and one AI worker initially, 24/7 schedule working without operator PC, and dashboard remains broker-disarmed.
- Report exact changed files/commits, tests and results, sources unavailable due to permission, any missing setup or secrets, and why coverage is incomplete.

## 11. Copy-paste instruction for an implementation agent
> Open https://github.com/danny8806/Indian-Market-Intelligence-AI and read docs/automation/START-HERE-OTHER-AI-HANDOFF.md and this COMPLETE-SOURCES-TOOLS-MODELS-AI-OPERATING-PLAN.md before making changes. Design and implement the news-only service in the phased order above. Python and Codex CLI must both actually fetch live permitted NSE/BSE and financial news. Add Gemini independent search after testing. Prefer free self-hosted HTTP/RSS/HTML/PDF/browser/MCP solutions, but never mistake a free package for unlimited news access. Keep strict IST publication evidence, source provenance, NIFTY 500 symbol mapping, dedupe, 10-minute VPS systemd runs and durable DB write/readback. Evaluate model/news coverage and quotas empirically. Have a separate, time-frozen 09:00 research-only final ranking with max five bullish/five bearish. Never enable broker orders. Deliver commits, actual test logs, confirmed source coverage, failure reports, DB persistence and deployment status; never claim success from documentation alone.

## 12. Technical documentation
- NSE RSS: https://www.nseindia.com/static/rss-feed
- SEBI corporate filings references: https://www.sebi.gov.in/curation/corporate_filings.html
- Codex CLI: https://learn.chatgpt.com/docs/cli/reference
- Codex noninteractive: https://learn.chatgpt.com/docs/non-interactive-mode
- Gemini web tools: https://geminicli.com/docs/cli/tutorials/web-tools/
- Scrapy: https://docs.scrapy.org/en/latest/
- Crawl4AI: https://docs.crawl4ai.com/
- SearXNG: https://docs.searxng.org/
- Docling: https://docling.ai/
- Firecrawl MCP: https://github.com/firecrawl/firecrawl-docs/blob/main/mcp-server.mdx
- Apify MCP: https://docs.apify.com/mcp
- Browserbase MCP: https://www.browserbase.com/mcp

**Current status:** This is an engineering specification, not proof of an installed tool, accessible source, live DB, scheduled VPS agent or real-time news flow.