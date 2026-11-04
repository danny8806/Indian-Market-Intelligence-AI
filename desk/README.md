# News Signal · Sniper Paper Desk

**Integration of the privately owned Sniper Paper Desk UI into this public repository.** The model-based per-stock selection system is replaced with the exact v1.0 verified news-signal feed from the existing FastAPI signal bridge. This code imports no prediction models or saved weights; do not copy `models/`, `research/`, credentials, or the old paper ledger.

## What it does

- Authenticated dark trading-terminal dashboard using the original scanner, chart, positions, P&L, performance, trade-history UI and live WebSocket state.
- Up to 5 LONG and 5 SHORT stock candidates selected by the current-session verified **09:00 IST research report**, not by a local ML model.
- **Direct integration:** `POST /api/v1/signals/incoming` with Bearer + Idempotency-Key. One immutable report per session. Authenticated `GET /api/v1/signals/latest`, `GET /api/v1/signals/status`. `GET /api/news/signals` is dashboard-cookie authenticated.
- Resolves news-selected NSE symbols to numeric Dhan IDs from the **official Dhan equity master** each day.
- Uses read-only Dhan market-data REST quotes + WebSocket, refreshes 15-minute chart candles where available, and never fabricates market data.
- Dynamic paper ledger, one entry per symbol per session, default ₹1 lakh allocation, 2% stop loss and exit at 15:25 IST; these are **paper fills at observed fresh prices**, not 09:15 open fills or actual broker confirmations.
- Missing report, stale data, missing credentials, unresolved instruments and late signals **block new entries**; the UI shows the reason. Source news and research direction are not reliable trade guarantees.
- No broker order submission from this runtime. The independent `live/kotak_orders.py` boundary is not imported.

## Run

Python 3.11+:

```bash
python -m pip install -r requirements-desk.txt
# Configure private shell environment or ignored .env:
export SIGNAL_DATABASE_URL="sqlite:////tmp/news_signal_reports.sqlite3"
export PAPER_DESK_DB="/tmp/news_paper.sqlite3"
export SIGNAL_BRIDGE_TOKEN="<random 32+ char secret>"
export DASHBOARD_PASSWORD="<private strong dashboard password>"
export DASHBOARD_SESSION_SECRET="<different random 32+ char secret>"
export DASHBOARD_COOKIE_SECURE="false" # local HTTP testing ONLY
export DHAN_CLIENT_ID="<your Dhan ID>"
export DHAN_PIN="<your private PIN>"
export DHAN_TOTP_SECRET="<private TOTP seed>"
python -m desk.app
```

Open http://127.0.0.1:8004 locally. The receiver runs at the **same** base URL: `POST http://127.0.0.1:8004/api/v1/signals/incoming`. In production, use HTTPS and set `DASHBOARD_COOKIE_SECURE=true`.

Docker deployment:

```bash
docker compose -f desk/compose.yaml up -d --build
```

`127.0.0.1:8004` is not publicly accessible. Place a TLS reverse proxy and an authenticated cloud service in front. Bind mounts must persist across restarts, and run exactly one paper-engine worker per database to prevent duplicate supervisors.

## Paper trading controls

Paper entries start **PAUSED** and require dashboard login to resume. To enable, first deliver today's verified report, configure Dhan data credentials and confirm Dhan symbol mapping; then press **Resume entries**. This does not submit real orders. The target signal batch can arrive up to 09:14 IST through the bridge; entries are eligible 09:15–09:20 IST only when fresh Dhan prices exist. Late/failed data leads to missed paper entries, never backfilled fills.

Stop monitoring operates for existing positions even when new entries are paused. Positions unresolved from previous sessions are preserved and block new overlapping entries rather than being closed at fictitious prices. Stop/slippage and P&L are simulated, gross of brokerage and taxes.

## Verification

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs automated backend, bridge, mock price and dashboard-integrity tests. An actual market feed, credential rotation, real timing, browser UI and cloud deployment require separate verification with your Dhan account and hosting environment. No valid authentication or live prices are stored in GitHub.

## Security

This is a paper-trading dashboard. Keep source credentials in an off-repo secret manager, terminate TLS at the reverse proxy, lock down API routes and apply backups/monitoring. The private source's older non-HTTPS VPS instance is **not** automatically migrated, replaced or modified by this code.
