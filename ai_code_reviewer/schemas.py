"""
schemas.py — Pydantic Models for Incoming GitHub Webhook Payloads
==================================================================
These models validate and type the raw JSON bodies that GitHub sends
to our webhook endpoint. Only the fields we actually *use* are declared;
Pydantic will silently ignore extra fields (model_config extra="ignore").
"""
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class _Repo(BaseModel):
    """Minimal repository descriptor embedded inside PR payloads."""

    model_config = {"extra": "ignore"}

    id: int
    name: str = Field(..., description="Repository name without owner, e.g. 'my-repo'")
    full_name: str = Field(..., description="owner/repo string")
    clone_url: HttpUrl
    default_branch: str = "main"


class _User(BaseModel):
    model_config = {"extra": "ignore"}

    login: str
    id: int


class _PullRequest(BaseModel):
    """Core pull-request fields we need for code review orchestration."""

    model_config = {"extra": "ignore"}

    number: int = Field(..., description="PR number within the repository")
    title: str
    body: Optional[str] = None
    state: str  # "open" | "closed"

    # The HEAD commit SHA that triggered this event
    head: _HeadRef
    base: _BaseRef

    user: _User
    html_url: HttpUrl
    diff_url: HttpUrl
    patch_url: HttpUrl

    # Counts — useful for size-gating the review
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0


class _HeadRef(BaseModel):
    """Points to the branch/commit being merged."""

    model_config = {"extra": "ignore"}

    sha: str = Field(..., description="The HEAD commit SHA")
    ref: str = Field(..., description="Branch name, e.g. 'feature/my-branch'")
    repo: Optional[_Repo] = None


class _BaseRef(BaseModel):
    """Points to the target branch (e.g. main)."""

    model_config = {"extra": "ignore"}

    sha: str
    ref: str
    repo: Optional[_Repo] = None


# ── Re-order forward references ────────────────────────────────────
_PullRequest.model_rebuild()


class PullRequestEvent(BaseModel):
    """
    Top-level model for GitHub `pull_request` webhook events.

    GitHub docs: https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request
    """

    model_config = {"extra": "ignore"}

    action: str = Field(
        ...,
        description=(
            "The action that triggered the event. "
            "We handle: 'opened', 'synchronize', 'reopened'."
        ),
    )
    number: int = Field(..., description="PR number (duplicate of pull_request.number)")
    pull_request: _PullRequest
    repository: _Repo
    sender: _User
    installation: Optional[_Installation] = None


class _Installation(BaseModel):
    """GitHub App installation ID — needed for generating auth tokens."""

    model_config = {"extra": "ignore"}

    id: int


# ── Rebuild all models to resolve forward references ────────────────
PullRequestEvent.model_rebuild()


# ── Structured output we hand off to the rest of the pipeline ──────
class ReviewContext(BaseModel):
    """
    Distilled, pipeline-ready context derived from a webhook payload.
    This is the canonical object passed between pipeline stages.
    """

    installation_id: Optional[int] = Field(
        None, description="GitHub App installation ID for token generation"
    )
    repo_full_name: str = Field(..., description="owner/repo")
    repo_clone_url: str
    pr_number: int
    pr_title: str
    head_sha: str = Field(..., description="Commit SHA to review")
    head_branch: str
    base_branch: str
    author_login: str
    additions: int
    deletions: int
    changed_files: int


# ── Step 2 Models: Diff & Tree-sitter AST Context ───────────────────

class DiffHunk(BaseModel):
    """Represents a single unified diff hunk (e.g. @@ -10,4 +10,6 @@)."""

    model_config = {"extra": "ignore"}

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    lines: list[str] = Field(default_factory=list)
    modified_new_lines: list[int] = Field(
        default_factory=list,
        description="1-indexed line numbers in the new file added or modified in this hunk",
    )


