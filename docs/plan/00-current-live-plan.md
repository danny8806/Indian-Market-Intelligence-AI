# Current plan — ChatGPT schedule to live Kotak desk

Updated: 5 November 2026 (Asia/Kolkata). This is the current plan for this repository. The older `signals/` GitHub publication workflow and the `sniper-paper-desk` project are historical and are not the live desk's signal transport or execution path.

## Daily contract

1. A ChatGPT scheduled task researches significant Nifty 500 news available from the previous NSE open session at 15:00 IST through the current session at 09:00 IST. It verifies sources, timestamps, issuer/symbol identity, materiality and counterevidence, then produces schema v1.0 JSON with up to five ranked LONG and five ranked SHORT candidates. Weak evidence yields `NO_TRADE` or `UNAVAILABLE`.
2. The task must deliver that complete JSON to the dashboard's authenticated `POST /api/v1/signals/incoming` endpoint and verify the `ACCEPTED` or `DUPLICATE` acknowledgment. A task run or a JSON answer alone is not delivery. No OpenAI API producer and no GitHub signal handoff are part of this plan.
3. The live desk stores the report, checks session date, 09:00 cutoff, arrival deadline, source fields and idempotency, then resolves candidates to exact current Dhan and Kotak instruments. Missing or ambiguous mappings block the candidate.
4. Dhan provides the actual 09:15–09:16 one-minute candle and fresh ticks. The first direct cross above its high for LONG or below its low for SHORT can trigger entry before 10:00 IST. The first five valid crossings per side take slots; rank breaks simultaneous ties. Amount sizing uses whole shares. Kotak Neo is the only order broker.
5. Kotak order/trade/position reports and persisted intents drive reconciliation and the authenticated dashboard. Positions are scheduled for 15:15 IST exit. A missing signal, stale feed, broker uncertainty, risk failure or disarmed state blocks new entries.

## Verified implementation

| Area | Current evidence | Status |
| --- | --- | --- |
| Direct JSON receiver | Authenticated FastAPI route, schema/date/idempotency checks and persistent store; local synthetic delivery tests | Built; no genuine ChatGPT delivery verified |
| Dashboard | Authenticated UI and state/orders/positions routes | Built; VPS private health verified |
| Dhan data and instrument mapping | Read-only data/tick/candle modules and exact mapping checks | Built in code; credentialed 09:15 candle timing and live mapping not verified |
| Kotak order and reconciliation path | Gateway, durable intents, supervisor and mocked boundary tests | Built in code; no credentialed account/order-feed test or real submission |
| Local regression suite | `python -m pytest -q` on 5 November 2026 | 88 passed |
| VPS | `kotak-news-live-kotak-live-news-1` healthy on loopback `127.0.0.1:8010`; `/health` 200 and `/ready` 503 on 5 November | Monitoring deployment running, trading not ready |
| Old dashboard | No listener on port 8004 on 5 November | Down |
| ChatGPT schedule | Visible ChatGPT account's Scheduled page showed no active stock task in the preceding check | Task/account association and delivery action unverified |
| Public HTTPS bridge | `neo.deltacapitals.systems` has no A record; app binds loopback | Not reachable from ChatGPT cloud |
| Live orders | Committed Compose sets `LIVE_ORDERS_ALLOWED=NO`; dashboard is disarmed | Disabled |

The live service's presence is not proof of a working daily decision or broker execution. Synthetic tests validate contracts and failure handling, not price accuracy, broker behavior or an unattended trading session.

## Next work, in dependency order

1. Confirm the intended ChatGPT scheduled task/account and its actual supported delivery tool. Update it with [the task prompt](../../bridge/CHATGPT_TASK_PROMPT.md), then run a genuine non-trading delivery test and verify the receiver acknowledgment. If ChatGPT scheduled tasks cannot perform an authenticated external POST, direct delivery requires a supported connected action; do not silently substitute an OpenAI API producer or GitHub feed.
2. Publish a dedicated DNS A record for the chosen bridge hostname pointing to `200.234.44.93`; install a separate HTTPS reverse-proxy site and certificate; set secure cookies and the exact public origin. Keep the existing company site untouched. Verify authenticated POST, duplicate handling, dashboard login and external reachability.
3. Configure Kotak and Dhan credentials privately, verify real account/session and feed contracts, obtain current exact instrument mappings, and audit the Dhan one-minute candle's start/end timestamp against the exchange clock.
4. Test first-cross entry, first-five-per-side capacity, sizing, broker order acknowledgments, partial fills, reconnect/restart reconciliation, loss limits and timed exit against real read-only data and controlled broker test conditions. Resolve the current 2% adverse-tick exit code against the user's stated no-stop/15:15-exit rule before any live arming.
5. Add operating alerts, backups/recovery verification and a daily end-to-end acceptance record. Enable real orders only after the operator has reviewed and explicitly authorized the final risk and exit configuration and all readiness gates pass.

No claim of exhaustive news coverage, a guaranteed 09:00 ChatGPT run, or profitable predictions is made by this plan.
