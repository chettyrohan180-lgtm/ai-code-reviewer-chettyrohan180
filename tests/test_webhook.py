"""
Integration tests for the webhook endpoint with HMAC signature verification.
"""
import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient

from ai_code_reviewer.config import get_settings
from ai_code_reviewer.main import create_app

client = TestClient(create_app())


def _make_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_webhook_missing_signature():
    response = client.post(
        "/api/webhook",
        json={"action": "opened"},
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert response.status_code == 401
    assert "Missing X-Hub-Signature-256" in response.json()["detail"]


def test_webhook_invalid_signature():
    response = client.post(
        "/api/webhook",
        content=b'{"action":"opened"}',
        headers={
            "X-Hub-Signature-256": "sha256=invalid_hex_digest_12345",
            "X-GitHub-Event": "pull_request",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.json()["detail"]


def test_webhook_unhandled_event():
    body = b'{"zen":"Keep it logically awesome."}'
    secret = get_settings().github_webhook_secret
    sig = _make_signature(body, secret)

    response = client.post(
        "/api/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "ping",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"


def test_webhook_valid_pr_event():
    payload = {
        "action": "opened",
        "number": 10,
        "pull_request": {
            "number": 10,
            "title": "Add feature X",
            "state": "open",
            "head": {"sha": "1234567890abcdef", "ref": "feat/x"},
            "base": {"sha": "fedcba0987654321", "ref": "main"},
            "user": {"login": "dev1", "id": 1},
            "html_url": "https://github.com/org/repo/pull/10",
            "diff_url": "https://github.com/org/repo/pull/10.diff",
            "patch_url": "https://github.com/org/repo/pull/10.patch",
            "additions": 15,
            "deletions": 3,
            "changed_files": 2,
        },
        "repository": {
            "id": 999,
            "name": "repo",
            "full_name": "org/repo",
            "clone_url": "https://github.com/org/repo.git",
            "default_branch": "main",
        },
        "sender": {"login": "dev1", "id": 1},
        "installation": {"id": 55555},
    }
    body = json.dumps(payload).encode("utf-8")
    secret = get_settings().github_webhook_secret
    sig = _make_signature(body, secret)

    response = client.post(
        "/api/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-uuid-1234",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert data["repo"] == "org/repo"
    assert data["pr_number"] == 10
