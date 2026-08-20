"""
client.py — Async Multi-Provider LLM Client
===========================================
Provides resilient, asynchronous chat completions with structured JSON
enforcement, automatic exponential backoff retries, and offline mock support.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import httpx

from ai_code_reviewer.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Asynchronous client for executing LLM completion calls with structured JSON output.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.provider = self.settings.llm_provider.lower()
        self.api_key = self.settings.llm_api_key
        self.model = self.settings.llm_model
        self.base_url = self._resolve_base_url()

    def _resolve_base_url(self) -> str:
        if self.settings.llm_base_url:
            return self.settings.llm_base_url.rstrip("/")

        if self.provider == "gemini":
            return "https://generativelanguage.googleapis.com/v1beta/openai"
        elif self.provider == "anthropic":
            return "https://api.anthropic.com/v1"
        else:
            # Default to OpenAI standard base URL
            return "https://api.openai.com/v1"

    @property
    def is_configured(self) -> bool:
        """Returns True if the client has a valid API key or is running in mock mode."""
        return bool(self.api_key) or self.provider == "mock"

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """
        Sends an async chat completion request requiring a structured JSON response.

        Args:
            system_prompt: High-level instructions and role definition.
            user_prompt: PR context, diffs, and AST details.
            temperature: Sampling temperature (defaults to settings.llm_temperature).
            max_tokens: Token budget for completion.
            max_retries: Number of retry attempts on transient network/rate errors.

        Returns:
            Parsed JSON dictionary returned by the LLM.
        """
        if self.provider == "mock" or not self.api_key:
            logger.info("LLMClient in mock/offline mode (no API key configured)")
            return {
                "summary": "Mock analysis complete — no issues found.",
                "findings": [],
            }

        temp = temperature if temperature is not None else self.settings.llm_temperature
        tokens = max_tokens if max_tokens is not None else self.settings.llm_max_tokens

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temp,
            "max_tokens": tokens,
            "response_format": {"type": "json_object"},
        }

        backoff = 1.0
        last_exception: Optional[Exception] = None

        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    logger.debug("Dispatching LLM request to %s (attempt %d/%d)", url, attempt, max_retries)
                    response = await client.post(url, headers=headers, json=payload)

                    if response.status_code in (401, 403):
                        logger.error("LLM authentication failed (%d). Check your API key. Skipping retries.", response.status_code)
                        break

                    if response.status_code == 429:
                        logger.warning("Rate limit hit (429). Retrying in %.1f s...", backoff)
                        await asyncio.sleep(backoff)
                        backoff *= 2.0
                        continue

                    if response.status_code >= 500:
                        logger.warning("Server error (%d). Retrying in %.1f s...", response.status_code, backoff)
                        await asyncio.sleep(backoff)
                        backoff *= 2.0
                        continue

                    response.raise_for_status()
                    data = response.json()

                    raw_content = data["choices"][0]["message"]["content"]
                    return json.loads(raw_content)

                except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError, KeyError) as exc:
                    last_exception = exc
                    logger.warning("LLM call attempt %d failed: %s", attempt, exc)
                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff *= 2.0

        logger.error("All %d LLM attempts failed. Last error: %s", max_retries, last_exception)
        return {
            "summary": f"LLM analysis failed after {max_retries} attempts: {last_exception}",
            "findings": [],
        }
