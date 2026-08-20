"""
Integration tests for ReviewPipelineOrchestrator and concurrent execution.
"""
import pytest

from ai_code_reviewer.pipeline import ReviewPipelineOrchestrator
from ai_code_reviewer.schemas import (
    CodeSymbolNode,
    EnrichedFileDiff,
    EnrichedPRContext,
    ReviewContext,
    ReviewVerdict,
)


def _build_test_context(files: list[EnrichedFileDiff]) -> EnrichedPRContext:
    review_context = ReviewContext(
        installation_id=999,
        repo_full_name="my-org/my-project",
        repo_clone_url="https://github.com/my-org/my-project.git",
        pr_number=101,
        pr_title="Optimize data pipeline and auth",
        head_sha="abcdef123456",
        head_branch="feature/optimize",
        base_branch="main",
        author_login="octo-coder",
        additions=50,
        deletions=10,
        changed_files=len(files),
    )
    return EnrichedPRContext(
        review_context=review_context,
        files=files,
        total_symbols_modified=sum(len(f.symbols) for f in files),
    )


@pytest.mark.asyncio
async def test_pipeline_clean_pr_approves():
    orchestrator = ReviewPipelineOrchestrator()

    symbol = CodeSymbolNode(
        name="safe_function",
        node_type="function_definition",
        start_line=1,
        end_line=4,
        code_snippet="""def safe_function(a: int, b: int) -> int:
    \"\"\"Clean pure function without issues.\"\"\"
    return a + b
""",
        docstring="Clean pure function without issues.",
        modified_lines=[3],
    )
    file_diff = EnrichedFileDiff(
        filename="src/math.py",
        status="modified",
        language="python",
        changed_lines=[3],
        symbols=[symbol],
    )

    ctx = _build_test_context([file_diff])
    review = await orchestrator.run_review(ctx)

    assert review.verdict == ReviewVerdict.APPROVE
    assert review.total_findings == 0
    assert "APPROVED" in review.summary_markdown
    assert "All checks passed!" in review.summary_markdown


@pytest.mark.asyncio
async def test_pipeline_critical_issues_request_changes():
    orchestrator = ReviewPipelineOrchestrator()

    symbol = CodeSymbolNode(
        name="insecure_login",
        node_type="function_definition",
        start_line=10,
        end_line=20,
        code_snippet="""def insecure_login(user, passw, cache=[]):
    api_key = "secret_abcdef1234567890"
    query = f"SELECT * FROM users WHERE username = '{user}'"
    cursor.execute(query)
    return True
""",
        modified_lines=[10, 11, 12],
    )
    file_diff = EnrichedFileDiff(
        filename="src/auth.py",
        status="modified",
        language="python",
        changed_lines=[10, 11, 12],
        symbols=[symbol],
    )

    ctx = _build_test_context([file_diff])
    review = await orchestrator.run_review(ctx)

    assert review.verdict == ReviewVerdict.REQUEST_CHANGES
    assert review.total_findings >= 2
    assert "CHANGES REQUESTED" in review.summary_markdown
    assert len(review.agent_results) == 4
