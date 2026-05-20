FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLI_SERVICE_PORT=8110 \
    CLI_SERVICE_MODE=codex

# Node.js + npm (python:3.11-slim is Debian-based; Codex CLI is installed via npm)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# CLIs for shell use inside the container; configure via .env (ANTHROPIC_*, CLAUDE_*).
# For programmatic agents, add @anthropic-ai/claude-agent-sdk in your app (see README).
RUN npm install -g @openai/codex
RUN npm install -g @anthropic-ai/claude-code

COPY app.py service_mode.py entrypoint.sh ./

RUN chmod +x /app/entrypoint.sh

EXPOSE 8110

ENTRYPOINT ["/app/entrypoint.sh"]
