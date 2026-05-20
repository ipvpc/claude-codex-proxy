"""Extract user/assistant text from Codex app-server JSON-RPC frames."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class TextSegment:
    role: str  # "user" | "assistant"
    text: str
    request_id: int | str | None  # JSON-RPC id on client requests, else None


def _walk(obj: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _walk(value, path + (key,))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            yield from _walk(value, path + (str(idx),))
    else:
        yield path, obj


def _segments_from_input_list(items: list[Any]) -> list[str]:
    texts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
        elif isinstance(item.get("text"), str) and item.get("text", "").strip():
            texts.append(item["text"])
    return texts


def extract_text_segments(payload: str, *, from_client: bool) -> list[TextSegment]:
    """
    Best-effort parsing of Codex app-server JSON-RPC messages.

    from_client=True  -> input rails (user text in requests)
    from_client=False -> output rails (assistant text in notifications/results)
    """
    try:
        msg = json.loads(payload)
    except json.JSONDecodeError:
        return []

    if not isinstance(msg, dict):
        return []

    req_id = msg.get("id")
    segments: list[TextSegment] = []

    if from_client and "method" in msg:
        method = msg.get("method")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        if method in ("turn/start", "turn/steer"):
            for text in _segments_from_input_list(params.get("input") or []):
                segments.append(TextSegment("user", text, req_id))
        elif method == "thread/start":
            # Optional initial user message in some clients
            for text in _segments_from_input_list(params.get("input") or []):
                segments.append(TextSegment("user", text, req_id))

    if not from_client:
        # Notifications: method + params
        if "method" in msg and isinstance(msg.get("params"), dict):
            params = msg["params"]
            for path, value in _walk(params):
                if path and path[-1] in ("text", "content", "final_transcript") and isinstance(value, str):
                    if value.strip() and _looks_like_assistant_path(path):
                        segments.append(TextSegment("assistant", value, None))
        # Responses with result payloads
        if isinstance(msg.get("result"), dict):
            for path, value in _walk(msg["result"]):
                if path and path[-1] in ("text", "content") and isinstance(value, str):
                    if value.strip() and _looks_like_assistant_path(path):
                        segments.append(TextSegment("assistant", value, None))

    return segments


def _looks_like_assistant_path(path: tuple[str, ...]) -> bool:
    lowered = "/".join(path).lower()
    if "user" in lowered or "input" in lowered:
        return False
    return any(
        token in lowered
        for token in ("agent", "assistant", "message", "output", "transcript", "item")
    )


def apply_text_replacement(payload: str, original: str, replacement: str) -> str:
    """Replace first occurrence of original text inside a JSON text frame."""
    if original == replacement or original not in payload:
        return payload
    try:
        msg = json.loads(payload)
    except json.JSONDecodeError:
        return payload.replace(original, replacement, 1)

    replaced = False

    def _patch(obj: Any) -> Any:
        nonlocal replaced
        if isinstance(obj, dict):
            return {k: _patch(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_patch(v) for v in obj]
        if isinstance(obj, str) and not replaced and obj == original:
            replaced = True
            return replacement
        return obj

    return json.dumps(_patch(msg), separators=(",", ":"))


def build_block_frame(request_id: int | str | None, rail: str | None, detail: str) -> str:
    body = {
        "error": {
            "code": -32050,
            "message": "Blocked by NeMo Guardrails",
            "data": {"rail": rail, "detail": detail},
        }
    }
    if request_id is not None:
        body["id"] = request_id
    return json.dumps(body, separators=(",", ":"))
