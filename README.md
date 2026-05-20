# claude-codex-proxy

Run **one** coding CLI at a time in Docker: **Codex** or **Claude Code**. Clients talk to that CLI’s native interface using **CLI login** (ChatGPT / claude.ai) — not `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` toward the public APIs.

| `CLI_SERVICE_MODE` | Process | How clients connect |
|--------------------|---------|---------------------|
| **`codex`** (default) | `codex app-server` | **WebSocket JSON-RPC** on `CLI_SERVICE_PORT` (`GET /healthz` for probes). Auth: `codex login` in the container. |
| **`claude`** | `claude remote-control` | **claude.ai / Claude app** at [claude.ai/code](https://claude.ai/code) (outbound-only; no API keys). Auth: `claude auth login` in the container. |

Set `CLI_SERVICE_MODE` in `.env` and configure only the matching section in `.env.example`.

## Quick start

```bash
cp .env.example .env
# CLI_SERVICE_MODE=codex   or   claude
docker compose up -d --build
```

### codex mode

1. Log in once (stores credentials in the `codex_home` volume):

   ```bash
   docker compose run --rm -it codex-service codex login
   ```

2. Start the stack:

   ```bash
   docker compose up -d
   ```

3. Point your Codex client at **`ws://localhost:8110`** (JSON-RPC 2.0 per [Codex App Server](https://developers.openai.com/codex/app-server)).

4. If the port is reachable beyond localhost, set **`CLI_WS_AUTH_TOKEN`** in `.env` (see `.env.example`).

Health check: `curl -s http://localhost:8110/healthz`

### claude mode

1. Set `CLI_SERVICE_MODE=claude` in `.env`.

2. Log in (Claude subscription — not an API key):

   ```bash
   docker compose up -d
   docker compose exec -it codex-service claude auth login
   ```

3. The container runs **`claude remote-control`**. Open [claude.ai/code](https://claude.ai/code) or the Claude mobile app and pick the session (name from `CLI_SERVICE_SESSION_NAME`).

Published port **8110** is not used for remote clients in this mode (Remote Control uses outbound HTTPS only). See [Remote Control](https://code.claude.com/docs/en/remote-control).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLI_SERVICE_MODE` | `codex` | `codex` or `claude` (aliases: `openai`, `anthropic`). |
| `CLI_SERVICE_PORT` | `8110` | **codex**: WebSocket/health port. **claude**: unused for clients. |
| `CODEX_APP_SERVER_LISTEN` | `ws://0.0.0.0:8110` | Codex app-server `--listen` URL. |
| `CLI_WS_AUTH_TOKEN` | — | **codex**: WebSocket capability token (recommended on shared networks). |
| `CLI_WS_AUTH_TOKEN_FILE` | — | **codex**: path to token file inside the container. |
| `CLI_SERVICE_SESSION_NAME` | `claude-codex-proxy` | **claude**: session title on claude.ai/code. |
| `CLI_REMOTE_CONTROL_SPAWN` | — | **claude**: `same-dir`, `worktree`, or `session`. |
| `CLI_REMOTE_CONTROL_VERBOSE` | — | **claude**: set `1` for verbose logs. |

API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CODEX_SERVICE_*`) are **not used** and are cleared at startup when set.

## Volumes

| Volume | Purpose |
|--------|---------|
| `codex_home` | `~/.codex` — Codex login and config |
| `claude_home` | `~/.claude` — Claude Code login and sessions |

## Codex client example

After `codex login`, connect with JSON-RPC over WebSocket (see [App Server docs](https://developers.openai.com/codex/app-server)):

```ts
// ws://codex-service:8110 from another container on the same network
// Authorization: Bearer <CLI_WS_AUTH_TOKEN> during handshake if configured
```

## What this is not

- **Not** an OpenAI/Anthropic HTTP API proxy (no `POST /v1/chat/completions` with injected API keys).
- **Not** a way to use both Codex and Claude Code auth in one container — pick one mode.

If you need the legacy OpenAI-compatible proxy for `agent-service`, use a separate deployment or an older revision of this repo.

## Build

```bash
docker compose build codex-service
```
