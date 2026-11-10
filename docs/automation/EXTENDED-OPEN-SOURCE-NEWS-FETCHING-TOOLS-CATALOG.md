# Expanded open-source news-fetching and AI-agent tool catalog

**Date:** 2026-11-10 IST. **Status:** research and implementation catalog; NOT installed, authenticated, deployed, or source-access verified on the user's VPS. **Goal:** make it easier for implementing AI agents to select from a broad ecosystem of tools for independent, permitted live financial-news discovery. This is a *curated, non-exhaustive* landscape; new projects appear continuously.

## Project navigation
- Repository: https://github.com/danny8806/Indian-Market-Intelligence-AI
- Main handoff: [START-HERE-OTHER-AI-HANDOFF.md](START-HERE-OTHER-AI-HANDOFF.md)
- Current operating design: [COMPLETE-SOURCES-TOOLS-MODELS-AI-OPERATING-PLAN.md](COMPLETE-SOURCES-TOOLS-MODELS-AI-OPERATING-PLAN.md)
- Free-tools plan: [FREE-TOOLS-NEWS-COLLECTOR-MORNING-PLAN.md](FREE-TOOLS-NEWS-COLLECTOR-MORNING-PLAN.md)
- Independent Codex fetcher: [codex-news-collector-10min.md](codex-news-collector-10min.md)

## Critical distinctions / constraints
- **Software open-source does not make a proprietary model, cloud search quota, or paid news article free.** Always verify the repository license, current maintenance status, provider quota and subscription/API requirements.
- A **coding agent** or **agent framework** is not automatically a live news-search service. News fetching requires tools/network access, correct permissions, and tested source retrieval.
- No crawler can guarantee **all websites**: publisher terms, authentication, paywalls, site changes, 401/403/429, robots policy and licensing constrain access. Keep a source registry and gap report. Do not bypass controls or CAPTCHA requirements.
- AI agents reading untrusted webpages/filings are exposed to **prompt injection**; sandbox them, restrict shell and filesystem tools, and never give agents access to Kotak/Dhan credentials, order endpoints, or broker configuration. Keep `LIVE_ORDERS_ALLOWED=NO`.
- Start with lightweight official NSE/BSE RSS, filings, issuer IR feeds and Python source-specific fetchers. Use browser and AI fallback for genuinely missed news, not on every URL.
- On this user's reported **2 vCPU / 8 GB RAM** VPS, run **one browser and one LLM CLI process** concurrently at first. No assumption that 100 packages should all be installed.

## 1. Open-source CLI, general-purpose and autonomous AI agents (not all have built-in web search)

| Tool | Source/docs | Potential role | Cautions |
|---|---|---|---|
| Codex CLI | https://github.com/openai/codex | Independent live news investigator with explicitly enabled tools; Python code maintenance | CLI open source; OpenAI model quota separate |
| OpenCode | https://github.com/anomalyco/opencode | Model-provider-neutral terminal news-research agent | Requires a model/search backend |
| Qwen Code | https://github.com/QwenLM/qwen-code | Alternate research and extraction agent | Actual web search and provider auth must be tested |
| Gemini CLI | https://github.com/google-gemini/gemini-cli | Search + web fetch with supported Google auth/model | Check current supported CLI/auth plans |
| goose | https://github.com/aaif-goose/goose | Tool/MCP-connected local research agent | Provider model/search access separate |
| Cline | https://github.com/cline/cline | Agentic code/tool/browser workflows | More suitable for operator-led work |
| Kilo Code | https://github.com/Kilo-Org/kilocode | Alternative tool-enabled CLI/editor agent | Provider quotas separate |
| Aider | https://github.com/Aider-AI/aider | Improve source-specific scrapers, tests and parsing | Coding assistant, not a built-in news index |
| OpenHands | https://github.com/OpenHands/OpenHands | Agent engineering and troubleshooting of ingestion code | Heavier runtime |
| Hermes Agent | https://github.com/NousResearch/hermes-agent | Long-running connected agent where permitted | Limit system permissions; verify current project version |
| Pi | https://github.com/badlogic/pi-mono | Extensible agent runtime with tools | Need to configure tool access |
| OpenClaw | https://github.com/openclaw/openclaw | Persistent agent coordination/search integrations | High security complexity; keep off broker VPS initially |
| Kimi Code CLI | https://github.com/MoonshotAI/kimi-cli | Optional alternative CLI researcher | Model/quota and web access need confirmation |
| Open Interpreter | https://github.com/OpenInterpreter/open-interpreter | Python/shell task assistant | Shell access high risk; keep isolated |
| Kimi / DeepSeek and other model CLIs | Provider-supported repos only after verification | Optional independent search/evaluation | Model weights/API access/terminal permissions vary |
| OpenAI Agents SDK | https://github.com/openai/openai-agents-python | Build lightweight tool-calling agents programmatically | Backend model inference may require paid API |

