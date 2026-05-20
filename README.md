# claude-codex-proxy

Docker service that runs **one** coding CLI at a time: **Codex** or **Claude Code**.

- **Clients** authenticate to **this service** with `CLI_SERVICE_CLIENT_KEY` (your gateway API key).
- **The container** authenticates to OpenAI/Anthropic through **CLI login** (`codex login` or `claude auth login`) — not with `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in `.env`.

| Layer | Credential | Who sets it |
|-------|------------|-------------|
| Client → gateway (port 8110) | `CLI_SERVICE_CLIENT_KEY` | You, in `.env`; clients send it on every request |
| Gateway → model providers | Codex / Claude Code session | Once per container, via CLI login inside Docker |

| `CLI_SERVICE_MODE` | What runs behind the gateway |
|--------------------|------------------------------|
| **`codex`** (default) | Codex **app-server** (JSON-RPC over WebSocket), proxied through the gateway |
| **`claude`** | Claude Code **remote-control** (sessions on claude.ai/code) plus HTTP metadata on the gateway |

**[NVIDIA NeMo Guardrails](https://developer.nvidia.com/nemo-guardrails)** screens user and assistant text on the Codex WebSocket path (and via `POST /guardrails/check` in any mode). This is separate from `CLI_SERVICE_CLIENT_KEY` and separate from the CLI’s own provider login.

---

## Quick start (operators)

```bash
cp .env.example .env
# Edit .env: set CLI_SERVICE_CLIENT_KEY and CLI_SERVICE_MODE
docker compose up -d --build
```

**codex mode** — log in to Codex inside the container:

```bash
docker compose exec -it codex-service codex login
```

**claude mode** — set `CLI_SERVICE_MODE=claude` in `.env`, rebuild, then:

```bash
docker compose exec -it codex-service claude auth login
```

---

## How clients connect

All clients hit the **gateway** on `CLI_SERVICE_PORT` (default **8110**). Every call must include the **same** `CLI_SERVICE_CLIENT_KEY` you configured in `.env`.

### Base URLs

| Where the client runs | Base URL (HTTP) | WebSocket (codex mode only) |
|-----------------------|-----------------|-----------------------------|
| Same machine as Docker | `http://localhost:8110` | `ws://localhost:8110/` |
| Another container on the Compose network | `http://codex-service:8110` | `ws://codex-service:8110/` |
| Remote host | `http://<host>:8110` | `ws://<host>:8110/` |

Replace `8110` if you changed `CLI_SERVICE_PORT` in `.env`.

### Client API key (required)

Send the service key using **either** header style:

```http
Authorization: Bearer <CLI_SERVICE_CLIENT_KEY>
```

```http
X-CLI-Service-Client-Key: <CLI_SERVICE_CLIENT_KEY>
```

| Result | Meaning |
|--------|---------|
| **401 Unauthorized** | Missing key, wrong key, or typo |
| **200** / WebSocket upgrade | Key accepted |

Do **not** send OpenAI (`sk-…`) or Anthropic (`sk-ant-…`) API keys to this gateway — they are ignored and stripped at container startup.

