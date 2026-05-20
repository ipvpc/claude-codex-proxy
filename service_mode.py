"""CLI_SERVICE_MODE: exclusive codex (OpenAI proxy) vs claude (Anthropic CLI/SDK)."""

from __future__ import annotations

import os

_VALID = frozenset({"codex", "claude"})
_ALIASES = {
    "openai": "codex",
    "anthropic": "claude",
}

_CODEX_ENV = (
    "OPENAI_API_KEY",
    "CODEX_SERVICE_UPSTREAM_API_KEY",
    "CODEX_SERVICE_OPENAI_API_KEY",
)

_CLAUDE_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


def resolve_service_mode() -> str:
    raw = os.getenv("CLI_SERVICE_MODE", "codex").strip().lower()
    mode = _ALIASES.get(raw, raw)
    if mode not in _VALID:
        raise ValueError(
            f"Invalid CLI_SERVICE_MODE={raw!r}. Use codex (OpenAI/Codex proxy) or claude (Claude Code)."
        )
    return mode


def mode_allows_openai_proxy(mode: str) -> bool:
    return mode == "codex"


def mode_allows_claude_cli(mode: str) -> bool:
    return mode == "claude"


def configured_codex_keys() -> list[str]:
    return [n for n in _CODEX_ENV if os.getenv(n, "").strip()]


def configured_claude_keys() -> list[str]:
    return [n for n in _CLAUDE_ENV if os.getenv(n, "").strip()]
