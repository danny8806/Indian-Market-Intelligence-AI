# Indian Market Intelligence AI — Signal Feed

Machine-readable daily **research watchlist**, published for use by a dashboard. This project **does not place orders**.

## Feed
- Latest: [signals/latest.json](signals/latest.json)
- Raw URL: https://raw.githubusercontent.com/danny8806/Indian-Market-Intelligence-AI/main/signals/latest.json
- Schema: [schema/stock-signals.schema.json](schema/stock-signals.schema.json)
- Sample input (fictional): [examples/signals.sample.json](examples/signals.sample.json)

The file contains up to five LONG and five SHORT candidates ranked by news significance and estimated **next-session open-to-close** impact. A selection is not a trade instruction. All signals include source references, event timestamps, and a fixed 09:00 IST research cutoff.

**Safety controls:** `status` must equal `READY`, `execution_enabled` is permanently `false`, today's `session_date` and `news_cutoff_at` must match, and each candidate must have a source before a dashboard displays it as actionable research. **Do not connect this JSON directly to a broker order endpoint.** Intraday shorting eligibility, position sizing, max loss, confirmation, and human/broker risk gates belong in a separate system.

## Scheduled flow
1. Existing ChatGPT task researches news from the previous trading day's 15:00 IST until 09:00 IST and produces a verified JSON report.
2. **Delivery bridge required:** that task must write `signals/incoming/YYYY-MM-DD.json` with its GitHub connector, or an external publisher must POST the verified payload via the GitHub Contents API. Connecting ChatGPT task delivery to GitHub is separate from installing this repository workflow; do not assume a report has been delivered just because a schedule exists.
3. GitHub Actions validates a newly committed incoming report (push trigger) and writes both `signals/archive/YYYY-MM-DD.json` and `signals/latest.json`.
4. A scheduled GitHub Actions fallback runs at **09:10 IST on weekdays** and writes status `UNAVAILABLE` if no verified report has arrived. GitHub scheduled runs can be delayed or missed; dashboards must independently check freshness.
5. The example Python dashboard reader rejects missing, stale, unavailable, or unsafe signals.

### Repository publish automation
[.github/workflows/publish-signals.yml](.github/workflows/publish-signals.yml) runs when an incoming file is pushed, when manually dispatched, and at the fallback time. It deliberately never manufactures bullish/bearish candidates.

### Dashboard example
```python
python dashboard/read_signals.py
```
No dependencies except Python 3.11+ standard library. This prints a JSON research watchlist if today's report is fresh, or an explicit reason to reject it.

### Manual test
Publish the fictional sample through the publisher with a real intended session date only in a test branch; **never** copy fictional stocks into the live incoming directory. For a validation-only test:
```python
python scripts/validate_signals.py --allow-sample examples/signals.sample.json
```

### External publisher
Create `signals/incoming/YYYY-MM-DD.json` on `main` via GitHub Contents API using a token limited to this repository's Contents write permission. Protect that token in a secret manager. Do not put it in a dashboard, frontend or JSON. The publish workflow validates the payload; it must contain real source-backed candidates or use `UNAVAILABLE` / `NO_TRADE`.

## Format
`schema_version: "1.0"`, `market: "NSE"`, `timezone: "Asia/Kolkata"`, `session_date: YYYY-MM-DD`, `news_cutoff_at: ISO-8601 09:00 IST`, `generated_at: ISO-8601`, `status: READY | NO_TRADE | UNAVAILABLE`, `execution_enabled: false`, `signals: []`.

Each candidate has `symbol`, `side` (`LONG` or `SHORT`), `rank` (1–5 for its side), `reason`, `sources` with URL and publication time, and optional `confidence` (null unless defensible). Only use information available by cutoff. Output can contain fewer than five positions per side.

This is an integration scaffold. Automatic delivery from ChatGPT depends on the scheduled task's GitHub tool access and successful connector writes; check GitHub Actions logs and the latest file before relying on the feed.