### HTTP endpoints (both modes)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/health` | Client key required | Liveness probe |
| `GET` | `/` | Client key required | Service metadata (mode, connection hints) |
| `GET` | `/docs` | Client key required | OpenAPI UI (FastAPI) |
| `POST` | `/guardrails/check` | Client key required | Run [NeMo Guardrails](https://developer.nvidia.com/nemo-guardrails) on a `messages` array |

**Examples**

From the host (PowerShell):

```powershell
$key = "your-cli-service-client-key"
Invoke-RestMethod -Uri "http://localhost:8110/health" -Headers @{ Authorization = "Bearer $key" }
```

From the host (bash):

```bash
export CLI_SERVICE_CLIENT_KEY="your-cli-service-client-key"
curl -s -H "Authorization: Bearer $CLI_SERVICE_CLIENT_KEY" http://localhost:8110/health
curl -s -H "Authorization: Bearer $CLI_SERVICE_CLIENT_KEY" http://localhost:8110/ | jq .
```

From another service on the same Docker network:

```bash
curl -s -H "X-CLI-Service-Client-Key: ${CLI_SERVICE_CLIENT_KEY}" \
  http://codex-service:8110/health
```

---

## Connecting in codex mode (`CLI_SERVICE_MODE=codex`)

Use this mode when your client speaks the **[Codex App Server](https://developers.openai.com/codex/app-server)** protocol (JSON-RPC 2.0 over WebSocket), for example the Codex VS Code extension or a custom app-server client.

### Connection steps

1. Ensure the stack is up and `codex login` has been run in the container.
2. Open a **WebSocket** to `ws://<host>:8110/` (trailing slash is fine).
3. On the WebSocket **handshake**, send:
   - `Authorization: Bearer <CLI_SERVICE_CLIENT_KEY>`
4. After the connection is accepted, follow Codex app-server lifecycle:
   - Send `initialize` (with `id`)
   - Send `initialized` notification
   - Use `thread/start`, `turn/start`, etc. ([protocol docs](https://developers.openai.com/codex/app-server))

The gateway proxies the WebSocket to an internal Codex app-server on localhost; clients never connect to port 8112 directly.

### Minimal Node.js client sketch

```javascript
import WebSocket from "ws";

const key = process.env.CLI_SERVICE_CLIENT_KEY;
const ws = new WebSocket("ws://localhost:8110/", {
  headers: { Authorization: `Bearer ${key}` },
});

ws.on("open", () => {
  ws.send(JSON.stringify({
    method: "initialize",
    id: 0,
    params: { clientInfo: { name: "my-app", title: "My App", version: "1.0.0" } },
  }));
  ws.send(JSON.stringify({ method: "initialized", params: {} }));
});

ws.on("message", (data) => console.log("server:", data.toString()));
```

### Codex config.toml (optional)

If a Codex CLI on another machine should target this gateway, point `base_url` at the WebSocket host and supply the client key per your client’s docs. The in-container app-server is already behind the gateway; external Codex CLIs typically use HTTP `base_url` only when using a **responses** proxy — for **app-server**, use a WebSocket-capable client library, not `POST /v1/chat/completions`.

### What does not work in codex mode

- `POST /v1/chat/completions` or other OpenAI HTTP APIs on this port (not implemented).
- WebSocket connections **without** `CLI_SERVICE_CLIENT_KEY` (rejected with close code **1008**).

---

## Connecting in claude mode (`CLI_SERVICE_MODE=claude`)

Use this mode when operators and users work through **Claude Code Remote Control** ([docs](https://code.claude.com/docs/en/remote-control)).

### Two connection surfaces

| Surface | Client key required? | How to connect |
|---------|----------------------|----------------|
| **HTTP gateway** (`:8110`) | **Yes** | `GET /health`, `GET /` with Bearer or `X-CLI-Service-Client-Key` |
| **Agent session** (claude.ai / mobile app) | No (uses Claude account) | After `claude auth login` in the container, open [claude.ai/code](https://claude.ai/code) and select the session named `CLI_SERVICE_SESSION_NAME` |

### Connection steps

1. Set `CLI_SERVICE_MODE=claude` in `.env` and `docker compose up -d --build`.
2. Run `docker compose exec -it codex-service claude auth login` (Claude subscription — not an API key in `.env`).
3. Verify the gateway with your client key:

   ```bash
   curl -s -H "Authorization: Bearer $CLI_SERVICE_CLIENT_KEY" http://localhost:8110/
   ```

4. On a phone or browser, open **https://claude.ai/code** (or the Claude app → Code) and continue the session shown as **`CLI_SERVICE_SESSION_NAME`** (default `claude-codex-proxy`).

Remote Control uses **outbound HTTPS** from the container; it does not expose a second public agent port. Port **8110** is only for health/metadata with your client key.

### What does not work in claude mode

- **WebSocket** to `ws://<host>:8110/` for agent work (gateway closes with an error — use claude.ai/code instead).
- Expecting `ANTHROPIC_API_KEY` in `.env` for clients (unset at startup; use `claude auth login`).

---

## NeMo Guardrails

This service embeds the [NeMo Guardrails](https://developer.nvidia.com/nemo-guardrails) library to orchestrate **input** and **output** safety rails before/after text reaches the Codex CLI. Configuration lives in `guardrails_config/` ([YAML schema](https://docs.nvidia.com/nemo/guardrails/latest/configure-rails/yaml-schema/guardrails-configuration/)).

### Profiles

| `GUARDRAILS_PROFILE` | Rails | Extra API key |
|----------------------|-------|----------------|
| **`default`** | Jailbreak heuristics (input + output), parallel | None |
| **`llm`** | Heuristics + `self check input` / `self check output` | `GUARDRAILS_MODERATION_API_KEY` (moderator only) |

Set `GUARDRAILS_ENABLED=0` to disable. Set `GUARDRAILS_FAIL_OPEN=1` to allow traffic if the guardrails engine fails to load (default: block on engine errors when screening runs).

### Where rails run

| Mode | Automatic screening | Manual check |
|------|---------------------|--------------|
| **codex** | Every Codex app-server WebSocket JSON-RPC frame (user `turn/start` text in; assistant notifications out) | `POST /guardrails/check` |
| **claude** | Not on claude.ai traffic (Remote Control is outbound-only) | `POST /guardrails/check` before sending prompts from your app |

Blocked Codex requests receive a JSON-RPC error (`code: -32050`, `"Blocked by NeMo Guardrails"`).

### Check messages over HTTP

```bash
curl -s -X POST http://localhost:8110/guardrails/check \
  -H "Authorization: Bearer $CLI_SERVICE_CLIENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello, help me refactor this module."}]}'
```

### Customize rails

Edit `guardrails_config/config.yml` (default) or `guardrails_config/llm/config.yml`, or point `GUARDRAILS_CONFIG_PATH` at your own folder. See the [NeMo Guardrails developer guide](https://docs.nvidia.com/nemo/guardrails/latest/) for flows such as content safety, topic control, PII masking, and [NVIDIA NIM microservices](https://developer.nvidia.com/nemo-guardrails).

---

## Client connection checklist

Use this before integrating an app or CI job:

- [ ] `.env` has a strong `CLI_SERVICE_CLIENT_KEY`
- [ ] `CLI_SERVICE_MODE` matches the CLI you need (`codex` or `claude`)
- [ ] Container is healthy: `curl` to `/health` with the client key returns `"status":"ok"`
- [ ] CLI login completed inside the container (`codex login` or `claude auth login`)
- [ ] **codex**: client uses WebSocket + JSON-RPC and sends Bearer token on handshake
- [ ] **claude**: operators use claude.ai/code; automations only need HTTP `/health` unless you add your own wrapper
- [ ] **Guardrails**: `GET /` shows `"guardrails": { "ready": true }` (or `GUARDRAILS_ENABLED=0` if intentionally off)

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLI_SERVICE_CLIENT_KEY` | **Yes** | — | API key every client must send to the gateway. |
| `CLI_SERVICE_MODE` | No | `codex` | `codex` or `claude` (aliases: `openai`, `anthropic`). |
| `CLI_SERVICE_PORT` | No | `8110` | Published gateway port. |
| `CODEX_INTERNAL_PORT` | No | `8112` | Internal Codex app-server (loopback only). |
| `CLI_SERVICE_SESSION_NAME` | No | `claude-codex-proxy` | **claude**: session title on claude.ai/code. |
| `CLI_REMOTE_CONTROL_SPAWN` | No | — | **claude**: `same-dir`, `worktree`, or `session`. |
| `CLI_REMOTE_CONTROL_VERBOSE` | No | — | **claude**: set `1` for verbose logs. |
| `GUARDRAILS_ENABLED` | No | `1` | Set `0` to disable NeMo Guardrails. |
| `GUARDRAILS_PROFILE` | No | `default` | `default` (heuristics) or `llm` (adds self-check rails). |
| `GUARDRAILS_CONFIG_PATH` | No | `/app/guardrails_config` | Path to `config.yml` and flows. |
| `GUARDRAILS_MODERATION_API_KEY` | If `llm` profile | — | OpenAI-compatible key for moderator LLM only. |
| `GUARDRAILS_FAIL_OPEN` | No | `0` | Set `1` to pass traffic when the guardrails engine errors. |

Legacy: `CLI_WS_AUTH_TOKEN` is used only if `CLI_SERVICE_CLIENT_KEY` is unset.

---

## Architecture

```
                    ┌─────────────────────────────────────┐
  Client            │  gate.py :8110 (CLI_SERVICE_PORT)   │
  (client API key)  │  • GET /health, GET /, /guardrails/check │
        │           │  • NeMo Guardrails (input/output)    │
        │           │  • WebSocket proxy (codex mode)      │
        └──────────►└──────────────┬──────────────────────┘
                                   │
              codex mode           │ ws://127.0.0.1:8112
                                   ▼
                    ┌─────────────────────────────────────┐
                    │  codex app-server (Codex login)       │
                    └─────────────────────────────────────┘

              claude mode          │  claude remote-control
                                   ▼
                    ┌─────────────────────────────────────┐
                    │  claude.ai / Claude app (user login)  │
                    └─────────────────────────────────────┘
```

---

## Volumes

| Volume | Purpose |
|--------|---------|
| `codex_home` | `~/.codex` — Codex login and config |
| `claude_home` | `~/.claude` — Claude Code login and sessions |

---

## What this is not

- Not an OpenAI- or Anthropic-compatible HTTP API for arbitrary `POST /v1/*` clients.
- Not a host for both Codex and Claude credentials at the same time — pick one `CLI_SERVICE_MODE`.
- Not a replacement for sharing your OpenAI/Anthropic API keys with downstream apps; share only `CLI_SERVICE_CLIENT_KEY` for access to **this** gateway.

---

## Build

```bash
docker compose build codex-service
```
