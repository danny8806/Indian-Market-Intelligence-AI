# Free overnight financial-news collector (research-only)

This component checks **all configured public source endpoints** in `sources.json`, persists news linked to NIFTY 500 companies, preserves undated candidates separately, and produces source failure and coverage reports. **Not a stock-selection AI and not a trading bridge.** It does not enable live orders or overwrite existing signals.

## Run

Python 3.11+:

    pip install -r news_collector/requirements.txt
    python -m unittest discover -s news_collector -p 'test_*.py' -v
    python -m news_collector.engine --session-date 2026-11-09
    python -m news_collector.enrich --session-date 2026-11-09 --max-docs 20

The optional --session-date specifies the target NSE session; for 2026-11-09 the window is 2026-11-06 15:00 through 2026-11-09 09:00 IST (end exclusive). The default skips weekends and the **verified NSE 2026 regular-session holiday dates** (including 10 November 2026); it does not treat exceptional Muhurat trading as a regular cash session. Update the calendar for 2027 or exchange changes. The official NIFTY 500 constituent CSV is fetched from Nifty Indices/NSE domains; cached snapshots display an explicit stale-unknown warning. If neither is available, do not claim NIFTY 500 coverage.

Files after each poll:
- news_collector/data/YYYY-MM-DD/events.jsonl: timestamp-validated overnight source URLs matched to NIFTY 500 companies.
- news_collector/data/YYYY-MM-DD/undated_candidates.jsonl: related articles without verifiable original publication times; never promotion-eligible.
- news_collector/data/YYYY-MM-DD/coverage.json: current per-source counts, errors, and coverage warnings.
- news_collector/data/YYYY-MM-DD/polls.jsonl: collection-run log.
- news_collector/data/YYYY-MM-DD/pdf_extraction.jsonl: bounded original NSE/BSE PDF text snippets, document hashes, failures and retry counters.
- news_collector/data/YYYY-MM-DD/enrichment_summary.json: PDF count, backlog, extraction result and 09:00 discovery provenance.
- news_collector/data/YYYY-MM-DD/source_gap_audit.json: company+material-event category matching and URL overlap across official main/mirror feeds. All unmatched entries are **investigation candidates, not confirmed missed disclosures**.
- news_collector/data/universe_snapshot.csv: last fetched official-format constituent CSV.

The feed stores headlines, excerpts, original URLs and dates. The enrichment stage downloads a **bounded subset of public official NSE/BSE PDFs**, extracts searchable text with free pypdf, stores short excerpts, financial context lines and SHA256 provenance (not full PDF text or PDF bytes), and logs inaccessible, encrypted, scanned, oversize and invalid downloads. It processes up to **20 additional PDFs per scheduled poll**; an initial backlog may remain. Company names are matched using exact official constituent names, explicit ticker syntax and conservative curated aliases from aliases.json. "Exchange only" indicates source presence, not proof another publisher missed the event. Historical replay is not guaranteed because RSS archives are finite.

## Source policies

Configured endpoints include previously successful, failed, blocked, stale and empty sources. Every request is a normal, unauthenticated bounded GET; no CAPTCHA, paywall or robots bypass. HTML sources require an article-local time tag for timestamp eligibility, except an explicitly configured `html_table` source whose own timestamp column is parsed. A 200 response is not proof every filing was found. Some external publishers restrict automated access; comply with their terms and disable sources if necessary.

## Official/issuer source registry

`source_registry.json` is the auditable master catalog for official and issuer endpoints. It records the URL, access status, last probe result, HTTP status, parsed item count, whether the endpoint is polled, and the reason an endpoint is not active. `sources.json` remains the enabled poll list.

Validate the two files together:

    python -m news_collector.source_registry --check

The check is also run during Docker image construction and again before the VPS activation script performs its collection smoke test. It fails closed when an ACTIVE registry entry has no enabled poll source, when URLs disagree, when a blocked/not-found endpoint is enabled, or when an enabled official source is missing from the registry. The image build and deployment therefore cannot silently activate an unverified endpoint.

Verified additions in this release:

- NSE insider trading, circulars, SAST Regulation 29/31, voting results, daily buyback, related-party transactions, investor complaints, unitholding patterns and statement-of-deviation RSS feeds. Each returned dated items in a direct collector-parser probe; the publication time comes from the feed, never from fetch time.
- DGFT notifications via an explicitly configured `html_table` parser. The table's hidden `CRT DT` value supplies the full date and time; date-only values remain unverified.

