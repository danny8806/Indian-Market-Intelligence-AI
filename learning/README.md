# Learning loop — research only

This module grades immutable 09:00 IST research signals, retrieves unadjusted daily OHLC from Yahoo Finance after market close, and can train an **isolated challenger** when enough verified sessions accumulate. It never places orders, edits past signals, posts to the live desk, or automatically deploys a model.

## Daily pipeline

1. Read signals/archive/YYYY-MM-DD.json or signals/incoming/YYYY-MM-DD.json; reject conflicting copies and validate the original schema. If no READY signals exist, report unavailable instead of making up predictions.
2. Fetch SYMBOL.NS using yfinance with auto_adjust=False and actions=True. Require session and previous close bars, nonzero volume, consistent OHLC and no split flags or extreme unverified returns.
3. Grade each direction using daily Open and Close, with equal-weight theoretical portfolio return calculated ONLY if every selected stock has usable prices. Append frozen source hashes and prices to learning/data/trades.csv; refuse silent changes to prior records.
4. Once >=40 sessions and >=160 complete observations exist, fit a logistic regression challenger on pre-09:00 signal text, direction, rank, source count and news age. Compare with majority-rate baseline on chronological holdout using Brier score, log loss and AUC. It is NEVER automatically promoted. Experimental weights and metrics are saved as a GitHub Actions artifact only.

## How to run manually

- Install: pip install -r requirements-learning.txt
- Test: python -m unittest discover -s tests -p test_learning.py -v
- Audit: python -m learning.feedback --session-date 2026-11-05
- Train: python -m learning.train

The workflow .github/workflows/daily-learning.yml runs at approximately 18:10 Asia/Kolkata on weekdays after merging to the DEFAULT branch. GitHub scheduled workflows may be delayed or missed. A manual run is also available.

## Important limitations

- This is a **selection-audit learner only**: it learns from stocks already selected in 09:00 reports. To learn missed-news discovery, preserve the full point-in-time premarket candidate pool including rejected names before 09:00. Otherwise training suffers from selection bias.
- Yahoo Finance data is not NSE-exchange-verified. Reconcile anomalies against official NSE bhavcopy and corporate actions before trusting performance.
- Exact daily Open fills are theoretical; execution at that price is not guaranteed, especially when picking stocks based on opening gaps.
- No news is independently fetched in this module. If morning signal JSON only reaches the direct HTTPS dashboard and not this repository, the daily job will report unavailable until a separately authorized read-only integration is added. Do not assume ChatGPT scheduler data reaches GitHub.
- No broker integration, no simulated orders, no automatic live trading, and no model-weight promotion.
- A trading-holiday skip is inferred from the absence of an eligible morning signal; this workflow is not an official exchange holiday calendar.

Next steps: introduce immutable full-candidate morning data, independent NSE price reconciliation, one-year historical backfill, properly purged walk-forward validation, after-cost realistic entry testing, and explicit approval of model changes.

## Upgrade 4 — Independent all-NIFTY-500 mover coverage audit

After the official NSE regular-session close, run:

    python -m learning.mover_audit --session-date 2026-11-06

The new source reads the NSE Full Bhavcopy (single public CSV) and the official-format NIFTY 500 constituent snapshot and reports the **top 10 open-to-close gainers and losers**, gap versus previous close, and **absolute ≥2%, ≥3%, ≥5% movers**. It excludes invalid/zero-volume/anomalous prices and reports unpriced members separately. Price records describe market movement, not actual trading fills.

**Crucial missed-news safeguard:** News coverage is measured ONLY when the matching day's immutable pre-09:00 candidate_snapshot.json exists and passes validation. Without it the result is MARKET_ONLY_NO_VERIFIABLE_PREOPEN_BASELINE with percentages null, never a fake zero coverage claim. A big move with no frozen candidate is NOT proof of missed news; it may have no premarket catalyst. When available, the audit uses the constituent membership saved in the actual frozen snapshot.

For top absolute movers without a frozen candidate, the report checks archived event URLs and first-seen timestamps. Potential reasons: first discovered after 9 AM, discovered between freeze and 9 AM, present in archived premarket items but absent in the frozen candidate pool, or no matching archived event. These are collection investigation hypotheses, not causal explanations or evidence of a regulatory breach.

Outputs:

- learning/data/mover_reports/YYYY-MM-DD.json: source-linked full market audit, prices, missing or anomalous records, candidate overlap and collection-gap leads.
- learning/data/mover_reports/YYYY-MM-DD.md: simple Markdown top movers and news-coverage table.

The scheduled after-close candidate-outcome workflow now runs this audit and archives reports. It does not change stock selections, deploy model weights or submit orders. If NSE Full Bhavcopy is blocked, the report preserves an explicit failure rather than making up prices.

6 November 2026 connectivity test: 495 valid NIFTY 500 stock records, 148 moved at least 2% absolute open-to-close, 76 at least 3%, and 26 at least 5%. There was no 6 November frozen 9 AM candidate snapshot; accordingly no news-capture percentage is available.
