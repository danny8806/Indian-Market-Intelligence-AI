# Open-source agents, web fetchers and source-access resilience

Date: 2026-11-10 IST. STATUS: research and rollout plan; NOT installed, running, or tested on VPS. This is an extension of:
- [Expanded OSS tools catalog](EXTENDED-OPEN-SOURCE-NEWS-FETCHING-TOOLS-CATALOG.md)
- [Complete source/tools/agents workflow](COMPLETE-SOURCES-TOOLS-MODELS-AI-OPERATING-PLAN.md)
- [Morning implementation handoff](START-HERE-OTHER-AI-HANDOFF.md)

## What "cannot be blocked" means in practice

**No open-source agent, crawler, browser or search provider has universal, guaranteed access to all websites.** A publisher can require a login, deny automated traffic, enforce terms/licensing, revoke an endpoint, introduce CAPTCHAs, or return 401/403/429. Tools advertised as "anti-blocking" are not an authorization to evade restrictions. Design for **source redundancy, authorized access, graceful degradation and verifiable coverage**, NOT bypass.

### Allowed resilience hierarchy per blocked source

1. Prefer official RSS/Atom, exchange filings, issuer investor-relations pages, press releases, regulator releases and documented provider APIs. NSE publishes official RSS categories: https://www.nseindia.com/static/rss-feed
2. Request licensed publisher data, approved API access or administrator permission when a restricted original is important.
3. Use independent permitted reporters and official primary-source documents, with precise provenance. A search snippet is a **lead** only, not full verified original.
4. Use a documented index or archive where access and redistribution are permitted; preserve the time of the original release separately from index discovery time.
5. Reduce legitimate load using conditional GET (ETag / Last-Modified), domain-level quotas, caching, exponential backoff, obey Retry-After on 429, dedicated official feeds and clearly identified user agents, if appropriate under site rules.
6. If a source remains inaccessible, record `SOURCE_BLOCKED`, `PAYWALL`, `AUTH_REQUIRED`, `RATE_LIMIT` or `PARSER_ERROR`, keep the URL and discovery metadata, and continue permitted sources. Never silently claim success or fill missing first-publication times.

**Do not implement:** CAPTCHA solving to defeat restrictions, stealth browser fingerprints, proxy/IP rotation to circumvent block decisions, unauthorized credential/session reuse, or methods to bypass subscriptions. Browser tooling is for JavaScript-rendered **authorized** pages, not universal access.

## Agents with research/search capability or configurable live tools

