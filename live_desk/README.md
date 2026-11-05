# Kotak Neo — Live News Trading Terminal

**LIVE-ONLY service.** This package contains **no paper execution engine, no simulated fills, no model-generated trades, and no synthetic portfolio history**. Kotak Neo's order, trade and position reports are the authoritative source for executed activity.

## Project layout

| Path | Role |
|---|---|
| `live_desk/app.py` | Authenticated FastAPI terminal + direct JSON signal receiver |
| `live_desk/supervisor.py` | Broker login, research intake, Dhan feed, monitoring and risk gates |
| `live_desk/kotak_gateway.py` | Kotak Neo v3 login, MIS market-order boundary and reconciliation |
| `live_desk/ledger.py` | Durable broker order intent lifecycle (not a simulated trade ledger) |
| `live_desk/runtime.py` | Fresh-tick 09:15 one-minute ORB breakout coordinator |
| `live_desk/dhan_data.py`, `ticker.py` | Read-only Dhan NSE data and live tick stream |
| `live_desk/broker_view.py` | Sanitize real Kotak Neo orders, positions and fills |
| `live_desk/static/` | Secure live-only browser dashboard |
| `live_desk/policy.json` | Read-only risk configuration; timestamp mode deliberately unset |
| `tests/test_live_kotak_terminal.py` | Broker API boundary and fail-closed mock tests |

## Source of trading signals

The existing direct API bridge accepts a validated daily research JSON through:

`POST /api/v1/signals/incoming`

Only a current-session `READY` report received after 09:00 IST and before 09:14 IST is eligible for the research intake. The report selects up to five LONG and five SHORT symbols. This report is **not itself an order instruction**. No trained prediction-model artifacts or static stock lists are used.

A signal-producing service must POST the JSON to the deployed HTTPS endpoint using the bridge's Bearer token and Idempotency-Key. **The existing ChatGPT scheduled research task is not yet proven to call a custom HTTPS endpoint.** Do not treat research scheduling as proof that the dashboard received signals. The receiver only consumes reports actually delivered.

## Live trading rule already ported from Sniper

- Evaluate the first completed 09:15 one-minute Dhan equity candle.
- LONG: actual fresh tick crosses above that candle's high.
- SHORT: actual fresh tick crosses below that candle's low.
- Current config: entry cutoff 10:00 IST, exit time 15:15 IST.
- At most 5 LONG and 5 SHORT, ₹1 lakh intended allocation each, ₹10 lakh gross cap.
- No duplicate entry order per symbol per session.
- Ledger persists each order intent before sending it to Kotak and reconciles with real order/trade reports.
- Orders are market-order MIS using official `nse_cm` symbol mapping. Broker confirmation—not a Dhan tick—sets filled quantities and prices.
- Daily gross loss gate (default ₹10,000) blocks new entries. Positions follow the configured 15:15 IST square-off; there is no implicit 2% tick stop. This is not a broker-native protective stop, so a feed outage, software crash or exchange gap can leave a real position exposed. Verify exit and recovery behavior before enabling unattended real-money trading.

These are engineering defaults inherited from the source project's live logic, not independently verified profitable trading rules.

## Install locally (read-only and disarmed by default)

1. Use Python 3.11+.
2. `python -m pip install -r requirements-live.txt`
3. Set private environment values:

```text
SIGNAL_DATABASE_URL=sqlite:////absolute/private/path/signals.db
SIGNAL_BRIDGE_TOKEN=<private random 32+ char token>
DASHBOARD_PASSWORD=<unique long password>
DASHBOARD_SESSION_SECRET=<different 32+ char secret>
DASHBOARD_COOKIE_SECURE=false  # local HTTP development ONLY
LIVE_KOTAK_LEDGER_DB=/absolute/private/path/live-orders.db
LIVE_ORDERS_ALLOWED=NO
KOTAK_NEO_CONSUMER_KEY=
KOTAK_NEO_MOBILE_NUMBER=
KOTAK_NEO_UCC=
KOTAK_NEO_MPIN=
KOTAK_NEO_TOTP_SECRET=
DHAN_CLIENT_ID=
DHAN_PIN=
DHAN_TOTP_SECRET=
LIVE_ARM_TOTP_SECRET=
```

