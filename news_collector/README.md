# Free overnight financial-news collector (research-only)

This component checks **all 43 configured public source endpoints** (the prior 36-source live audit plus 7 official fallback endpoints), persists news linked to NIFTY 500 companies, preserves undated candidates separately, and produces source failure and coverage reports. **Not a stock-selection AI and not a trading bridge.** It does not enable live orders or overwrite existing signals.

## Run

Python 3.11+:

    pip install -r news_collector/requirements.txt
    python -m unittest discover -s news_collector -p 'test_*.py' -v
    python -m news_collector.engine --session-date 2026-11-09

The optional --session-date specifies the target NSE session; for 2026-11-09 the window is 2026-11-06 15:00 through 2026-11-09 09:00 IST (end exclusive). A weekend-aware, **not holiday-aware**, default is supplied. Override on NSE holidays. The official NIFTY 500 constituent CSV is fetched from Nifty Indices/NSE domains; cached snapshots display an explicit stale-unknown warning. If neither is available, do not claim NIFTY 500 coverage.

Files after each poll:
- news_collector/data/YYYY-MM-DD/events.jsonl: timestamp-validated overnight source URLs matched to NIFTY 500 companies.
- news_collector/data/YYYY-MM-DD/undated_candidates.jsonl: related articles without verifiable original publication times; never promotion-eligible.
- news_collector/data/YYYY-MM-DD/coverage.json: current per-source counts, errors, and coverage warnings.
- news_collector/data/YYYY-MM-DD/polls.jsonl: collection-run log.
- news_collector/data/universe_snapshot.csv: last fetched official-format constituent CSV.

The feed stores headlines, excerpts, original URLs and dates. PDFs are linked but not automatically analyzed. Company names are matched conservatively; short symbols and aliases may be missed. "Exchange only" indicates source presence, not proof another publisher missed the event. Historical replay is not guaranteed because RSS archives are finite.

## Source policies

Configured endpoints include previously successful, failed, blocked, stale and empty sources. Every request is a normal, unauthenticated bounded GET; no CAPTCHA, paywall or robots bypass. HTML sources require an article-local time tag for timestamp eligibility. A 200 response is not proof every filing was found. Some external publishers restrict automated access; comply with their terms and disable sources if necessary.

## Automation

The scheduled research workflow on the default branch is best-effort (GitHub Actions may delay starts): 16:10, 20:10, 00:10, 04:10, 07:10, 08:35, 08:58 and 09:05 IST on weekdays, with UTC midnight boundaries. It updates the research-data directory only, not broker endpoints.

## Remaining production work

1. Stable licensed exchange feed, official NSE holiday calendar and disclosure-time provenance.
2. NSE/BSE reconciliation by ISIN, event type and original disclosure ID (current source-group comparison is only company-level).
3. Company alias matching and an accuracy/recall benchmark using manually labeled examples.
4. Continuous monitoring of source inventory, missing pages, API limits, 09:00 completeness and latency.
5. Independent, immutable pre-market snapshot for the downstream ranking model. No live trading or automatic orders are authorized.
