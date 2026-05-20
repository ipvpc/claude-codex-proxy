"""
HTTP/WebSocket gateway in front of the active CLI.

Clients must present CLI_SERVICE_CLIENT_KEY (not OpenAI/Anthropic API keys).
Optional NeMo Guardrails screen user/assistant text on the Codex WebSocket path.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import websockets

from codex_messages import (
    apply_text_replacement,
    build_block_frame,
    extract_text_segments,
)
from guardrails_service import guardrails_service

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("gate")

APP_NAME = "cli-service-gate"

CLIENT_KEY = os.getenv("CLI_SERVICE_CLIENT_KEY", "").strip() or os.getenv(
    "CLI_WS_AUTH_TOKEN", ""
).strip()
if not CLIENT_KEY:
    print("CLI_SERVICE_CLIENT_KEY is required (client API key for this service).", file=sys.stderr)
    sys.exit(1)

CLI_SERVICE_MODE = os.getenv("CLI_SERVICE_MODE", "codex").strip().lower()
if CLI_SERVICE_MODE in ("openai",):
    CLI_SERVICE_MODE = "codex"
elif CLI_SERVICE_MODE in ("anthropic",):
    CLI_SERVICE_MODE = "claude"

CODEX_INTERNAL_WS = os.getenv("CODEX_INTERNAL_WS_URL", "ws://127.0.0.1:8112").strip()
CLI_SERVICE_PORT = os.getenv("CLI_SERVICE_PORT", "8110").strip()


def _extract_client_key(request: Request) -> str | None:
    header = request.headers.get("x-cli-service-client-key", "").strip()
    if header:
        return header
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _authorized(request: Request) -> bool:
    key = _extract_client_key(request)
    return bool(key) and key == CLIENT_KEY


def _ws_authorized(websocket: WebSocket) -> bool:
    key = websocket.headers.get("x-cli-service-client-key", "").strip()
    if key:
        return key == CLIENT_KEY
    auth = websocket.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() == CLIENT_KEY
    return False


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await guardrails_service.initialize()
    yield


app = FastAPI(title=APP_NAME, version="0.3.0", lifespan=_lifespan)


@app.middleware("http")
async def require_client_key(request: Request, call_next):
    if not _authorized(request):
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Missing or invalid client API key. "
                "Send Authorization: Bearer <CLI_SERVICE_CLIENT_KEY> or "
                "X-CLI-Service-Client-Key: <CLI_SERVICE_CLIENT_KEY>."
            },
        )
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME, "cli_service_mode": CLI_SERVICE_MODE}


@app.get("/")
async def root() -> dict[str, object]:
    return {
        "service": APP_NAME,
        "cli_service_mode": CLI_SERVICE_MODE,
        "client_key_required": True,
        "listen_port": CLI_SERVICE_PORT,
        "guardrails": guardrails_service.status,
        "codex": {
            "websocket_url": f"ws://<host>:{CLI_SERVICE_PORT}/",
            "protocol": "JSON-RPC 2.0 (Codex app-server)",
            "guardrails_on_websocket": guardrails_service.active,
            "docs": "https://developers.openai.com/codex/app-server",
            "active": CLI_SERVICE_MODE == "codex",
        },
        "claude": {
            "remote_control": "https://claude.ai/code",
            "active": CLI_SERVICE_MODE == "claude",
            "note": "Claude agent traffic uses claude.ai; use POST /guardrails/check to screen text.",
        },
        "auth": {
            "headers": [
                "Authorization: Bearer <CLI_SERVICE_CLIENT_KEY>",
                "X-CLI-Service-Client-Key: <CLI_SERVICE_CLIENT_KEY>",
            ],
            "upstream_openai_api_key": False,
            "upstream_anthropic_api_key": False,
        },
    }


@app.post("/guardrails/check")
async def guardrails_check(body: dict[str, Any]) -> dict[str, object]:
    """
    Run NeMo Guardrails on arbitrary messages (for clients and claude-mode integrations).

    Body: { "messages": [ {"role": "user"|"assistant", "content": "..."}, ... ] }
    """
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages array required")

    results: list[dict[str, object]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        outcome = await guardrails_service.screen(role, content)
        results.append(
            {
                "role": role,
                "allowed": outcome.allowed,
                "status": outcome.status,
                "content": outcome.content,
                "rail": outcome.rail,
                "detail": outcome.detail,
            }
        )
        if not outcome.allowed:
            return {
                "allowed": False,
                "results": results,
                "blocked_by": outcome.rail,
                "detail": outcome.detail,
            }

    return {"allowed": True, "results": results, "guardrails": guardrails_service.status}


async def _screen_frame(payload: str, *, from_client: bool) -> tuple[bool, str, str | None, str | None]:
    if not guardrails_service.active:
        return True, payload, None, None

    segments = extract_text_segments(payload, from_client=from_client)
    if not segments:
        return True, payload, None, None

    out_payload = payload
    for seg in segments:
        outcome = await guardrails_service.screen(seg.role, seg.text)
        if not outcome.allowed:
            return False, out_payload, outcome.rail, outcome.detail
        if outcome.status == "modified" and outcome.content != seg.text:
            out_payload = apply_text_replacement(out_payload, seg.text, outcome.content)

    return True, out_payload, None, None


async def _relay_ws(client: WebSocket, upstream_url: str) -> None:
    await client.accept()
    async with websockets.connect(upstream_url, open_timeout=30) as upstream:

        async def client_to_upstream() -> None:
            try:
                while True:
                    message = await client.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if message["type"] != "websocket.receive":
                        continue
                    text = message.get("text")
                    if text is None:
                        if message.get("bytes") is not None:
                            await upstream.send(message["bytes"])
                        continue

                    allowed, forward_text, rail, detail = await _screen_frame(text, from_client=True)
                    if not allowed:
                        try:
                            parsed = __import__("json").loads(text)
                            req_id = parsed.get("id") if isinstance(parsed, dict) else None
                        except Exception:
                            req_id = None
                        await client.send_text(
                            build_block_frame(req_id, rail, detail or "Input blocked")
                        )
                        continue
                    await upstream.send(forward_text)
            except WebSocketDisconnect:
                pass
            finally:
                await upstream.close()

        async def upstream_to_client() -> None:
            try:
                async for payload in upstream:
                    if isinstance(payload, str):
                        allowed, forward_text, rail, detail = await _screen_frame(
                            payload, from_client=False
                        )
                        if not allowed:
                            await client.send_text(
                                build_block_frame(
                                    None, rail, detail or "Output blocked"
                                )
                            )
                            continue
                        await client.send_text(forward_text)
                    else:
                        await client.send_bytes(payload)
            except websockets.ConnectionClosed:
                pass
            finally:
                await client.close()

        forward = asyncio.create_task(client_to_upstream())
        backward = asyncio.create_task(upstream_to_client())
        _done, pending = await asyncio.wait({forward, backward}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


@app.websocket("/")
@app.websocket("/{full_path:path}")
async def websocket_gateway(websocket: WebSocket, full_path: str = "") -> None:
    if not _ws_authorized(websocket):
        await websocket.close(code=1008, reason="Unauthorized")
        return
    if CLI_SERVICE_MODE != "codex":
        await websocket.close(
            code=1008,
            reason="WebSocket proxy only in CLI_SERVICE_MODE=codex; use claude.ai/code for claude mode.",
        )
        return
    try:
        await _relay_ws(websocket, CODEX_INTERNAL_WS)
    except (OSError, websockets.InvalidStatusCode, websockets.WebSocketException) as exc:
        await websocket.close(code=1011, reason=f"Upstream codex app-server unavailable: {exc}")
