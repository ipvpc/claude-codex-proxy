#!/bin/sh
set -e

# Exactly one stack: codex (OpenAI-compatible HTTP proxy) or claude (Claude Code CLI/SDK).
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

if [ "$MODE" = "codex" ]; then
  unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL ANTHROPIC_MODEL \
    CLAUDE_CODE_OAUTH_TOKEN CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX \
    CLAUDE_CODE_USE_FOUNDRY CLAUDE_CODE_USE_ANTHROPIC_AWS 2>/dev/null || true
else
  unset OPENAI_API_KEY CODEX_SERVICE_UPSTREAM_API_KEY CODEX_SERVICE_OPENAI_API_KEY \
    CODEX_SERVICE_UPSTREAM_RESPONSES_URL CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL 2>/dev/null || true
fi

PORT="${CLI_SERVICE_PORT:-8110}"
exec uvicorn app:app --host 0.0.0.0 --port "$PORT"