4. Run `python -m live_desk.app`; open `http://127.0.0.1:8010` on the same computer.
5. The API and UI share one server and database. The browser requires dashboard login. Signal ingestion requires a different token.
6. Run `docker compose -f live_desk/compose.yaml up -d --build` to start the loopback-bound container. It is purposely not publicly exposed.

For a cloud VPS: deploy behind HTTPS, use a managed secret store, persistent encrypted database and backups, stable clock, restricted network access, alerts, independent broker position reconciliation, and a single active supervisor process. Set `DASHBOARD_COOKIE_SECURE=true` in production and configure `DASHBOARD_PUBLIC_ORIGIN=https://your-domain.example` to validate cross-site request origin through a TLS reverse proxy. Never put Kotak MPIN/TOTP seeds into GitHub code, CI logs, ChatGPT or the browser.

## Default safety locks

**No real orders are enabled in the committed configuration.**

- `LIVE_ORDERS_ALLOWED=NO` in Compose; real order arming is disabled.
- `policy.json` has `dhan_candle_timestamp_mode: null`. Confirm the actual Dhan bar timestamp convention against an exchange-session response before changing to `start` or `end`.
- Without authentic Kotak Neo and Dhan credentials, the service shows unavailable broker/data state.
- Invalid/missing news, wrong-day tick data, stale broker books, unresolved symbols, insufficient funds, unknown order submissions, failed fill reconciliation and negative daily gross MTM risk block new orders.
- Browser arming also requires authenticated login, a same-origin request, exact real-money acknowledgement phrase, and a separate six-digit operator TOTP. Arming never persists over a process restart or new trading day.
- Real orders, even exits, must never be triggered by historical or fabricated prices. The supervisor validates broker-reported position quantities before selecting session exits.
- Only a human-controlled, fully reviewed change to production configuration can lift the default execution lock, and only after account-specific risk and exit tests are complete.

## API routes

| Endpoint | Access | Result |
|---|---|---|
| `POST /api/v1/signals/incoming` | Signal producer Bearer + idempotency | Immutable verified source JSON |
| `GET /api/state` | Dashboard cookie | Live broker and signal snapshot |
| `GET /api/live/positions` | Dashboard cookie | Actual Kotak positions only |
| `GET /api/live/orders` | Dashboard cookie | Kotak order report only |
| `GET /api/live/fills` | Dashboard cookie | Kotak trade report only |
| `POST /api/live/arm` | Cookie, same-origin, exact phrase and operator TOTP | Requires separate live-trading authorization gate |
| `POST /api/live/disarm` | Cookie + same-origin | Disables new entries; reconcile existing broker exposure |
| `GET /health` | Liveness | Never guarantees broker or signal readiness |
| `GET /ready` | Monitoring readiness | HTTP 503 when risk/data/broker checks are not satisfied |

The dashboard must not expose raw credentials. All browser-facing data uses sanitized broker reports, and source links render as safe HTTPS links.

## Verification boundary

GitHub CI checks Python tests using mocked broker data, browser JavaScript syntax, live FastAPI startup and a Docker image build. These tests **do not place actual Kotak orders**, do not use credentials, and do not establish profitability or intraday stop execution quality.

The **real scheduled ChatGPT → direct API delivery**, live Kotak session login, exact funds and symbol responses, actual Dhan 09:15 candles, partial-fill cases, disconnections and hosted VPS integration still need separate credentialed end-to-end verification.

Official SDK: https://github.com/Kotak-Neo/kotak-neo-python . Its v3 `limits()` method takes no arguments and returns limits across all exchanges.
