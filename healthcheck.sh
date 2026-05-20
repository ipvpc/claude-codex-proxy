#!/bin/sh
MODE="${CLI_SERVICE_MODE:-codex}"
case "$MODE" in
  openai|codex) MODE=codex ;;
  anthropic|claude) MODE=claude ;;
esac

if [ "$MODE" = "codex" ]; then
  PORT="${CLI_SERVICE_PORT:-8110}"
  curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null
else
  claude auth status >/dev/null 2>&1
fi
