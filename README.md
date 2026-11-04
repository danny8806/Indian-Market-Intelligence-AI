# Indian Market Intelligence AI — Signal Feed

## Live Kotak Neo Dashboard (no simulated execution)

The new [**live-only Kotak Neo trading dashboard**](live_desk/README.md) consumes this repository's exact v1.0 news-signal contract through the authenticated **direct HTTPS API bridge**, uses read-only Dhan market data for fresh market prices, and shows actual Kotak Neo broker orders, positions and reported fills. There is no local stock-prediction model, no paper trading engine and no synthetic order P&L in the live package.

**Important:** This source-code integration is not a deployed trading service. The committed Docker configuration keeps `LIVE_ORDERS_ALLOWED=NO`. Real-money execution must not be enabled until Kotak/Dhan account credentials, current NSE instrument mappings, Dhan 09:15 bar timestamps, risk controls, broker order reconciliation, network loss behavior, cloud hosting and authorized signal delivery are verified end-to-end.

Use `python -m live_desk.app` after installing `requirements-live.txt` and configuring a private environment; see [live_desk/README.md](live_desk/README.md). The existing signal validation and research workflow remain independent of broker execution.


> **Direct API integration available:** Use [bridge/README.md](bridge/README.md) to send complete research-signal JSON over authenticated HTTPS directly to your dashboard's FastAPI receiver. GitHub is only a source-code host in this mode; no signal-file polling is needed. The bridge receiver/sender and CI tests are implemented, but no public deployment or automatic ChatGPT-to-API delivery has yet been verified.


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

## Direct signal API bridge

`bridge/app.py` adds a second delivery route while preserving the exact v1.0 JSON contract. It accepts `POST /api/v1/signals/incoming` with `Authorization: Bearer <SIGNAL_BRIDGE_TOKEN>`, `Idempotency-Key: <unique-session-key>` and `Content-Type: application/json`. The body is the full report object, not a list of tickers. It checks the existing validator, current IST session, 09:00 cutoff, and a 09:14 IST arrival deadline for `READY`. It stores the original validated payload once per session. Identical retries return `DUPLICATE`; conflicting content returns HTTP 409. `GET /api/v1/signals/latest` and `/api/v1/signals/status` require the same bearer token and return only today's report. `/api/v1/health` is unauthenticated and contains no signal data.

Install `requirements-bridge.txt`, configure `SIGNAL_DATABASE_URL` and a random 32+ character `SIGNAL_BRIDGE_TOKEN` in a secret manager, then run `python -m bridge.app`. The default bind address is `127.0.0.1:8000`. To receive requests from a cloud ChatGPT scheduled task, deploy behind HTTPS, authentication, rate limits and a stable hostname. A local-only address cannot be reached by a cloud task. Never paste the bearer token into a public repository, signal JSON, or frontend.

The ChatGPT schedule must produce the same v1.0 payload, then use an available authorized HTTP action to POST it. The schedule's ability to perform that POST has **not** been verified. If its tools cannot call this endpoint, keep the existing GitHub incoming-file delivery and let a separate trusted integration service relay the validated report. Check the task's actual run and the bridge's `ACCEPTED` response; a scheduled run by itself is not proof of delivery. See [official OpenAI Scheduled tasks documentation](https://learn.chatgpt.com/docs/automations) for task execution boundaries.

The bridge does not place orders. The new `live/orb.py` calls Dhan's one-minute intraday endpoint for the 09:15 candle; its epoch timestamp convention must be audited against a real response before use. `live/kotak_orders.py` holds the Kotak Neo live order boundary and requires an external risk approval, exact mapped `pTrdSymbol`, whole-share quantity and unique tag. Account authentication, live price feed, order reconciliation and a complete execution service remain to be built. No paper trade or simulated market feed is used by these modules.