**Not preferred for new installs:** Claude Code is proprietary (do not label open-source). The old Microsoft AutoGen repo is archived; use Microsoft Agent Framework instead. Roo Code is reportedly discontinued/archived; verify status before relying on it. Do not add these as required services.

## 2. Open-source deep research and agent orchestration

| Tool | Repository | Useful role |
|---|---|---|
| GPT Researcher | https://github.com/assafelovic/gpt-researcher | Multi-source research with citations and configurable retrievers |
| Open Deep Research (LangGraph) | https://github.com/langchain-ai/open_deep_research | Deep web investigation with model/search/tool adapters |
| LangGraph | https://github.com/langchain-ai/langgraph | Stateful discovery/verification pipeline and checkpoints |
| LangChain | https://github.com/langchain-ai/langchain | Retrieval tool adapters and document pipelines |
| CrewAI | https://github.com/crewAIInc/crewAI | Searcher / verifier / critic role delegation |
| PydanticAI | https://github.com/pydantic/pydantic-ai | Structured validated agent output |
| smolagents | https://github.com/huggingface/smolagents | Lightweight tool-using agents |
| Google ADK | https://github.com/google/adk-python | Multi-agent flows and tool access |
| Microsoft Agent Framework | https://github.com/microsoft/agent-framework | Supported successor to archived AutoGen |
| Agno | https://github.com/agno-agi/agno | General-purpose tool-calling agents |
| LlamaIndex | https://github.com/run-llama/llama_index | Indexed private filings and retrieval QA |
| Haystack | https://github.com/deepset-ai/haystack | Search and extraction pipelines |
| Mastra | https://github.com/mastra-ai/mastra | TypeScript agents and workflows |
| Langfuse | https://github.com/langfuse/langfuse | Audit agent traces, prompt runs and quality |
| DSPy | https://github.com/stanfordnlp/dspy | Structured/model-optimized extraction experiments |

Most frameworks above **do not fetch the internet autonomously**: provide source-restricted HTTP/search/browser tools, documented schemas, quotas and actual retrieval evidence.

## 3. HTTP clients, crawling and website exploration

