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
