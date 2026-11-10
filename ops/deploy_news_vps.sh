#!/usr/bin/env bash
# Pinned-SSH isolated news database release. No change to trade/dashboard stacks.
set -Eeuo pipefail
umask 077

SHA="$GITHUB_SHA"
HOST="$VPS_HOST"
USER_NAME="$VPS_USER"
BASE="/home/jadhavdnyaneshwar701/market-news-db"

[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "BLOCKED: invalid Git commit"; exit 2; }
[[ "$HOST" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "BLOCKED: VPS_HOST absent/invalid"; exit 2; }
[[ "$USER_NAME" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "BLOCKED: VPS_USER absent/invalid"; exit 2; }
if [[ -z "$VPS_SSH_PRIVATE_KEY" || -z "$VPS_SSH_KNOWN_HOSTS" ]]; then
  echo "NOT DEPLOYED: required pinned VPS SSH secrets are missing."
  exit 3
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
printf '%s\n' "$VPS_SSH_PRIVATE_KEY" > "$WORK/key"
printf '%s\n' "$VPS_SSH_KNOWN_HOSTS" > "$WORK/known_hosts"
chmod 600 "$WORK/key" "$WORK/known_hosts"

SSH=(-i "$WORK/key" -o IdentitiesOnly=yes -o BatchMode=yes
     -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$WORK/known_hosts"
     -o ConnectTimeout=12)
SCP=(-i "$WORK/key" -o IdentitiesOnly=yes -o BatchMode=yes
     -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$WORK/known_hosts"
     -o ConnectTimeout=12)
# Only research news code and isolated PostgreSQL config; no live trading.
tar -czf "$WORK/news-release.tgz" \
    --exclude='*/__pycache__' --exclude='*.pyc' --exclude='.env' \
    news_collector ops/news-stack

REMOTE="$USER_NAME@$HOST"
REMOTE_TAR="/tmp/market-news-release-$SHA.tgz"
echo "Deploying separate news collection stack to VPS over pinned SSH..."
ssh "${SSH[@]}" "$REMOTE" \
    "install -d -m 700 '$BASE/releases/$SHA' && install -d -m 700 '$BASE/config'"
scp "${SCP[@]}" "$WORK/news-release.tgz" "$REMOTE:$REMOTE_TAR"
ssh "${SSH[@]}" "$REMOTE" \
    "tar -xzf '$REMOTE_TAR' -C '$BASE/releases/$SHA' && rm -f '$REMOTE_TAR' && bash '$BASE/releases/$SHA/ops/news-stack/activate-news-vps.sh' '$BASE' '$SHA'"
echo "SUCCESS: news-only VPS database and worker health-check returned success."