| Tool | Repository/docs | Role | VPS preference |
|---|---|---|---|
| Python Requests | https://github.com/psf/requests | Simple sanctioned API/HTML calls | P0 |
| HTTPX | https://github.com/encode/httpx | Concurrent HTTP/2 fetching, async | P0 |
| aiohttp | https://github.com/aio-libs/aiohttp | High-throughput async HTTP | P1 |
| urllib3 | https://github.com/urllib3/urllib3 | Low-level HTTP pools/retries | P1 |
| curl | https://curl.se/ | Downloads, HEAD, conditional requests | P0 |
| wget | https://www.gnu.org/software/wget/ | Safe batch downloads | P1 |
| Scrapy | https://github.com/scrapy/scrapy | Structured spider + middleware + queues | P0/P1 |
| Crawlee Python | https://github.com/apify/crawlee-python | Unified requests/BS4/Playwright crawling | P1 |
| Crawlee TypeScript | https://github.com/apify/crawlee | Node-based crawling | Optional |
| Crawl4AI | https://github.com/unclecode/crawl4ai | Web-to-Markdown, structured extraction | P1 |
| Colly | https://github.com/gocolly/colly | Lightweight Go crawler | Optional |
| Apache Nutch | https://github.com/apache/nutch | Industrial-scale crawler (Java/Hadoop) | Not recommended on 2 vCPU |
| StormCrawler | https://github.com/DigitalPebble/storm-crawler | Distributed continuous crawler | Not recommended |
| Heritrix | https://github.com/internetarchive/heritrix3 | Archive-grade site crawling | Not recommended |
| Browsertrix Crawler | https://github.com/webrecorder/browsertrix-crawler | Capture whole webpages/archives with browser | Optional, expensive |
| HTTrack | https://www.httrack.com/ | Website mirroring | Avoid broad mirrors; prefer targeted pages |
| Katana | https://github.com/projectdiscovery/katana | Discover URL/link structure | Security-focused, use only on authorized sites |
| ScrapeGraphAI | https://github.com/ScrapeGraphAI/Scrapegraph-ai | LLM-assisted structured extraction | Provider/compute cost |
| news-please | https://github.com/fhamborg/news-please | Purpose-built news crawler + article extraction | P1 |
| scrapy-playwright | https://github.com/scrapy-plugins/scrapy-playwright | JS render selectively inside Scrapy | P1 |

Choose **one** primary crawling framework (Scrapy or Crawlee), not all. Use conditional GET/ETags, timeouts, retries, per-domain rate limits and source timestamps.

## 4. Browser automation, AI browser agents and browser tool connectors

| Tool | Repository | Role |
|---|---|---|
| Playwright | https://github.com/microsoft/playwright | Headless Chromium/Firefox/WebKit for JS sources |
| Selenium | https://github.com/SeleniumHQ/selenium | Alternative browser automation |
| Puppeteer | https://github.com/puppeteer/puppeteer | Node Chromium automation |
| chromedp | https://github.com/chromedp/chromedp | Lightweight Go Chrome automation |
| go-rod | https://github.com/go-rod/rod | Chrome DevTools-driven Go automation |
| Stagehand | https://github.com/browserbase/stagehand | AI-assisted structured browser extraction |
| Browser Use | https://github.com/browser-use/browser-use | LLM-driven browser actions, local option |
| Browser Harness | https://github.com/browser-use/browser-harness | Connect agent to existing browser |
| Skyvern | https://github.com/Skyvern-AI/skyvern | AI-guided browser flows + extraction; AGPL |
| LaVague | https://github.com/lavague-ai/LaVague | Research option for browser-driven agents; check maintenance |
| BrowserGym | https://github.com/ServiceNow/BrowserGym | Evaluate browser agents; not needed for routine fetch |
| Playwright MCP | https://github.com/microsoft/playwright-mcp | Give Codex/other agents browser actions |
| Scrapy MCP | https://scrapy.org/ | Give agents access to controlled Scrapy jobs |
| Model Context Protocol Python SDK | https://github.com/modelcontextprotocol/python-sdk | Build allowed fetch/search/source MCP adapters |
| FastMCP | https://github.com/jlowin/fastmcp | Build typed tool endpoints and wrappers |

For financial headlines, prefer deterministic HTTP fetching. **Do not** use browser agents to defeat CAPTCHAs, paywalls or anti-bot blocks. Any browser/search MCP should be sandboxed and read-only by default.

## 5. RSS, feed generation, feed discovery and feed readers

