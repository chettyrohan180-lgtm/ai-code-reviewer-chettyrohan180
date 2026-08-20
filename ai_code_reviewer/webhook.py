"""
webhook.py — HMAC Signature Verification & Payload Parsing
============================================================
This module owns the single FastAPI router that handles all incoming
GitHub App webhooks at `POST /api/webhook`.

Security model:
  1. Read the raw request body *before* parsing JSON (Pydantic needs the
     original bytes for HMAC comparison).
  2. Compare `X-Hub-Signature-256` against HMAC-SHA256(secret, body).
  3. Only if valid → parse payload → dispatch to the pipeline.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from pydantic import ValidationError

from ai_code_reviewer.config import get_settings
from ai_code_reviewer.schemas import PullRequestEvent, ReviewContext
from ai_code_reviewer.github_diff_fetcher import fetch_enriched_pr_context
from ai_code_reviewer.github_commenter import post_pull_request_review
from ai_code_reviewer.pipeline import ReviewPipelineOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Webhook"])

# ── Events we actually handle ───────────────────────────────────────────────
HANDLED_ACTIONS = frozenset({"opened", "synchronize", "reopened"})


# ── HMAC Verification Helper ────────────────────────────────────────────────

def _verify_signature(raw_body: bytes, signature_header: str | None) -> None:
    """
    Validates the `X-Hub-Signature-256` header against the raw request body.

    GitHub always sends:
        X-Hub-Signature-256: sha256=<hex_digest>

    We compute our own HMAC and do a *constant-time* comparison to prevent
    timing-based attacks.

    Args:
        raw_body:          The unmodified request body bytes.
        signature_header:  The value of `X-Hub-Signature-256`.

    Raises:
        HTTPException 401 — if the header is missing or the digest doesn't match.
    """
    if not signature_header:
        logger.warning("Webhook request missing X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header",
        )

    # Header format: "sha256=<hex_digest>"
    parts = signature_header.split("=", 1)
    if len(parts) != 2 or parts[0] != "sha256":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed X-Hub-Signature-256 header (expected 'sha256=<digest>')",
        )

    incoming_digest = parts[1]
    secret = get_settings().github_webhook_secret.encode("utf-8")

    expected_digest = hmac.new(
        key=secret,
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison — prevents timing side-channel attacks
    if not hmac.compare_digest(expected_digest, incoming_digest):
        logger.warning("Webhook signature mismatch — possible spoofed request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    logger.debug("Webhook signature verified")


# ── Payload Parser ──────────────────────────────────────────────────────────

def _parse_pull_request_event(raw_body: bytes) -> PullRequestEvent:
    """
    Deserialises the raw JSON body into a `PullRequestEvent` Pydantic model.

    Raises:
        HTTPException 422 — if the payload doesn't match our expected schema.
    """
    try:
        return PullRequestEvent.model_validate_json(raw_body)
    except ValidationError as exc:
        logger.error("Payload validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid pull_request payload: {exc.error_count()} error(s)",
        ) from exc


def _build_review_context(event: PullRequestEvent) -> ReviewContext:
    """
    Distils a raw `PullRequestEvent` into the minimal `ReviewContext` struct
    that will be consumed by the pipeline in later steps.
    """
    pr = event.pull_request
    return ReviewContext(
        installation_id=event.installation.id if event.installation else None,
        repo_full_name=event.repository.full_name,
        repo_clone_url=str(event.repository.clone_url),
        pr_number=pr.number,
        pr_title=pr.title,
        head_sha=pr.head.sha,
        head_branch=pr.head.ref,
        base_branch=pr.base.ref,
        author_login=event.sender.login,
        additions=pr.additions,
        deletions=pr.deletions,
        changed_files=pr.changed_files,
    )


async def _process_review_pipeline(context: ReviewContext) -> None:
    """
    Background worker that fetches PR diff/AST content, runs
    the multi-agent review pipeline, and publishes review comments to GitHub.
    """
    logger.info("Starting background review pipeline for PR #%d (%s)", context.pr_number, context.repo_full_name)
    try:
        enriched_pr = fetch_enriched_pr_context(context)
        orchestrator = ReviewPipelineOrchestrator()
        review = await orchestrator.run_review(enriched_pr)
        logger.info(
            "Completed review for PR #%d: %s verdict, %d findings. Submitting to GitHub...",
            context.pr_number,
            review.verdict.value,
            review.total_findings,
        )
        submit_result = post_pull_request_review(review)
        logger.info("GitHub review submit status for PR #%d: %s", context.pr_number, submit_result.get("status"))
    except Exception as exc:
        logger.error("Error executing review pipeline for PR #%d: %s", context.pr_number, exc, exc_info=True)


# ── Webhook Endpoint ────────────────────────────────────────────────────────

@router.post(
    "/webhook",
    summary="GitHub App Webhook Receiver",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
    x_github_delivery: Annotated[str | None, Header()] = None,
) -> dict:
    """
    Entry-point for all GitHub App webhook deliveries.

    Flow:
        1. Read raw body.
        2. Verify HMAC-SHA256 signature.
        3. Filter to `pull_request` events with actionable actions.
        4. Parse payload → build ReviewContext.
        5. Dispatch context to the background review pipeline.

    Returns:
        202 Accepted with a status message.
    """
    logger.info(
        "Webhook delivery %s | event=%s",
        x_github_delivery or "unknown",
        x_github_event or "unknown",
    )

    # ── 1. Read raw bytes (must happen before any JSON parsing) ──────────
    raw_body: bytes = await request.body()

    # ── 2. Verify signature ───────────────────────────────────────────────
    _verify_signature(raw_body, x_hub_signature_256)

    # ── 3. Filter events — only handle pull_request ───────────────────────
    if x_github_event != "pull_request":
        logger.debug("Ignoring event type: %s", x_github_event)
        return {"status": "ignored", "reason": f"Event '{x_github_event}' not handled"}

    # ── 4. Parse & validate payload ───────────────────────────────────────
    event = _parse_pull_request_event(raw_body)

    if event.action not in HANDLED_ACTIONS:
        logger.info("Ignoring pull_request action: %s", event.action)
        return {
            "status": "ignored",
            "reason": f"Action '{event.action}' not in handled set {list(HANDLED_ACTIONS)}",
        }

    # ── 5. Build pipeline context ─────────────────────────────────────────
    context = _build_review_context(event)

    logger.info(
        "Queuing review | repo=%s pr=#%d sha=%s files=%d",
        context.repo_full_name,
        context.pr_number,
        context.head_sha[:8],
        context.changed_files,
    )

    # ── 6. Trigger background pipeline execution ─────────────────────────
    background_tasks.add_task(_process_review_pipeline, context)

    return {
        "status": "accepted",
        "repo": context.repo_full_name,
        "pr_number": context.pr_number,
        "head_sha": context.head_sha,
        "changed_files": context.changed_files,
    }

