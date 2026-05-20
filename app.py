"""
codex-service: internal proxy for OpenAI-compatible HTTP APIs used by Codex and agent-service.

- Injects an API Bearer toward the configured upstream URL (not ChatGPT OAuth / Codex browser login).
- Upstream key resolution: CODEX_SERVICE_UPSTREAM_API_KEY, then CODEX_SERVICE_OPENAI_API_KEY, then OPENAI_API_KEY.
- Optional CODEX_SERVICE_CLIENT_KEY: require header X-Codex-Service-Client-Key for internal auth.
"""

from __future__ import annotations

import os
import sys
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

APP_NAME = "codex-service"


def _upstream_bearer_token() -> tuple[str, str]:
    """
    Bearer token sent to upstream (OpenAI, OpenRouter, Azure, etc.).

    Not OAuth / ChatGPT browser login — those tokens are not used here.

    Priority: CODEX_SERVICE_UPSTREAM_API_KEY, CODEX_SERVICE_OPENAI_API_KEY, OPENAI_API_KEY.
    Use a dedicated var when .env OPENAI_API_KEY is an OpenRouter key but upstream URL is api.openai.com.
    """
    for name in ("CODEX_SERVICE_UPSTREAM_API_KEY", "CODEX_SERVICE_OPENAI_API_KEY", "OPENAI_API_KEY"):
        v = os.getenv(name, "").strip()
        if v:
            return v, name
    return "", ""


UPSTREAM_RESPONSES_URL = os.getenv(
    "CODEX_SERVICE_UPSTREAM_RESPONSES_URL",
    "https://api.openai.com/v1/responses",
).strip()
UPSTREAM_CHAT_COMPLETIONS_URL = os.getenv(
    "CODEX_SERVICE_UPSTREAM_CHAT_COMPLETIONS_URL",
    "https://api.openai.com/v1/chat/completions",
).strip()
CLIENT_KEY = os.getenv("CODEX_SERVICE_CLIENT_KEY", "").strip()
REQUEST_TIMEOUT = float(os.getenv("CODEX_SERVICE_REQUEST_TIMEOUT", "120"))

POST_V1_ROUTES: dict[str, str] = {
    "responses": UPSTREAM_RESPONSES_URL,
    "chat/completions": UPSTREAM_CHAT_COMPLETIONS_URL,
}

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)


def _filter_request_headers(src: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in src.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk == "authorization":
            continue
        out[k] = v
    return out


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    # Strip content-encoding: httpx already decompresses gzip/br when we read the body;
    # forwarding the original header makes downstream clients try to decompress again → zlib -3.
    skip = HOP_BY_HOP | {"content-length", "content-encoding"}
    return {k: v for k, v in headers.items() if k.lower() not in skip}


async def _proxy_post_upstream(upstream_url: str, request: Request) -> Response:
    api_key, _key_source = _upstream_bearer_token()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "No upstream API key on codex-service. Set one of: "
                "CODEX_SERVICE_UPSTREAM_API_KEY, CODEX_SERVICE_OPENAI_API_KEY, or OPENAI_API_KEY. "
                "(OAuth / Codex CLI login is not used — only API keys toward the configured upstream URL.)"
            ),
        )

    body = await request.body()
    headers = _filter_request_headers(dict(request.headers))
    headers["Authorization"] = f"Bearer {api_key}"
    headers["Host"] = httpx.URL(upstream_url).host or "api.openai.com"

    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    client = httpx.AsyncClient(timeout=timeout)
    stream_cm = client.stream(
        "POST",
        upstream_url,
        headers=headers,
        content=body,
    )
    upstream = await stream_cm.__aenter__()
    try:
        ct = (upstream.headers.get("content-type") or "").lower()
        if "text/event-stream" in ct:
            status = upstream.status_code
            media = upstream.headers.get("content-type", "text/event-stream")
            resp_headers = _filter_response_headers(upstream.headers)

            async def event_stream() -> AsyncIterator[bytes]:
                try:
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
                finally:
                    await stream_cm.__aexit__(None, None, None)
                    await client.aclose()

            return StreamingResponse(
                event_stream(),
                status_code=status,
                media_type=media,
                headers=resp_headers,
            )

        payload = await upstream.aread()
    except BaseException:
        await stream_cm.__aexit__(*sys.exc_info())
        await client.aclose()
        raise

    await stream_cm.__aexit__(None, None, None)
    await client.aclose()
    return Response(
        content=payload,
        status_code=upstream.status_code,
        headers=_filter_response_headers(upstream.headers),
    )


app = FastAPI(title=APP_NAME, version="0.1.0")


@app.middleware("http")
async def enforce_client_key(request: Request, call_next):
    if request.url.path in ("/health", "/", "/docs", "/openapi.json", "/redoc"):
        return await call_next(request)
    if CLIENT_KEY:
        if request.headers.get("x-codex-service-client-key", "") != CLIENT_KEY:
            return JSONResponse(status_code=403, content={"detail": "Missing or invalid X-Codex-Service-Client-Key"})
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": APP_NAME}


@app.get("/")
async def root() -> dict[str, object]:
    _key, key_source = _upstream_bearer_token()
    return {
        "service": APP_NAME,
        "post_paths": list(POST_V1_ROUTES.keys()),
        "upstreams": {
            "responses": UPSTREAM_RESPONSES_URL,
            "chat/completions": UPSTREAM_CHAT_COMPLETIONS_URL,
        },
        "upstream_api_key_configured": bool(_key),
        "upstream_api_key_env": key_source or None,
        "auth_note": (
            "Upstream uses API key (Bearer), not ChatGPT OAuth. "
            "401 from this path means upstream rejected the key or URL/key mismatch (e.g. OpenRouter key vs api.openai.com)."
        ),
        "client_key_required": bool(CLIENT_KEY),
    }


@app.post("/v1/{full_path:path}")
async def proxy_v1(full_path: str, request: Request) -> Response:
    upstream_url = POST_V1_ROUTES.get(full_path)
    if not upstream_url:
        allowed = ", ".join(sorted(POST_V1_ROUTES))
        raise HTTPException(
            status_code=403,
            detail=f"POST path not allowed. Allowed under /v1/: {allowed}",
        )
    return await _proxy_post_upstream(upstream_url, request)
