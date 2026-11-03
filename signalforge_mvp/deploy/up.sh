#!/usr/bin/env bash
# Bring up the SignalForge stack on a VM with HTTPS. Run from anywhere:
#   bash deploy/up.sh
set -euo pipefail

cd "$(dirname "$0")/.."  # -> signalforge_mvp/

if [ ! -f deploy/.env ]; then
  echo "Missing deploy/.env — copy deploy/.env.vm.example to deploy/.env and fill it in." >&2
  exit 1
fi

docker compose --env-file deploy/.env \
  -f docker-compose.yml -f deploy/docker-compose.vm.yml \
  up -d --build

echo
echo "Up. Caddy is fetching a certificate for \$SF_DOMAIN (first run takes ~30s)."
echo "Then open https://\$SF_DOMAIN  (see deploy/.env)."
