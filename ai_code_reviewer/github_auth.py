"""
github_auth.py — GitHub App Authentication (JWT + Installation Tokens)
=======================================================================
GitHub Apps authenticate in two layers:
  1. A short-lived JWT signed with your App's RSA private key.
     Used to call App-level endpoints (e.g. list installations).
  2. An installation access token (expires after 1 hour) fetched
     using that JWT, scoped to a specific installation.
     Used for all repository-level operations.

References:
  - https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app
  - https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app
"""
from __future__ import annotations

import time
import logging
from functools import lru_cache
from typing import Optional

import jwt
import httpx
from github import Github, GithubIntegration

from ai_code_reviewer.config import get_settings

logger = logging.getLogger(__name__)


# ── JWT Generation ──────────────────────────────────────────────────────────

def _build_jwt() -> str:
    """
    Create a 10-minute-lived JWT signed with the App's RSA private key.

    The payload follows GitHub's required structure:
      - iat: issued-at, backdated 60 s to account for clock drift
      - exp: expiry, now + 10 minutes (GitHub maximum)
      - iss: the App's numeric ID
    """
    settings = get_settings()
    now = int(time.time())

    payload = {
        "iat": now - 60,          # Backdate 60 s for clock skew tolerance
        "exp": now + (10 * 60),   # Maximum allowed by GitHub
        "iss": settings.github_app_id,
        "alg": "RS256",
    }

    token = jwt.encode(
        payload,
        settings.github_private_key,
        algorithm="RS256",
    )
    logger.debug("Generated GitHub App JWT (expires in ~10 min)")
    return token


# ── Installation Token Retrieval ────────────────────────────────────────────

def get_installation_token(installation_id: int) -> str:
    """
    Exchange a JWT for an installation access token scoped to `installation_id`.

    Args:
        installation_id: The numeric GitHub App installation ID, which is
                         embedded in the webhook payload under `installation.id`.

    Returns:
        A short-lived Bearer token string (valid for 1 hour).

    Raises:
        httpx.HTTPStatusError: If GitHub rejects the request.
    """
    jwt_token = _build_jwt()
    settings = get_settings()

    url = (
        f"https://api.github.com/app/installations/"
        f"{installation_id}/access_tokens"
    )
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    with httpx.Client(timeout=15.0) as client:
        response = client.post(url, headers=headers)

    response.raise_for_status()
    token = response.json()["token"]
    logger.info("Obtained installation access token for installation %s", installation_id)
    return token


# ── Authenticated PyGithub Client ───────────────────────────────────────────

def get_github_client(installation_id: int) -> Github:
    """
    Returns a PyGithub `Github` client authenticated with an installation token.

    Usage:
        gh = get_github_client(installation_id=12345678)
        repo = gh.get_repo("owner/repo")

    Args:
        installation_id: GitHub App installation ID from the webhook payload.

    Returns:
        An authenticated `github.Github` instance.
    """
    token = get_installation_token(installation_id)
    return Github(token)


# ── Convenience: client without an installation (App-level) ────────────────

@lru_cache(maxsize=1)
def get_integration_client() -> GithubIntegration:
    """
    Returns a PyGithub `GithubIntegration` client for App-level operations.

    Cached — the integration client itself is stateless (it regenerates
    JWTs on demand internally via PyGithub's logic).
    """
    settings = get_settings()
    return GithubIntegration(
        integration_id=settings.github_app_id,
        private_key=settings.github_private_key,
    )
