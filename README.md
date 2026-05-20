# codex-service

Small **HTTP proxy** for OpenAI-compatible endpoints used by **Codex** (`POST /v1/responses`) and **`agent-service`** (`POST /v1/chat/completions`). This service injects an **API key (Bearer)** toward the configured upstream URL. **It does not use ChatGPT OAuth or Codex CLI browser login** — those flows are separate from this proxy.

Callers send a **placeholder** `Authorization` (or none); the proxy strips it and sends **`Authorization: Bearer <upstream key>`** (see key priority below).

The Docker image also installs **Node.js 22**, **npm**, and the global **`@openai/codex`** CLI for experimentation (the default process is still the Python **FastAPI** app on port **8110**).

## Quick start (Docker Compose)

From the repo root, **`codex-service`** starts with the stack (no profile). **`agent-service`** defaults **`OPENAI_BASE_URL`** to **`http://codex-service:8110/v1`** and depends on **`codex-service`**.

```bash
docker compose up -d codex-service agent-service
```

- Published port: **8110** (host and container).
- Loads variables from **`.env`** (see below). Set an **upstream API key** that matches **`CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL`** (OpenAI `sk-…` for `api.openai.com`, or OpenRouter key for `openrouter.ai`, etc.).

Check health:

```bash
curl -s http://localhost:8110/health
```

See which env var supplies the upstream key (no secret values):

```bash
curl -s http://localhost:8110/ | jq .
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CODEX_SERVICE_UPSTREAM_API_KEY` | One of three | — | Highest priority Bearer for upstream (use for Docker secrets / dedicated key). |
| `CODEX_SERVICE_OPENAI_API_KEY` | One of three | — | Second priority; use when `.env` **`OPENAI_API_KEY`** is an OpenRouter key but upstream is **`api.openai.com`**. |
| `OPENAI_API_KEY` | One of three | — | Fallback upstream Bearer if the two above are unset. |
| `CODEX_SERVICE_PORT` | No | `8110` | Listen port (Dockerfile / compose). |
| `CODEX_SERVICE_UPSTREAM_RESPONSES_URL` | No | `https://api.openai.com/v1/responses` | Full URL for the upstream Responses endpoint (e.g. Azure OpenAI if you change it). |
| `CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL` | No | `https://api.openai.com/v1/chat/completions` | Upstream for `POST /v1/chat/completions` (used by `agent-service`). |
| `CODEX_SERVICE_CLIENT_KEY` | No | — | If set, every request except `/`, `/health`, `/docs`, `/openapi.json`, `/redoc` must send header **`X-Codex-Service-Client-Key`** with this exact value. |
| `CODEX_SERVICE_REQUEST_TIMEOUT` | No | `120` | Upstream HTTP timeout (seconds). |

## API behavior

- **`GET /health`** — Liveness JSON.
- **`GET /`** — Service metadata (paths, upstream URLs, **`upstream_api_key_env`** shows which env var won, **`auth_note`** about API key vs OAuth).
- **`POST /v1/responses`** — Forwarded to `CODEX_SERVICE_UPSTREAM_RESPONSES_URL`.
- **`POST /v1/chat/completions`** — Forwarded to `CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL`.
- For both: incoming **`Authorization`** is **removed** and replaced with the resolved upstream Bearer. Supports buffered JSON and **`text/event-stream`** responses.
- Any other **`POST /v1/...`** — **403**.

### **`401 Unauthorized` on `POST /v1/chat/completions`**

That status is **passed through from the upstream** (e.g. OpenAI). This proxy does **not** implement OAuth.

- **Wrong key for URL**: an **OpenRouter** key against **`https://api.openai.com/...`** returns **401**. Set **`CODEX_SERVICE_OPENAI_API_KEY`** (or **`CODEX_SERVICE_UPSTREAM_API_KEY`**) to a real **OpenAI** key, **or** set **`CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL`** to OpenRouter’s chat URL and use an OpenRouter key.
- **Invalid / revoked / typo** in whichever env var **`upstream_api_key_env`** shows on **`GET /`**.

