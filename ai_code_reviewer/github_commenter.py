"""
github_commenter.py — GitHub PR Review & Inline Comment Submitter
==================================================================
Submits multi-agent review summaries, overall verdicts (APPROVE,
REQUEST_CHANGES, COMMENT), and line-accurate inline review comments with
one-click GitHub suggestion blocks via the GitHub REST API / PyGithub.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from github import Github, GithubException

from ai_code_reviewer.github_auth import get_github_client
from ai_code_reviewer.schemas import (
    AggregatedPRReview,
    FindingCategory,
    ReviewFinding,
    ReviewVerdict,
    SeverityLevel,
)

logger = logging.getLogger(__name__)

SEVERITY_BADGES = {
    SeverityLevel.CRITICAL: "**[CRITICAL]**",
    SeverityLevel.HIGH: "**[HIGH]**",
    SeverityLevel.MEDIUM: "**[MEDIUM]**",
    SeverityLevel.LOW: "**[LOW]**",
    SeverityLevel.INFO: "**[INFO]**",
}

CATEGORY_LABELS = {
    FindingCategory.SECURITY: "Security Vulnerability",
    FindingCategory.PERFORMANCE: "Performance Bottleneck",
    FindingCategory.BUG_RISK: "Logic / Bug Risk",
    FindingCategory.CODE_QUALITY: "Code Quality & Maintainability",
}


def format_inline_comment(finding: ReviewFinding) -> str:
    """
    Formats a granular ReviewFinding into an aesthetic, actionable GitHub
    PR inline review comment, with optional one-click suggestion blocks.
    """
    badge = SEVERITY_BADGES.get(finding.severity, "**[NOTE]**")
    cat_label = CATEGORY_LABELS.get(finding.category, finding.category.value)
    sym_info = f" in `{finding.symbol_name}`" if finding.symbol_name else ""

    lines = [
        f"{badge} **{finding.title}** ({cat_label}){sym_info}",
        "",
        finding.message,
    ]

    if finding.suggested_fix and finding.suggested_fix.strip():
        lines.extend([
            "",
            "```suggestion",
            finding.suggested_fix.strip(),
            "```",
        ])

    lines.extend([
        "",
        f"> *Confidence: `{int(finding.confidence_score * 100)}%` | AI Code Reviewer*",
    ])

    return "\n".join(lines)


def post_pull_request_review(
    review: AggregatedPRReview,
    github_client: Optional[Github] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Publishes the AggregatedPRReview as an official GitHub Pull Request Review
    with overall verdict and inline comments on modified code lines.

    Args:
        review: AggregatedPRReview containing findings, verdict, and markdown summary.
        github_client: Optional PyGithub client (useful for unit testing/mocking).
        dry_run: If True, skips network calls and returns the review payload.

    Returns:
        Dictionary summarizing the review submission status.
    """
    ctx = review.review_context

    if dry_run:
        logger.info("[Dry Run] Skipping review submission for %s PR #%d", ctx.repo_full_name, ctx.pr_number)
        return {
            "status": "dry_run",
            "repo": ctx.repo_full_name,
            "pr_number": ctx.pr_number,
            "verdict": review.verdict.value,
            "inline_comments_count": len(review.all_findings),
        }

    if github_client is None:
        if ctx.installation_id is None:
            raise ValueError(
                f"Cannot post review: installation_id missing for repository {ctx.repo_full_name}"
            )
        github_client = get_github_client(ctx.installation_id)

    logger.info(
        "Submitting review for %s #%d (commit: %s, verdict: %s, inline comments: %d)",
        ctx.repo_full_name,
        ctx.pr_number,
        ctx.head_sha[:8],
        review.verdict.value,
        len(review.all_findings),
    )

    repo = github_client.get_repo(ctx.repo_full_name)
    pr = repo.get_pull(ctx.pr_number)
    commit = repo.get_commit(ctx.head_sha)

    # Build inline comments list
    raw_comments: list[dict[str, Any]] = []
    for finding in review.all_findings:
        raw_comments.append({
            "path": finding.file,
            "line": finding.line_start,
            "side": "RIGHT",
            "body": format_inline_comment(finding),
        })

    # Map verdict enum to GitHub review event string
    # GitHub valid events: "APPROVE", "REQUEST_CHANGES", "COMMENT"
    event_map = {
        ReviewVerdict.APPROVE: "APPROVE",
        ReviewVerdict.REQUEST_CHANGES: "REQUEST_CHANGES",
        ReviewVerdict.COMMENT: "COMMENT",
    }
    event_str = event_map.get(review.verdict, "COMMENT")

    # Author cannot request changes or approve their own PR on GitHub.
    # If the bot is author or permissions restrict, GitHub requires "COMMENT".
    # PyGithub create_review handles event_str.

    try:
        if raw_comments:
            created_review = pr.create_review(
                commit=commit,
                body=review.summary_markdown,
                event=event_str,
                comments=raw_comments,
            )
        else:
            created_review = pr.create_review(
                commit=commit,
                body=review.summary_markdown,
                event=event_str,
            )

        logger.info(
            "Successfully posted review for PR #%d (review ID: %s)",
            ctx.pr_number,
            getattr(created_review, "id", "created"),
        )
        return {
            "status": "success",
            "review_id": getattr(created_review, "id", None),
            "verdict": event_str,
            "inline_comments_posted": len(raw_comments),
        }

    except GithubException as exc:
        logger.warning(
            "Batch review submission with inline comments failed (status %s: %s). Retrying with summary body fallback...",
            exc.status,
            exc.data if hasattr(exc, "data") else exc,
        )

        # Fallback: if inline comments had invalid line positions outside diff hunks,
        # post the review summary body without inline comments so developer gets feedback.
        try:
            created_review = pr.create_review(
                commit=commit,
                body=review.summary_markdown,
                event=event_str if event_str != "REQUEST_CHANGES" else "COMMENT",
            )
            return {
                "status": "fallback_success",
                "review_id": getattr(created_review, "id", None),
                "verdict": event_str,
                "inline_comments_posted": 0,
                "note": "Inline comments fell back to summary body due to diff position mismatch.",
            }
        except GithubException as fallback_exc:
            logger.error("Failed to post even fallback review for PR #%d: %s", ctx.pr_number, fallback_exc)
            raise