Retired from active polling after repeated empty/404 results and retained in the registry with evidence: NSE announcements HTML, BSE announcements HTML, RBI releases HTML and the SEBI press-release HTML URL. Their official RSS/table equivalents remain active.

Recorded as unavailable without bypass: MCA returns HTTP 403; US FDA returns an abuse-detection 404 to the collector user agent (a browser user agent returning 200 is not authorization); TCS, Infosys, Tata Motors, Dr Reddy's and HUL return 403; Maruti, Bajaj Finserv and Asian Paints returned 404. CCI orders are behind an interactive search form; CDSCO release dates are date-only; MoD pages expose no dated list; several issuer IR pages are navigation shells. These stay `REGISTRY_ONLY`, `BLOCKED` or `NOT_FOUND` and are not polled. The issuer catalog is partial and grows only from observed access evidence, not from assumptions.

## Automation

The scheduled research workflow on the default branch is best-effort (GitHub Actions may delay starts): 16:10, 20:10, 00:10, 04:10, 07:10, 08:35, 08:58 and 09:05 IST on weekdays, with UTC midnight boundaries. After regular news collection it performs bounded PDF enrichment and source-gap auditing. It updates the research-data directory only, not broker endpoints.

## Remaining production work

1. Stable licensed exchange feed, future-year NSE holiday updates and disclosure-time provenance.
2. Exact NSE/BSE reconciliation by ISIN and original disclosure ID: current upgrade compares company + material event category and exact feed URLs; different documents in the same category are NOT certified as the same event.
3. Extend and test manually curated company aliases and BSE scrip-code/ISIN mapping against labeled false positives and false negatives; current matching is conservative and may miss media nicknames.
4. Continuous monitoring of source inventory, missing pages, API limits, 09:00 completeness and latency.
5. Independent, immutable pre-market snapshot for the downstream ranking model. No live trading or automatic orders are authorized.

## Upgrade 3 — Structured reported financial evidence & pre-open training pool

The free **financial_facts.py** extractor reads a small, bounded evidence sample from PDF extraction records. It only records explicit YoY or QoQ percent assertions attached to named financial metrics (revenue, EBITDA, PAT, order book). An unlabeled table is not treated as a comparable financial result. Each numeric assertion includes the original source URL, PDF SHA256, reported period if visible, verbatim short evidence text and a flag indicating manual arithmetic verification is outstanding. Positive/negative evidence summaries describe *reported financial change*, not expected stock-price direction.

Run `python -m news_collector.candidates --session-date 2026-11-09` to build a **research-only preview** from all eligible NIFTY 500 news candidates and PDFs actually processed before the specified as-of time. A run after 09:00 marks that preview `POST_CUTOFF_RESEARCH_PREVIEW_NOT_TRAINABLE`.

A separate create-only workflow at 08:55 and 08:58 IST attempts to write `candidate_snapshot.json` once, only if it runs between **08:50 and 09:00**, has a fresh (no older than 15 minutes) official-source inventory, and knows the genuine first-seen and PDF extraction times. **No retroactive snapshot is permitted.** GitHub scheduled jobs can run late, in which case training for that session must be skipped rather than reconstructed from closing prices. The 08:48 source collection is intended to improve freshness but does not guarantee complete news coverage through 09:00.

The independent **learning/candidate_outcomes.py** script waits until the NSE session is complete, reads only a frozen pre-09:00 snapshot, and labels **all candidates** with unadjusted open-to-close moves from the public NSE Full Bhavcopy CSV (or a caller-supplied OHLCV file). If any selected security is missing, it logs a partial diagnostic and **writes zero training rows** for that date, avoiding a biased selected subset. Exchange CSV availability and corporate actions can still block reliable labels; the system does not guarantee opening fills, short-sale eligibility, or broker P&L.

**learning/train_candidates.py** fits an independent, nondeployed logistic-regression challenger only after >=40 complete sessions and >=250 labeled observations exist. It uses a strictly chronological holdout and compares Brier score with a constant-rate baseline. Its weights/metrics are only GitHub Actions research artifacts; it neither changes the 09:00 stock selections nor sends orders. No trained accuracy is claimed until enough days have been observed and tested.

