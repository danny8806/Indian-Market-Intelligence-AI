# Direct Signal Delivery (GitHub not used as transport)

The **direct bridge** is an authenticated HTTP receiver for the existing research-only JSON report v1.0. It does not generate news or connect to a broker. Files are hosted in GitHub purely as **source code**; once deployed, delivery uses HTTPS -> FastAPI -> database -> dashboard API. No GitHub JSON polling is required.

## Source

- Receiver: `bridge/app.py`
- Sender: `bridge/send.py`
- Existing JSON validator: `scripts/validate_signals.py`
- Automated test suite: `tests/test_direct_delivery.py`, `tests/test_bridge.py`
- Docker container: `bridge/Dockerfile`
- Compose: `bridge/compose.yaml`

## Start locally

Requires Python 3.11+, and either PostgreSQL or SQLite (SQLite suitable for a single-instance development/test deployment).

```bash
python -m pip install -r requirements-bridge.txt
export SIGNAL_BRIDGE_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export SIGNAL_DATABASE_URL="sqlite:///$(pwd)/research_signals.db"
python -m bridge.app
```

It listens on `http://127.0.0.1:8000` locally. Windows users can set environment variables in PowerShell using `$env:SIGNAL_BRIDGE_TOKEN = ...`. Store tokens in a secure secret store and never commit or paste them into a public frontend.

Use the Docker Compose alternative from the repo root:

```bash
docker compose -f bridge/compose.yaml up -d --build
```

It uses `127.0.0.1:8000` by design. To receive cloud messages, deploy the bridge behind an HTTPS-enabled reverse proxy on a hosted server, or use a secure private tunnel and allowlist clients.

## Endpoints

| Method | Route | Auth | Description |
| --- | --- | --- | --- |
| POST | `/api/v1/signals/incoming` | Bearer token + Idempotency-Key | Store one immutable validated report per session |
| GET | `/api/v1/signals/latest` | Bearer token | Get current-session research report |
| GET | `/api/v1/signals/status` | Bearer token | See report status |
| GET | `/api/v1/health` | No token | Liveness only; no signal data |

The POST body is the **entire** JSON report, not a ticker list. Use `schema/stock-signals.schema.json` and the validation script as the contract. NEVER post fictional `examples/signals.sample.json` or `status=READY` without source-backed news.

## Direct sender from an authorized process

After the producer has created a real `/secure/path/to/report.json`:

```bash
export SIGNAL_BRIDGE_URL="https://YOUR-DEPLOYED-DOMAIN/api/v1/signals/incoming"
export SIGNAL_BRIDGE_TOKEN="USE_THE_RECEIVER_SECRET_FROM_A_SECRET_MANAGER"
python -m bridge.send --file /secure/path/to/report.json
```

The sender verifies the report date, news cutoff, transport security, bearer token configuration, size, and the API's SHA-256 acknowledgment. Identical retries are safe; conflicting reports are rejected.

A local development-only command can use `--url http://127.0.0.1:8000/api/v1/signals/incoming --allow-http-localhost` to bypass HTTPS solely on loopback.

### Dashboard reader

Use `GET /api/v1/signals/latest` with a server-side Bearer token, check `status`, `session_date`, `report.execution_enabled=false`, and verify the report before displaying signals. Never put the secret into the browser: the live desk proxies a sanitized view to the UI and independently gates any order path.

## Important limitation: ChatGPT scheduled tasks

The old ChatGPT 09:00 task was configured to attempt GitHub publication. The live desk does not consume that path. For **direct** delivery, an authorized sender must actually POST the report to a deployed, reachable bridge URL. This repository provides both sender and receiver, **not a direct HTTP capability inside the ChatGPT product scheduler**. Whether that scheduler can call your arbitrary API is unverified and may require a separate connected integration or a producer service using the OpenAI API. Do not claim automatic AI->API delivery until a real scheduled run receives an `ACCEPTED` acknowledgment. See [CHATGPT_TASK_PROMPT.md](CHATGPT_TASK_PROMPT.md) for a prompt and delivery acceptance checklist.

If there is no verified report, deliver `UNAVAILABLE` or `NO_TRADE` with an empty signals array. Under no circumstances invent stock picks or treat unavailable data as trades.

### Deployment and safety status

The automated CI suite tests in-process HTTP delivery with synthetic `NO_TRADE` JSON, auth, idempotency, persistence, and safety rejection. **There is no live public server/endpoint configured yet, and no test has delivered a real stock report to your own dashboard.** Configure HTTPS, deployment, credentials, and monitoring before calling the connection production-ready.

**No live order execution is enabled by these modules.**