| Tool | Official/open-source repo | How it could contribute | Tool/model prerequisites |
|---|---|---|---|
| Codex CLI | https://github.com/openai/codex | Independent fresh company filings and corroboration | ChatGPT/Codex sign-in, explicitly enabled search/browser/MCP; usage cap |
| Gemini CLI | https://github.com/google-gemini/gemini-cli | Separate Google-backed discovery | Working current web-search/web-fetch and authentication |
| GPT Researcher | https://github.com/assafelovic/gpt-researcher | Search several sources, produce cited event summaries | Search backend, LLM provider/local model |
| DeerFlow | https://github.com/bytedance/deer-flow | Parallel specialist subagents, tool orchestration, scheduled research | Quite heavy; configured search backends, container isolation, LLM |
| Local Deep Research | https://github.com/LearningCircuit/local-deep-research | Multi-step grounded investigation, self-hosted index | SearXNG/search provider and model |
| Vane (formerly Perplexica) | https://github.com/ItzCrazyKns/Perplexica | Self-hosted cited web search over SearXNG | Search backend and supported model |
| STORM | https://github.com/stanford-oval/storm | Thorough multi-perspective source synthesis | Not for frequent 10-min collection |
| Skyvern | https://github.com/Skyvern-AI/skyvern | Guided authorized web interaction and extraction | Browser infrastructure and LLM; AGPL considerations |
| Browser Use | https://github.com/browser-use/browser-use | AI navigates authorized JS sites | Browser, model/provider, isolation |
| Stagehand | https://github.com/browserbase/stagehand | Structured AI extraction | Browser and model |
| Goose | https://github.com/aaif-goose/goose | MCP-connected CLI research workflows | Search/MCP connectors, model |
| OpenCode | https://github.com/anomalyco/opencode | Alternate independent web-discovery agent | Provider + real retrieval/search enabled |
| Qwen Code | https://github.com/QwenLM/qwen-code | Independent checking / company event parsing | Search/MCP backend; auth and quota |
| Cline | https://github.com/cline/cline | Tool/CLI work for source discovery and repairs | Model and enabled browser/MCP |
| OpenHands | https://github.com/OpenHands/OpenHands | Agentic engineering of fetchers and parser tests | Heavy runtime; use for development not every 10 minutes |
| smolagents | https://github.com/huggingface/smolagents | Lightweight tool-using source-specific agents | Explicitly registered permitted search/fetch tools |
| LangGraph | https://github.com/langchain-ai/langgraph | Durable stateful research and evidence reviewer | Agent runtime, retrievers and models |
| CrewAI | https://github.com/crewAIInc/crewAI | Parallel searcher/verifier/critic roles | Search, model, retrieval and costs |
| PydanticAI | https://github.com/pydantic/pydantic-ai | Strict JSON record agents with validation | Model and source tools |
| Agno | https://github.com/agno-agi/agno | Agent orchestration with tooling | Search backend/provider |
| Microsoft Agent Framework | https://github.com/microsoft/agent-framework | Structured multi-agent workflows | Provider and tools |
| Google ADK | https://github.com/google/adk-python | Tool-enabled agent workflows | Providers/web connectors |
| Agent Reach | Check upstream repository via its project page | Web/social/video/RSS retrieval integrations | Only permitted sources; social content is weaker than filings |
| SurfSense | https://github.com/shaneholloman/surfsense | Search across already-ingested data and documents | Not a primary guaranteed web-fetcher |
| TrendRadar | https://github.com/sansan0/TrendRadar | News/RSS trend aggregation, keyword triggers, MCP | Need verified Indian-finance feeds |
| Maxun | https://github.com/getmaxun/maxun | Create reusable scraper/monitor robots and MCP extraction | Self-hosted AGPL; permitted pages only |
| Lightpanda | https://github.com/lightpanda-io/browser | Lower-resource headless browser for eligible pages | Verify JS compatibility before replacement of Playwright |

**Maintenance caution:** This is a shortlist of candidates, not an audited guarantee that each command, license or feature remains supported. Measure their extra unique verified discoveries before adding to production.

## Dedicated open-source fetchers and page monitors

- **HTTP / crawlers:** httpx, aiohttp, requests, curl, Scrapy, Crawlee Python, Colly, Crawl4AI, ScrapeGraphAI, news-please, Scrapling (adaptive parsing only on permitted pages), Firecrawl self-host edition.
- **Browser engines:** Playwright, Selenium, Puppeteer, chromedp, go-rod, Lightpanda. Do not run multiple simultaneously by default on 2-vCPU, 8-GB VPS.
- **Feed generation:** feedparser, RSSHub, RSS-Bridge, FreshRSS, Miniflux, feed_seeker, feedfinder2, XML sitemaps. Only legitimate accessible site routes.
- **New-page / modified-page detection:** changedetection.io, urlwatch, webchanges, Huginn, TrendRadar, WebSub where supported.
- **Search discovery / archives:** SearXNG, GDELT, Media Cloud, Common Crawl and an optional approved provider API (Exa, Tavily, Firecrawl, Brave Search). Search snippets are leads, not proof.
- **HTML / PDF:** Beautiful Soup, lxml, selectolax, Trafilatura, Goose3, newspaper4k, extruct, PyMuPDF, pdfplumber, pypdf, Docling, MarkItDown; OCR only for actual scanned PDFs.
- **Pipelines & DB:** Pydantic, SQLAlchemy, PostgreSQL, SQLite spool, Scrapy AutoThrottle, systemd, flock, APScheduler, Dagster or Prefect for later scaling, Prometheus/Alertmanager, Grafana.
- **Deep research / summary:** GPT Researcher, DeerFlow, Local Deep Research for *exceptional events*, not 144 daily heavyweight research cycles.

