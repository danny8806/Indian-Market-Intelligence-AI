# Section-9 data-field map

Audit date: 2026-11-10 IST. This maps the required data-record fields from
`START-HERE-OTHER-AI-HANDOFF.md` section 4/9 to the current implementation.
It records gaps instead of claiming they are already satisfied.

The additive columns below were deployed in release `974b806` on 2026-11-10
16:41 IST. The one-time backfill updated 1,725 of 3,524 existing rows; columns
were added idempotently and no article ID was duplicated. The running release
reads `974b806`.

| Required field | Current storage | Status |
| --- | --- | --- |
| Verified company | `news_article_symbols.symbol`, `news_articles.symbols`, plus `news_articles.company_name` when exactly one NIFTY/BSE issuer is resolved | Present for single-issuer records; multi-symbol media records keep symbols only |
| NSE/BSE symbol | `news_articles.symbols` JSON and `news_article_symbols` | Present |
| Event category | `news_articles.category`, computed by `news_collector/classification.py` from the same deterministic rules used for reconciliation | Present |
| Headline | `news_articles.headline` | Present |
| Numbers / financial figures | `news_articles.financial_figures` JSON exists, but current feeds do not supply structured figures; PDF enrichment still writes `financial_context_lines` only to `data/<session>/pdf_extraction.jsonl` | **Gap**: schema ready, enrichment write-back not wired |
| Primary URL | `news_articles.url`; revisions keep the URL in evidence | Present |
| Source name | `news_articles.sources`, `news_source_checks.source`, `news_raw_documents.source` | Present |
| Original publication timestamp with timezone | `news_articles.published_at` (timestamptz) and `news_article_revisions.published_at` | Present when a real feed timestamp exists; never substituted with fetch time |
| Publication-time verification method | `news_articles.verification_method`: `official_exchange_feed_timestamp`, `verified_publisher_page_timestamp`, `source_feed_timestamp` or `unverified_no_publication_time` | Present |
| First public availability timestamp | `news_articles.first_seen_at` is the first collector observation, not a publisher-declared first-availability time | Partial: only first observed time is available |
| Fetch timestamp | `news_articles.first_seen_at` / `last_seen_at`, `news_source_checks.checked_at`, `news_raw_documents.captured_at` | Present |
| Updates / corrections | `news_article_revisions` (append-only, unique by article + evidence) | Present |
| Sentiment (including mixed/unclear) | `news_articles.sentiment` and `sentiment_score`; `BULLISH`, `BEARISH`, `MIXED` or `UNCLEAR` | Present as a deterministic headline reading, not a model prediction |
| Confidence | Morning signal JSON only | Partial |
| Discovery agent/tool | `news_articles.discoverer`; also retained in revision evidence | Present |
| HTTP / retrieval status | `news_source_checks.status` and `error`; raw-document details JSON | Present |
| Idempotency key | `news_articles.id` (URL/source/filing hash), `news_archive_batches.batch_id`, revision id | Present |
| ISIN | `news_articles.isin` when an upstream item supplies it; the NSE equity master currently keeps symbol/name only | Partial: column ready, feed/universe mapping not yet wired |

## Deliberate non-gaps

- Unknown publication times are stored as `published_at = NULL` with
  `record_kind = discovery_only`; they are never promoted from fetch time.
- Approved source access evidence for blocked/not-found endpoints lives in
  `news_collector/source_registry.json`, not in the article table.
- Category and sentiment are keyword-derived and can be revised by a later
  backfill; revisions preserve prior classifications through the evidence rows.

## Remaining migration

`financial_figures` write-back from PDF enrichment and ISIN population from the
NSE master remain open. Both need a separately tested enrich-to-DB path; neither
is allowed to guess a missing value.