| Tool | Repository | Role |
|---|---|---|
| feedparser | https://github.com/kurtmckee/feedparser | Python RSS/Atom parsing |
| RSSHub | https://github.com/DIYgod/RSSHub | Route-based feeds for sites without standard RSS |
| RSS-Bridge | https://github.com/RSS-Bridge/rss-bridge | CSS/XPath-based feeds for sites lacking feeds |
| FreshRSS | https://github.com/FreshRSS/FreshRSS | Self-hosted feed aggregation, XPath scraping and WebSub |
| Miniflux | https://github.com/miniflux/v2 | Lightweight RSS feed consumer/API |
| Newsboat | https://github.com/newsboat/newsboat | Terminal RSS monitor |
| Tiny Tiny RSS | https://gitlab.tt-rss.org/tt-rss/tt-rss | Self-hosted feed reader; verify available licensing |
| RSS Guard | https://github.com/martinrotter/rssguard | Desktop RSS reader (not VPS ingestion core) |
| Media Cloud feed_seeker | https://github.com/mediacloud/feed_seeker | Discover RSS/Atom feeds on publisher websites |
| FeedFinder2 | https://github.com/dfm/feedfinder2 | Find RSS/Atom feed endpoints from webpage |
| Python sitemap parsing | https://github.com/mediacloud/ultimate-sitemap-parser | Discover URLs in publisher XML sitemaps |
| WebSub | https://www.w3.org/TR/websub/ | Event/push updates from supported publishers |

RSSHub and RSS-Bridge **do not automatically grant access** to restricted publisher content. They are source-to-feed convenience tools.

## 6. Monitor website changes and trigger incremental news fetching

| Tool | Repository | Useful when |
|---|---|---|
| changedetection.io | https://github.com/dgtlmoon/changedetection.io | Investor-relations pages and filing listing page changes |
| urlwatch | https://github.com/thp/urlwatch | Lightweight site text/selector change monitoring |
| webchanges | https://github.com/yvann/webchanges | URL change detection and notifications |
| Huginn | https://github.com/huginn/huginn | Multi-step site/RSS/event agents with triggers |
| FreshRSS WebSub | https://github.com/FreshRSS/FreshRSS | Near-real-time updates from compatible publishers |
| Prometheus + Alertmanager | https://github.com/prometheus/prometheus | Source health and staleness alerts |
| Grafana OSS | https://github.com/grafana/grafana | Monitor fetch success rate, lag and errors |

A *change detected* does not prove a *new report* or its publication time. Re-fetch the source and verify the original event.

## 7. Public and self-hosted search, global news indexes and archives

| Service or software | Link | What it gives |
|---|---|---|
| SearXNG | https://github.com/searxng/searxng | Open-source aggregator of public search engines; upstream limits apply |
| YaCy | https://github.com/yacy/yacy_search_server | Distributed open-source search engine |
| GDELT | https://www.gdeltproject.org/ | Free global news index and 15-min data files; API may rate-limit |
| Media Cloud | https://www.mediacloud.org/ | Searchable open-data news archive / directory; usage terms apply |
| Common Crawl | https://commoncrawl.org/ | Free bulk historical web snapshots (NOT primary breaking news source) |
| OpenSearch | https://github.com/opensearch-project/OpenSearch | Self-hosted indexing of collected records (NOT a web crawler by itself) |
| Meilisearch | https://github.com/meilisearch/meilisearch | Search collected articles/events |
| Typesense | https://github.com/typesense/typesense | Fast on-prem search for stored news |
| Apache Solr | https://github.com/apache/solr | Full-text indexing (resource-heavy for current host) |
| Qdrant | https://github.com/qdrant/qdrant | Optional semantic search over archived news |
| pgvector | https://github.com/pgvector/pgvector | PostgreSQL vector search if required |
| FAISS | https://github.com/facebookresearch/faiss | Approximate similarity for dedup (optional) |

Search engines return **leads**. Publisher URLs and timestamps are the evidence; GDELT/Media Cloud/Common Crawl coverage and timeliness vary.

## 8. Article text extraction, document and earnings PDF parsing

