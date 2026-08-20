"""
Unit tests for client.py (LLMClient configuration, retry logic, and mock mode).
"""
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from ai_code_reviewer.config import Settings
from ai_code_reviewer.llm.client import LLMClient


def test_llm_client_base_url_resolution(tmp_path):
    pem_file = tmp_path / "dummy.pem"
    pem_file.write_text("DUMMY_KEY", encoding="utf-8")

    openai_settings = Settings(
        github_app_id=123,
        github_private_key_path=pem_file,
        github_webhook_secret="secret",
        llm_provider="openai",
    )
    client_openai = LLMClient(settings=openai_settings)
    assert client_openai.base_url == "https://api.openai.com/v1"

    gemini_settings = Settings(
        github_app_id=123,
        github_private_key_path=pem_file,
        github_webhook_secret="secret",
        llm_provider="gemini",
    )
    client_gemini = LLMClient(settings=gemini_settings)
    assert "googleapis.com" in client_gemini.base_url


@pytest.mark.asyncio
async def test_llm_client_mock_mode(tmp_path):
    pem_file = tmp_path / "dummy.pem"
    pem_file.write_text("DUMMY_KEY", encoding="utf-8")

    settings = Settings(
        github_app_id=123,
        github_private_key_path=pem_file,
        github_webhook_secret="secret",
        llm_provider="mock",
    )
    client = LLMClient(settings=settings)
    result = await client.complete_structured("system prompt", "user prompt")

    assert "summary" in result
    assert result["findings"] == []


@pytest.mark.asyncio
async def test_llm_client_successful_response(tmp_path):
    pem_file = tmp_path / "dummy.pem"
    pem_file.write_text("DUMMY_KEY", encoding="utf-8")

    settings = Settings(
        github_app_id=123,
        github_private_key_path=pem_file,
        github_webhook_secret="secret",
        llm_provider="openai",
        llm_api_key="sk-test-key-12345",
    )
    client = LLMClient(settings=settings)

    mock_llm_json = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "summary": "Detected unindexed query.",
                        "findings": [],
                    })
                }
            }
        ]
    }

    mock_response = httpx.Response(200, json=mock_llm_json, request=httpx.Request("POST", "https://api.openai.com"))

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await client.complete_structured("system prompt", "user prompt")

        assert result["summary"] == "Detected unindexed query."
        assert result["findings"] == []