### Read-only quick commands

```
python -m news_collector.candidates --session-date 2026-11-09
python -m unittest discover -s news_collector -p 'test_*.py' -v
python -m unittest discover -s learning -p test_candidate_learning.py -v
python -m learning.candidate_outcomes --session-date 2026-11-09
python -m learning.train_candidates
```

The outcome command above will correctly refuse to label a future or unfinished session or a session without a genuine frozen snapshot. No automatic live orders are enabled.


## Added discovery: announcement-aggregator search indexes (optional)

The original **43** public endpoints are preserved. This extension adds **8**
separate discovery paths for **BazaarWatch, ALFA Finder, PatternsRadar and
ResultKal**: four free Google News site-search RSS queries and four optional
Serper Google-search queries. These are *search-indexed leads*, not direct
publisher scrapers or licensed exchange-feed replacements.

- The Google News site queries work without a key when indexed results exist.
  Search-index `pubDate` is intentionally **not accepted** as the underlying
  exchange/publisher disclosure time, including for the original broad Google
  News RSS feed. Such leads remain in `undated_candidates.jsonl` until
  independently verified from a permitted original source.
- The Serper sources use `SERPER_API_KEY` from the environment. If unset, they
  show `SKIPPED_NO_KEY` in `coverage.json`, not a false successful poll.
  Requests use the search endpoint only; no aggregator site is crawled and
  result domains are allowlisted.
- Additional results do **not** change trade signals or the candidate freeze
  until an independently verified publication timestamp and NIFTY 500 issuer
  match are available. Search snippets may contain errors and should not be
  treated as official disclosure evidence.
- Publisher crawling, article-body ingestion, reuse, and redistribution must
  follow each source's terms and permissions. A Google-indexed link does not
  grant rights to scrape the destination page.
- The free index may omit some or all aggregator articles. It is a coverage
  experiment, not an assurance that the eight added paths find eight unique
  classes of announcements.

For optional Serper testing, set `SERPER_API_KEY` as a repository Actions
secret and expose it to **the read-only overnight collector job only** as an
environment variable. Keep secrets out of commits and job logs. Without the
key, the four RSS index feeds remain usable, subject to availability.

The following never occur in this extension: order placement, Kotak token
access, account access, enabling automated trading, or modifying the published
`signals/latest.json`.


## Cross-repository source-method audit and reuse (10 November 2026)

Reviewed all 30 accessible account repositories by name and the tree/source
code of related projects. The reusable collectors were:

- **Indian-Market-Intelligence:** official RBI, PIB, TRAI, US Fed and ECB
  catalogs; bounded XML recovery; transient network retry; source permission
  gates; explicit global-news discovery timestamps. Eight official/global
  sources are added from its catalog and share the existing bounded worker pool.
- **StockSenseAI:** simple `requests` + RSS parsing + per-source fetch health.
  The main collector already had equivalent RSS and `coverage.json` health
  accounting, so its five sources were not added again as duplicates.
- **Kotak-Neo-Algo:** ISIN cross-check and complete NSE/BSE announcements
  pagination. Its direct exchange APIs are **not imported** without verified
  permission/entitlement, and broker/trading calls are never reused. Existing
  symbol matching is tightened to avoid nested legal-name false positives.

### New source and provenance behavior

- Adds RBI press releases, notifications and speeches; TRAI RSS; PIB English
  releases; U.S. Fed and ECB press releases; GDELT global article-index RSS.
  The exact URLs and publisher attribution requirements are retained in
  `sources.json`. Publisher-site restricted feeds are not newly enabled.
- Macro/regulatory announcements that do not name a NIFTY 500 company are saved
  separately in `macro_context.jsonl`, *only when the original feed offers a
  parseable timezone-aware timestamp inside the session window*. They are not
  automatically assigned a stock or direction and do not enter trading signals.
- GDELT global RSS and Google News RSS are search/discovery indexes:
  their timestamps are not treated as original company announcements.
- Transient network failures and HTTP 408/429/5xx may retry up to twice
  **only** for newly configured feeds. HTTP 403/401 and other permanent errors
  are never retried as a workaround.
- NSE RSS truncation may recover only complete `<item>` elements when the XML
  is cut at EOF; malformed interior XML remains an error. Original raw source
  provenance and time validation remain required.