### **`Error -3 while decompressing data: incorrect header check`** (client behind this proxy)

That usually meant the proxy forwarded **`Content-Encoding: gzip`** while **`httpx`** had already decompressed the upstream body. **`codex-service`** now strips **`Content-Encoding`** (and **`Content-Length`**) on proxied responses so callers see plain JSON. Rebuild **`codex-service`** if you still see this on an old image.

## Example: `agent-service` → `codex-service`

`agent-service` calls **`{OPENAI_BASE_URL}/chat/completions`**. Point the base URL at this proxy and give a **non-empty placeholder** API key (the proxy discards it and uses the key configured on `codex-service`).

1. Start **`codex-service`** and **`agent-service`** (same Compose network; **`depends_on`** is set on **`agent-service`**):

   ```bash
   docker compose up -d codex-service agent-service
   ```

2. Ensure **`codex-service`** has the real key in `.env` (or `environment`):

   ```env
   OPENAI_API_KEY=sk-...your-real-key...
   ```

3. **`docker-compose.yml`** already routes **`agent-service`** LLM calls through **`codex-service`** by default (`OPENAI_BASE_URL`, placeholder **`OPENAI_API_KEY`**, **`OPENAI_MODEL=gpt-4o-mini`**, backup cleared unless you set **`AGENT_SERVICE_OPENAI_BACKUP_*`**). To use **OpenRouter (or direct) again** for chat only, set in **`.env`**:

   ```env
   AGENT_SERVICE_OPENAI_BASE_URL=https://openrouter.ai/api/v1
   AGENT_SERVICE_OPENAI_API_KEY=sk-or-v1-...
   AGENT_SERVICE_OPENAI_MODEL=anthropic/claude-3.5-sonnet
   ```

   - **`OPENAI_BASE_URL`** (inside the container) must end at **`/v1`** when using this proxy; `agent-service` appends **`/chat/completions`**.
   - With the proxy, **`OPENAI_API_KEY`** on **`agent-service`** is only a placeholder; the real key is on **`codex-service`**.

4. If **`codex-service`** has **`CODEX_SERVICE_CLIENT_KEY`** set, set the **same value** on **`agent-service`** as **`CODEX_SERVICE_CLIENT_KEY`**. `agent-service` will send **`X-Codex-Service-Client-Key`** on every **`/chat/completions`** request (gateway chat in `app.py` and agent synthesis in `alpha5_agents`).

   Optional: **`LLM_UPSTREAM_HEADERS_JSON`** on `agent-service` (JSON object of string header names to values) merges extra headers on those same LLM calls; **`CODEX_SERVICE_CLIENT_KEY`** still wins for **`X-Codex-Service-Client-Key`** if both define it.

## Calling from another container

Use base URL **`http://codex-service:8110/v1`** on the same Docker network. If `CODEX_SERVICE_CLIENT_KEY` is set, add:

`X-Codex-Service-Client-Key: <same value as env>`

## Pointing Codex CLI at this proxy

In `~/.codex/config.toml` (example provider + profile):

```toml
[model_providers.alpha5-codex-service]
name = "alpha5-codex-service"
base_url = "http://codex-service:8110/v1"
wire_api = "responses"

[profiles.alpha5-proxy]
model_provider = "alpha5-codex-service"
```

Adjust `base_url` if you reach the host from outside Compose (e.g. `http://localhost:8110/v1`).

## Local run (without Docker)

```bash
cd codex-service
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
set OPENAI_API_KEY=sk-...   # Windows
export OPENAI_API_KEY=sk-...  # Linux/macOS
uvicorn app:app --host 0.0.0.0 --port 8110
```

## Build image only

From repo root:

```bash
docker compose build codex-service
```

## Notes

- This is a **gateway + API key** pattern: the OpenAI key exists **only** on `codex-service` (or your secret store that injects it). It does **not** replace OpenAI billing or terms of use.
- For **Azure OpenAI**, set `CODEX_SERVICE_UPSTREAM_RESPONSES_URL` and/or `CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL` to your deployment URLs (and keep `OPENAI_API_KEY` as the key that upstream expects).
