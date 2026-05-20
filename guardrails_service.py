"""NeMo Guardrails integration for the CLI gateway."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger("guardrails")

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ScreenOutcome:
    allowed: bool
    status: str
    content: str
    rail: str | None = None
    detail: str | None = None


def _enabled() -> bool:
    return os.getenv("GUARDRAILS_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")


def _config_dir() -> str:
    base = os.getenv("GUARDRAILS_CONFIG_PATH", "/app/guardrails_config").strip()
    profile = os.getenv("GUARDRAILS_PROFILE", "default").strip().lower()
    if profile == "llm":
        return os.path.join(base, "llm")
    return base


class GuardrailsService:
    def __init__(self) -> None:
        self._rails = None
        self._ready = False
        self._disabled_reason: str | None = None
        self._lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        return _enabled() and self._ready

    @property
    def status(self) -> dict[str, object]:
        return {
            "enabled": _enabled(),
            "ready": self._ready,
            "profile": os.getenv("GUARDRAILS_PROFILE", "default"),
            "config_path": _config_dir(),
            "disabled_reason": self._disabled_reason,
            "docs": "https://docs.nvidia.com/nemo/guardrails/latest/",
            "product": "https://developer.nvidia.com/nemo-guardrails",
        }

    async def initialize(self) -> None:
        if not _enabled():
            self._disabled_reason = "GUARDRAILS_ENABLED=0"
            return
        async with self._lock:
            if self._ready or self._disabled_reason:
                return
            try:
                from nemoguardrails import LLMRails, RailsConfig
                from nemoguardrails.rails.llm.options import RailType

                config_dir = _config_dir()
                profile = os.getenv("GUARDRAILS_PROFILE", "default").strip().lower()
                if profile == "llm":
                    key = os.getenv("GUARDRAILS_MODERATION_API_KEY", "").strip()
                    if not key:
                        raise RuntimeError(
                            "GUARDRAILS_PROFILE=llm requires GUARDRAILS_MODERATION_API_KEY "
                            "(moderator LLM only — not the CLI client key)."
                        )
                    os.environ.setdefault("OPENAI_API_KEY", key)

                config = RailsConfig.from_path(config_dir)
                self._rails = LLMRails(config)
                self._RailType = RailType
                self._ready = True
                logger.info("NeMo Guardrails loaded from %s (profile=%s)", config_dir, profile)
            except Exception as exc:
                self._disabled_reason = str(exc)
                logger.warning("NeMo Guardrails disabled: %s", exc)

    async def screen(self, role: Role, text: str) -> ScreenOutcome:
        if not _enabled():
            return ScreenOutcome(True, "disabled", text)
        if not self._ready:
            await self.initialize()
        if not self._ready or not self._rails:
            return ScreenOutcome(True, "unavailable", text, detail=self._disabled_reason)

        from nemoguardrails.rails.llm.options import RailStatus, RailType

        rail_type = RailType.INPUT if role == "user" else RailType.OUTPUT
        try:
            result = await self._rails.check_async(
                [{"role": role, "content": text}],
                rail_types=[rail_type],
            )
        except Exception as exc:
            logger.exception("Guardrails check failed")
            if os.getenv("GUARDRAILS_FAIL_OPEN", "0").strip().lower() in ("1", "true", "yes"):
                return ScreenOutcome(True, "error_fail_open", text, detail=str(exc))
            return ScreenOutcome(
                False,
                "error",
                text,
                rail="guardrails_error",
                detail=str(exc),
            )

        if result.status == RailStatus.BLOCKED:
            return ScreenOutcome(
                False,
                "blocked",
                text,
                rail=result.rail,
                detail=result.content or "Content blocked by guardrails.",
            )
        if result.status == RailStatus.MODIFIED:
            return ScreenOutcome(True, "modified", result.content or text, rail=result.rail)
        return ScreenOutcome(True, "passed", result.content or text)

    async def screen_segments(self, segments: list) -> tuple[bool, str | None, str | None, str | None]:
        """Returns (allowed, replacement_for_modified, rail, detail)."""
        for seg in segments:
            outcome = await self.screen(seg.role, seg.text)
            if not outcome.allowed:
                return False, None, outcome.rail, outcome.detail
            if outcome.status == "modified" and outcome.content != seg.text:
                return True, outcome.content, outcome.rail, None
        return True, None, None, None


guardrails_service = GuardrailsService()
