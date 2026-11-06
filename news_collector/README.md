# Free overnight financial-news collector (research-only)

This component checks **all 43 configured public source endpoints** (the prior 36-source live audit plus 7 official fallback endpoints), persists news linked to NIFTY 500 companies, preserves undated candidates separately, and produces source failure and coverage reports. **Not a stock-selection AI and not a trading bridge.** It does not enable live orders or overwrite existing signals.

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

Configured endpoints include previously successful, failed, blocked, stale and empty sources. Every request is a normal, unauthenticated bounded GET; no CAPTCHA, paywall or robots bypass. HTML sources require an article-local time tag for timestamp eligibility. A 200 response is not proof every filing was found. Some external publishers restrict automated access; comply with their terms and disable sources if necessary.

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