| Tool | Source | Main task |
|---|---|---|
| Trafilatura | https://github.com/adbar/trafilatura | Clean article main text, dates and metadata |
| newspaper4k | https://github.com/AndyTheFactory/newspaper4k | Article extraction and metadata |
| goose3 | https://github.com/goose3/goose3 | HTML article extraction |
| news-please | https://github.com/fhamborg/news-please | News crawler + metadata |
| readability-lxml | https://github.com/buriy/python-readability | Main story body |
| jusText | https://github.com/miso-belica/jusText | Remove navigation/boilerplate |
| Beautiful Soup | https://www.crummy.com/software/BeautifulSoup/ | Site-specific parsing |
| lxml / Parsel / selectolax | https://lxml.de/ ; https://github.com/scrapy/parsel ; https://github.com/rushter/selectolax | Fast HTML/DOM extraction |
| extruct | https://github.com/scrapinghub/extruct | schema.org JSON-LD/OpenGraph/microdata timestamps |
| PyMuPDF | https://github.com/pymupdf/PyMuPDF | Fast PDF text extraction |
| pypdf | https://github.com/py-pdf/pypdf | PDF metadata/text |
| pdfplumber | https://github.com/jsvine/pdfplumber | PDF table and layout extraction |
| pdfminer.six | https://github.com/pdfminer/pdfminer.six | PDF text/layout |
| Docling | https://github.com/docling-project/docling | Layout- and table-aware PDF conversion |
| MarkItDown | https://github.com/microsoft/markitdown | PDF/doc/HTML to Markdown |
| Unstructured | https://github.com/Unstructured-IO/unstructured | Partition documents into elements |
| Camelot | https://github.com/camelot-dev/camelot | Text-based PDF tables |
| Tabula (tabula-py) | https://github.com/chezou/tabula-py | PDF tables using Java backend |
| Marker | https://github.com/datalab-to/marker | Higher-quality PDF/markup conversion; expensive |
| Tesseract / OCRmyPDF | https://github.com/tesseract-ocr/tesseract ; https://github.com/ocrmypdf/OCRmyPDF | Scans only if standard text extraction fails |

Use PDF text extraction first, then tables for financial statements, and OCR only when necessary. Preserve page numbers, units, reporting period and source links.

## 9. Entity resolution, classification, duplicate detection

| Tool | Role |
|---|---|
| Pydantic / JSON Schema | Validate structured discovery payloads |
| spaCy | NER for companies, organizations and dates |
| GLiNER | Flexible named-entity recognition; model inference costs compute |
| RapidFuzz | Company-name and ticker alias matching |
| dateparser / python-dateutil | Convert timestamps/timezones safely |
| pandas / Polars | Group and compare event candidates |
| DuckDB | Lightweight local analytical joins over events |
| datasketch / MinHash | Find similar syndicated or duplicate articles |
| sentence-transformers / embeddings | Optional semantic matching; use only after simple canonical URL and hashes |
| SQLite / PostgreSQL | Upserts, unique constraints and source cursor history |

Define a verified NSE/BSE **point-in-time symbol/ISIN mapping**, and do not force uncertain matches.

## 10. Reliable automation, storage and observability

| Tool | Job |
|---|---|
| systemd timers and services | Exactly scheduled 10-minute VPS attempts |
| flock / PostgreSQL advisory lock | Ensure one ingestion cycle at a time |
| APScheduler | Python scheduling alternative |
| Celery + Redis | Asynchronous distributed jobs (overkill initially) |
| RQ | Simple Python Redis-backed queue |
| Prefect OSS | Retryable workflow automation |
| Dagster OSS | Asset-based data pipelines |
| Apache Airflow | Mature scheduler but heavyweight on 2 vCPU |
| Temporal | Durable workflows, significant setup |
| n8n | Useful self-hosted workflow tool but **source-available/fair-code**, not strictly OSI open-source |
| Activepieces | Visual self-hosted automation; inspect current license/feature tiers |
| PostgreSQL + SQLAlchemy | Canonical normalized event and provenance DB |
| SQLite WAL | Offline durable spool / initial staging |
| MinIO | Optional self-hosted raw filing/document object store |
| Prometheus + Alertmanager | Per-source failure/lag monitoring |
| Grafana OSS / Loki | Metrics and log review |
| Docker Compose | Isolated services, CPU/memory limits |

