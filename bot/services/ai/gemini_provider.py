"""Google Gemini Provider Adapter for KROVEX.

Implements asynchronous communication with Google Gemini Generative Language API
via aiohttp with zero external heavy SDK dependencies and strict credential redaction.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional
import aiohttp

from bot.services.ai.base_provider import AIResponse, BaseAIProvider
from bot.utils.logger import get_logger

logger = get_logger("death_bot.ai.gemini")

GEMINI_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider(BaseAIProvider):
    """Asynchronous Gemini API provider using raw HTTP REST."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-3.5-flash-lite",
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.model = model.strip() if model and model.strip() else "gemini-3.5-flash-lite"
        self._session = session
        self._owns_session = False

    @property
    def is_configured(self) -> bool:
        """True if Gemini API key is configured."""
        return bool(self.api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Ensure an active aiohttp ClientSession exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    def _sanitize_log_url(self, url: str) -> str:
        """Mask API key query parameters in logs."""
        if not self.api_key:
            return url
        return url.replace(self.api_key, "***REDACTED***")

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        temperature: float = 0.8,
        max_tokens: int = 400,
        timeout: float = 12.0,
    ) -> AIResponse:
        """Generate conversational reply using Gemini API."""
        if not self.is_configured:
            return AIResponse(
                content="",
                model=self.model,
                success=False,
                error="Gemini API key is not configured.",
            )

        # Build contents array
        contents: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            # Map role: Gemini uses 'user' and 'model'
            gemini_role = "model" if role in ("model", "assistant") else "user"
            content = msg.get("content", "").strip()
            if content:
                contents.append({
                    "role": gemini_role,
                    "parts": [{"text": content}],
                })

        if not contents:
            return AIResponse(
                content="",
                model=self.model,
                success=False,
                error="Cannot generate response with empty message history.",
            )

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": max(0.0, min(temperature, 1.0)),
                "maxOutputTokens": max(10, min(max_tokens, 2048)),
            },
        }

        if system_prompt and system_prompt.strip():
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt.strip()}],
            }

        url = GEMINI_API_ENDPOINT.format(model=self.model)
        session = await self._get_session()
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        try:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                status = resp.status

                if status == 429:
                    logger.warning("Gemini API rate limit exceeded (HTTP 429).")
                    return AIResponse(
                        content="",
                        model=self.model,
                        success=False,
                        error="AI provider rate limit reached (HTTP 429). Please try again shortly.",
                    )

                if status != 200:
                    try:
                        err_json = await resp.json()
                        err_msg = err_json.get("error", {}).get("message", f"HTTP {status}")
                    except Exception:
                        err_msg = f"HTTP {status}"

                    # Scrub any potential key reflection in error message
                    if self.api_key and self.api_key in err_msg:
                        err_msg = err_msg.replace(self.api_key, "***REDACTED***")

                    logger.error("Gemini API error [Status %d]: %s", status, err_msg)
                    return AIResponse(
                        content="",
                        model=self.model,
                        success=False,
                        error=f"Gemini API returned status {status}: {err_msg}",
                    )

                data = await resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return AIResponse(
                        content="",
                        model=self.model,
                        success=False,
                        error="No response candidates returned by Gemini.",
                    )

                primary = candidates[0]
                finish_reason = primary.get("finishReason", "STOP")
                content_obj = primary.get("content", {})
                parts = content_obj.get("parts", [])

                text_fragments = [p.get("text", "") for p in parts if "text" in p]
                reply_text = "".join(text_fragments).strip()

                usage_meta = data.get("usageMetadata", {})
                total_tokens = usage_meta.get("totalTokenCount", 0)

                return AIResponse(
                    content=reply_text,
                    model=self.model,
                    tokens_used=total_tokens,
                    finish_reason=finish_reason,
                    success=True,
                    error=None,
                )

        except asyncio.TimeoutError:
            logger.warning("Gemini request timed out after %.1f seconds.", timeout)
            return AIResponse(
                content="",
                model=self.model,
                success=False,
                error="AI provider request timed out. Please try again.",
            )
        except aiohttp.ClientConnectorError as exc:
            logger.error("Network connection error reaching Gemini: %s", exc)
            return AIResponse(
                content="",
                model=self.model,
                success=False,
                error="Network connection error reaching AI provider.",
            )
        except Exception as exc:
            logger.error("Unexpected error invoking Gemini: %s", exc, exc_info=True)
            return AIResponse(
                content="",
                model=self.model,
                success=False,
                error=f"Unexpected error: {type(exc).__name__}",
            )

    async def close(self) -> None:
        """Close dedicated HTTP session if owned."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None
