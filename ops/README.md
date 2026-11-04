# Deploy Kotak Neo live-only monitoring to the existing VPS

The previously deployed Sniper paper service is documented in the separate [Sniper deployment script](https://github.com/danny8806/sniper-paper-desk/blob/main/deploy_vps.py). It uses VPS 200.234.44.93, SSH user root, directory /home/jadhavdnyaneshwar701/sniper-paper-desk, and Docker host port 8004.

**Do not use the old deploy_vps.py for this project.** It stops the existing dashboard, copies model artifacts and changes Nginx. The new deployment keeps those resources untouched.

## Isolated live-only server deployment

- Source: Indian-Market-Intelligence-AI/live_desk, bridge and scripts; no paper engine, saved models, paper ledger, or historic model assets
- New directory: /home/jadhavdnyaneshwar701/kotak-news-live
- Versioned release: new directory releases/<Git commit SHA>
- Private settings file: /home/jadhavdnyaneshwar701/kotak-news-live/config/live.env
- New container: Docker Compose project kotak-news-live
- Bind: 127.0.0.1:8010 (no public plaintext exposure)
- Order setting: LIVE_ORDERS_ALLOWED=NO, enforced by committed Compose configuration
- 8004 paper server and its company Nginx routes: unchanged

## Step 1 — Prepare private settings on the VPS

Using your existing authorized SSH login to the VPS, execute:

~~~bash
sudo install -d -m 700 /home/jadhavdnyaneshwar701/kotak-news-live/config
sudo nano /home/jadhavdnyaneshwar701/kotak-news-live/config/live.env
sudo chmod 600 /home/jadhavdnyaneshwar701/kotak-news-live/config/live.env
~~~

Minimum required environment file contents, replacing placeholders with genuine, private values:

~~~dotenv
SIGNAL_BRIDGE_TOKEN=LONG_UNIQUE_RANDOM_SECRET_AT_LEAST_32_CHARS
DASHBOARD_PASSWORD=LONG_PRIVATE_DASHBOARD_PASSWORD
DASHBOARD_SESSION_SECRET=DIFFERENT_LONG_RANDOM_SECRET_AT_LEAST_32_CHARS
DASHBOARD_PUBLIC_ORIGIN=https://YOUR_PRIVATE_LIVE_SUBDOMAIN
~~~

To connect to real broker books and market data, separately configure these settings in the same protected server file after your account has API access:

~~~dotenv
KOTAK_NEO_CONSUMER_KEY=
KOTAK_NEO_MOBILE_NUMBER=
KOTAK_NEO_UCC=
KOTAK_NEO_MPIN=
KOTAK_NEO_TOTP_SECRET=
DHAN_CLIENT_ID=
DHAN_PIN=
DHAN_TOTP_SECRET=
LIVE_ARM_TOTP_SECRET=
~~~

Do not paste broker credentials, VPS passwords, SSH private keys or TOTP secrets into ChatGPT, GitHub source files, or browser JavaScript. The existing paper application's .env file is not copied.

## Step 2 — Add GitHub Actions deployment secrets

Go to Indian-Market-Intelligence-AI → Settings → Secrets and variables → Actions → New repository secret.

The deployment requires **VPS_SSH_PRIVATE_KEY** (an approved dedicated ED25519 deploy private key) and **VPS_SSH_KNOWN_HOSTS** (a verified, pinned SSH host-key entry). The corresponding public key must be authorized on the VPS, and the fingerprint must be confirmed through a trusted administration channel rather than blindly trusting a newly scanned key.

Optionally add **VPS_HOST** and **VPS_USER**. Defaults are taken from the old deployment script: 200.234.44.93 and root respectively. A restricted deploy user with tightly controlled Docker access is preferable, but the account must be able to write the dedicated directory and run Docker Compose.

## Step 3 — Deploy

Open GitHub Actions in Indian-Market-Intelligence-AI, choose **Deploy Kotak live-only dashboard to existing VPS**, click **Run workflow** and select main. This action also triggers on deployment-related source changes after the secrets are configured.

The workflow first runs the signal and live-only tests, verifies Python/JS and both deployment shell scripts, then uploads only the live service source over pinned-host-key SSH. The server builds its own Docker image, starts the isolated container, checks its health and verifies that an unauthenticated API call is rejected. If health fails, it rolls back the isolated live container or stops that failed first instance.

Check on the VPS:

~~~bash
docker compose -p kotak-news-live --env-file /home/jadhavdnyaneshwar701/kotak-news-live/config/live.env -f /home/jadhavdnyaneshwar701/kotak-news-live/current/live_desk/compose.yaml ps
curl -fsS http://127.0.0.1:8010/health
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8010/api/state
~~~

Expected: the health JSON says LIVE_ONLY and orders_armed false. The unauthenticated account-data API returns 401. The /ready endpoint is expected to return 503 until real broker, feed, signals and risk checks are available.

## Step 4 — HTTPS browser access

Port 8010 binds only to the server loopback interface. Create a **dedicated HTTPS subdomain** and proxy its root path to 127.0.0.1:8010, using a real TLS certificate and a known public origin. See the Nginx template in this folder. Never reuse the existing plaintext port 8004 browser login for real broker controls. Do not change company Nginx routes without approval.

## Signal delivery and trading readiness

The live-only app accepts direct research reports using an authenticated POST /api/v1/signals/incoming. The producer must actually POST the exact existing JSON v1.0 document; ChatGPT scheduled tasks are not proven to post to an arbitrary API. No delivery means no new live entries.

The deployment runs with real-money orders disabled and with the Dhan opening-candle timestamp convention unset until verified against a real exchange response. It does **not** place orders or authenticate a real Kotak account during the smoke check. Broker-native protective stops and crash recovery must be independently verified before enabling unattended real-money operation.

A passing GitHub code test is not proof of a successful VPS deployment. Inspect the deployment Actions log and the VPS health endpoint for actual server status.

## One-time secure SSH bootstrap from your Windows computer

An audit of the user's older public MCX repository identified scripts with hardcoded historical VPS passwords. **Assume that old VPS password is compromised and rotate it through your hosting provider's trusted console before continuing.** Removing it from a repository's current files alone does not erase Git history.

The new [bootstrap_deploy_access.py](bootstrap_deploy_access.py) utility allows an authorized operator to convert their **new private VPS password (or existing private local environment file)** into a separate ED25519 GitHub Actions deployment key. This is a local workstation step; it does not expose the password to GitHub.

1. On your Windows computer, install Python, GitHub CLI (gh), and run `gh auth login` with permission to manage this repository's Actions secrets.
2. Install Python dependencies locally: `python -m pip install paramiko cryptography`.
3. Using your **hosting provider's VPS console** (not an unverified public key scan), obtain and independently confirm the server's ED25519 host fingerprint by running:

~~~bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
~~~

4. From the freshly checked out Indian-Market-Intelligence-AI repository on **your PC**, run:

~~~powershell
python ops/bootstrap_deploy_access.py --trusted-host-fingerprint 'SHA256:REPLACE_WITH_VERIFIED_SERVER_FINGERPRINT'
~~~

The script uses the private local `VPS_PASS` environment variable if configured, or reads it from the older **local and ignored** `~/Desktop/MCX-TRADER-LIVE/mcx-trader.env`; otherwise it securely prompts for the password without echoing it. It verifies the actual VPS SSH host key **before** password login, generates a separate deployment ED25519 key locally, installs only the public half on the VPS, verifies the key login, and writes the private key and pinned host-key string directly to GitHub Actions Secrets through your authenticated `gh` CLI.

**No VPS password, broker MPIN, key bytes, or token should be pasted into ChatGPT or committed.** Do not copy the old root password from the public MCX repository: it must be rotated first. The local script itself is never executed on a GitHub runner.

5. Complete the server's private `config/live.env` file according to Step 1, then rerun the GitHub deployment workflow. The VPS remains private on localhost port 8010 and live orders remain OFF.

If the VPS host-key fingerprint differs from the trusted provider console value, stop and investigate rather than disabling strict SSH host verification.
