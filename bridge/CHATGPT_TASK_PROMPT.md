# ChatGPT 09:00 IST research task — direct delivery contract

The following prompt can be given to the existing scheduled task. It does not grant that task an HTTP tool. Configure an authorized connector or server-side producer with a protected bearer token separately. Never place the token in the prompt or chat. A scheduled run is not evidence of API delivery; verify the receiver's `ACCEPTED` or `DUPLICATE` acknowledgment and `GET /api/v1/signals/status` from a trusted server-side client.

## Prompt to paste into the task

> Each NSE trading day at 09:00 Asia/Kolkata, research material news for the approved Nifty 500 stock universe. Use news first available from the previous trading day's 15:00 IST through today's 09:00 IST. Prioritize original NSE/BSE filings and authoritative reporting. Verify company-symbol identity, source URLs, publication times, financial figures, significance, counterevidence, and whether the information was already expected. Select up to five LONG and five SHORT candidates, ranked separately from 1 in each direction. Fewer are acceptable; never fill slots with weak or invented news. This is a research watchlist, not an order instruction.
>
> Produce one JSON object matching `schema/stock-signals.schema.json` version 1.0 exactly. Set `market` to `NSE`, `timezone` to `Asia/Kolkata`, `session_date` to today's IST date, `news_cutoff_at` to today's 09:00:00+05:30, `generated_at` to the actual generation time, `execution_enabled` to `false`, and `status` to `READY` only when at least one candidate is verified. Each candidate must have `symbol`, `side`, sequential `rank`, `reason`, `news_summary`, `first_available_at`, `sources` (each with HTTPS `url`, `title`, and `published_at`), and `confidence` only if defensible. No source or event may have become available after the cutoff. If evidence is insufficient, use `NO_TRADE` or `UNAVAILABLE`, an empty `signals` array, and a clear `reason`. Never use placeholder URLs or example stocks.
>
> If an authorized HTTP action is actually available, validate the object, then POST the entire JSON object once to the configured HTTPS `/api/v1/signals/incoming` endpoint with `Content-Type: application/json`, `Authorization: Bearer` from the connector's secret store, and a stable `Idempotency-Key`. Check for HTTP 200 and an `ACCEPTED` or `DUPLICATE` response whose `session_date` and SHA-256 match the submitted canonical JSON. Report the acknowledgment status and hash. If that action is unavailable or delivery fails, explicitly say `NOT DELIVERED`; do not claim that creating JSON or updating GitHub delivered it to the dashboard. Do not place secrets in the report or task output.

## Receiver rules

- Endpoint: `POST https://<approved-live-host>/api/v1/signals/incoming`.
- Body: complete schema v1.0 JSON object, maximum 256,000 bytes.
- Headers: `Content-Type: application/json`, `Authorization: Bearer <secret>`, `Idempotency-Key: <stable-unique-session-key>`.
- `READY` must arrive after 09:00 and before 09:14 IST on its session date. A same-report retry returns `DUPLICATE`; conflicting contents return HTTP 409.
- `GET /api/v1/signals/status` requires the bearer token and confirms whether the current session report was stored. The live dashboard's authenticated state is the operator-facing view.
- Missing report, `NO_TRADE`, or `UNAVAILABLE` means no new entries.

No approved HTTPS hostname or verified scheduled-task HTTP action is configured in this repository. Until both exist and a genuine report is acknowledged, direct automatic delivery is unverified.
