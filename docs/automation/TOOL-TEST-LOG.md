# Open-source tool test log — news collector

Test date: 2026-11-10 IST. Tests ran on the 2-vCPU / 8-GB Ubuntu VPS or in
disposable local environments. No test used proxy rotation, user-agent
spoofing, CAPTCHA solving or any other access-control bypass.

This log records what was actually tested. A tool is not production
infrastructure merely because it appears in the catalog or in this file.

## Production dependencies

| Tool | Test evidence | Decision |
| --- | --- | --- |
| `requests`, `beautifulsoup4`, `pypdf`, `SQLAlchemy`, `psycopg` | Used by the deployed collector, archive sync and PDF enrichment; 130 offline tests pass | Keep |
| Custom RSS/XML parser | Parses NSE/BSE and publisher feeds; no `feedparser` dependency | Keep |
| `systemd` timers | 10-minute collector and morning timers active on the VPS | Keep |
| PostgreSQL 16 | Isolated `market_news` database; transactional batch commits and pending-batch replay | Keep |

## Probes and outcomes

| Tool | Probe | Result | Decision |
| --- | --- | --- | --- |
| `pypdf` | Extract text from an 8.9-MB NSE PDF | 25,393 characters in 0.39 s | Keep (already deployed) |
| `pdfplumber` | Same PDF | 25,358 characters, 0 tables, 0 errors, 0.85 s | Reject: negligible text gain, slower, no table benefit on this document |
| `trafilatura` / `readability` | Extract article text and metadata from Mint, Business Standard and NDTV Profit | Text and titles extracted; Mint and Business Standard expose exact `article:published_time`; NDTV Profit returned HTTP 403 | Candidate only; not added to production requirements |
| Playwright | Load `https://www.5paisa.com/news/stocks` in a headless browser | Browser started and rendered, but the site returned HTTP 403 and exposed zero article links | Reject for 5paisa; not installed in production |
| RapidFuzz | Cluster 80 real collected headlines | 49 clusters, 16 multi-item clusters, 0.0006 s; clusters were mostly repeated exchange names/headlines | Reject: deterministic URL/event fingerprints already cover the useful duplicate cases |
| `urlwatch` 2.29 | Two passes over 10 robots-allowed public pages on the VPS | Pass 1: 10 `NEW`, 0 errors, 2.61 s. Pass 2: 3 `CHANGED`, 0 errors, 1.76 s. Cache: 1,261,568 bytes, 10 GUIDs | Reject as-is: whole-page `html2text` includes volatile scripts/session data, so 3 pages changed within seconds. Production use needs per-page selectors and change thresholds |
| GDELT DOC API | Collector request with a 7-second read timeout | `ReadTimeout` | Source remains disabled; do not claim it works |
| `changedetection.io`, `SearXNG`, `RSSHub`, `RSS-Bridge`, `Scrapy`, `Crawl4AI`, `Docling`, `MarkItDown`, `PyMuPDF`, Browser Use, Stagehand, n8n, Playwright MCP, Fetch MCP | Not tested on the VPS in this batch | Not installed. Each needs a controlled test, a concrete coverage gap, and measured CPU/RAM before adoption |

## Source-access probes

- The enabled collector list contains 98 unique sources. Current source-state
  totals after the 18:20 IST batch are 73 `OK`, 9 `EMPTY`, 6 `ERROR`,
  3 `BLOCKED_ROBOTS`, 7 `SKIPPED_COST_GUARD`, 4 `SKIPPED_NO_KEY`,
  1 `VERIFIED` (Codex) and 1 `QUOTA_LIMIT` (OpenCode).
  Codex recorded `VERIFIED` at 18:06 IST with two NSE filing URLs after a real
  `web_search` event. Both URLs had already been collected by Python at
  17:10/17:20 IST, so this proves live retrieval but not new coverage.
  OpenCode recorded `QUOTA_LIMIT`; no bypass was attempted.
- Provenance is write-once. A later lane that re-observes an existing URL is
  retained in `news_article_revisions`; it cannot rewrite the article-level
  `discoverer`. A regression test covers this. The two rows Codex re-observed
  remain `discoverer=python`, matching their earliest revisions at 17:10/17:20
  IST; Codex remains recorded at 18:06 in revision evidence.
- News18 Business listing cards returned 16 article links with robots
  permission. Publisher verification runs only in the 08:40–09:00 premarket
  window, capped at two article fetches per source per run. Outside that
  window, undated listing cards stay discovery-only and are not written as
  signals. A sampled article exposed `2026-11-10T16:02:46+05:30` in the direct
  verifier probe.
- Business Standard's BSE-announcement listing fallback returned one unrelated
  article link, so that source keeps its existing empty status instead of
  enabling the fallback.
- DGFT returned HTTP 403 from the VPS while locally returning HTTP 200; it
  stays disabled. MCA, FDA, several issuer IR pages, Financial Express, NDTV
  Profit, Reuters India, Angel One, HDFC Securities and ICICI Direct remain
  blocked or registry-only for the reasons recorded in
  `news_collector/source_registry.json`.

## Morning verifier dry run

- Ran `verify-morning-report.sh 2026-11-11` against an empty report table on
  2026-11-10 18:28 IST. The first run failed at the signal query because
  `'signal|' || s->>'side'` parses as `('signal|' || s) ->> 'side'` in
  PostgreSQL. The query now wraps each JSON extraction in `coalesce(...)`; the
  fixed script exits 0 with zero rows and is deployed in ops-only release
  `d2c8700`. The deployed Python tree is byte-identical to `69395c5`.

## AI-agent lanes

| Lane | Current evidence | Status |
| --- | --- | --- |
| Codex CLI | Passed the `web_search` event gate and returned `VERIFIED` with two NSE filing URLs at 18:06 IST. Both URLs had already been collected by Python at 17:10/17:20 IST | Live retrieval proven; no unique coverage demonstrated yet |
| OpenCode | Free-model quota exhausted until 2026-11-11 05:30 IST; logs show `QUOTA_LIMIT`/`SKIPPED_BUDGET` | No proven live retrieval |
| Gemini, Qwen, Claude, Copilot, Ollama | No verified authentication, installed binary or live-search evidence in the collector | Not configured |

The audited `agent_intake.py` inbox remains the safe path for externally
authenticated agents. A model response without a retrievable URL and a
recorded retrieval event is not accepted as live evidence.

## Evidence files

- `docs/automation/evidence/urlwatch-2026-11-10.json` — hash-only urlwatch
  cache and pass metadata. No page content is stored.
- `docs/automation/evidence/codex-live-retrieval-2026-11-10.json` — Codex
  `VERIFIED` status, the two NSE URLs, full revision-lane history and the
  OpenCode `QUOTA_LIMIT` state, read back from PostgreSQL.
- `docs/automation/evidence/morning-verifier-dry-run-2026-11-10.txt` — output
  of the fixed 09:12 verifier against the empty 2026-11-11 report, including
  zero signal/late-evidence counts and the active timer state.
- `news_collector/source_registry.json` — per-endpoint access evidence and
  reasons for blocked or registry-only entries.
- `docs/automation/FREE-TOOLS-NEWS-COLLECTOR-MORNING-PLAN.md` — full catalog
  and acceptance criteria.