class CodeSymbolNode(BaseModel):
    """
    An AST node (function, method, class) extracted via Tree-sitter
    that encloses one or more changed lines.
    """

    model_config = {"extra": "ignore"}

    name: str = Field(..., description="Symbol identifier (e.g., 'calculate_tax' or 'AuthService.login')")
    node_type: str = Field(..., description="Tree-sitter node type (e.g., 'function_definition', 'class_definition')")
    start_line: int = Field(..., description="1-indexed start line in the target file")
    end_line: int = Field(..., description="1-indexed end line in the target file")
    code_snippet: str = Field(..., description="Full source code of the enclosing AST node")
    docstring: Optional[str] = Field(None, description="Extracted docstring or doc-comment if present")
    parent_symbol: Optional[str] = Field(None, description="Parent class or namespace name if nested")
    modified_lines: list[int] = Field(
        default_factory=list,
        description="Changed line numbers falling inside this symbol",
    )


class EnrichedFileDiff(BaseModel):
    """
    A single modified file with parsed diff hunks, target changed lines,
    and enclosing Tree-sitter AST symbol definitions.
    """

    model_config = {"extra": "ignore"}

    filename: str = Field(..., description="Path to the file in the repository")
    old_filename: Optional[str] = Field(None, description="Original filename if renamed")
    status: str = Field(..., description="'added', 'modified', 'removed', 'renamed'")
    additions: int = 0
    deletions: int = 0
    language: str = Field("unknown", description="Programming language (e.g., 'python', 'javascript')")
    patch: Optional[str] = Field(None, description="Raw git unified patch string")
    hunks: list[DiffHunk] = Field(default_factory=list)
    changed_lines: list[int] = Field(
        default_factory=list,
        description="All 1-indexed line numbers added or modified in the new file",
    )
    deleted_lines: list[int] = Field(
        default_factory=list,
        description="1-indexed line numbers deleted from the old file",
    )
    symbols: list[CodeSymbolNode] = Field(
        default_factory=list,
        description="Extracted Tree-sitter symbols enclosing the changed lines",
    )
    unscoped_diff_lines: list[int] = Field(
        default_factory=list,
        description="Changed lines outside any function/class (e.g., top-level imports, config)",
    )


class EnrichedPRContext(BaseModel):
    """
    Complete, token-optimized context combining PR metadata, parsed diffs,
    and Tree-sitter symbol nodes ready for AI agent review.
    """

    model_config = {"extra": "ignore"}

    review_context: ReviewContext
    files: list[EnrichedFileDiff] = Field(default_factory=list)
    total_symbols_modified: int = 0
    estimated_tokens: int = 0


# ── Step 3 Models: Multi-Agent Review Pipeline ──────────────────────

class SeverityLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(str, Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    BUG_RISK = "bug_risk"
    CODE_QUALITY = "code_quality"


class ReviewVerdict(str, Enum):
    APPROVE = "APPROVE"
    COMMENT = "COMMENT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class ReviewFinding(BaseModel):
    """
    A single granular finding produced by a specialized review agent.
    """

    model_config = {"extra": "ignore"}

    file: str = Field(..., description="Path to the file containing the issue")
    line_start: int = Field(..., description="1-indexed starting line number")
    line_end: int = Field(..., description="1-indexed ending line number")
    symbol_name: Optional[str] = Field(None, description="Enclosing AST function or class name")
    category: FindingCategory
    severity: SeverityLevel
    title: str = Field(..., description="Brief one-line summary of the issue")
    message: str = Field(..., description="Detailed explanation of why this is a concern")
    suggested_fix: Optional[str] = Field(None, description="Suggested code replacement or recommendation")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class AgentReviewResult(BaseModel):
    """
    Consolidated review result produced by a single specialized agent.
    """

    model_config = {"extra": "ignore"}

    agent_name: str
    category: FindingCategory
    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str = Field("", description="Agent's high-level summary of analysis")
    passed: bool = Field(True, description="True if no critical or high severity findings")
    execution_time_ms: float = 0.0


class AggregatedPRReview(BaseModel):
    """
    Final review verdict and aggregated findings from all agents.
    """

    model_config = {"extra": "ignore"}

    review_context: ReviewContext
    agent_results: list[AgentReviewResult] = Field(default_factory=list)
    all_findings: list[ReviewFinding] = Field(default_factory=list)
    verdict: ReviewVerdict = ReviewVerdict.APPROVE
    summary_markdown: str = ""
    total_findings: int = 0


