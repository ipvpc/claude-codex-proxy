#!/bin/sh
set -e
PORT="${CLI_SERVICE_PORT:-8110}"
KEY="${CLI_SERVICE_CLIENT_KEY:-${CLI_WS_AUTH_TOKEN:-}}"
if [ -z "$KEY" ]; then
  echo "CLI_SERVICE_CLIENT_KEY not set" >&2
  exit 1
fi
curl -fsS -H "Authorization: Bearer ${KEY}" "http://127.0.0.1:${PORT}/health" >/dev/null
