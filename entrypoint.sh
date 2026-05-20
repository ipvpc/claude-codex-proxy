#!/bin/sh
set -e

# One active CLI stack. Clients use the CLI's own protocol + login — not OPENAI_API_KEY / ANTHROPIC_API_KEY.
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

if [ "$MODE" = "codex" ]; then
  unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL ANTHROPIC_MODEL \
    OPENAI_API_KEY CODEX_SERVICE_UPSTREAM_API_KEY CODEX_SERVICE_OPENAI_API_KEY \
    CODEX_SERVICE_UPSTREAM_RESPONSES_URL CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL \
    CLAUDE_CODE_OAUTH_TOKEN 2>/dev/null || true

  LISTEN="${CODEX_APP_SERVER_LISTEN:-ws://0.0.0.0:${PORT}}"
  echo "Starting Codex app-server (${LISTEN}). Authenticate with: docker compose exec codex-service codex login" >&2

  if [ -n "${CLI_WS_AUTH_TOKEN_FILE:-}" ] && [ -f "${CLI_WS_AUTH_TOKEN_FILE}" ]; then
    exec codex app-server --listen "$LISTEN" \
      --ws-auth capability-token --ws-token-file "${CLI_WS_AUTH_TOKEN_FILE}"
  fi
  if [ -n "${CLI_WS_AUTH_TOKEN:-}" ]; then
    TOKEN_FILE="/tmp/cli-ws-token"
    printf '%s' "$CLI_WS_AUTH_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    exec codex app-server --listen "$LISTEN" \
      --ws-auth capability-token --ws-token-file "$TOKEN_FILE"
  fi
  exec codex app-server --listen "$LISTEN"
fi

unset OPENAI_API_KEY CODEX_SERVICE_UPSTREAM_API_KEY CODEX_SERVICE_OPENAI_API_KEY \
  CODEX_SERVICE_UPSTREAM_RESPONSES_URL CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL \
  ANTHROPIC_API_KEY 2>/dev/null || true

SESSION_NAME="${CLI_SERVICE_SESSION_NAME:-claude-codex-proxy}"
echo "Starting Claude Code remote-control (session: ${SESSION_NAME})." >&2
echo "Connect from phone/browser at https://claude.ai/code after: docker compose exec -it codex-service claude auth login" >&2

RC_ARGS=""
if [ -n "${CLI_REMOTE_CONTROL_SPAWN:-}" ]; then
  RC_ARGS="$RC_ARGS --spawn ${CLI_REMOTE_CONTROL_SPAWN}"
fi
if [ "${CLI_REMOTE_CONTROL_VERBOSE:-}" = "1" ]; then
  RC_ARGS="$RC_ARGS --verbose"
fi

# shellcheck disable=SC2086
exec claude remote-control --name "$SESSION_NAME" $RC_ARGS
