FROM node:22-slim

WORKDIR /app

ENV CLI_SERVICE_PORT=8110 \
    CLI_SERVICE_MODE=codex \
    CODEX_INTERNAL_PORT=8112 \
    GUARDRAILS_ENABLED=1 \
    GUARDRAILS_CONFIG_PATH=/app/guardrails_config \
    GUARDRAILS_PROFILE=default

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex @anthropic-ai/claude-code

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY gate.py guardrails_service.py codex_messages.py entrypoint.sh healthcheck.sh ./
COPY guardrails_config /app/guardrails_config

RUN chmod +x /app/entrypoint.sh /app/healthcheck.sh

EXPOSE 8110

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD ["/app/healthcheck.sh"]

ENTRYPOINT ["/app/entrypoint.sh"]
