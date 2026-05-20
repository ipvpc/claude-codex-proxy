#!/bin/sh
set -e

# Clients need CLI_SERVICE_CLIENT_KEY to reach the gateway (not OpenAI/Anthropic keys).
if [ -z "${CLI_SERVICE_CLIENT_KEY:-}" ] && [ -z "${CLI_WS_AUTH_TOKEN:-}" ]; then
  echo "CLI_SERVICE_CLIENT_KEY is required — clients must send this key to connect." >&2
  exit 1
fi
export CLI_SERVICE_CLIENT_KEY="${CLI_SERVICE_CLIENT_KEY:-$CLI_WS_AUTH_TOKEN}"

MODE="${CLI_SERVICE_MODE:-codex}"
case "$MODE" in
  openai|codex) MODE=codex ;;
  anthropic|claude) MODE=claude ;;
  *)
    echo "Invalid CLI_SERVICE_MODE='${CLI_SERVICE_MODE}' (use: codex | claude)" >&2
    exit 1
    ;;
esac
export CLI_SERVICE_MODE="$MODE"

PORT="${CLI_SERVICE_PORT:-8110}"
INTERNAL_PORT="${CODEX_INTERNAL_PORT:-8112}"
export CODEX_INTERNAL_WS_URL="ws://127.0.0.1:${INTERNAL_PORT}"

# Strip upstream provider API keys — CLI login handles model access inside the container.
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL ANTHROPIC_MODEL \
  OPENAI_API_KEY CODEX_SERVICE_UPSTREAM_API_KEY CODEX_SERVICE_OPENAI_API_KEY \
  CODEX_SERVICE_UPSTREAM_RESPONSES_URL CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL \
  CLAUDE_CODE_OAUTH_TOKEN 2>/dev/null || true

if [ "$MODE" = "codex" ]; then
  echo "Starting Codex app-server (internal ${CODEX_INTERNAL_WS_URL})." >&2
  echo "Clients: ws://<host>:${PORT}/ with Authorization: Bearer <CLI_SERVICE_CLIENT_KEY>" >&2
  echo "CLI login (once): docker compose exec -it codex-service codex login" >&2
  if [ "${GUARDRAILS_ENABLED:-1}" != "0" ]; then
    echo "NeMo Guardrails: enabled (profile=${GUARDRAILS_PROFILE:-default})" >&2
  fi
  codex app-server --listen "ws://127.0.0.1:${INTERNAL_PORT}" &
  CODEX_PID=$!
  trap 'kill "$CODEX_PID" 2>/dev/null || true' EXIT INT TERM
else
  SESSION_NAME="${CLI_SERVICE_SESSION_NAME:-claude-codex-proxy}"
  echo "Starting Claude Code remote-control (session: ${SESSION_NAME})." >&2
  echo "HTTP gateway: http://<host>:${PORT}/health (requires CLI_SERVICE_CLIENT_KEY)" >&2
  echo "Sessions: https://claude.ai/code after: docker compose exec -it codex-service claude auth login" >&2
  RC_ARGS=""
  if [ -n "${CLI_REMOTE_CONTROL_SPAWN:-}" ]; then
    RC_ARGS="$RC_ARGS --spawn ${CLI_REMOTE_CONTROL_SPAWN}"
  fi
  if [ "${CLI_REMOTE_CONTROL_VERBOSE:-}" = "1" ]; then
    RC_ARGS="$RC_ARGS --verbose"
  fi
  # shellcheck disable=SC2086
  claude remote-control --name "$SESSION_NAME" $RC_ARGS &
  CLAUDE_PID=$!
  trap 'kill "$CLAUDE_PID" 2>/dev/null || true' EXIT INT TERM
fi

exec uvicorn gate:app --host 0.0.0.0 --port "$PORT"
