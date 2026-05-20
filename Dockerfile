FROM node:22-slim

WORKDIR /app

ENV CLI_SERVICE_PORT=8110 \
    CLI_SERVICE_MODE=codex

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex @anthropic-ai/claude-code

COPY entrypoint.sh healthcheck.sh ./
RUN chmod +x /app/entrypoint.sh /app/healthcheck.sh

EXPOSE 8110

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["/app/healthcheck.sh"]

ENTRYPOINT ["/app/entrypoint.sh"]