## 11. Recommended small VPS profile — do NOT deploy all catalog items

- **Always, every 10 min:** systemd + Python HTTPX/feedparser + NSE/BSE/issuer sources + Trafilatura + PostgreSQL or SQLite. Use conditional requests/cursors and log access failures. Record dedup hashes.
- **Codex independent search:** 1 CLI agent with allowed live search/MCP; do not merely summarize Python results. Budget usage per day and rotate source/sector search groups. Continue Python when out of quota.
- **Alternative search:** Gemini or another verified agent as a second independent retrieval lane on selective schedules; test genuinely unique verified events found, not article count.
- **One browser only when needed:** Playwright + Crawl4AI or Browser Use, with strict timeout/rate limits. Do not run all browser frameworks at once.
- **Incremental feed discovery:** RSSHub / RSS-Bridge for permitted no-RSS sources; changedetection.io or urlwatch for issuer IR pages.
- **Global discovery:** GDELT + SearXNG and optionally Media Cloud; confirm each original URL and timestamp. Use Common Crawl for historical audits only.
- **PDF:** PyMuPDF default; Docling/pdfplumber when table extraction required; OCR only when no readable text.
- **Database:** raw_document / news_event / event_sources / agent_discoveries / source_runs / source_cursors, with immutable as-of snapshots for 09:00 IST selection. Log every attempted URL, denied access, insert, duplicate and update.
- **Final research:** after verified 09:00 IST cutoff, a separate strong reasoning agent plus reviewer ranks up to 5 bullish / 5 bearish NIFTY 500; if weak data, output NO_TRADE. Keep all real-money execution disabled.

## 12. Implementation/testing requirements

1. Audit existing repository before installing anything.
2. Check `free -h`, `nproc`, `df -h /`, existing Docker stats and dashboard health.
3. Build Python official-feed MVP with two consecutive idempotent DB readback tests.
4. Run Codex with actual live source-access proof; log searched sites, URLs and publication timestamps, not claimed web coverage.
5. Add only ONE additional tool per source-coverage gap. Collect 10–20 minute sample metrics: unique verified events, duplication, first-availability timestamp accuracy, failures, model quota and memory.
6. Enable 10-minute systemd timer only after manual tests; verify two actual timer runs and persistent DB data.
7. Maintain original-source timestamp vs discovery timestamp. Daily trading cutoff = prior NSE session 15:00 to current day 09:00 IST, accounting for weekends/holidays.
8. Keep broker credentials and trade execution outside the collector entirely.
9. Never claim deployment until VPS logs and DB rows verify success.

## 13. Reference documentation and known status warnings

- Scrapy official: https://www.scrapy.org/
- Crawlee for Python: https://crawlee.dev/python/docs/
- Crawl4AI: https://docs.crawl4ai.com/
- RSS-Bridge: https://github.com/RSS-Bridge/rss-bridge
- RSSHub: https://github.com/DIYgod/RSSHub
- Huginn: https://github.com/huginn/huginn
- Changedetection.io: https://changedetection.io/
- Browser Use: https://github.com/browser-use/browser-use
- Skyvern: https://github.com/Skyvern-AI/skyvern
- Open Deep Research: https://www.langchain.com/blog/open-deep-research
- **AutoGen archived:** https://github.com/microsoft/autogen (Microsoft directs new users to Agent Framework)
- **Microsoft Agent Framework:** https://learn.microsoft.com/agent-framework/overview
- **OpenClaw security:** https://github.com/openclaw/openclaw/security (untrusted articles can contain prompt injection)
- Common Crawl: https://www.commoncrawl.org/
- Media Cloud: https://www.mediacloud.org/

**This catalog is intentionally broader than the deployment plan. It is NOT a command to install everything; verify maintenance and provider access before adopting any tool.**
