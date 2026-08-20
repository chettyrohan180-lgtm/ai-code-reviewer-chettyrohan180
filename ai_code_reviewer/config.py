"""
config.py — Centralized Settings via Pydantic BaseSettings
============================================================
Reads values from the environment (or a .env file) and exposes them
as a typed, validated singleton accessible throughout the app.
"""
from __future__ import annotations

from pathlib import Path
from functools import lru_cache
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application-wide configuration.
    All fields are read from environment variables or a `.env` file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── GitHub App ──────────────────────────────────────────────────
    github_app_id: int = Field(..., description="Numeric GitHub App ID")

    github_private_key_path: Path = Field(
        ..., description="Path to the .pem private key file"
    )

    github_webhook_secret: str = Field(
        ..., description="Shared secret for HMAC signature verification"
    )

    # ── Server ──────────────────────────────────────────────────────
    port: int = Field(default=8000, ge=1, le=65535)
    app_env: str = Field(default="development")

    # ── LLM Configuration ──────────────────────────────────────────
    llm_provider: str = Field(
        default="openai",
        description="LLM provider: 'openai', 'gemini', 'anthropic', 'custom', 'mock'",
    )
    llm_api_key: str = Field(default="", description="API key for the selected LLM provider")
    openai_api_key: str = Field(default="", description="OpenAI API key (alias)")
    gemini_api_key: str = Field(default="", description="Gemini API key (alias)")
    anthropic_api_key: str = Field(default="", description="Anthropic API key (alias)")
    llm_model: str = Field(default="gpt-4o-mini", description="Model name to use")
    llm_base_url: Optional[str] = Field(default=None, description="Custom base URL for OpenAI-compatible proxies / Ollama")
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=4096, ge=1)
    llm_timeout_seconds: float = Field(default=60.0, ge=1.0)

    # ── Derived: private key contents ───────────────────────────────
    # Populated after model validation — not read from env directly.
    github_private_key: str = Field(default="", init=False)

    @model_validator(mode="after")
    def _validate_and_load(self) -> "Settings":
        """Read the PEM file contents and resolve LLM API key aliases."""
        pem_path = self.github_private_key_path
        if not pem_path.exists():
            raise FileNotFoundError(
                f"GitHub App private key not found at: {pem_path}. "
                "Download it from your GitHub App settings page."
            )
        self.github_private_key = pem_path.read_text(encoding="utf-8")

        # Resolve LLM API key from provider-specific aliases if llm_api_key is unset
        if not self.llm_api_key:
            if self.llm_provider == "openai" and self.openai_api_key:
                self.llm_api_key = self.openai_api_key
            elif self.llm_provider == "gemini" and self.gemini_api_key:
                self.llm_api_key = self.gemini_api_key
            elif self.llm_provider == "anthropic" and self.anthropic_api_key:
                self.llm_api_key = self.anthropic_api_key
            elif self.openai_api_key:
                self.llm_api_key = self.openai_api_key

        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


Settings.model_rebuild()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached singleton Settings instance.
    Use this everywhere instead of constructing Settings() directly.
    """
    return Settings()  # type: ignore[call-arg]

