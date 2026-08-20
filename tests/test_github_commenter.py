"""
Unit and integration tests for github_commenter.py
"""
from unittest.mock import MagicMock

import pytest
from github import GithubException

from ai_code_reviewer.github_commenter import (
    format_inline_comment,
    post_pull_request_review,
)
from ai_code_reviewer.schemas import (
    AggregatedPRReview,
    FindingCategory,
    ReviewContext,
    ReviewFinding,
    ReviewVerdict,
    SeverityLevel,
)


def _make_dummy_review(findings: list[ReviewFinding], verdict: ReviewVerdict) -> AggregatedPRReview:
    ctx = ReviewContext(
        installation_id=123,
        repo_full_name="owner/repo",
        repo_clone_url="https://github.com/owner/repo.git",
        pr_number=7,
        pr_title="Add auth endpoints",
        head_sha="deadbeef9999",
        head_branch="feature/auth",
        base_branch="main",
        author_login="octocat",
        additions=25,
        deletions=2,
        changed_files=1,
    )
    return AggregatedPRReview(
        review_context=ctx,
        all_findings=findings,
        verdict=verdict,
        summary_markdown="## Review Summary\n\nAutomated analysis completed.",
        total_findings=len(findings),
    )


def test_format_inline_comment_with_suggestion():
    finding = ReviewFinding(
        file="src/auth.py",
        line_start=15,
        line_end=15,
        symbol_name="login",
        category=FindingCategory.SECURITY,
        severity=SeverityLevel.CRITICAL,
        title="Hardcoded API Secret",
        message="Secret token found in source code.",
        suggested_fix="os.getenv('API_KEY')",
        confidence_score=0.98,
    )
    comment = format_inline_comment(finding)

    assert "**[CRITICAL]**" in comment
    assert "Hardcoded API Secret" in comment
    assert "Security Vulnerability" in comment
    assert "in `login`" in comment
    assert "```suggestion\nos.getenv('API_KEY')\n```" in comment
    assert "Confidence: `98%`" in comment


def test_format_inline_comment_without_suggestion():
    finding = ReviewFinding(
        file="src/calc.py",
        line_start=5,
        line_end=5,
        category=FindingCategory.CODE_QUALITY,
        severity=SeverityLevel.LOW,
        title="Debug print found",
        message="Remove leftover print statement.",
        suggested_fix=None,
        confidence_score=0.90,
    )
    comment = format_inline_comment(finding)

    assert "**[LOW]**" in comment
    assert "```suggestion" not in comment
    assert "Confidence: `90%`" in comment


def test_post_pull_request_review_dry_run():
    review = _make_dummy_review([], ReviewVerdict.APPROVE)
    res = post_pull_request_review(review, dry_run=True)

    assert res["status"] == "dry_run"
    assert res["repo"] == "owner/repo"
    assert res["verdict"] == "APPROVE"


def test_post_pull_request_review_mocked_success():
    finding = ReviewFinding(
        file="src/auth.py",
        line_start=10,
        line_end=10,
        category=FindingCategory.SECURITY,
        severity=SeverityLevel.HIGH,
        title="SQL Injection",
        message="Raw query parameter interpolation.",
        suggested_fix=None,
    )
    review = _make_dummy_review([finding], ReviewVerdict.REQUEST_CHANGES)

    mock_commit = MagicMock()
    mock_created_review = MagicMock()
    mock_created_review.id = 98765

    mock_pr = MagicMock()
    mock_pr.create_review.return_value = mock_created_review

    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    mock_repo.get_commit.return_value = mock_commit

    mock_client = MagicMock()
    mock_client.get_repo.return_value = mock_repo

    res = post_pull_request_review(review, github_client=mock_client)

    assert res["status"] == "success"
    assert res["review_id"] == 98765
    assert res["verdict"] == "REQUEST_CHANGES"
    assert res["inline_comments_posted"] == 1

    # Verify PyGithub create_review call arguments
    mock_pr.create_review.assert_called_once()
    _, kwargs = mock_pr.create_review.call_args
    assert kwargs["commit"] == mock_commit
    assert kwargs["event"] == "REQUEST_CHANGES"
    assert len(kwargs["comments"]) == 1
    assert kwargs["comments"][0]["path"] == "src/auth.py"
    assert kwargs["comments"][0]["line"] == 10


def test_post_pull_request_review_fallback_on_diff_mismatch():
    finding = ReviewFinding(
        file="src/auth.py",
        line_start=999,  # Invalid line outside diff
        line_end=999,
        category=FindingCategory.SECURITY,
        severity=SeverityLevel.HIGH,
        title="Out of range issue",
        message="Line 999 is outside diff.",
    )
    review = _make_dummy_review([finding], ReviewVerdict.REQUEST_CHANGES)

    mock_commit = MagicMock()
    mock_created_review = MagicMock()
    mock_created_review.id = 5555

    mock_pr = MagicMock()
    # First call with inline comments raises GithubException (422 Unprocessable Entity)
    # Second call (fallback without inline comments) succeeds
    mock_pr.create_review.side_effect = [
        GithubException(422, {"message": "Pull request line is outside the diff range"}, headers=None),
        mock_created_review,
    ]

    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    mock_repo.get_commit.return_value = mock_commit

    mock_client = MagicMock()
    mock_client.get_repo.return_value = mock_repo

    res = post_pull_request_review(review, github_client=mock_client)

    assert res["status"] == "fallback_success"
    assert res["review_id"] == 5555
    assert res["inline_comments_posted"] == 0
    assert mock_pr.create_review.call_count == 2