## News coverage routing, 10-minute cadence

- **Every cycle** Python polls official NSE/BSE/company feeds, authorized media RSS/API and source-specific publisher sitemaps with cache validators and incremental cursors.
- **Codex independently searches** rotated source/topic/ticker groups using permitted live tools and returns strict JSON with exact source URLs, attempted tools and timestamp evidence.
- **Other agent (Gemini or GPT Researcher)** runs selectively to find unique missed events or resolve disagreement. Do not run expensive deep research on empty cycles.
- **Page monitor** discovers when investor-relations pages change. It triggers a permitted fetch, but the detection time is NOT automatically the publication time.
- **Browser fallback** opens one authorized JS page at a time; never bypass a site denial.
- **Document extractor** parses disclosed PDF body/tables and evidence. Verify each event with original documents.
- **Deduplicate** using original URL/source ID, issuer/ISIN, event facts and historical corrections; retain original evidence.
- **Save** raw documents, events, source status and a persistent cursor in a dedicated DB; verify readback. Keep source access and legal provenance.
- **09:00 IST** freeze previous NSE session 15:00→current session 09:00 news based on first public availability, not fetched-at. Final AI with independent critic chooses 0–5 LONG and 0–5 SHORT research candidates only; keep existing broker orders disabled.

## Recommended first 10 tools for this 2-vCPU / 8-GB VPS

1. **Python HTTPX + feedparser** — official RSS/HTTP fetching.
2. **Trafilatura + BeautifulSoup + extruct** — clean text, metadata, structured publisher timestamps.
3. **Scrapy with AutoThrottle** — source-specific compliant spiders.
4. **PyMuPDF + pdfplumber** — results/filing PDFs and tables.
5. **Codex CLI + explicitly tested read-only source retrieval** — independent AI discovery.
6. **RSSHub OR RSS-Bridge** — fill legitimate RSS gaps.
7. **changedetection.io OR urlwatch** — issuer page change alerts.
8. **GDELT + SearXNG** — find indexed leads missed by feeds.
9. **One Playwright/Lightpanda worker** — accessible JS sources only.
10. **PostgreSQL + SQLite fallback + systemd** — durable history and every-10-minute jobs.

Add Gemini, GPT Researcher, DeerFlow, Maxun, Browser Use, Stagehand and Firecrawl only after the above baseline shows a measurable gap. They may require inference or hosted-service fees and significant RAM.

## Verification/acceptance checklist

- Run individual access tests on 10 official/issuer sources and 10 media sources; record response codes, fetch time, real publication timestamp evidence, and links.
- Distinguish source `401`, `403`, `429` and `404`, with compliant fallback and no evasion.
- Test legitimate delay reduction (If-None-Match / If-Modified-Since), recheck that source freshness was not reduced.
- Independently verify one Codex direct live find not present in Python batch and keep tool evidence.
- Confirm that when publisher is inaccessible, no AI fabricates the full text, timestamp or original publication.
- Run two timer cycles and confirm persistent new DB rows or legitimately empty cycles and error metrics.
- Measure RAM/CPU on existing VPS and preserve dashboard health with real-money trading disabled.
- Store coverage score by source and detect missed reports after market close.

## Sources
- NSE RSS: https://www.nseindia.com/static/rss-feed
- Scrapy AutoThrottle: https://docs.scrapy.org/en/master/topics/autothrottle.html
- DeerFlow independent tools: https://github.com/bytedance/deer-flow
- Lightpanda/browser: https://github.com/lightpanda-io/browser
- Maxun: https://github.com/getmaxun/maxun
- Local Deep Research: https://github.com/LearningCircuit/local-deep-research
- Browser Use: https://github.com/browser-use/browser-use
- Firecrawl self-host: https://github.com/firecrawl/firecrawl