- If an official filing headline contains nested company names, the more
  specific matching legal name is favored. This does not replace a genuine
  ISIN/event-ID reconciliation and is not a complete issuer guarantee.

Run the offline regression suite:

```sh
python -m pip install -r news_collector/requirements.txt
python -m unittest discover -s news_collector -p 'test_*.py' -v
```

Review `coverage.json`, `macro_context.jsonl`, and `source_gap_audit.json`
for source-level success, failures and unmatched evidence. No claim of
all-source completeness is made, and no automatic live orders are enabled.


## Multi-source discovery expansion — 10 November 2026

The catalog now includes **80 configured endpoints/adapters** (including the
original feeds, exchange mirrors, regulator/macro sources, Google News
site-specific discovery, and seven credentialed provider adapters). Catalog
count is NOT a measure of successful, authorized or unique stories.

### Free/public methods
- Official NIFTY 500 constituent CSV; NSE/BSE public feeds where permissible.
- RBI, SEBI, TRAI, PIB, Federal Reserve, ECB official RSS.
- Zerodha Pulse, other public media RSS where permitted.
- Google News RSS plus ten publisher-specific site searches (Moneycontrol,
  Reuters, NDTV Profit, CNBC-TV18, ET, Business Standard, Financial Express,
  Trendlyne, Mint and Business Today); all are **discovery-only**.
- GDELT article listings, source-gap reports, bounded official PDF parsing,
  conservative ticker mapping, provenance tracking and nightly research output.

### Optional API discovery (never automatically buys credits)
Configure desired API keys as GitHub Actions repository **secrets**:
`SERPER_API_KEY` (existing aggregator search),
`TAVILY_API_KEY`, `EXA_API_KEY`, `BRAVE_SEARCH_API_KEY`,
`MARKETAUX_API_TOKEN`, `GNEWS_API_KEY`,
`NEWSDATA_API_KEY` and `NEWSAPI_API_KEY`.

For the seven new providers, additionally set a repository Actions **variable**
`ENABLE_PAID_NEWS_APIS=true`. By default these report
`SKIPPED_COST_GUARD`. When opted in, missing individual keys show
`SKIPPED_NO_KEY`; no external request is made for those providers.
The optional Serper aggregator sources continue to use their separately
configured `SERPER_API_KEY` gate. Each enabled provider makes one bounded
search request per collector poll; check plan quotas and GitHub schedule rates
before opting in. The connector never logs API tokens or retains returned
full page text.

Provider APIs: Tavily Search, Exa Search, Brave News Search, Marketaux Finance
News, GNews Search, NewsData Latest and NewsAPI Everything. All API responses
are treated as **unverified discovery metadata** even if they include a
`publishedAt` field. API-record snippets and URLs are saved as *undated
candidates* until a permitted original publisher/official disclosure provides
a verified publication timestamp. Some free APIs delay news for 12–24 hours;
they must NOT be relied on for 9 AM trading selection.

### Permissions / data quality
- Index appearance is not evidence of original publication time.
- A blocked news publisher does not grant crawling rights through a search
  service; this project only keeps search-index leads and does not fetch
  restricted page bodies.
- Public or official endpoints may also impose contractual limits on
  automated polling/retention. Sources requiring permission must remain
  unavailable for production use until approved, licensed or otherwise cleared.
- No paywall/CAPTCHA bypass, no orders, no broker account credentials, no
  unverified data promoted into `signals/latest.json`.
- The audited `agent_intake.py` inbox accepts a `gemini` report, but the lane is
  **not configured** until Gemini CLI authentication and a real `web_search` or
  `web_fetch` trace are verified on the VPS. A report without tool evidence and
  HTTPS URLs is rejected; the pipeline does not install unauthenticated CLIs or
  treat model output as live retrieval.
- `events.jsonl` contains NIFTY 500 matches with parseable original feed time;
  `undated_candidates.jsonl` contains discovery leads not eligible for trades;
  `macro_context.jsonl` contains unmatched regulator/macro items with feed
  time, not direct stock signals.
- Inspect `coverage.json` and `source_gap_audit.json` after each run; a
  200/OK response is not proof a source delivered all available documents.

Run local tests:
```sh
python -m pip install -r news_collector/requirements.txt
python -m unittest discover -s news_collector -p 'test_*.py' -v
```
